"""钢琴同步已认可词音：从已有和声整理钢琴标记，保留所有真实键音及拍轴。"""
# 钢琴同步已认可词音：新增演奏层和声标记整理；不运行原曲音高、和弦识别，不重配全曲键音。
from collections import defaultdict
from copy import deepcopy
import hashlib
import json

from guitar_variable_repeat import measure_timeline

POLICY = {'version': 1, 'minimum_harmony_ticks': 480, 'preferred_chords_per_bar': 2,
          # 钢琴同步已认可词音：修改只标记政策，原限制保留；只准有双窗口原低音证据的生成低音碰撞删减。
          # 'maximum_chords_per_full_bar': 4, 'note_pitch_or_time_changes_allowed': False}
          'maximum_chords_per_full_bar': 4, 'note_pitch_or_time_changes_allowed': False,
          'generated_colliding_bass_omission_allowed': True, 'minimum_source_bass_fraction': .55,
          'minimum_source_bass_margin': .25}


def fingerprint(value):
    # 钢琴同步已认可词音：新增实际材料摘要，修订标记不能脱离当前拍轴／歌词／音符单独生效。
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()


def source_payload(project):
    # 钢琴同步已认可词音：新增仅纳入真实来源，派生标记和验收结果自身不作为通过依据。
    piano = project['arrangements']['piano']
    return {'voice': project['accepted_vocal_project'], 'harmony': project['shared_analysis']['harmony'],
            'input_binding': project['shared_analysis'].get('input_binding'),
            'piano_notes': piano['notes'], 'pedal': piano.get('pedal', [])}


def identity(chord):
    # 钢琴同步已认可词音：新增同一组和弦音的等价归并；分解中的低音／转位不自动变成另一套和弦。
    return tuple(sorted(chord['pitch_classes']))


def overlap(a, b, c, d):
    # 钢琴同步已认可词音：新增实际持续范围交集。
    return max(0, min(b, d) - max(a, c))


def merge(rows):
    # 钢琴同步已认可词音：新增只合并连续等价和声，旧分析字典及引用身份保持在source_chord_ids。
    result = []
    for value in sorted(rows, key=lambda h: h['start_tick']):
        row = deepcopy(value)
        if result and result[-1]['end_tick'] == row['start_tick'] and identity(result[-1]) == identity(row):
            result[-1]['end_tick'] = row['end_tick']
            result[-1]['source_chord_ids'] = sorted(set(result[-1]['source_chord_ids'] + row['source_chord_ids']))
        else:
            result.append(row)
    return result


def _raw_view(project, timeline):
    # 钢琴同步已认可词音：新增排除无拍引子被旧投影夹到0拍的过期标签，不删引子录音或钢琴音符。
    first = timeline[0]['start_seconds']
    raw = [h for h in project['shared_analysis']['harmony'] if h['name'] != 'N.C.'
           and h.get('end_seconds', float('inf')) > first and h['end_tick'] > h['start_tick']]
    boundaries = sorted({0, timeline[-1]['end_tick'], *[t for h in raw for t in (h['start_tick'], h['end_tick'])]})
    rows = []
    for left, right in zip(boundaries, boundaries[1:]):
        active = [h for h in raw if h['start_tick'] <= left < h['end_tick']]
        if active:
            parent = max(active, key=lambda h: (h['start_tick'], h.get('start_seconds', 0)))
            rows.append({**deepcopy(parent), 'start_tick': left, 'end_tick': right,
                         'selected_source_id': parent['id'], 'source_chord_ids': [parent['id']]})
    return merge(rows)


