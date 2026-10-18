"""局部词音归属修订：按来源绑定证据分字或重挂词，冻结拍轴和全部伴奏。"""
# 局部词音归属修订：新增显式局部入口，任何音高重识别／和弦重编均不在本模块执行。
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
from workspace_location import local_path
from accompaniment_analysis import SongClock
from score_export import attach_lyrics, sha256
from source_timing_revision import rebuild_events
from guitar_readability_acceptance import fingerprint, music_payload
from guitar_variable_repeat import build_repeat_plan, bar_signature, measure_timeline


def _checked_owner(characters, index):
    # 局部词音归属修订：新增按身份取字，不能按相同文字搜索串到另一遍。
    if not isinstance(index, int) or index < 0 or index >= len(characters) or characters[index]['index'] != index:
        raise ValueError('局部修订歌词身份无效。')
    return characters[index]


def _portion(note, begin, end, first_tick, last_tick, owner, clock):
    # 局部词音归属修订：新增只拆原音的连续范围，音高和总持续范围保持，不添加猜出的新声音。
    value = deepcopy(note)
    identity = note['id'] + '.local_owner_' + str(owner)
    value.update(id=identity, lyric_index=owner, start_seconds=begin, end_seconds=end,
                 start_tick=first_tick, end_tick=last_tick, source_lyric_index=note.get('lyric_index'))
    source_segments = note.get('performance_segments', [note])
    segments = []
    for item in source_segments:
        left, right = max(begin, item['start_seconds']), min(end, item['end_seconds'])
        if right > left:
            segments.append({**deepcopy(item), 'piece_id': identity, 'start_seconds': left, 'end_seconds': right})
    value['performance_segments'] = segments
    for key in ('source_interval_seconds', 'time_projection_source_seconds', 'rebuild_source_part_seconds'):
        if key in value:
            value[key] = [begin, end]
    value['notation_source_start_seconds'], value['notation_source_end_seconds'] = begin, end
    value['quantized_start_seconds'], value['quantized_end_seconds'] = clock.seconds(first_tick), clock.seconds(last_tick)
    value['start_error_seconds'] = value['quantized_start_seconds'] - begin
    value['end_error_seconds'] = value['quantized_end_seconds'] - end
    # 局部词音归属修订：新增实际演唱投影只在切点分开，原音最外侧播放边界不动。
    value['playback_start_tick'] = note.get('playback_start_tick', note['start_tick']) if begin == note['start_seconds'] else clock.quantize(begin, 30)
    value['playback_end_tick'] = note.get('playback_end_tick', note['end_tick']) if end == note['end_seconds'] else clock.quantize(end, 30)
    value['word_alignment'] = {'method': 'source_bound_local_ownership_review',
                               'ancestor': deepcopy(note.get('word_alignment')),
                               'requires_review': True, 'scope': 'local_candidate_not_whole_song_certificate'}
    value['local_source_parent_id'] = note['id']
    return value


