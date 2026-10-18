"""器乐主旋律简化与规整节奏：共享器乐主线，保留演唱段和物理拍轴。"""
# 器乐主旋律简化与规整节奏：新增独立策略；原逐攻击候选和旧版编配继续保留供复核。
from __future__ import annotations
from copy import deepcopy
from pathlib import Path
import math
import numpy as np
from accompaniment_analysis import SongClock, LOW_MIDI, HIGH_MIDI, extract_features
from accompaniment_arrange import TUNING, piano_hand_positions, validate_playability
from guitar_capo import capo_at
from guitar_grip_policy import grip_position_path

POLICY = {
    'version': 1, 'scope': ['intro', 'interlude', 'outro'],
    'analysis_grid_ticks': 120, 'preferred_grid_ticks': 240,
    'minimum_note_ticks': 120, 'minimum_active_rms_fraction': .06,
    'pitch_change_cost': 1.45, 'interval_cost': .075,
    'source_priority': {'six_piano': .55, 'six_guitar': .35, 'other': .3, 'accompaniment': .25},
    'mode': 'monophonic_backbone_without_inner_chord_fills',
    'quality_status': 'automatic_melody_reduction_requires_listening',
}


# 器乐主旋律简化与规整节奏：新增按真实段落范围筛选；混合小节的演唱音不能整小节删掉。
def instrumental_sections(shared):
    return [s for s in shared.get('sections', []) if s['kind'] in POLICY['scope']]


# 器乐主旋律简化与规整节奏：新增半开区间，段落尾点属于下一段。
def inside(tick, section):
    return section['start_tick'] <= tick < section['end_tick']


# 器乐主旋律简化与规整节奏：新增能量相对门限、多轨相对音高支持；静音分离轨不参与平均。
def sample_evidence(features, seconds, low, high, primary_floor=None):
    pitches = np.arange(low, high + 1)
    rows, priorities, sources = [], [], []
    for name, feature in features.items():
        # 器乐主旋律简化与规整节奏：修改，旧零偏移读窗保留；其它歌曲的分离轨偏移也按绑定秒轴处理。
        # sl = feature.window(*seconds)
        offset = float(feature.source.get('offset_seconds', 0))
        # 器乐主旋律简化与规整节奏：修改，旧浮点差保留；消除等价偏移窗边界的亚纳秒误差。
        # local = tuple(t-offset for t in seconds)
        local = tuple(round(t-offset, 12) for t in seconds)
        sl = feature.window(*local)
        energy = float(np.mean(feature.rms[sl]))
        floor = max(1e-10, float(np.percentile(feature.rms, 90)) * POLICY['minimum_active_rms_fraction'])
        # 器乐主旋律简化与规整节奏：修改，旧读窗保留；能量和音高证据使用同一个校正窗口。
        # weights = feature.pitch_weights(*seconds)[low - LOW_MIDI:high - LOW_MIDI + 1]
        # full = feature.pitch_weights(*seconds)
        full = feature.pitch_weights(*local)
        weights = full[low - LOW_MIDI:high - LOW_MIDI + 1]
        if energy < floor or float(weights.sum()) <= 1e-10 or weights.sum() < .035 * full.sum():
            continue
        # 器乐主旋律简化与规整节奏：新增相对峰值，避免任一轨的音量和重复制品冒充多张独立选票。
        rows.append(weights / max(1e-10, float(weights.max())))
        priorities.append(POLICY['source_priority'].get(name, .2))
        sources.append(name)
    if not rows:
        return np.zeros(len(pitches)), []
    # 器乐主旋律简化与规整节奏：修改，旧无主声部区分的平均保留；上方旋律明确时弱化低音/内声部。
    # return np.average(rows, axis=0, weights=priorities), sources
    result = np.average(rows, axis=0, weights=priorities)
    if primary_floor is not None and np.any(pitches >= primary_floor):
        upper = float(result[pitches >= primary_floor].max())
        if upper >= .24 * float(result.max()):
            result[pitches < primary_floor] *= .18
    return result, sources


