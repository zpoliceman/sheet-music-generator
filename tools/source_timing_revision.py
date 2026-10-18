"""最小拍轴与词音伴奏修复：仅时间投影、局部字头复核及祖先保护。"""
# 最小拍轴与词音伴奏修复：新增显式隔离路线；不调用整曲音高、调性、和弦或吉他配音解码。
from collections import defaultdict
from copy import deepcopy
import bisect
import math
import numpy as np
from score_export import PPQ, TempoMap, split_interval, attach_lyrics, sha256
from accompaniment_analysis import SongClock
from phrase_harmony_plan import arrangement_view
from source_timing_acceptance import require_clock_passed, fingerprint

POLICY = {'version': 1, 'name': 'source_bound_time_projection', 'vocal_grid_ticks': 30,
          'accompaniment_grid_ticks': 120, 'maximum_unsupported_initial_seconds': .4,
          'whole_song_pitch_chord_or_key_recognition': False, 'normal_collection_write': False,
          'guitar_maximum_fret': 12, 'minimum_continuous_repeat_measures': 8}


def projected_tick(mapping, second, grid=30):
    # 最小拍轴与词音伴奏修复：新增从原曲绝对秒直接投影；不按旧小节编号倍增或平移歌词。
    return max(0, int(round(mapping.seconds_to_quarters(second) * PPQ / grid)) * grid)


def refine_word_heads(vocal, acoustic, verifier):
    # 最小拍轴与词音伴奏修复：新增局部清辅音检查，真实滑音／有声声母及尾端全部保留。
    notes = deepcopy(vocal['quantized_notes'])
    groups = defaultdict(list)
    for note in notes:
        if note.get('lyric_index') is not None and not note.get('grace'):
            groups[note['lyric_index']].append(note)
    edits, conflicts, protected = [], [], []
    for char in vocal['lyrics']['characters']:
        group = sorted(groups.get(char['index'], []), key=lambda n: n['start_seconds'])
        if not group:
            conflicts.append({'character_index': char['index'], 'kind': 'existing_word_without_note'})
            continue
        note = group[0]
        phonemes = [p for p in char.get('phonemes', []) if not p.get('skipped') and p.get('start_seconds') is not None]
        nucleus = next((p for p in phonemes if p.get('role') == 'nucleus'), None)
        if note['start_seconds'] > char['end_seconds'] - .015:
            conflicts.append({'character_index': char['index'], 'kind': 'word_window_and_existing_note_ownership_conflict',
                              'word_seconds': [char['start_seconds'], char['end_seconds']],
                              'note_seconds': [note['start_seconds'], note['end_seconds']],
                              'action': 'preserve_and_mark_unresolved_do_not_borrow_next_word'})
        if not nucleus or not phonemes or phonemes[0].get('role') != 'initial':
            continue
        start, target = note['start_seconds'], nucleus['start_seconds']
        if not .12 <= target - start <= POLICY['maximum_unsupported_initial_seconds'] or target >= note['end_seconds'] - .08:
            continue
        prefix = acoustic.midi[(acoustic.times >= start) & (acoustic.times < target - .015)]
        body = acoustic.midi[(acoustic.times >= target) & (acoustic.times < min(note['end_seconds'], target + .18))]
        voiced = float(np.mean(np.isfinite(prefix))) if len(prefix) else 0.
        matched = float(np.mean(np.isfinite(body) & (abs(body - note['pitch_midi']) < .65))) if len(body) else 0.
        if voiced > .35 or matched < .65:
            protected.append({'character_index': char['index'], 'note_id': note['id'], 'prefix_voiced_fraction': voiced,
                              'action': 'keep_real_early_pitch_or_uncertain_nucleus'})
            continue
        check = verifier({'pitch_midi': note['pitch_midi'], 'start_seconds': target,
                          'end_seconds': min(note['end_seconds'], target + .18)})
        if check['yin_agreement'] < .8 or check['vocal_dbfs'] < -45 or check['foreground_ratio_db'] < -6:
            continue
        edits.append({'note_id': note['id'], 'character_index': char['index'], 'before_start_seconds': start,
                      'after_start_seconds': target, 'end_seconds_preserved': note['end_seconds'],
                      'pitch_midi_preserved': note['pitch_midi'], 'independent_audio': check})
        note['start_seconds'] = target
        note['time_only_head_correction'] = deepcopy(edits[-1])
    return notes, {'edits': edits, 'unresolved': conflicts, 'early_pitch_protected': protected}


