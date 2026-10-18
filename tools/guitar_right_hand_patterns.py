"""常用右手伴奏型：演唱伴奏的稳定模板、真实弦品映射与保留区审计。"""
# 常用右手伴奏型：新增独立吉他策略，不重写人声、钢琴或共享音频分析。
from __future__ import annotations
from score_export import PPQ  # 跨曲低音与强拍复用通用修复：新增按真实拍号计算尾拍来源覆盖。
from collections import Counter
from copy import deepcopy
from functools import lru_cache
import json
from pathlib import Path
import statistics

from accompaniment_arrange import TUNING, grip_info, shape_candidates
from accompaniment_analysis import SongClock, chord_name, pc_name
# 结构稳定伴奏与人声合播：修改，原代码注释保留。
# from guitar_grip_policy import grip_position_path
from guitar_grip_policy import grip_position_path
# 结构稳定伴奏与人声合播：新增统一夹位与实际混合时值。
from guitar_capo import capo_at
from guitar_pattern_grid import pattern_schedule, pattern_duration
from score_export import key_definition

POLICY = {'name': 'common_vocal_right_hand', 'version': 1, 'phrase_measures': 4,
          'arpeggio_first': True, 'protected_sections': ['intro', 'interlude', 'outro'],
          'protect_mixed_boundary_measures': True, 'protect_feature_melody_measures': True,
          'protect_cross_supported_chord_attacks': True,
          'quality_status': 'guitar_arrangement_choice_requires_listening'}


# 常用右手伴奏型：新增离线库校验，节拍长度与原作者正文/规范示例的来源分别保留。
@lru_cache(maxsize=1)
def library():
    data = json.loads((Path(__file__).parent / 'data/guitar_right_hand_patterns.json').read_text(encoding='utf-8'))
    ids, sources = set(), {s['id'] for s in data['sources']}
    for p in data['patterns']:
        if p['id'] in ids or len(p['slots']) * p['step_ticks'] != p['meter'][0] * 480 * 4 / p['meter'][1]:
            raise ValueError('右手库标识重复或拍长错误：' + p['id'])
        ids.add(p['id'])
        if not p['source_ids'] or not set(p['source_ids']).issubset(sources):
            raise ValueError('右手库缺少有效来源：' + p['id'])
        for slot in p['slots']:
            parts = slot.split('+')
            if len(parts) > 4 or len(set(parts)) != len(parts) or any(t not in ('B', 'B2', '1', '2', '3', 'D', 'U', '-') for t in parts):
                raise ValueError('右手库拨弦记号错误：' + p['id'])
    return data


# 常用右手伴奏型：新增只识别完整正常演唱小节；混合边界、特色填句及已支持齐奏留原编配。
def eligible_measures(shared, guitar):
    bar = shared['statistics']['bar_ticks']; count = shared['statistics']['measure_count']
    vocals = [s for s in shared.get('sections', []) if s['kind'] == 'vocal']
    good, skipped = [], []
    for m in range(count):
        start, end = m * bar, (m + 1) * bar
        if not any(s['start_tick'] <= start and end <= s['end_tick'] for s in vocals):
            skipped.append({'measure': m + 1, 'reason': 'instrumental_or_mixed_boundary'}); continue
        notes = [n for n in guitar['notes'] if n['start_tick'] < end and n['end_tick'] > start]
        feature = any(n.get('role') not in ('bass', 'harmony') or n.get('source_melody_id') for n in notes)
        feature |= any(n['start_tick'] < end and n['start_tick'] + n['duration_ticks'] > start
                       for n in shared.get('instrumental_melody', []) if n.get('role') in ('instrumental_melody', 'countermelody'))
        retained = any(start <= e['start_tick'] < end and e.get('arrangement_reason') == 'retained_cross_supported_simultaneous_chord'
                       for e in guitar['attack_events'])
        # 常用右手伴奏型：修改，原所有跨小节低音都排除会留下大部分普通伴奏，保留原式。
        # crossing = any(n['start_tick'] < start < n['end_tick'] or n['start_tick'] < end < n['end_tick'] for n in notes)
        # reason = 'protected_feature_melody' if feature else 'protected_cross_supported_chord_attacks' if retained else 'protected_cross_bar_sustain' if crossing else 'silence' if not notes else None
        # 常用右手伴奏型：修改，只有前小节延音而无新起音的小节不套分解，原判断保留。
        # reason = 'protected_feature_melody' if feature else 'protected_cross_supported_chord_attacks' if retained else 'silence' if not notes else None
        reason = 'protected_feature_melody' if feature else 'protected_cross_supported_chord_attacks' if retained else 'silence_or_held_only' if not any(start <= n['start_tick'] < end for n in notes) else None
        if reason: skipped.append({'measure': m + 1, 'reason': reason})
        else: good.append(m + 1)
    # 常用右手伴奏型：新增只保护从不可改区域延续进来的持续音；可改区域之间的普通低音可随模板编配。
    while True:
        # 规整分解节奏与延音显示：修改，原所有继承音阻止重编保留；普通和声延音可共存，器乐主线仍保护。
        # inherited = [m for m in good if any(n['start_tick'] < (m-1)*bar < n['end_tick'] and
        #               n['start_tick']//bar+1 not in good for n in guitar['notes'])]
        regular = bool(guitar['configuration'].get('regular_rhythm_policy'))
        inherited = [m for m in good if any(n['start_tick'] < (m-1)*bar < n['end_tick'] and
                      n['start_tick']//bar+1 not in good and (not regular or n.get('role') not in ('bass','harmony') or n.get('source_melody_id'))
                      for n in guitar['notes'])]
        if not inherited: break
        for m in inherited: good.remove(m); skipped.append({'measure': m, 'reason': 'protected_inherited_sustain'})
    return good, skipped