def _plan_bar(project, measure, raw):
    # 钢琴同步已认可词音：新增只在不足一拍或过密小节选择已有和弦，稳定小节不重解。
    start, end = measure['start_tick'], measure['end_tick']
    notes = [n for n in project['arrangements']['piano']['notes'] if overlap(start, end, n['start_tick'], n['end_tick'])]
    local = [h for h in raw if overlap(start, end, h['start_tick'], h['end_tick'])]
    pool = {identity(h): h for h in local}
    if not pool:
        return [], {'measure': measure['number'], 'no_harmony_label': True}
    states = {}
    beats = list(range(start, end, 480))
    for i, tick in enumerate(beats):
        finish = min(end, tick + 480)
        # 钢琴同步已认可词音：新增低音换根约束只针对本拍新攻击，前拍自然释放尾部不伪装为本拍再次换和弦。
        bass = {n['pitch_midi'] % 12 for n in notes if n.get('role') == 'bass' and tick <= n['start_tick'] < finish}
        candidates = []
        for key, parent in pool.items():
            if not bass <= set(key):
                continue
            total = sum(overlap(tick, finish, n['start_tick'], n['end_tick']) * (3 if n.get('role') == 'bass' else 1)
                        for n in notes if n.get('role') != 'instrumental_melody')
            match = sum(overlap(tick, finish, n['start_tick'], n['end_tick']) * (3 if n.get('role') == 'bass' else 1)
                        for n in notes if n.get('role') != 'instrumental_melody' and n['pitch_midi'] % 12 in key)
            prior = sum(overlap(tick, finish, h['start_tick'], h['end_tick']) for h in local if identity(h) == key) / (finish-tick)
            score = 2 * match / max(1, total) + .25 * prior
            candidates.append((key, parent, score, match / max(1, total), sorted(bass)))
        if not candidates:
            raise ValueError('钢琴局部标记不能在保留本拍真实低音的前提下稳定，需另核原声：' + str((measure['number'], tick)))
        next_states = {}
        for key, parent, score, fit, bass_pcs in candidates:
            options = [(score, [], 0)] if i == 0 else [
                (old_score + score - (.65 if old_key != key else 0), path, changes + (old_key != key))
                for (old_key, changes), (old_score, path) in states.items() if changes + (old_key != key) <= 3]
            for value, path, changes in options:
                state = (key, changes)
                if state not in next_states or value > next_states[state][0]:
                    next_states[state] = (value, path + [(tick, finish, parent, fit, bass_pcs)])
        states = next_states
    _, path = max(states.values(), key=lambda pair: pair[0])
    rows = [{**deepcopy(h), 'start_tick': left, 'end_tick': right} for left, right, h, fit, bass in path]
    return merge(rows), {'measure': measure['number'], 'source_ids': sorted({h['selected_source_id'] for h in local}),
                         'beats': [{'start_tick': a, 'end_tick': b, 'selected_source_id': h['selected_source_id'],
                                    'key_tone_coverage': fit, 'new_bass_pitch_classes': bass}
                                   for a, b, h, fit, bass in path]}


def _resolve_generated_bass_collisions(project, bass_features):
    # 钢琴同步已认可词音：新增只处理时间规整撞在同一攻击点的生成低音，原始器乐旋律和独立真实演奏音不能删除。
    from accompaniment_analysis import SongClock
    piano = project['arrangements']['piano']
    grouped = defaultdict(list)
    for note in piano['notes']:
        if note.get('hand') == 'left' and note.get('role') == 'bass':
            grouped[note['start_tick']].append(note)
    removed = []
    clock = SongClock(project['accepted_vocal_project'])
    for tick, group in grouped.items():
        pitches = {n['pitch_midi'] for n in group}
        if len(pitches) < 2 or not any(abs(a-b) == 1 for a in pitches for b in pitches):
            continue
        # 钢琴同步已认可词音：新增同一原和弦内的真实半音配音不当作两个生成循环碰撞。
        if len({n.get('chord_id') for n in group}) < 2:
            continue
        if (bass_features is None or any(not n.get('phrase_harmony_generated') or n.get('source_melody_id') for n in group)
                or bass_features.source['sha256'] != project['shared_analysis']['input_binding']['sources']['bass']['sha256']):
            raise ValueError('生成低音碰撞缺少来源证据，不能擅自删减。')
        start = clock.seconds(tick)
        finish = clock.seconds(max(n['end_tick'] for n in group))
        windows = [(start, min(finish, start + .25)), (start, finish)]
        observations = []
        for a, b in windows:
            chroma = bass_features.chroma(a, b, low=28, high=60)
            observations.append({'seconds': [a, b], 'chroma': chroma.tolist(), 'dominant_pc': int(chroma.argmax())})
        winner = observations[0]['dominant_pc']
        if (any(o['dominant_pc'] != winner or o['chroma'][winner] < POLICY['minimum_source_bass_fraction']
                or any(o['chroma'][winner] - o['chroma'][n['pitch_midi'] % 12] < POLICY['minimum_source_bass_margin']
                       for n in group if n['pitch_midi'] % 12 != winner) for o in observations)
                or not any(n['pitch_midi'] % 12 == winner for n in group)):
            raise ValueError('生成低音碰撞的原声双窗口未支持同一个保留音。')
        for note in group:
            if note['pitch_midi'] % 12 != winner:
                removed.append({'note': deepcopy(note), 'reason': 'generated_cycle_anchors_collided_at_same_beat',
                                'source_sha256': bass_features.source['sha256'], 'windows': observations,
                                'retained_pitch_class': winner})
    ids = {row['note']['id'] for row in removed}
    piano['notes'] = [n for n in piano['notes'] if n['id'] not in ids]
    # 钢琴同步已认可词音：新增仅移除已删音的旧攻击引用，其它键音、指法、踏板及手位保持。
    for event in piano.get('attack_events', []):
        if any(identity in ids for identity in event.get('note_ids', [])):
            event['note_ids'] = [identity for identity in event['note_ids'] if identity not in ids]
    return removed