def rebuild_events(vocal, timeline):
    # 最小拍轴与词音伴奏修复：新增按真实小节范围切分，跨线只加延音，不裁断原有长音。
    old = defaultdict(list)
    for event in vocal['events']:
        old[event.get('piece_id')].append(event)
    events = []
    for measure in timeline:
        start, end = measure['start_tick'], measure['end_tick']
        cursor = start
        for note in vocal['quantized_notes']:
            # 最小拍轴与词音伴奏修复：修改弱起线上的零记谱时值倚音判定，原持续音条件保留。
            # if note['start_tick'] >= end or note['end_tick'] <= start:
            # 最小拍轴与词音伴奏修复：修改表达式为显式可见区间，原条件表达式保留，便于复核零时值语义。
            # if (not start <= note['start_tick'] < end) if note.get('grace') else (note['start_tick'] >= end or note['end_tick'] <= start):
            visible = start <= note['start_tick'] < end if note.get('grace') else note['start_tick'] < end and note['end_tick'] > start
            if not visible:
                continue
            a, b = max(start, note['start_tick']), min(end, note['end_tick'])
            if a > cursor:
                for part in split_interval(cursor - start, a - start, end - start):
                    events.append({**part, 'start_tick': part['start_tick'] + start, 'piece_id': None,
                                   'pitch_midi': None, 'grace': False, 'ties': [], 'lyric_index': None,
                                   'measure': measure['number'], 'offset_ticks': part['start_tick']})
                # 最小拍轴与词音伴奏修复：新增填休止后推进游标，倚音不应令同一空白再次计时。
                cursor = a
            template = deepcopy(old[note['id']][0]) if old[note['id']] else {}
            for field in ('id', 'lyric', 'slurs', 'tuplet', 'tuplet_start', 'tuplet_stop'):
                template.pop(field, None)
            if note.get('grace'):
                events.append({**template, 'start_tick': a, 'duration_ticks': 0, 'piece_id': note['id'],
                               'pitch_midi': note['pitch_midi'], 'grace': True, 'type': 'eighth', 'dots': 0,
                               'ties': [], 'measure': measure['number'], 'offset_ticks': a - start,
                               'lyric_index': note.get('lyric_index')})
                continue
            for part in split_interval(a - start, b - start, end - start):
                tick, duration = part['start_tick'] + start, part['duration_ticks']
                events.append({**template, **part, 'start_tick': tick, 'piece_id': note['id'],
                               'pitch_midi': note['pitch_midi'], 'grace': False, 'lyric_index': note.get('lyric_index'),
                               'ties': (['stop'] if tick > note['start_tick'] else []) +
                                       (['start'] if tick + duration < note['end_tick'] else []),
                               'measure': measure['number'], 'offset_ticks': tick - start})
                # 最小拍轴与词音伴奏修复：新增转音连奏两端迁移，改小节线不能删掉原有滑音／连奏关系。
                slurs = [s for event in old[note['id']] for s in event.get('slurs', [])
                         if (s['type'] == 'start' and tick == note['start_tick'])
                         or (s['type'] == 'stop' and tick + duration == note['end_tick'])]
                if slurs:
                    events[-1]['slurs'] = deepcopy(slurs)
            cursor = max(cursor, b)
        if cursor < end:
            for part in split_interval(cursor - start, end - start, end - start):
                events.append({**part, 'start_tick': part['start_tick'] + start, 'piece_id': None,
                               'pitch_midi': None, 'grace': False, 'ties': [], 'lyric_index': None,
                               'measure': measure['number'], 'offset_ticks': part['start_tick']})
    for index, event in enumerate(events):
        event['id'] = 'timing_event_' + str(index + 1)
    vocal['events'] = events
    vocal['lyric_mapping'] = attach_lyrics(events, vocal['lyrics']['characters'])