# 常用右手伴奏型：新增根音/斜线低音与三根高弦映射，缺弦按真实音域重映射并记录。
def string_map(shape, capo):
    frets = {int(s): f for s, f in shape['frets'].items()}
    sounding = {s: TUNING[s] + capo + f for s, f in frets.items()}
    bass = min(sounding, key=sounding.get)
    upper = sorted(s for s in frets if s != bass)[:3]
    if len(upper) < 2: raise ValueError('常用分解需要低音及至少两根高弦。')
    result = {'B': bass, 'B2': next((s for s in sorted(frets, reverse=True) if s != bass and s >= 4), bass)}
    for token, string in zip(('1', '2', '3'), upper + [upper[-1]] * (3 - len(upper))): result[token] = string
    return result


# 常用右手伴奏型：新增按实际拨到的音选完整候选，三度/七音/挂留/加音不能被高弦模板漏掉。
def shape_for(chord, capo):
    choices = shape_candidates(chord['root_pc'], chord['quality'], chord['bass_pc'], capo)
    scored = []
    for shape in choices:
        mapped = string_map(shape, capo)
        # 常用右手伴奏型：修改，默认上行/环绕不用B2，不能将未拨的备用低音算成性质音保留，原式保留。
        # played = {TUNING[s] + capo + shape['frets'][str(s)] for s in mapped.values()}
        played = {TUNING[mapped[t]] + capo + shape['frets'][str(mapped[t])] for t in ('B','1','2','3')}
        missing = set(chord['pitch_classes']) - {p % 12 for p in played}
        # 常用右手伴奏型：新增缺性质音惩罚，必要时以一根内弦替代重复高弦，保持真实手型。
        essential = set(chord['pitch_classes']) - {(chord['root_pc'] + 7) % 12}
        # 常用右手伴奏型：新增优先含性质音的高弦，仍缺时把重复高弦换为当前手型中的性质音内弦。
        remapped = 0
        for pc in sorted(missing & essential):
            pcs = {t: (TUNING[mapped[t]] + capo + shape['frets'][str(mapped[t])]) % 12 for t in ('B','1','2','3')}
            counts = Counter(pcs.values())
            replace = [t for t in ('3','2','1') if counts[pcs[t]] > 1 or pcs[t] not in essential]
            locations = [int(s) for s, f in shape['frets'].items() if (TUNING[int(s)] + capo + f) % 12 == pc]
            if replace and locations:
                token = replace[0]; mapped[token] = min(locations, key=lambda s: abs(s - mapped[token])); remapped += 1
        played = {(TUNING[mapped[t]] + capo + shape['frets'][str(mapped[t])]) % 12 for t in ('B','1','2','3')}
        missing = set(chord['pitch_classes']) - played
        value = shape['cost'] + 8 * len(missing & essential) + .2 * len(missing) + .7 * remapped
        scored.append((value, shape, mapped))
    _, shape, mapped = min(scored, key=lambda x: x[0])
    return deepcopy(shape), mapped


# 常用右手伴奏型：新增从原攻击密度/音序打分，四小节乐句维持一个主型，型间变化有代价。
# 结构稳定伴奏与人声合播：修改，原代码注释保留。
# def phrase_plan(shared, guitar, measures):
    # bar = shared['statistics']['bar_ticks']; meter = shared['timing']['meter']