# 器乐主旋律简化与规整节奏：新增全段连续音高路径；换音有成本，内声部短攻击不必成为主旋律。
def continuous_path(evidence, pitches):
    if not len(evidence):
        return []
    distance = np.abs(pitches[:, None] - pitches[None, :])
    transition = POLICY['pitch_change_cost'] * (distance > 0) + POLICY['interval_cost'] * np.minimum(distance, 12)
    emissions = np.log(.035 + evidence)
    costs, traces = emissions[0].copy(), []
    for row in emissions[1:]:
        options = costs[:, None] - transition
        trace = np.argmax(options, axis=0)
        costs = row + options[trace, np.arange(len(pitches))]
        traces.append(trace)
    best = int(np.argmax(costs)); path = [best]
    for trace in reversed(traces):
        best = int(trace[best]); path.append(best)
    return [int(pitches[i]) for i in reversed(path)]


# 器乐主旋律简化与规整节奏：新增源候选音域先验，避免把低音根音当主线；可随其他歌曲移调。
def melody_register(shared, section):
    candidates = [n['pitch_midi'] for n in shared.get('instrumental_melody', []) if inside(n['start_tick'], section)]
    if candidates:
        return max(LOW_MIDI, int(np.percentile(candidates, 15)) - 2), min(HIGH_MIDI, int(np.percentile(candidates, 95)) + 2)
    return 55, 88


# 器乐主旋律简化与规整节奏：新增真实同音再起音检查，不用其它弦的攻击强行拆开持续旋律。
def rearticulations(features, clock, start, end, pitch):
    found = set()
    for name, feature in features.items():
        strengths = [a['strength'] for a in feature.attacks]
        threshold = float(np.percentile(strengths, 65)) * .7 if strengths else math.inf
        for attack in feature.attacks:
            t = attack['seconds'] + float(feature.source.get('offset_seconds', 0))
            tick = round(clock.tick(t) / 240) * 240
            if not start + 240 <= tick <= end - 240 or attack['strength'] < threshold:
                continue
            # 器乐主旋律简化与规整节奏：修改，旧绝对秒取特征保留；起音定位用曲秒，轨内音高窗用轨秒。
            # prior = feature.pitch_weights(t - .14, t - .025)[pitch - LOW_MIDI]
            # after = feature.pitch_weights(t + .015, t + .11)
            local = attack['seconds']
            prior = feature.pitch_weights(local - .14, local - .025)[pitch - LOW_MIDI]
            after = feature.pitch_weights(local + .015, local + .11)
            level = float(after[pitch - LOW_MIDI])
            if level >= 1.55 * max(1e-10, float(prior)) and level >= .32 * float(after.max()):
                found.add(tick)
    return sorted(found)