def project_voice(original, candidate, source_notes):
    # 最小拍轴与词音伴奏修复：新增保留音符身份与完整来源尾端的联合边界量化，倚音分类不随拍单位重跑。
    vocal = deepcopy(original)
    mapping = TempoMap(candidate['knots'])
    notes = deepcopy(source_notes)
    for note in notes:
        a = projected_tick(mapping, note['start_seconds'])
        b = max(a + 30, projected_tick(mapping, note['end_seconds']))
        note.update(start_tick=a, end_tick=b, playback_start_tick=a, playback_end_tick=b,
                    quantized_start_seconds=mapping.quarters_to_seconds(a / PPQ),
                    quantized_end_seconds=mapping.quarters_to_seconds(b / PPQ))
        note['time_projection_source_seconds'] = [note['start_seconds'], note['end_seconds']]
    for a, b in zip(notes, notes[1:]):
        if not a.get('grace') and not b.get('grace') and a['end_tick'] > b['start_tick']:
            boundary = max(a['start_tick'] + 30, b['start_tick'])
            if boundary >= b['end_tick']:
                raise ValueError('原词音无法在细网格保持顺序，须局部复核，不能吞音')
            a.update(end_tick=boundary, playback_end_tick=boundary)
            b.update(start_tick=boundary, playback_start_tick=boundary)
    # 最小拍轴与词音伴奏修复：新增记谱边界与真实发声分开；细网格保留试听，正文用受来源误差约束的规整音值。
    regularize_notation(notes, mapping, original['lyrics']['characters'])
    for note in notes:
        note['quantized_start_seconds'] = mapping.quarters_to_seconds(note['start_tick'] / PPQ)
        note['quantized_end_seconds'] = mapping.quarters_to_seconds(note['end_tick'] / PPQ)
        note['start_error_seconds'] = note['quantized_start_seconds'] - note['start_seconds']
        note['end_error_seconds'] = note['quantized_end_seconds'] - note['end_seconds']
    vocal['quantized_notes'] = notes
    vocal['timing'].update(knots=deepcopy(candidate['knots']), score_start_quarter=0., meter=[4, 4],
                            measure_timeline=deepcopy(candidate['measure_timeline']),
                            steady_tempo_bpm=float(60 / np.median(np.diff(mapping.seconds))),
                            local_beat_clock={'status': 'tracked', 'kind': 'source_bound_time_only'},
                            initial_pickup_measure=bool(candidate['measure_timeline'][0]['pickup']))
    vocal['statistics'].update(measure_count=len(candidate['measure_timeline']), bar_ticks=1920,
                               total_ticks=candidate['measure_timeline'][-1]['end_tick'])
    # 最小拍轴与词音伴奏修复：新增当前记谱与实际播放误差分别统计，旧拍轴的误差数字不混入本轮结论。
    onset_errors = [abs(n['start_error_seconds']) for n in notes if not n.get('grace')]
    vocal['statistics']['quantization_error_seconds'] = {'median_abs': float(np.median(onset_errors)),
                                                        'p95_abs': float(np.percentile(onset_errors, 95)), 'max_abs': max(onset_errors)}
    vocal['statistics']['notation_timing_policy'] = {'version': 1, 'grid': 'source_bounded_regular',
                                                    'performance_source_seconds_preserved': True, 'unvoiced_initial_articulation_is_not_a_new_rest': True}
    vocal['tempo_events'] = [{'tick': int(round(row['quarter'] * PPQ)), 'bpm': mapping.tempo_at(row['quarter'])}
                             for row in mapping.knots[:-1]]
    # 最小拍轴与词音伴奏修复：新增最高层修订指纹；历史来源层保留作祖先，不能假称它已验收新拍轴。
    vocal['time_only_revision'] = {'version': 1, 'ancestor_vocal_sha256': fingerprint(original),
                                  'candidate_sha256': fingerprint(candidate), 'source_duration_seconds': candidate['source_duration_seconds'],
                                  'audio_origin_seconds': 0., 'whole_pitch_decoder_called': False}
    rebuild_events(vocal, candidate['measure_timeline'])
    return vocal