def phrase_plan(shared, guitar, measures):
    # 结构稳定伴奏与人声合播：新增原音频/真实乐句路径，旧四小节路径供兼容。
    if guitar['configuration'].get('structure_policy'):
        from guitar_structure_patterns import structured_phrase_plan
        return structured_phrase_plan(shared,guitar,measures)
    bar = shared['statistics']['bar_ticks']; meter = shared['timing']['meter']
    patterns = [p for p in library()['patterns'] if p['default_candidate'] and p['meter'] == meter]
    if not patterns: return []
    phrases, current = [], []
    for measure in measures:
        if current and (measure != current[-1] + 1 or len(current) == POLICY['phrase_measures']): phrases.append(current); current = []
        current.append(measure)
    if current: phrases.append(current)
    capo = guitar['configuration']['capo_fret']; shapes = {}
    for chord in shared['harmony']:
        if chord['name'] != 'N.C.': shapes[chord['id']] = shape_for(chord, capo)
    costs, traces, details = [], [], []
    for phrase in phrases:
        begin, end = (phrase[0] - 1) * bar, phrase[-1] * bar
        actual = [n for n in guitar['notes'] if begin <= n['start_tick'] < end]
        events = sorted({n['start_tick'] for n in actual})
        observations = [a for t in shared['measure_textures'] for a in t['attacks'] if begin <= a['tick'] < end]
        desired = (len(events) + len(observations)) / (2 * len(phrase))
        contour = {}
        for n in actual:
            if n['role'] == 'harmony': contour.setdefault(n['start_tick'], []).append(n['pitch_midi'])
        row_details, row_cost = [], []
        for p in patterns:
            step = p['step_ticks']
            phases = Counter(t % step for t in events)
            # 规整分解节奏与延音显示：修改，旧观测相位保留；规整编配明确采用记谱拍格零相位。
            # phase = min(phases, key=lambda v: (-phases[v], v)) if phases else 0
            phase = 0 if guitar['configuration'].get('regular_rhythm_policy') else min(phases, key=lambda v: (-phases[v], v)) if phases else 0
            errors = []
            for tick, pitches in contour.items():
                chord = next((h for h in shared['harmony'] if h['start_tick'] <= tick < h['end_tick']), None)
                if not chord or chord['name'] == 'N.C.': continue
                shape, mapped = shapes[chord['id']]
                slot = round(((tick % bar) - phase) / step) % len(p['slots'])
                token = p['slots'][slot].split('+')[-1]; string = mapped[token]
                target = TUNING[string] + capo + shape['frets'][str(string)]
                errors.append(min(abs(target - pitch) for pitch in pitches))
            cost = .7 * abs(desired - len(p['slots'])) + .14 * statistics.mean(errors or [0])
            row_details.append({'measures': phrase, 'pattern_id': p['id'], 'phase_tick': phase,
                                'desired_attacks_per_measure': desired, 'score': cost})
            row_cost.append(cost)
        if not costs: costs.append(row_cost); traces.append([-1] * len(patterns))
        else:
            c, tr = [], []
            contiguous = phrase[0] == phrases[len(costs) - 1][-1] + 1
            for i, cost in enumerate(row_cost):
                options = [old + (2.0 if contiguous and j != i else 0) for j, old in enumerate(costs[-1])]
                best = min(range(len(options)), key=options.__getitem__); c.append(cost + options[best]); tr.append(best)
            costs.append(c); traces.append(tr)
        details.append(row_details)
    if not phrases: return []
    selected = [min(range(len(costs[-1])), key=costs[-1].__getitem__)]
    for tr in traces[:0:-1]: selected.append(tr[selected[-1]])
    selected.reverse()
    return [details[i][j] for i, j in enumerate(selected)]