def apply_local_lyric_review(project, review):
    """仅允许原音连续拆分和局部重挂词；输出是新候选，不自动清除整曲音乐未决。"""
    # 局部词音归属修订：新增实际内容和原声双重绑定，旧版本／错曲目均必须明确失败。
    if review.get('version') != 1 or review.get('input_music_sha256') != fingerprint(music_payload(project)):
        raise ValueError('局部修订证据与当前实际音乐不一致。')
    source = project['shared_analysis']['input_binding']['sources']['vocals']
    if review.get('vocals_sha256') != source['sha256'] or sha256(source['path']) != source['sha256']:
        raise ValueError('局部修订原唱来源不一致。')
    if not review.get('evidence_files'):
        raise ValueError('局部修订缺少可复核原声证据。')
    for item in review['evidence_files']:
        if not local_path(item['path']).is_file() or sha256(item['path']) != item['sha256']:
            raise ValueError('局部修订证据文件缺失或已改变。')
    # 两处我局部词音核对：新增只从绑定的对象型JSON读取听辨身份，数组或其它证据不冒充听辨。
    listener_ids = set()
    for item in review['evidence_files']:
        if Path(item['path']).suffix == '.json':
            evidence = json.loads(local_path(item['path']).read_text('utf-8-sig'))
            if isinstance(evidence, dict) and evidence.get('review_id'):
                listener_ids.add(evidence['review_id'])
    result = deepcopy(project)
    voice = result['accepted_vocal_project']
    characters = voice['lyrics']['characters']
    notes = voice['quantized_notes']
    clock = SongClock(voice)
    changed_ids, new_ids, changed_owners = set(), set(), set()
    operations = []
    for operation in review.get('operations', []):
        # 局部词音归属修订：新增有明确听辨的轻声字入口，音高未定时只记字音提示，不伪造固定音高或MIDI攻击。
        if operation['kind'] == 'unpitched_lyric_cue':
            owner = operation['owner']
            char = _checked_owner(characters, owner)
            begin, end = operation['seconds']
            if (not operation.get('listener_review_id') or not math.isfinite(begin) or not math.isfinite(end)
                    or end <= begin or end - begin > .5):
                raise ValueError('轻声字入口缺少明确局部听辨或时间范围无效。')
            cue = {'id': 'local_unpitched_' + str(owner), 'character_index': owner, 'text': char['text'],
                   'start_seconds': begin, 'end_seconds': end, 'start_tick': clock.quantize(begin, 30),
                   'end_tick': clock.quantize(end, 30), 'kind': 'soft_lyric_pitch_unspecified',
                   'label': '轻声', 'listener_review_id': operation['listener_review_id'],
                   'onset_uncertainty_seconds': operation.get('onset_uncertainty_seconds'),
                   'fixed_pitch_assigned': False, 'midi_note_generated': False}
            if any(c.get('character_index') == owner for c in voice.get('unpitched_lyric_cues', [])):
                raise ValueError('轻声字入口重复。')
            voice.setdefault('unpitched_lyric_cues', []).append(cue)
            changed_owners.add(owner)
            operations.append(deepcopy(operation))
            continue
        identities = {note['id']: i for i, note in enumerate(notes)}
        identity = operation['note_id']
        if identity not in identities or identity in changed_ids:
            raise ValueError('局部修订音符不存在、重复或已经处理。')
        index = identities[identity]
        note = notes[index]
        if operation.get('expected_source_seconds') != [note['start_seconds'], note['end_seconds']]:
            raise ValueError('局部修订原音完整范围不一致。')
        changed_ids.add(identity)
        changed_owners.add(note.get('lyric_index'))
        if operation['kind'] == 'split_owner':
            boundaries = [note['start_seconds'], *operation['boundaries_seconds'], note['end_seconds']]
            ticks = [note['start_tick'], *[clock.quantize(t, 30) for t in operation['boundaries_seconds']], note['end_tick']]
            owners = operation['owners']
            if len(owners) + 1 != len(boundaries) or len(set(owners)) != len(owners):
                raise ValueError('局部分字数量或身份重复。')
            if any(not math.isfinite(t) for t in boundaries) or any(b <= a for a, b in zip(boundaries, boundaries[1:])):
                raise ValueError('局部分字超出原持续范围或逆序。')
            if any(b <= a for a, b in zip(ticks, ticks[1:])):
                raise ValueError('局部分字不能在当前固定拍轴合理记谱，不得移动小节凑音符。')
            # 两处我局部词音核对：新增来源绑定的短下滑表达；只标演唱动作，不猜一个固定终止音或重算音高。
            motions = {}
            for motion in operation.get('pitch_motions', []):
                owner = motion.get('owner')
                listener = motion.get('listener_review_id')
                # 两处我局部词音核对：修改重复解析证据，原对象假设式保留；兼容数组型声学观察。
                # bound_listener = any(json.loads(local_path(item['path']).read_text('utf-8-sig')).get('review_id') == listener
                #                      for item in review['evidence_files'] if Path(item['path']).suffix == '.json')
                bound_listener = listener in listener_ids
                if (owner not in owners or owner in motions or motion.get('kind') != 'short_falling_glide'
                        or not listener or not bound_listener):
                    raise ValueError('短下滑缺少绑定听辨、归属无效或动作不受支持。')
                motions[owner] = motion
            replacement = []
            for owner, left, right, a, b in zip(owners, boundaries, boundaries[1:], ticks, ticks[1:]):
                char = _checked_owner(characters, owner)
                value = _portion(note, left, right, a, b, owner, clock)
                value['line_index'] = char.get('line_index')
                # 两处我局部词音核对：新增短下滑沿用原始连续音段和记谱参考音，不生成新的固定落音。
                if owner in motions:
                    if right - left > .5:
                        raise ValueError('短下滑超出局部短音范围，不能以标记代替重新核对。')
                    value['pitch_motion'] = {'kind': 'short_falling_glide', 'label': '短下滑',
                                             'terminal_pitch_unspecified': True,
                                             'listener_review_id': motions[owner]['listener_review_id']}
                replacement.append(value)
                new_ids.add(value['id'])
                changed_owners.add(owner)
            notes[index:index + 1] = replacement
        elif operation['kind'] == 'reassign_owner':
            owner = operation['owner']
            char = _checked_owner(characters, owner)
            note['source_lyric_index'] = note.get('lyric_index')
            note.update(lyric_index=owner, line_index=char.get('line_index'))
            note['local_owner_review'] = {'evidence_id': review.get('review_id'), 'ancestor_word_alignment': deepcopy(note.get('word_alignment'))}
            note['word_alignment'] = {'method': 'source_bound_local_ownership_review', 'requires_review': True,
                                      'scope': 'local_candidate_not_whole_song_certificate'}
            new_ids.add(identity)
            changed_owners.add(owner)
        else:
            raise ValueError('不支持的局部修订；不能借本入口改拍轴、音高或整曲伴奏。')
        operations.append(deepcopy(operation))
    if not operations:
        raise ValueError('局部修订没有操作。')
    for change in review.get('character_windows', []):
        char = _checked_owner(characters, change['character_index'])
        if char['index'] not in changed_owners:
            raise ValueError('不能修改局部操作之外的歌词。')
        left, right = change['seconds']
        if not math.isfinite(left) or not math.isfinite(right) or right <= left:
            raise ValueError('局部字窗不是正长度。')
        char['local_timing_review'] = {'ancestor_window': [char['start_seconds'], char['end_seconds']],
                                       'evidence_id': review.get('review_id'), 'onset_uncertainty_seconds': change.get('onset_uncertainty_seconds')}
        char.update(start_seconds=left, end_seconds=right)
    # 局部词音归属修订：新增只更新受影响字的首音／转音角色，不重排其它音符。
    for owner in changed_owners - {None}:
        group = sorted((n for n in notes if n.get('lyric_index') == owner), key=lambda n: n['start_seconds'])
        if not group:
            # 局部词音归属修订：修改明确轻声且无固定音高的字允许字音提示，其余搬空仍拒绝。
            # raise ValueError('局部重挂词搬空原字，必须先给出原声支持的替代音。')
            if not any(c['character_index'] == owner for c in voice.get('unpitched_lyric_cues', [])):
                raise ValueError('局部重挂词搬空原字，必须先给出原声支持的替代音。')
            continue
        if any(c['character_index'] == owner for c in voice.get('unpitched_lyric_cues', [])):
            raise ValueError('同一个字不能同时当固定音高和轻声不定音高入口。')
        for i, note in enumerate(group):
            # 局部词音归属修订：修改兼容未保存anchor的旧谱，原直读式保留。
            # if note['id'] in new_ids or note['anchor'] != (i == 0):
            if note['id'] in new_ids or note.get('anchor') != (i == 0):
                changed_ids.add(note['id'])
                note.update(anchor=i == 0, role='main' if i == 0 else 'turn')
    notes.sort(key=lambda n: (n['start_seconds'], n['end_seconds'], n['id']))
    if any(b['start_seconds'] < a['end_seconds'] - 1e-7 for a, b in zip(notes, notes[1:])):
        raise ValueError('局部修订造成实际人声重叠。')
    # 局部词音归属修订：新增只重建受影响小节，其它小节事件身份、歌词、延音与布局保持原样。
    timeline = measure_timeline(result)
    affected = {event['measure'] for event in voice['events'] if event.get('piece_id') in changed_ids}
    affected.update(m['number'] for m in timeline for n in notes if n['id'] in new_ids
                    and n['start_tick'] < m['end_tick'] and n['end_tick'] > m['start_tick'])
    # 局部词音归属修订：新增轻声提示所在小节也纳入局部重建，保证入口可见。
    affected.update(m['number'] for m in timeline for cue in voice.get('unpitched_lyric_cues', [])
                    if m['start_tick'] <= cue['start_tick'] < m['end_tick'])
    unchanged_events = [deepcopy(e) for e in voice['events'] if e['measure'] not in affected]
    temp = deepcopy(voice)
    rebuild_events(temp, [m for m in timeline if m['number'] in affected])
    for event in temp['events']:
        event['id'] = 'local_word_event_' + hashlib.sha256(json.dumps([event['measure'], event['start_tick'], event.get('piece_id'), event['duration_ticks']], ensure_ascii=False).encode()).hexdigest()[:16]
    voice['events'] = sorted(unchanged_events + temp['events'], key=lambda e: (e['measure'], e['start_tick']))
    voice['lyric_mapping'] = attach_lyrics(voice['events'], characters)
    # 局部词音归属修订：新增轻声字的独立映射，不伪造一个不存在的带音高event。
    for cue in voice.get('unpitched_lyric_cues', []):
        owner = cue['character_index']
        if owner in voice['lyric_mapping']['unmapped_character_indices']:
            voice['lyric_mapping']['unmapped_character_indices'].remove(owner)
            voice['lyric_mapping']['mapped_characters'] += 1
            voice['lyric_mapping']['mapping'].append({'character_index': owner, 'event_ids': [], 'unpitched_cue_id': cue['id']})
    voice['lyric_mapping']['unpitched_character_indices'] = [c['character_index'] for c in voice.get('unpitched_lyric_cues', [])]
    if voice['lyric_mapping']['issues'] or voice['lyric_mapping']['unmapped_character_indices']:
        raise ValueError('局部词音修订出现歌词逆序或漏字。')
    # 局部词音归属修订：新增当前计数重算，不借祖先的统计通过字段证明新数据。
    voice['statistics'].update(lyric_split_pieces=len(notes), classified_grace_notes=sum(bool(n.get('grace')) for n in notes),
                               main_notes=sum(n.get('role') == 'main' and not n.get('grace') for n in notes),
                               turn_notes=sum(n.get('role') == 'turn' and not n.get('grace') for n in notes))
    if 'rhythm_grouping' in voice['statistics']:
        voice['statistics']['local_revision_ancestor_rhythm_grouping'] = voice['statistics'].pop('rhythm_grouping')
    # 局部词音归属修订：新增独立完整保护，不因局部音节修改而重算一音伴奏或变更反复结构。
    if result['arrangements'] != project['arrangements'] or result['shared_analysis'] != project['shared_analysis'] or voice['timing'] != project['accepted_vocal_project']['timing']:
        raise ValueError('局部修订侵犯受保护伴奏、和声或拍轴。')
    old_plan, new_plan = build_repeat_plan(project), build_repeat_plan(result)
    if old_plan['repeat_groups'] != new_plan['repeat_groups'] or old_plan['reading_route'] != new_plan['reading_route']:
        raise ValueError('局部挂词改变已通过的长段复用路线。')
    signatures = [bar_signature(result, m) for m in timeline]
    if signatures != [bar_signature(project, m) for m in timeline]:
        raise ValueError('局部挂词改变真实吉他演奏。')
    audit = {'version': 1, 'review_id': review.get('review_id'), 'input_music_sha256': review['input_music_sha256'],
             'operations': operations, 'changed_existing_note_ids': sorted(changed_ids), 'new_note_ids': sorted(new_ids),
             'affected_measures': sorted(affected), 'changed_character_indices': sorted(changed_owners - {None}),
             'arrangements_identical': True, 'clock_and_measures_identical': True, 'guitar_signatures_identical': True,
             'repeat_groups_identical': True, 'whole_song_pitch_or_chord_recalculated': False,
             'music_acceptance': 'needs_review'}
    result['local_lyric_revision'] = audit
    # 局部词音归属修订：新增失效旧通过摘要，后续须对实际新词音重新验收；不删前轮未决。
    for key in ('guitar_readability_acceptance', 'guitar_source_bass_acceptance'):
        if key in result:
            result.pop(key)
    result['music_acceptance'] = deepcopy(project.get('music_acceptance', {}))
    result['music_acceptance'].update(status='needs_review', publication_allowed=False)
    return result, audit