# 钢琴同步已认可词音：修改可选局部原低音证据参数，原标签专用签名保留。
# def revise_piano_labels(project):
def revise_piano_labels(project, bass_features=None):
    # 钢琴同步已认可词音：新增局部派生视图，实际键音、踏板、左右手及全部其它声部不变。
    result = deepcopy(project)
    # 钢琴同步已认可词音：新增先修有证据的局部生成碰撞，不重新规划其余音高或音符时间。
    removed = _resolve_generated_bass_collisions(result, bass_features)
    timeline = measure_timeline(project)
    raw = _raw_view(project, timeline)
    rows, audits, affected = [], [], []
    for measure in timeline:
        a, b = measure['start_tick'], measure['end_tick']
        local = [{**deepcopy(h), 'start_tick': max(a, h['start_tick']), 'end_tick': min(b, h['end_tick'])}
                 for h in raw if overlap(a, b, h['start_tick'], h['end_tick'])]
        local = merge(local)
        invalid = (not measure['pickup'] and (len(local) > (b-a)//480 or any(h['end_tick']-h['start_tick'] < 480 for h in local)))
        if invalid:
            # 钢琴同步已认可词音：修改使用局部碰撞删减后的实际键音，原未处理视图保留。
            # local, audit = _plan_bar(project, measure, raw)
            local, audit = _plan_bar(result, measure, raw)
            audits.append(audit)
            affected.append(measure['number'])
        rows.extend(local)
    harmony = merge(rows)
    for i, row in enumerate(harmony):
        row['id'] = 'piano_readable_harmony_' + str(i + 1)
    piano = result['arrangements']['piano']
    piano['readable_harmony'] = harmony
    # 钢琴同步已认可词音：修改摘要绑定实际保留键音，原未区分删减前后摘要保留。
    # piano['piano_label_revision'] = {'policy': deepcopy(POLICY), 'source_sha256': fingerprint(source_payload(project)),
    piano['piano_label_revision'] = {'policy': deepcopy(POLICY), 'source_sha256': fingerprint(source_payload(result)),
                                    'source_before_sha256': fingerprint(source_payload(project)),
                                    'harmony_sha256': fingerprint(harmony), 'affected_measures': affected,
                                    # 钢琴同步已认可词音：修改真实范围记录，原完全相同声明保留。
                                    # 'bar_reviews': audits, 'all_notes_and_pedal_identical': True,
                                    'bar_reviews': audits, 'all_surviving_notes_and_pedal_identical': True,
                                    'removed_generated_bass_notes': removed,
                                    'source_harmony_reidentified': False}
    # 钢琴同步已认可词音：修改仅允许明确记录的生成低音省略，原全相等式保留；其它音乐仍逐字段比较。
    # if source_payload(result) != source_payload(project) or result['arrangements']['guitar'] != project['arrangements']['guitar']:
    before_payload, after_payload = deepcopy(source_payload(project)), deepcopy(source_payload(result))
    removed_ids = {r['note']['id'] for r in removed}
    before_payload['piano_notes'] = [n for n in before_payload['piano_notes'] if n['id'] not in removed_ids]
    if before_payload != after_payload or result['arrangements']['guitar'] != project['arrangements']['guitar']:
        raise ValueError('钢琴局部标记整理侵犯了原音符、拍轴、共享和声或吉他。')
    return result


def assess_piano_labels(project):
    # 钢琴同步已认可词音：新增独立来源／实际控制密度检查，不用旧通过标记替代检查。
    piano = project['arrangements']['piano']
    audit, harmony = piano.get('piano_label_revision', {}), piano.get('readable_harmony', [])
    errors = []
    if audit.get('source_sha256') != fingerprint(source_payload(project)) or audit.get('harmony_sha256') != fingerprint(harmony):
        errors.append('piano_label_source_or_output_changed')
    originals = {h['id']: h for h in project['shared_analysis']['harmony']}
    timeline = measure_timeline(project)
    for row in harmony:
        parent = originals.get(row.get('selected_source_id'))
        if parent is None or any(row.get(k) != parent.get(k) for k in ('root_pc', 'quality', 'pitch_classes', 'bass_pc', 'name')):
            errors.append('piano_label_not_from_existing_harmony:' + row['id'])
        if row['end_tick'] - row['start_tick'] < 480 and row['start_tick'] >= timeline[0]['end_tick']:
            errors.append('piano_harmony_shorter_than_one_beat:' + row['id'])
    for measure in timeline:
        a, b = measure['start_tick'], measure['end_tick']
        local = [h for h in harmony if overlap(a, b, h['start_tick'], h['end_tick'])]
        if len(local) > max(1, (b-a)//480):
            errors.append('too_many_piano_harmonies:' + str(measure['number']))
    for audit_bar in audit.get('bar_reviews', []):
        for cell in audit_bar['beats']:
            parent = originals[cell['selected_source_id']]
            bass = [n for n in piano['notes'] if n.get('role') == 'bass' and cell['start_tick'] <= n['start_tick'] < cell['end_tick']]
            if any(n['pitch_midi'] % 12 not in parent['pitch_classes'] for n in bass):
                errors.append('piano_new_bass_not_in_held_harmony:' + str(cell['start_tick']))
    return {'valid': not errors, 'errors': errors, 'scope': 'existing_piano_harmony_labels_and_new_bass_attacks',
            'changed_note_pitches_or_times': False, 'removed_generated_bass_notes': len(audit.get('removed_generated_bass_notes', [])),
            'affected_measures': audit.get('affected_measures', []),
            'harmonies': len(harmony), 'source_sha256': fingerprint(source_payload(project))}