# 常用右手伴奏型：新增规范拨弦及休止/换和弦变体；新增攻击明确标为编配而非原曲检测。
def measure_notes(shared, guitar, measure, plan, serial):
    bar = shared['statistics']['bar_ticks']; start, end = (measure - 1) * bar, measure * bar
    pattern = next(p for p in library()['patterns'] if p['id'] == plan['pattern_id'])
    old = [n for n in guitar['notes'] if start <= n['start_tick'] < end]
    attacks = sorted({n['start_tick'] for n in old})
    # 结构稳定伴奏与人声合播：修改，原代码注释保留。
    # capo = guitar['configuration']['capo_fret']; step = pattern['step_ticks']; phase = plan['phase_tick']
    # points = {start + phase + i * step for i in range(len(pattern['slots'])) if start + phase + i * step < end}
    capo = capo_at(guitar,start); step = pattern['step_ticks']; phase = plan['phase_tick']
    points = {start+phase+r['offset'] for r in pattern_schedule(pattern) if start+phase+r['offset']<end}
    # 常用右手伴奏型：新增保留明显晚进入及连续无声间隙，不用固定八次拨弦填满休止。
    leading = attacks[0] if attacks[0] - start >= 480 else start
    active_end = max(n['end_tick'] for n in old)
    gaps = []
    for left, right in zip(attacks, attacks[1:]):
        held_end = max(n['end_tick'] for n in old if n['start_tick'] <= left)
        if right - held_end >= 480: gaps.append((held_end, right))
    # 规整分解节奏与延音显示：新增保留完整休拍，自动短偏移按四分拍整理并逐小节保留旧边界。
    regular = bool(guitar['configuration'].get('regular_rhythm_policy'))
    original_entry, original_end = leading, active_end
    if regular:
        leading = start + ((leading-start)//480)*480
        active_end = min(end, start + ((active_end-start+479)//480)*480)
        gaps = [(((a+479)//480)*480, (b//480)*480) for a, b in gaps if (b//480)*480 > ((a+479)//480)*480]
    points = {t for t in points if leading <= t < active_end and not any(a <= t < b for a, b in gaps)}
    if leading > start: points.add(leading)
    if not points: points.add(attacks[0])
    # 常用右手伴奏型：新增和弦切换在原拍点发出其低音，模板保持全小节相位。
    chord_starts = {h['start_tick'] for h in shared['harmony'] if start < h['start_tick'] < end and h['name'] != 'N.C.'}
    # 规整分解节奏与延音显示：新增换和弦低音在下一常用格拨响，不插入额外十六分起音。
    # 结构稳定伴奏与人声合播：修改，原代码注释保留。
    # if regular: chord_starts = {((t+step-1)//step)*step for t in chord_starts if ((t+step-1)//step)*step < end}
    if regular:
        if guitar['configuration'].get('structure_policy'):
            grid=sorted(start+phase+r['offset'] for r in pattern_schedule(pattern))
            chord_starts={next((p for p in grid if p>=t),end) for t in chord_starts}
            chord_starts.discard(end)
        else: chord_starts = {((t+step-1)//step)*step for t in chord_starts if ((t+step-1)//step)*step < end}
    points.update(t for t in chord_starts if leading <= t < active_end and not any(a <= t < b for a, b in gaps))
    # 强拍相位与伴奏同步纠错：新增和弦切换/休止后从模板首音重启，禁止只替换中间音的标签。
    cycle_origins = [start]
    if guitar['configuration'].get('beat_synchronous_patterns'):
        cycle_origins = sorted({start,leading} | chord_starts | {b for a,b in gaps if b < end})
        points = set()
        for origin_index, cycle_origin in enumerate(cycle_origins):
            limit = cycle_origins[origin_index+1] if origin_index+1 < len(cycle_origins) else end
            points.update(cycle_origin+r['offset'] for r in pattern_schedule(pattern)
                          if leading <= cycle_origin+r['offset'] < min(limit,active_end)
                          and not any(a <= cycle_origin+r['offset'] < b for a,b in gaps))
    notes, events, realized = [], [], []
    for tick in sorted(points):
        # 首拍与首尾局部补证：新增小节内部跨入真实尾响时不再续填模板；先前拨音的完整延音不改。
        from first_generation_tail import pattern_attack_allowed
        if not pattern_attack_allowed(shared,tick):continue
        chord = next((h for h in shared['harmony'] if h['start_tick'] <= tick < h['end_tick']), None)
        if not chord or chord['name'] == 'N.C.': continue
        # 结构稳定伴奏与人声合播：修改，原代码注释保留。
        # shape, mapped = shape_for(chord, capo)
        # slot = ((tick - start - phase) // step) % len(pattern['slots'])
        capo = capo_at(guitar,tick)
        shape, mapped = shape_for(chord, capo)
        # 强拍相位与伴奏同步纠错：修改，原整小节取模保留；按本次实际循环的首音起点取模。
        # slot = ((tick - start - phase) // step) % len(pattern['slots'])
        cycle_origin = max(origin for origin in cycle_origins if origin <= tick)
        slot = ((tick - cycle_origin - phase) // step) % len(pattern['slots'])
        slot_duration = pattern_duration(pattern,slot)
        token = 'B' if tick in chord_starts or tick == min(points) else pattern['slots'][slot]
        tokens = token.split('+')
        nearest = min(old, key=lambda n: abs(n['start_tick'] - tick))
        source_ids = [n['id'] for n in old if n['start_tick'] == nearest['start_tick']]
        adaptation = 'chord_change_bass' if tick in chord_starts else 'entry_bass' if tick == min(points) and token != pattern['slots'][slot] else None
        strings = list(dict.fromkeys(mapped[t] for t in tokens))
        for string in strings:
            fret = shape['frets'][str(string)]; pitch = TUNING[string] + capo + fret
            role = 'bass' if string == mapped['B'] else 'harmony'
            # 结构稳定伴奏与人声合播：修改，原代码注释保留。
            # hold = max(step, 480) if role == 'bass' else step
            hold = max(slot_duration, 480) if role == 'bass' else slot_duration
            finish = min(tick + hold, chord['end_tick'], active_end, end)
            if finish <= tick: continue
            # 规整分解节奏与延音显示：修改，旧编号保留；重编已有模板使用独立编号避免保留音碰撞。
            # identity = f'guitar_pattern_note_{serial:05}'; serial += 1
            # 结构稳定伴奏与人声合播：修改，原代码注释保留。
            # identity = f"{'guitar_regular_note' if regular else 'guitar_pattern_note'}_{serial:05}"; serial += 1
            # 强拍相位与伴奏同步纠错：修改，原命名保留；二次重编不能与保留的v10/v11结构音符ID相撞。
            # namespace='guitar_structured_note' if guitar['configuration'].get('structure_policy') else 'guitar_regular_note' if regular else 'guitar_pattern_note'
            namespace='guitar_beat_note' if guitar['configuration'].get('beat_synchronous_patterns') else 'guitar_structured_note' if guitar['configuration'].get('structure_policy') else 'guitar_regular_note' if regular else 'guitar_pattern_note'
            identity = f'{namespace}_{serial:05}'; serial += 1
            note = {'id': identity, 'pitch_midi': pitch, 'string': string, 'fret': fret, 'role': role,
                    'start_tick': tick, 'end_tick': finish, 'velocity': 78 if role == 'bass' else 68 if slot in pattern['accent_slots'] else 64,
                    'finger': shape['fingers'].get(string, 0), 'octave_adjustment': 0, 'path_octave_adjustment': 0,
                    'chord_id': chord['id'], 'section': 'vocal', 'source': nearest['source'],
                    'source_attack_seconds': nearest['source_attack_seconds'], 'source_note_ids': source_ids,
                    'observed_kind': nearest.get('observed_kind'), 'onset_origin': 'arranged_common_pattern',
                    'arrangement_reason': 'common_right_hand_vocal_accompaniment', 'texture_measure': measure,
                    'right_hand_pattern_id': pattern['id'], 'right_hand_slot': slot, 'right_hand_token': token,
                    'pattern_adaptation': adaptation, 'pattern_baseline_frets': deepcopy(shape['frets']),
                    'pattern_string_map': mapped, 'arpeggio_step': None, 'arpeggio_pitch_class': None}
            notes.append(note)
            # 强拍相位与伴奏同步纠错：新增实际循环起点供独立实音核验。
            if guitar['configuration'].get('beat_synchronous_patterns'):
                note['pattern_cycle_origin_tick'] = cycle_origin
        key = key_definition(pc_name(chord['key']['tonic_pc'] - capo, chord['key']) + ':major')
        events.append({'start_tick': tick, 'kind': 'arpeggio', 'chord_id': chord['id'],
                       'chart_id': None, 'shape_name': chord_name(chord['root_pc'] - capo, chord['quality'], chord['bass_pc'] - capo, key),
                       'sounding_name': chord['name'], 'source': nearest['source'], 'stroke': None, 'stroke_status': None,
                       'observed_kind': nearest.get('observed_kind'), 'onset_origin': 'arranged_common_pattern',
                       'arrangement_reason': 'common_right_hand_vocal_accompaniment', 'texture_measure': measure,
                       'right_hand_pattern_id': pattern['id'], 'right_hand_slot': slot,
                       # 结构稳定伴奏与人声合播：修改，原代码注释保留。
                       # 'pattern_adaptation': adaptation, 'source_note_ids': source_ids})
                       'pattern_adaptation': adaptation, 'source_note_ids': source_ids,
                       'right_hand_duration_ticks':slot_duration, 'right_hand_duration_source':'regular_pattern_slot' if regular else 'pattern_slot'})
        realized.append({'tick': tick, 'slot': slot, 'token': token, 'strings': strings, 'adaptation': adaptation})
        if guitar['configuration'].get('beat_synchronous_patterns'):
            events[-1]['pattern_cycle_origin_tick'] = cycle_origin
    # 常用右手伴奏型：新增短和弦被模板截取时补性质音，用手型内相邻弦替代重复音而非换左手。
    for chord_id in {n['chord_id'] for n in notes}:
        chord = next(h for h in shared['harmony'] if h['id'] == chord_id)
        # 结构稳定伴奏与人声合播：修改，原代码注释保留。
        # values = [n for n in notes if n['chord_id'] == chord_id]
        # essential
        values = [n for n in notes if n['chord_id'] == chord_id]
        capo = capo_at(guitar,chord['start_tick'])
        essential = set(chord['pitch_classes']) - {(chord['root_pc'] + 7) % 12}
        if len(values) < max(4, len(essential)): continue
        for pc in sorted(essential - {n['pitch_midi'] % 12 for n in values}):
            counts = Counter(n['pitch_midi'] % 12 for n in values)
            substitutes = [n for n in values if n['role'] == 'harmony' and
                           (n['pitch_midi'] % 12 not in essential or counts[n['pitch_midi'] % 12] > 1)]
            found = False
            for note in reversed(substitutes):
                locations = [int(s) for s, f in note['pattern_baseline_frets'].items()
                             if (TUNING[int(s)] + capo + f) % 12 == pc and int(s) != note['pattern_string_map']['B']]
                if not locations: continue
                string = min(locations, key=lambda s: abs(s - note['string']))
                note['string'] = string; note['fret'] = note['pattern_baseline_frets'][str(string)]
                note['pitch_midi'] = TUNING[string] + capo + note['fret']
                note['pattern_string_map'] = {**note['pattern_string_map'], note['right_hand_token']: string}
                note['pattern_adaptation'] = 'chord_quality_tone'
                for row in realized:
                    if row['tick'] == note['start_tick']: row['strings'] = [string]; row['adaptation'] = 'chord_quality_tone'
                for event in events:
                    if event['start_tick'] == note['start_tick']: event['pattern_adaptation'] = 'chord_quality_tone'
                found = True; break
            if not found: break
    # 常用右手伴奏型：新增重拨同弦前结束前音；不改变被保留区域的任何音符。
    for string in range(1, 7):
        values = sorted([n for n in notes if n['string'] == string], key=lambda n: n['start_tick'])
        for before, after in zip(values, values[1:]): before['end_tick'] = min(before['end_tick'], after['start_tick'])
    # 规整分解节奏与延音显示：修改，原返回保留；新增原进入/结束时间的编配审计。
    # return notes, events, {'measure': measure, 'pattern_id': pattern['id'], 'phase_tick': phase,
    return notes, events, {'measure': measure, 'pattern_id': pattern['id'], 'phase_tick': phase,
                           'source_entry_tick': original_entry, 'source_active_end_tick': original_end,
                           'leading_rest_end_tick': leading, 'active_end_tick': active_end,
                           # 强拍相位与伴奏同步纠错：新增循环边界；短和弦只弹模板开头片段仍可严格核验。
                           # 'protected_silence_gaps': gaps, 'realized_attacks': realized}, serial
                           'protected_silence_gaps': gaps, 'realized_attacks': realized,
                           'cycle_origins':cycle_origins}, serial


# 常用右手伴奏型：新增没有新起音小节的跨线延音，不能把小节分组当作截音边界。
def preserve_held_bridges(shared, original, notes, rows, included):
    bar = shared['statistics']['bar_ticks']; bridges = []
    for old in original['notes']:
        measure = old['start_tick'] // bar + 1; boundary = measure * bar
        if measure not in included or old['end_tick'] <= boundary: continue
        next_attacks = [n for n in original['notes'] if boundary <= n['start_tick'] < old['end_tick']]
        if next_attacks: continue
        candidates = [n for n in notes if n['chord_id'] == old['chord_id'] and
                      (measure-1)*bar <= n['start_tick'] < boundary and n['pitch_midi']%12 == old['pitch_midi']%12]
        if not candidates: continue
        note = min(candidates, key=lambda n:(abs(n['pitch_midi']-old['pitch_midi']),-n['start_tick']))
        future = [n['start_tick'] for n in notes if n['string']==note['string'] and n['start_tick']>note['start_tick']]
        chord = next(h for h in shared['harmony'] if h['id']==note['chord_id'])
        end = min(old['end_tick'],chord['end_tick'],min(future,default=old['end_tick']))
        if end > boundary:
            note['end_tick']=end;note['held_bridge_source_note_id']=old['id']
            item={'source_note_id':old['id'],'new_note_id':note['id'],'end_tick':end,'exact_pitch_preserved':note['pitch_midi']==old['pitch_midi']}
            bridges.append(item)
            for row in rows:
                if row['measure']==measure:row.setdefault('held_bridges',[]).append(item)
    return bridges


# 常用右手伴奏型：新增跨小节性质音复核，短片段漏掉性质音时用常见低高音合拨补足。
# 结构稳定伴奏与人声合播：修改，原代码注释保留。
# def complete_quality(shared, notes, events, rows, capo, serial):
def complete_quality(shared, notes, events, rows, capo, serial, guitar=None):
    for chord in shared['harmony']:
        # 结构稳定伴奏与人声合播：修改，原代码注释保留。
        # selected = [n for n in notes if n['chord_id'] == chord['id']]
        # essential
        selected = [n for n in notes if n['chord_id'] == chord['id']]
        if guitar is not None: capo = capo_at(guitar,chord['start_tick'])
        essential = set(chord['pitch_classes']) - {(chord['root_pc'] + 7) % 12}
        if len(selected) < max(4, len(essential)): continue
        for pc in sorted(essential - {n['pitch_midi'] % 12 for n in selected}):
            basses = [n for n in selected if n['role'] == 'bass']
            added = False
            for bass in basses:
                tick = bass['start_tick']; group = [n for n in notes if n['start_tick'] == tick]
                occupied = {n['string'] for n in group}
                locations = [int(s) for s, f in bass['pattern_baseline_frets'].items()
                             if int(s) not in occupied and (TUNING[int(s)] + capo + f) % 12 == pc]
                keys = [t for t in ('3','2','1') if t not in bass['right_hand_token'].split('+')]
                if not locations or not keys: continue
                token = keys[0]; string = min(locations, key=lambda s: abs(s - bass['pattern_string_map'][token]))
                combined = bass['right_hand_token'] + '+' + token
                mapped = {**bass['pattern_string_map'], token: string}
                for note in group:
                    note['right_hand_token'] = combined; note['pattern_string_map'] = mapped
                    note['pattern_adaptation'] = 'chord_quality_pinch'
                pattern = next(p for p in library()['patterns'] if p['id'] == bass['right_hand_pattern_id'])
                future = [n['start_tick'] for n in notes if n['string'] == string and n['start_tick'] > tick]
                # 结构稳定伴奏与人声合播：修改，原代码注释保留。
                # end = min(bass['end_tick'], tick + pattern['step_ticks'], min(future, default=bass['end_tick']))
                # 结构稳定伴奏与人声合播：修改，兼容旧工程缺少slot的性质音补全。
                # end = min(bass['end_tick'], tick + pattern_duration(pattern,bass['right_hand_slot']), min(future, default=bass['end_tick']))
                end = min(bass['end_tick'], tick + pattern_duration(pattern,bass.get('right_hand_slot',0)), min(future, default=bass['end_tick']))
                # 规整分解节奏与延音显示：修改，旧补性质音编号保留；新版使用独立编号防止与旧保留音重名。
                # note = {**deepcopy(bass), 'id':f'guitar_pattern_note_{serial:05}', 'role':'harmony',
                # 结构稳定伴奏与人声合播：修改，结构版补音使用独立编号避免与保留音冲突。
                # identity = f"{'guitar_regular_quality' if bass['id'].startswith('guitar_regular_') else 'guitar_pattern_note'}_{serial:05}"
                # 强拍相位与伴奏同步纠错：修改，原补音命名保留；新品质合拨也使用独立纠错命名空间。
                # namespace = 'guitar_structured_quality' if bass['id'].startswith('guitar_structured_') else ('guitar_regular_quality' if bass['id'].startswith('guitar_regular_') else 'guitar_pattern_note')
                namespace = 'guitar_beat_quality' if bass['id'].startswith('guitar_beat_') else 'guitar_structured_quality' if bass['id'].startswith('guitar_structured_') else ('guitar_regular_quality' if bass['id'].startswith('guitar_regular_') else 'guitar_pattern_note')
                identity = f'{namespace}_{serial:05}'
                note = {**deepcopy(bass), 'id':identity, 'role':'harmony',
                        'string':string, 'fret':bass['pattern_baseline_frets'][str(string)],
                        'pitch_midi':TUNING[string] + capo + bass['pattern_baseline_frets'][str(string)],
                        'end_tick':end, 'velocity':64}
                for previous in notes:
                    if previous['string'] == string and previous['start_tick'] < tick < previous['end_tick']:
                        previous['end_tick'] = tick
                notes.append(note); selected.append(note); serial += 1
                for row in rows:
                    for attack in row['realized_attacks']:
                        if attack['tick'] == tick:
                            attack['token'] = combined; attack['strings'] = sorted(occupied | {string})
                            attack['adaptation'] = 'chord_quality_pinch'
                for event in events:
                    if event['start_tick'] == tick: event['pattern_adaptation'] = 'chord_quality_pinch'
                added = True; break
            if not added: raise ValueError('常用型无法补齐和弦性质音：' + chord['id'])
    return serial


# 常用右手伴奏型：新增实际持续时序失败时回退该小节，保持原独奏与其它受保护音完整。
# 乐句节奏与音值分组：新增从现有音符编号后分配，升级已套型工程不会冒用旧音ID。
def next_note_serial(notes, minimum=1):
    values = [int(n['id'].rsplit('_',1)[-1]) for n in notes if n['id'].rsplit('_',1)[-1].isdigit()]
    return max([minimum-1] + values) + 1


def apply_common_patterns(shared, vocal, guitar):
    # 规整分解节奏与延音显示：修改，旧仅按名字幂等保留；从旧模板升级规整规则允许重编一次。
    # if guitar['configuration'].get('right_hand_policy', {}).get('name') == POLICY['name']: return guitar
    regular = bool(guitar['configuration'].get('regular_rhythm_policy'))
    existing = guitar['configuration'].get('right_hand_policy', {})
    if existing.get('name') == POLICY['name'] and existing.get('regular_grid', False) == regular: return guitar
    original = deepcopy(guitar); good, skipped = eligible_measures(shared, guitar)
    plans = phrase_plan(shared, guitar, good); bar = shared['statistics']['bar_ticks']
    by_measure = {m: p for p in plans for m in p['measures']}
    # 乐句节奏与音值分组：修改，原固定序号注释保留；保证新旧源审计ID唯一。
    # generated, new_events, rows, serial = [], [], [], 1
    generated, new_events, rows, serial = [], [], [], next_note_serial(original['notes'])
    for measure in good:
        if measure not in by_measure: continue
        ns, es, row, serial = measure_notes(shared, original, measure, by_measure[measure], serial)
        generated.extend(ns); new_events.extend(es); rows.append(row)
    # 常用右手伴奏型：新增保留跨入无攻击小节的同音级延音，再检查性质音与持续时序。
    bridges=preserve_held_bridges(shared,original,generated,rows,set(by_measure))
    # 常用右手伴奏型：新增跨小节补齐性质音，保持原始相位和起音点，合拨不变成扫弦。
    # 结构稳定伴奏与人声合播：修改，原代码注释保留。
    # complete_quality(shared, generated, new_events, rows, guitar['configuration']['capo_fret'], serial)
    complete_quality(shared, generated, new_events, rows, guitar['configuration']['capo_fret'], serial, guitar=guitar)
    included = set(by_measure); fallback = []
    while True:
        guitar['notes'] = sorted([n for n in original['notes'] if n['start_tick'] // bar + 1 not in included] +
                                [n for n in generated if n['start_tick'] // bar + 1 in included], key=lambda n: (n['start_tick'], n['string']))
        guitar['attack_events'] = sorted([e for e in original['attack_events'] if e['start_tick'] // bar + 1 not in included] +
                                        [e for e in new_events if e['start_tick'] // bar + 1 in included], key=lambda e: e['start_tick'])
        check = grip_position_path({**guitar, 'fingering_diagrams': []}, vocal)
        if check['valid']: break
        tick = check['tick']; failing = tick // bar + 1
        candidates = [m for m in (failing, failing - 1) if m in included]
        if not candidates: raise ValueError('受保护区域原手位仍不可行：' + str(check))
        restored = candidates[0]; included.remove(restored)
        fallback.append({'measure': restored, 'reason': check['reason'], 'tick': tick})
    guitar['hand_positions'] = check['positions']
    positions = {p['tick']: p['position'] for p in check['positions']}
    for tick in sorted({n['start_tick'] for n in guitar['notes']}):
        active = [n for n in guitar['notes'] if n['start_tick'] <= tick < n['end_tick']]
        info = grip_info({n['string']: n['fret'] for n in active})
        if info is None: raise ValueError('右手模板持续按位不可覆盖。')
        for note in active:
            if note['start_tick'] == tick and note.get('right_hand_pattern_id'):
                note['finger'] = info['fingers'].get(note['string'], 0); note['hand_position'] = positions[tick]
    # 常用右手伴奏型：新增保留源工程完整快照摘要，旧来源音编号可从审计对应回原工程。
    protected = [n for n in original['notes'] if n['start_tick'] // bar + 1 not in included]
    present = {n['id']: n for n in guitar['notes']}
    if any(present.get(n['id']) != n for n in protected): raise ValueError('右手模板意外改动受保护音符。')
    for key in ('fingering_diagrams', 'notation_regions', 'grip_hand_positions', 'grip_fingerings', 'tab_display', 'rhythm_display'):
        guitar.pop(key, None)
    # 规整分解节奏与延音显示：修改，原策略记录保留；记录是否采用规整拍格。
    # guitar['configuration']['right_hand_policy'] = {**POLICY, 'library_count': len(library()['patterns'])}
    guitar['configuration']['right_hand_policy'] = {**POLICY, 'library_count': len(library()['patterns']), 'regular_grid': regular}
    guitar['right_hand_patterns'] = {'phrases': plans, 'measures': [r for r in rows if r['measure'] in included],
                                    'changed_measures': sorted(included), 'skipped_measures': skipped,
                                    'playability_fallbacks': fallback, 'protected_note_ids': [n['id'] for n in protected],
                                    'protected_notes_unchanged': True, 'original_note_count': len(original['notes']),
                                    'source_event_count': len(original['attack_events']),
                                    'held_bridges':bridges,
                                    'new_note_count': sum(bool(n.get('right_hand_pattern_id')) for n in guitar['notes']),
                                    'source_notes': [n for n in original['notes'] if n['start_tick'] // bar + 1 in included]}
    guitar['adjustments'].append({'type': 'common_right_hand_vocal_accompaniment', 'changed_measures': sorted(included),
                                  'reason': '按正常演唱乐句稳定分解，原曲观察保留在共享分析，实际音序/节奏是吉他编配选择'})
    # 规整分解节奏与延音显示：新增本轮实际改写范围；回退保留的旧模板仍保留其原有语义记录。
    guitar['right_hand_patterns']['applied_this_run'] = sorted(included)
    old_plans = original.get('right_hand_patterns', {})
    retained_rows = [r for r in old_plans.get('measures', []) if r['measure'] not in included]
    if retained_rows:
        guitar['right_hand_patterns']['measures'].extend(deepcopy(retained_rows))
        guitar['right_hand_patterns']['changed_measures'] = sorted(included | {r['measure'] for r in retained_rows})
    return guitar


# 常用右手伴奏型：新增独立语义复核，检查模板格位、来源、真实左手基准及低音和弦意义。
def validate_patterns(shared, guitar):
    # 原声覆盖与选音归属通用修复：新增认可段落来源适配；音高／节奏和完整持续音仍由实际输出独立检查。
    if guitar.get('approved_section_preservation'):
        from approved_music_sections import validate_rhythm_chain
        return validate_rhythm_chain(shared,guitar,validate_patterns)
    if 'right_hand_patterns' not in guitar: return None
    errors = []; patterns = {p['id']: p for p in library()['patterns']}; bar = shared['statistics']['bar_ticks']
    changed = set(guitar['right_hand_patterns']['changed_measures']); grouped = {}
    for note in guitar['notes']:
        pid = note.get('right_hand_pattern_id')
        if not pid: continue
        grouped.setdefault(note['start_tick'], []).append(note)
        measure = note['start_tick'] // bar + 1; p = patterns.get(pid)
        # 跨曲低音与强拍复用通用修复：修改，原只认发声尾秒会拒绝有源支持的末拍补全；旧条件完整保留。
        # if measure not in changed or not any(s['kind'] == 'vocal' and s['start_tick'] <= note['start_tick'] < s['end_tick'] for s in shared['sections']):
        inside = any(s['kind'] == 'vocal' and s['start_tick'] <= note['start_tick'] < s['end_tick'] for s in shared['sections'])
        info = guitar.get('phrase_harmony_performance', {})
        if not inside and info.get('coverage_version') == 2 and note.get('phrase_harmony_generated'):
            # 跨曲低音与强拍复用通用修复：新增独立来源检查，仅允许最后不完整拍且原伴奏持续到该起音，不能扩散到真正器乐。
            pulse = int(PPQ*4/shared['timing']['meter'][1])
            sources = [n for n in info.get('source_notes', []) if n['id'] in note.get('source_note_ids', [])]
            inside = any(s['kind'] == 'vocal' and s['end_tick']//pulse*pulse <= note['start_tick'] <
                         ((s['end_tick']+pulse-1)//pulse)*pulse and any(
                             s['start_tick'] <= n['start_tick'] < s['end_tick'] and n['end_tick'] > note['start_tick']
                             and n.get('role') in ('bass','harmony') and not n.get('source_melody_id') for n in sources)
                         for s in shared['sections'])
        if measure not in changed or not inside:
            errors.append('pattern_outside_vocal:' + note['id'])
        if p is None or not 0 <= note['right_hand_slot'] < len(p['slots']): errors.append('pattern_or_slot_invalid:' + note['id']); continue
        if note['onset_origin'] != 'arranged_common_pattern' or not note.get('source_note_ids'): errors.append('pattern_source_invalid:' + note['id'])
        if note['pattern_baseline_frets'].get(str(note['string'])) != note['fret']: errors.append('pattern_fret_differs_from_grip:' + note['id'])
        h = next((h for h in shared['harmony'] if h['id'] == note['chord_id']), None)
        if not h or note['pitch_midi'] % 12 not in set(h['pitch_classes']) | {h['bass_pc']}: errors.append('pattern_pitch_outside_chord:' + note['id'])
        if h and note['role'] == 'bass' and note['pitch_midi'] % 12 != h['bass_pc']: errors.append('pattern_wrong_slash_bass:' + note['id'])
        if not note['pattern_adaptation'] and note['right_hand_token'] != p['slots'][note['right_hand_slot']]: errors.append('pattern_token_invalid:' + note['id'])
    for tick, notes in grouped.items():
        n = notes[0]; expected = {n['pattern_string_map'][t] for t in n['right_hand_token'].split('+')}
        if {n['string'] for n in notes} != expected: errors.append('pattern_plucked_strings_invalid:' + str(tick))
    # 常用右手伴奏型：新增足够攻击的和弦性质音覆盖，防止候选握住但整段根本没弹出加音/挂留。
    for h in shared['harmony']:
        ns = [n for notes in grouped.values() for n in notes if n['chord_id'] == h['id']]
        essential = set(h['pitch_classes']) - {(h['root_pc'] + 7) % 12}
        if len(ns) >= max(4, len(essential)) and essential - {n['pitch_midi'] % 12 for n in ns}:
            errors.append('pattern_missing_chord_quality:' + h['id'])
    return {'valid': not errors, 'errors': errors, 'changed_measure_count': len(changed),
            'pattern_ids': dict(Counter(r['pattern_id'] for r in guitar['right_hand_patterns']['measures'])),
            'pattern_note_count': sum(bool(n.get('right_hand_pattern_id')) for n in guitar['notes']),
            'adapted_attack_count': sum(bool(ns[0]['pattern_adaptation']) for ns in grouped.values()),
            'library_count': len(patterns), 'music_quality': 'requires_original_audio_comparison_and_player_review'}