def regularize_notation(notes, mapping, characters):
    # 最小拍轴与词音伴奏修复：新增来源约束的单声部起音联合选择；不重识别音高、不重分倚音、不改变实际播放完整音值。
    normal = [n for n in notes if not n.get('grace')]
    normal.sort(key=lambda n: n['start_seconds'])
    previous_words = set()
    states = {None: (0., ())}
    for index, note in enumerate(normal):
        observed = mapping.seconds_to_quarters(note['start_seconds']) * PPQ
        head = note.get('lyric_index') is not None and note.get('lyric_index') not in previous_words
        previous_words.add(note.get('lyric_index'))
        choices = [tick for tick in range(max(0, round(observed / 30) * 30 - 90), round(observed / 30) * 30 + 91, 30)
                   if abs(tick - observed) <= PPQ * .18]
        following = {}
        # 最小拍轴与词音伴奏修复：新增长音占位硬约束，起音联合选择不能先压短旧长音、再靠尾端补救。
        previous_length = (mapping.seconds_to_quarters(normal[index - 1]['end_seconds'])
                           - mapping.seconds_to_quarters(normal[index - 1]['start_seconds'])) if index else 0.
        minimum_step = max(30, math.ceil(previous_length * .85 * PPQ / 30) * 30) if previous_length >= .5 else 30
        for tick in choices:
            complexity = 0. if tick % 120 == 0 else (1.6 if head else .65) if tick % 60 == 0 else (2.4 if head else 1.2)
            cost = ((tick - observed) / PPQ / .10) ** 2 + complexity
            candidates = [(old_cost + cost, path + (tick,)) for prior, (old_cost, path) in states.items()
                          # 最小拍轴与词音伴奏修复：修改原最小30tick约束，旧式保留：if prior is None or tick - prior >= 30。
                          if prior is None or tick - prior >= minimum_step]
            if candidates:
                following[tick] = min(candidates, key=lambda row: (row[0], row[1]))
        if not following:
            raise ValueError('规整记谱无法保留所有原音起点，停止，不吞音：' + note['id'])
        states = following
    selected = min(states.values(), key=lambda row: (row[0], row[1]))[1]
    lookup = {c['index']: c for c in characters}
    for index, (note, tick) in enumerate(zip(normal, selected)):
        original_end = mapping.seconds_to_quarters(note['end_seconds']) * PPQ
        source_length = mapping.seconds_to_quarters(note['end_seconds']) - mapping.seconds_to_quarters(note['start_seconds'])
        grid = 120 if source_length >= .25 else 60 if source_length >= .12 else 30
        end = max(tick + 30, round(original_end / grid) * grid)
        # 最小拍轴与词音伴奏修复：新增长音最小记谱覆盖，真实播放仍完整保留，不能为规则音值把长音压为短装饰。
        if source_length >= .5:
            end = max(end, tick + math.ceil(source_length * .85 * PPQ / 30) * 30)
        bridge = None
        if index + 1 < len(normal):
            nxt = normal[index + 1]
            gap = nxt['start_seconds'] - note['end_seconds']
            before, after = lookup.get(note.get('lyric_index'), {}), lookup.get(nxt.get('lyric_index'), {})
            correction = nxt.get('time_only_head_correction')
            articulation = (correction is not None and after.get('index') == before.get('index', -2) + 1
                            and after.get('line_index') == before.get('line_index')
                            and correction['before_start_seconds'] - note['end_seconds'] <= .08 and gap <= .4)
            if gap <= .12 or articulation:
                end = selected[index + 1]
                bridge = 'source_contiguous' if gap <= .12 else 'verified_unvoiced_initial_between_adjacent_words'
            else:
                end = min(end, selected[index + 1])
        if end <= tick or (source_length >= .5 and (end - tick) / PPQ < source_length * .75):
            raise ValueError('规整记谱会过度缩短已有长音，停止：' + note['id'])
        note.update(start_tick=tick, end_tick=end)
        note['time_only_notation'] = {'version': 1, 'performance_interval_preserved_in_playback_ticks': True,
                                      'source_bounded_grid': True, 'articulation_bridge': bridge}
    by_id = {n['id']: n for n in notes}
    for note in notes:
        if note.get('grace'):
            anchor = by_id.get(note.get('anchor_id')) or next((n for n in normal if n['start_seconds'] >= note['end_seconds']), None)
            if anchor is None:
                raise ValueError('已有倚音缺主音，不重新分类或删除')
            note.update(start_tick=anchor['start_tick'], end_tick=anchor['start_tick'])
    notes.sort(key=lambda n: (n['start_tick'], not n.get('grace'), n['start_seconds']))