# 器乐主旋律简化与规整节奏：新增谱面主线构建；起止都落十六分网格，优先八分网格。
def build_plan(shared, vocal, features):
    clock = SongClock(vocal); notes, summaries = [], []
    for index, section in enumerate(instrumental_sections(shared)):
        start = math.ceil(section['start_tick'] / 120) * 120
        end = min(clock.total_ticks, math.floor(section['end_tick'] / 120) * 120)
        # 器乐主旋律简化与规整节奏：新增检测主音末尾上限，尾奏残响/分离噪声不能编成长串新旋律。
        candidates = [n for n in shared.get('instrumental_melody', []) if inside(n['start_tick'], section)]
        audible_end = min(end, math.ceil(max((n['start_tick']+n['duration_ticks'] for n in candidates), default=end)/120)*120)
        # 器乐主旋律简化与规整节奏：修改，旧覆盖整段采样保留；检测旋律结束后保留休止。
        # ticks = np.arange(start, end, 120, dtype=int)
        ticks = np.arange(start, audible_end, 120, dtype=int)
        if not len(ticks):
            continue
        low, high = melody_register(shared, section); pitches = np.arange(low, high + 1)
        # 器乐主旋律简化与规整节奏：修改，旧普通支持平均保留；音域先验随歌曲和移调推算，不含歌曲表。
        # sampled = [sample_evidence(features, (max(section['start_seconds'], clock.seconds(t - 60)),
        #             min(section['end_seconds'], clock.seconds(t + 180))), low, high) for t in ticks]
        primary_floor = int(round(float(np.percentile([n['pitch_midi'] for n in candidates], 65)))) if candidates else None
        sampled = [sample_evidence(features, (max(section['start_seconds'], clock.seconds(t - 60)),
                    min(section['end_seconds'], clock.seconds(t + 180))), low, high, primary_floor) for t in ticks]
        evidence = np.array([row for row, sources in sampled]); active = np.any(evidence > 0, axis=1)
        spans = []; i = 0
        while i < len(ticks):
            if not active[i]:
                i += 1; continue
            j = i + 1
            while j < len(ticks) and active[j]:
                j += 1
            path = continuous_path(evidence[i:j], pitches)
            k = 0
            while k < len(path):
                m = k + 1
                while m < len(path) and path[m] == path[k]:
                    m += 1
                spans.append({'start_tick': int(ticks[i+k]), 'end_tick': int(ticks[i+m-1]+120),
                              'pitch_midi': path[k], 'support': float(np.mean(evidence[i+k:i+m, path[k]-low])),
                              'sources': sorted({s for row, names in sampled[i+k:i+m] for s in names})})
                k = m
            i = j
        # 器乐主旋律简化与规整节奏：新增八分拍格优先；强而明确的短主音允许正常十六分，不输出32分/附点16分。
        for span in spans:
            for field in ('start_tick', 'end_tick'):
                old = span[field]; snapped = round(old / 240) * 240
                if span['end_tick'] - span['start_tick'] >= 240:
                    span[field] = max(start, min(end, snapped))
            if span['end_tick'] <= span['start_tick']:
                span['end_tick'] = min(end, span['start_tick'] + 120)
        for a, b in zip(spans, spans[1:]):
            if a['end_tick'] > b['start_tick']:
                a['end_tick'] = b['start_tick']
        count_before = len(notes)
        for span in spans:
            if span['end_tick'] - span['start_tick'] < 120:
                continue
            cuts = [span['start_tick']] + rearticulations(features, clock, span['start_tick'], span['end_tick'], span['pitch_midi']) + [span['end_tick']]
            for a, b in zip(cuts, cuts[1:]):
                if b - a < 120:
                    continue
                # 器乐主旋律简化与规整节奏：新增原始证据与编配选择分开记录；不是原曲逐音转录。
                notes.append({**span, 'id': f'instrumental_backbone_{len(notes)+1:05}', 'section': section['kind'],
                              'section_index': index, 'start_tick': a, 'end_tick': b, 'duration_ticks': b-a,
                              'source_seconds': clock.seconds(a), 'onset_origin': 'simplified_melodic_backbone'})
        summaries.append({'section': section['kind'], 'start_tick': start, 'end_tick': end,
                          'original_candidate_count': sum(inside(n['start_tick'], section) for n in shared.get('instrumental_melody', [])),
                          'backbone_note_count': len(notes)-count_before, 'register': [low, high],
                          # 器乐主旋律简化与规整节奏：新增可核查音域/尾部裁简上限，节段实际时间保持。
                          'primary_register_floor': primary_floor, 'audible_end_tick': audible_end,
                          'active_cell_count': int(active.sum()), 'total_cell_count': len(ticks)})
    if not features and instrumental_sections(shared):
        raise ValueError('器乐主线简化需要绑定音频证据；不以空谱冒充已提取旋律。')
    return {'policy': deepcopy(POLICY), 'notes': notes, 'sections': summaries,
            'source_evidence': {name: {'sha256': f.source.get('sha256'), 'path': f.source.get('path')} for name, f in features.items()}}