def export_preserved_local_project(project_path, output):
    # 局部词音归属修订：新增后续重导的安全路线，歌词已变不触发整曲吉他重新编配。
    from score_export import read_json, save_json
    from source_timing_acceptance import require_isolated_output
    from guitar_source_bass_acceptance import require_changed_bass_source
    from guitar_readability_acceptance import assess_guitar_readability, require_guitar_readability
    from export_timing_revision import export_revision
    root = Path(__file__).resolve().parents[1]
    output = require_isolated_output(output, root)
    if output.exists() and any(output.iterdir()):
        raise ValueError('局部修订重导必须使用新的隔离目录，不能覆盖现有版本。')
    project = read_json(project_path)
    audit = project.get('local_lyric_revision', {})
    if audit.get('output_music_sha256') != fingerprint(music_payload(project)):
        raise ValueError('局部词音修订已失效，不能沿用旧验收或重新编配覆盖。')
    original_path = Path(audit.get('source_project', ''))
    if not local_path(original_path).is_file() or sha256(original_path) != audit.get('source_project_sha256'):
        raise ValueError('局部词音修订的认可原稿已改变或缺失。')
    original = read_json(original_path)
    if (project['arrangements'] != original['arrangements'] or project['shared_analysis'] != original['shared_analysis']
            or project['accepted_vocal_project']['timing'] != original['accepted_vocal_project']['timing']):
        raise ValueError('局部词音修订的伴奏或拍轴保护不成立。')
    require_changed_bass_source(project, project.get('guitar_source_bass_acceptance'))
    output.mkdir(parents=True, exist_ok=True)
    save_json(output / 'project.json', project)
    export_revision(output / 'project.json', output, instruments=('vocal', 'guitar'))
    final = assess_guitar_readability(project, build_repeat_plan(project), output_dir=output)
    require_guitar_readability(project, final)
    project['guitar_readability_acceptance'] = final
    save_json(output / 'project.json', project)
    return {'valid': True, 'output': str(output), 'music_acceptance': project['music_acceptance']['status'],
            'normal_entry_changed': False, 'guitar_rearranged': False}