def project_arrangements(project, vocal, features):
    # 最小拍轴与词音伴奏修复：新增来源秒投影及有限起音对齐；原有和弦顺序、音高、弦品、力度和两手材料不重猜。
    original = project['accepted_vocal_project']
    old_clock, mapping = SongClock(original), TempoMap(vocal['timing']['knots'])
    total = vocal['statistics']['total_ticks']
    shared = deepcopy(arrangement_view(project['shared_analysis'], original))
    for field in ('phrase_harmony_plan', 'arranged_harmony', 'approved_section_preservation'):
        shared.pop(field, None)
    shared['_phrase_harmony_view'] = True
    audit = {'excluded_unmetered_notes': {}, 'onset_changes': {}, 'pitch_or_chord_decoder_called': False}

    def retime_row(row, grid=120):
        row = deepcopy(row)
        for name in ('start_tick', 'end_tick', 'tick'):
            if name in row:
                row[name] = min(total, projected_tick(mapping, old_clock.seconds(row[name]), grid))
        if 'start_tick' in row and 'end_tick' in row and row['end_tick'] <= row['start_tick']:
            row['end_tick'] = min(total, row['start_tick'] + grid)
        return row

    shared['harmony'] = [retime_row(h) for h in shared['harmony']]
    shared['sections'] = [retime_row(s) for s in shared['sections']]
    shared['timing'], shared['statistics'], shared['notation'] = deepcopy(vocal['timing']), deepcopy(vocal['statistics']), deepcopy(vocal['notation'])
    arrangements = {}
    for name, ancestor in project['arrangements'].items():
        arrangement = deepcopy(ancestor)
        source_feature = features.get('six_guitar' if name == 'guitar' else 'accompaniment')
        rendered, excluded, changes = [], [], []
        # 最小拍轴与词音伴奏修复：新增先核对循环互斥性；两个不同原循环竞争同一拍点时保留原声时间，不能压成一次拨弦。
        cycle_origins = sorted({n['pattern_cycle_origin_tick'] for n in ancestor['notes']
                                if n.get('onset_origin') == 'arranged_common_pattern' and n.get('pattern_cycle_origin_tick') is not None})
        anchor_groups = defaultdict(list)
        for origin in cycle_origins:
            anchor_groups[projected_tick(mapping, old_clock.seconds(origin), 480)].append(origin)
        # 最小拍轴与词音伴奏修复：修改循环互斥处理，原跳过式保留；整拍冲突时仅细化相关循环的完整锚点，内部音序不变。
        # cycle_anchors = {origins[0]: anchor for anchor, origins in anchor_groups.items() if len(origins) == 1}
        cycle_grids = {origin: 480 for origin in cycle_origins}
        cycle_anchors = {origin: projected_tick(mapping, old_clock.seconds(origin), 480) for origin in cycle_origins}
        lanes_for_cycles = defaultdict(list)
        for note in ancestor['notes']:
            lane = note['string'] if name == 'guitar' else (note['hand'], note['pitch_midi'])
            lanes_for_cycles[lane].append(note)
        def cycle_start(note):
            origin = note.get('pattern_cycle_origin_tick') if note.get('onset_origin') == 'arranged_common_pattern' else None
            if origin not in cycle_anchors:
                return projected_tick(mapping, old_clock.seconds(note['start_tick']), 30)
            relative = mapping.seconds_to_quarters(old_clock.seconds(note['start_tick'])) - mapping.seconds_to_quarters(old_clock.seconds(origin))
            return max(0, cycle_anchors[origin] + round(relative * 480 / 30) * 30)
        for iteration in range(5):
            conflicts = set()
            for lane in lanes_for_cycles.values():
                ordered = sorted(lane, key=lambda n: n['start_tick'])
                for a, b in zip(ordered, ordered[1:]):
                    if old_clock.seconds(a['start_tick']) < mapping.seconds[0] or old_clock.seconds(b['start_tick']) >= mapping.seconds[-1]:
                        continue
                    if cycle_start(a) >= cycle_start(b):
                        conflicts.update(n.get('pattern_cycle_origin_tick') for n in (a, b)
                                         if n.get('onset_origin') == 'arranged_common_pattern')
            if not conflicts:
                break
            for origin in conflicts:
                cycle_grids[origin] = max(30, cycle_grids[origin] // 2)
                cycle_anchors[origin] = projected_tick(mapping, old_clock.seconds(origin), cycle_grids[origin])
        for note in ancestor['notes']:
            a, b = old_clock.seconds(note['start_tick']), old_clock.seconds(note['end_tick'])
            if a < mapping.seconds[0] - .04 or a >= mapping.seconds[-1]:
                excluded.append({'id': note['id'], 'pitch_midi': note['pitch_midi'], 'seconds': [a, b],
                                 'reason': 'outside_metered_music_original_and_ancestor_retained'})
                continue
            # 最小拍轴与词音伴奏修复：修改钢琴源器乐的细网格，原统一粗网格式保留；不同手内起音不能被吸成不可弹的大跨度和弦。
            # revised = retime_row(note, 120)
            revised = retime_row(note, 30 if name == 'piano' and note.get('onset_origin') != 'arranged_common_pattern' else 120)
            # 最小拍轴与词音伴奏修复：新增可回退的原声细网格；独立吸附不能令同弦两次起音重合。
            revised['time_only_original_fine_start_tick'] = projected_tick(mapping, a, 30)
            revised['time_only_original_fine_end_tick'] = max(revised['time_only_original_fine_start_tick'] + 30, projected_tick(mapping, b, 30))
            # 最小拍轴与词音伴奏修复：新增用独立源起音校时，不以相同和弦名制造不存在的新音符。
            matches = [] if source_feature is None else [attack for attack in source_feature.attacks
                if abs(attack['seconds'] - a) <= .22 and any(p['pitch_midi'] % 12 == note['pitch_midi'] % 12
                and p['relative_weight'] >= .35 for p in attack['pitches'])]
            # 最小拍轴与词音伴奏修复：新增钢琴原器乐只投影来源时间；不能用同音级攻击合并不同音区的起音。
            if name == 'piano' and note.get('onset_origin') != 'arranged_common_pattern':
                matches = []
            if matches:
                attack = min(matches, key=lambda r: abs(r['seconds'] - a))
                tick = min(total - 120, projected_tick(mapping, attack['seconds'], 120))
                revised['start_tick'] = tick
                revised['end_tick'] = min(total, max(tick + 120, projected_tick(mapping, b, 120)))
                revised['time_only_source_attack_seconds'] = attack['seconds']
            # 最小拍轴与词音伴奏修复：新增共同分解型按整个循环校时；不能只把旧拍号换成新小节号而留下错位低音。
            # 最小拍轴与词音伴奏修复：修改循环启用条件，原无互斥检查式保留。
            # if note.get('onset_origin') == 'arranged_common_pattern' and note.get('pattern_cycle_origin_tick') is not None:
            if note.get('onset_origin') == 'arranged_common_pattern' and note.get('pattern_cycle_origin_tick') in cycle_anchors:
                origin_second = old_clock.seconds(note['pattern_cycle_origin_tick'])
                # 最小拍轴与词音伴奏修复：修改读取已检查的循环锚点，原直接取整式保留。
                # anchor = projected_tick(mapping, origin_second, 480)
                anchor = cycle_anchors[note['pattern_cycle_origin_tick']]
                origin_quarter = mapping.seconds_to_quarters(origin_second)
                actual_quarter = mapping.seconds_to_quarters(a)
                end_quarter = mapping.seconds_to_quarters(b)
                # 最小拍轴与词音伴奏修复：修改循环内部投影，原过粗网格式保留；完整循环移位，内部原有密集起音不强行合并。
                # target = max(0, anchor + round((actual_quarter - origin_quarter) * 480 / 120) * 120)
                # finish = min(total, max(target + 120, anchor + round((end_quarter - origin_quarter) * 480 / 120) * 120))
                target = max(0, anchor + round((actual_quarter - origin_quarter) * 480 / 30) * 30)
                finish = min(total, max(target + 30, anchor + round((end_quarter - origin_quarter) * 480 / 30) * 30))
                revised.update(start_tick=target, end_tick=finish,
                               time_only_pattern_cycle={'old_origin_tick': note['pattern_cycle_origin_tick'], 'new_origin_tick': anchor,
                                                        'whole_cycle_shift_quarters': anchor / 480 - origin_quarter,
                                                        'cycle_anchor_grid_ticks': cycle_grids[note['pattern_cycle_origin_tick']]})
                revised['time_only_original_fine_start_tick'], revised['time_only_original_fine_end_tick'] = target, finish
            if revised['end_tick'] <= revised['start_tick']:
                excluded.append({'id': note['id'], 'reason': 'outside_last_measure', 'seconds': [a, b]})
                continue
            changes.append({'id': note['id'], 'before_seconds': a, 'after_seconds': mapping.quarters_to_seconds(revised['start_tick'] / PPQ),
                            'matched_original_attack': bool(matches)})
            rendered.append(revised)
        rendered.sort(key=lambda n: (n['start_tick'], n.get('string', 0), n['pitch_midi']))
        # 最小拍轴与词音伴奏修复：新增每条弦／同手同音的单人延音截止，保留原身份和音高；截断属于待听审差异。
        by_lane = defaultdict(list)
        for note in rendered:
            lane = note['string'] if name == 'guitar' else (note['hand'], note['pitch_midi'])
            by_lane[lane].append(note)
        collisions = []
        for lane in by_lane.values():
            # 最小拍轴与词音伴奏修复：新增按原声顺序限制每次吸附的邻域，避免粗网格先打乱同弦顺序再反复回退。
            lane.sort(key=lambda n: n['time_only_original_fine_start_tick'])
            for index, note in enumerate(lane):
                original_tick = note['time_only_original_fine_start_tick']
                gaps = ([original_tick - lane[index - 1]['time_only_original_fine_start_tick']] if index else [])
                if index + 1 < len(lane):
                    gaps.append(lane[index + 1]['time_only_original_fine_start_tick'] - original_tick)
                limit = max(0, min(gaps) / 2 - 15) if gaps else 120
                if abs(note['start_tick'] - original_tick) > limit:
                    note['start_tick'], note['end_tick'] = original_tick, min(total, note['time_only_original_fine_end_tick'])
                    note['time_only_attack_snap_rejected'] = 'preserve_neighbour_source_attack_order'
            # 最小拍轴与词音伴奏修复：新增联合顺序约束，保留确实密集的原音，拒绝把两个起音吸到同一攻击点。
            for a, b in zip(lane, lane[1:]):
                if a['start_tick'] >= b['start_tick']:
                    for note in (a, b):
                        note['start_tick'] = note['time_only_original_fine_start_tick']
                        note['end_tick'] = min(total, note['time_only_original_fine_end_tick'])
                        note['time_only_attack_snap_rejected'] = 'preserve_same_string_or_hand_attack_order'
            lane.sort(key=lambda n: n['start_tick'])
            for a, b in zip(lane, lane[1:]):
                if a['end_tick'] > b['start_tick']:
                    if a['start_tick'] == b['start_tick']:
                        # 最小拍轴与词音伴奏修复：修改错误信息，原简略异常保留；暴露具体身份便于可重放诊断。
                        # raise ValueError('时间投影产生同弦／同音同时重发，须局部复核，不能静默删除')
                        raise ValueError('时间投影产生同弦／同音同时重发，须局部复核：' + str((name, a['id'], b['id'], a['start_tick'], a['time_only_original_fine_start_tick'], b['time_only_original_fine_start_tick'])))
                    collisions.append({'id': a['id'], 'before_end_tick': a['end_tick'], 'after_end_tick': b['start_tick']})
                    a['end_tick'] = b['start_tick']
        arrangement['notes'] = rendered
        # 最小拍轴与词音伴奏修复：修改踏板量化的零长度重发，原逐项式保留；同刻取原顺序末状态并去掉冗余状态。
        # arrangement['pedal'] = [retime_row(row) for row in ancestor.get('pedal', [])]
        pedal_by_tick = {row['tick']: row for row in (retime_row(p) for p in sorted(ancestor.get('pedal', []), key=lambda r: r['tick']))}
        arrangement['pedal'] = []
        state = 0
        for tick, pedal in sorted(pedal_by_tick.items()):
            if bool(pedal['value']) != bool(state):
                arrangement['pedal'].append(pedal)
                state = pedal['value']
        arrangement['notation_regions'] = [retime_row(row) for row in ancestor.get('notation_regions', [])]
        # 最小拍轴与词音伴奏修复：新增指型图范围同投影，图式与实际弦品完全沿用祖先，不重新猜指法。
        arrangement['fingering_diagrams'] = [retime_row(row) for row in ancestor.get('fingering_diagrams', [])]
        arrangement['configuration']['capo_segments'] = [retime_row(row) for row in ancestor['configuration'].get('capo_segments', [])]
        arrangement['time_only_revision'] = {'version': 1, 'ancestor_note_signature': fingerprint(ancestor['notes']),
                                            'sustain_collision_adjustments': collisions, 'pitch_and_fret_preserved': True}
        if name == 'guitar':
            arrangement['configuration']['maximum_fret'] = 12
            if any(note['fret'] > 12 for note in rendered):
                raise ValueError('祖先含超过12品的音，须走既有通用乐句降八度，不能放宽限制')
        # 最小拍轴与词音伴奏修复：新增只重排手位时间，已有音高、弦品及手的分配保持；不调用钢琴音区重配。
        from accompaniment_arrange import piano_hand_positions, validate_playability
        if name == 'guitar':
            from guitar_grip_policy import grip_position_path
            arrangement['hand_positions'] = [retime_row(row, 30) for row in ancestor.get('hand_positions', [])]
            path = grip_position_path(arrangement, vocal)
            # 最小拍轴与词音伴奏修复：新增时间改变后无解的完整持握图撤回；只退为实际数字谱，音符／弦品不改、不虚标x。
            withdrawn = []
            while not path['valid']:
                bad = next((d for d in arrangement['fingering_diagrams'] if d['id'] == path.get('chart_id')), None)
                if bad is None:
                    break
                arrangement['fingering_diagrams'].remove(bad)
                withdrawn.append({'diagram_id': bad['id'], 'reason': path['reason'], 'tick': path['tick']})
                for region in arrangement['notation_regions']:
                    if region['start_tick'] < bad['end_tick'] and region['end_tick'] > bad['start_tick']:
                        region.update(mode='solo_tab', reason='time_revision_unplayable_diagram_withdrawn')
                path = grip_position_path(arrangement, vocal)
            arrangement['time_only_revision']['withdrawn_unplayable_diagrams'] = withdrawn
            arrangement['time_only_revision']['hand_time_plan'] = {k: v for k, v in path.items() if k != 'positions'}
            if path['valid']:
                arrangement['hand_positions'] = path['positions']
        else:
            try:
                arrangement['hand_positions'] = piano_hand_positions(rendered, SongClock(vocal), ancestor['configuration'].get('maximum_hand_position_semitones_per_second', 96))
                arrangement['time_only_revision']['hand_time_plan'] = {'valid': True, 'pitch_register_revoicing_performed': False}
            except ValueError as error:
                arrangement['time_only_revision']['hand_time_plan'] = {'valid': False, 'reason': str(error)}
                arrangement['hand_positions'] = {hand: [retime_row(row, 30) for row in rows]
                                                 for hand, rows in ancestor.get('hand_positions', {}).items()}
        arrangement['time_only_revision']['actual_playability'] = validate_playability(arrangement, SongClock(vocal))
        arrangements[name] = arrangement
        # 最小拍轴与词音伴奏修复：修改日志在联合约束之后读取实际输出，原先吸附提案不再冒充最终时间。
        # audit['excluded_unmetered_notes'][name], audit['onset_changes'][name] = excluded, changes
        final = {n['id']: n for n in rendered}
        for row in changes:
            row['after_seconds'] = mapping.quarters_to_seconds(final[row['id']]['start_tick'] / PPQ)
            row['source_snap_rejected'] = final[row['id']].get('time_only_attack_snap_rejected')
        audit['excluded_unmetered_notes'][name], audit['onset_changes'][name] = excluded, changes
    return shared, arrangements, audit


def build_revision(project, candidate, assessment, binding, acoustic, verifier, word_reviews=()):
    # 最小拍轴与词音伴奏修复：新增不可越过的阶段及数据指纹检查；修改候选后旧的passed不可复用。
    require_clock_passed(assessment)
    if (assessment['candidate_sha256'] != fingerprint(candidate)
            or assessment['mix_sha256'] != binding['sources']['mix']['sha256']):
        raise ValueError('拍轴验收与实际输入不一致')
    source_notes, heads = refine_word_heads(project['accepted_vocal_project'], acoustic, verifier)
    # 最小拍轴与词音伴奏修复：新增“唱出”与“起音／音高已明”分开记录，前者不能自动消除字音归属冲突。
    presence = {row['character_index']: row for row in word_reviews if row.get('status') == 'confirmed_sung'}
    for row in heads['unresolved']:
        if row['character_index'] in presence:
            row['confirmed_sung_review'] = deepcopy(presence[row['character_index']])
            row['presence_is_not_a_pitch_or_onset_certificate'] = True
    vocal = project_voice(project['accepted_vocal_project'], candidate, source_notes)
    # 最小拍轴与词音伴奏修复：新增未决挂词的可见标记；保留原音并提示复核，不能以字数齐全宣称归属正确。
    pending_indices = {row['character_index'] for row in heads['unresolved']}
    for event in vocal['events']:
        if event.get('lyric_index') in pending_indices:
            event['review'] = True
            event['time_only_ownership_status'] = 'unresolved_preserved'
    return vocal, heads