# 器乐主旋律简化与规整节奏：新增固定演唱指法的单线换弦动态规划；允许器乐线必要八度降位并明确记录。
def guitar_locations(notes, configuration, vocal):
    clock = SongClock(vocal); groups = {}
    for note in notes:
        groups.setdefault(note['start_tick'], []).append(note)
    # 器乐主旋律简化与规整节奏：修改，旧起音端点路径注释保留；音符结束也必须作为换把边界。
    # ticks = sorted(groups); states, costs, traces = [], [], []
    ticks = sorted({t for n in notes for t in (n['start_tick'], n['end_tick'])})
    states, costs, traces, held = [], [], [], []
    for index, tick in enumerate(ticks):
        # 器乐主旋律简化与规整节奏：修改，旧仅考虑起音保留；持续旋律必须保持同弦同品。
        # group = groups[tick]; capo = capo_at({'configuration': configuration}, tick)
        # added = [n for n in group if n.get('backbone_id')]
        group = groups.get(tick, []); capo = capo_at({'configuration': configuration}, tick)
        added = [n for n in notes if n.get('backbone_id') and n['start_tick'] <= tick < n['end_tick']]
        held.append(added[0]['id'] if added else None)
        if len(added) > 1:
            raise ValueError('简化器乐主线必须单声部')
        options = []
        active_old = [n for n in notes if not n.get('backbone_id') and n['start_tick'] <= tick < n['end_tick']]
        if added:
            pitch = added[0]['pitch_midi']
            for shift in (0, -12, 12):
                for string, base in TUNING.items():
                    fret = pitch + shift - base - capo
                    if not 0 <= fret <= 20 or any(n['string'] == string for n in active_old):
                        continue
                    # 器乐主旋律简化与规整节奏：修改，旧四品覆盖保留；与既有五品硬约束一致。
                    # for position in range(max(1, fret-4), min(20, max(1, fret))+1) if fret else range(1, 21):
                    #     if all(n['fret'] == 0 or position <= n['fret'] <= position+4 for n in active_old):
                    for position in range(max(1, fret-5), min(20, max(1, fret))+1) if fret else range(1, 21):
                        if all(n['fret'] == 0 or position <= n['fret'] <= position+5 for n in active_old):
                            options.append((position, string, fret, shift))
        else:
            # 器乐主旋律简化与规整节奏：新增旧音弦品硬约束，不能为了新前奏重写正常演唱按法。
            frets = [n['fret'] for n in active_old if n['fret'] > 0]
            # 器乐主旋律简化与规整节奏：修改，旧四品覆盖保留；固定旧谱位置仍遵循五品手跨。
            # options = [(p, None, None, 0) for p in range(1, 21) if all(p <= f <= p+4 for f in frets)]
            options = [(p, None, None, 0) for p in range(1, 21) if all(p <= f <= p+5 for f in frets)]
        if not options:
            raise ValueError(f'器乐主线无固定演唱指法的可行弦品：{tick}')
        states.append(options); row, trace = [], []
        for position, string, fret, shift in options:
            preference = .004 * position + .15 * abs(shift) + (.01 * (fret or 0))
            if not index:
                row.append(preference); trace.append(-1); continue
            max_move = 24 * (clock.seconds(tick) - clock.seconds(ticks[index-1]))
            # 器乐主旋律简化与规整节奏：修改，旧仅端点速度检查保留；运动时不能离开仍发声的旧按法。
            # choices = [costs[-1][i] + .07*abs(position-old[0]) + preference
            #            if abs(position-old[0]) <= max_move + 1e-6 else math.inf for i, old in enumerate(states[index-1])]
            old_frets = [n['fret'] for n in notes if not n.get('backbone_id') and n['start_tick'] <= ticks[index-1] < n['end_tick'] and n['fret'] > 0]
            choices = []
            for i, old in enumerate(states[index-1]):
                continued = not held[index] or held[index] != held[index-1] or (string, fret, shift) == old[1:]
                previous_frets = old_frets + ([old[2]] if held[index-1] and old[2] else [])
                cover = all(position <= f <= position+5 for f in previous_frets)
                choices.append(costs[-1][i] + .07*abs(position-old[0]) + preference
                               if continued and cover and abs(position-old[0]) <= max_move+1e-6 else math.inf)
            best = int(np.argmin(choices)); row.append(choices[best]); trace.append(best)
        if not any(math.isfinite(x) for x in row):
            raise ValueError(f'器乐主线换把超速：{tick}')
        costs.append(row); traces.append(trace)
    if not ticks:
        return []
    best = int(np.argmin(costs[-1])); path = [best]
    for trace in traces[:0:-1]:
        path.append(trace[path[-1]])
    path.reverse(); positions = []
    for index, tick in enumerate(ticks):
        position, string, fret, shift = states[index][path[index]]
        positions.append({'tick': tick, 'position': position})
        # 器乐主旋律简化与规整节奏：修改，旧假定每一边界均有起音保留；结束边界不添加音符。
        # for note in groups[tick]:
        for note in groups.get(tick, []):
            if note.get('backbone_id'):
                note.update(string=string, fret=fret, finger=1 if fret else 0, hand_position=position,
                            pitch_midi=note['pitch_midi']+shift, octave_adjustment=shift)
    return positions


# 器乐主旋律简化与规整节奏：新增只替换实际器乐段的攻击，普通段原音符和原攻击完整保留。
def apply_plan(shared, vocal, arrangements, plan):
    sections = instrumental_sections(shared); result = deepcopy(arrangements); statistics = {}
    for name, arrangement in result.items():
        keep = lambda tick: not any(inside(tick, s) for s in sections)
        removed = [n for n in arrangement['notes'] if not keep(n['start_tick'])]
        preserved = [n for n in arrangement['notes'] if keep(n['start_tick'])]
        originals = deepcopy(preserved)
        additions, events = [], []
        for lead in plan['notes']:
            chord = next((h for h in shared.get('harmony', []) if h['start_tick'] <= lead['start_tick'] < h['end_tick']), None)
            note = {'id': name+'_'+lead['id'], 'backbone_id': lead['id'], 'pitch_midi': lead['pitch_midi'],
                    'start_tick': lead['start_tick'], 'end_tick': lead['end_tick'], 'velocity': 90,
                    'role': 'instrumental_melody', 'section': lead['section'], 'chord_id': chord['id'] if chord else None,
                    'source': 'instrumental_backbone', 'source_attack_seconds': lead['source_seconds'],
                    'source_melody_id': None, 'onset_origin': lead['onset_origin'],
                    'arrangement_reason': 'retain_primary_line_omit_dense_inner_voices'}
            if name == 'piano':
                note.update(hand='right', finger=1)
            additions.append(note)
            events.append({'start_tick': lead['start_tick'], 'kind': 'melody', 'chord_id': note['chord_id'],
                           'source': note['source'], 'onset_origin': note['onset_origin'], 'backbone_id': lead['id'],
                           'arrangement_reason': note['arrangement_reason'], 'stroke': None})
        arrangement['notes'] = sorted(preserved + additions, key=lambda n: (n['start_tick'], n['id']))
        arrangement['attack_events'] = sorted([e for e in arrangement.get('attack_events', []) if keep(e['start_tick'])] + events,
                                             key=lambda e: e['start_tick'])
        arrangement['configuration']['instrumental_policy'] = deepcopy(POLICY)
        # 器乐主旋律简化与规整节奏：新增迁移旧保护账本，仅将本轮授权替换的器乐音移到历史记录。
        # 正常演唱/混合小节的其它旧音继续受原验证器检查，原source_notes完整保留便于追溯。
        ledger = arrangement.get('regular_rhythm')
        if ledger is not None:
            removed_ids = {n['id'] for n in removed}
            superseded = [n for n in ledger.get('preserved_notes', []) if n['id'] in removed_ids]
            ledger.setdefault('superseded_instrumental_notes', []).extend(deepcopy(superseded))
            ledger['preserved_notes'] = [n for n in ledger.get('preserved_notes', []) if n['id'] not in removed_ids]
            ledger['preserved_note_ids'] = [n['id'] for n in ledger['preserved_notes']]
            ledger['instrumental_replacement_reason'] = '用户授权器乐主线简化；演唱/其它保留音的原保护约束继续有效'
        if name == 'guitar':
            arrangement['hand_positions'] = guitar_locations(arrangement['notes'], arrangement['configuration'], vocal)
            # 器乐主旋律简化与规整节奏：新增清除旧绘图缓存，导出重新匹配指型，不能留下没有音的和弦图。
            for field in ('fingering_diagrams', 'grip_hand_positions', 'notation_regions', 'grip_fingerings',
                          'tab_display', 'rhythm_display', 'time_alignment_display'):
                arrangement.pop(field, None)
            check = grip_position_path({**arrangement, 'fingering_diagrams': []}, vocal)
            if not check['valid']:
                raise ValueError('新器乐线实际持续换把不可行：'+str(check))
            arrangement['hand_positions'] = check['positions']
        else:
            arrangement['hand_positions'] = piano_hand_positions(arrangement['notes'], SongClock(vocal))
            # 器乐主旋律简化与规整节奏：修改，旧误用起音字段保留；踏板事件使用tick且必须保留释放，防止悬挂。
            # arrangement['pedal'] = [e for e in arrangement.get('pedal', []) if keep(e['start_tick'])]
            # 器乐主旋律简化与规整节奏：修改，旧保留所有释放保留；仅保留有实际踩下的对应释放，避免孤立踏板符号。
            # arrangement['pedal'] = [e for e in arrangement.get('pedal', []) if keep(e['tick']) or e['value'] == 0]
            pedals, running = [], False
            for event in arrangement.get('pedal', []):
                if event['value'] > 0 and keep(event['tick']):
                    pedals.append(event); running = True
                elif event['value'] == 0 and running:
                    pedals.append(event); running = False
            arrangement['pedal'] = pedals
        if originals != [n for n in arrangement['notes'] if not n.get('backbone_id')]:
            # 器乐主旋律简化与规整节奏：新增严格逐字段保护，排序改变不属于音乐修改。
            if {n['id']: n for n in originals} != {n['id']: n for n in arrangement['notes'] if not n.get('backbone_id')}:
                raise ValueError('器乐简化意外修改了正常演唱段音符')
        check = validate_playability(arrangement, SongClock(vocal))
        if not check['valid']:
            raise ValueError(name+'器乐简化演奏验证失败：'+str(check['errors'][:6]))
        statistics[name] = {'removed_instrumental_note_count': len(removed), 'backbone_note_count': len(additions),
                            'preserved_other_note_count': len(preserved), 'preserved_other_notes_equal': True,
                            'playability': check}
        arrangement['instrumental_simplification'] = statistics[name]
    shared = deepcopy(shared); shared['instrumental_backbone'] = deepcopy(plan)
    return shared, result, {'valid': True, 'policy': deepcopy(POLICY), 'sections': plan['sections'], 'instruments': statistics}


# 器乐主旋律简化与规整节奏：新增缓存证据入口，历史缓存只读复制，既有原唱/和声/定拍均不重算。
def simplify_instrumentals(shared, vocal, arrangements, cache):
    from performance_beat_clock import copy_features
    binding = shared['input_binding']; cache = Path(cache)
    copy_features(binding, cache, [vocal.get('performance_clock_correction', {}).get('feature_cache')])
    features = {name: extract_features(binding['sources'][name], cache, name)
                for name in POLICY['source_priority'] if name in binding['sources']}
    plan = build_plan(shared, vocal, features)
    return apply_plan(shared, vocal, arrangements, plan)
