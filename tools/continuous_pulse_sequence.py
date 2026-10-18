"""连续源拍序与人声联合重解通用修复：原攻击序列联合选拍，不读取歌曲名、歌词或参考答案。"""
from collections import defaultdict
from copy import deepcopy
import math
import numpy as np
from score_export import PPQ, TempoMap

# 连续源拍序与人声联合重解通用修复：新增独立版本；历史拍轴1/2/3策略不改变。
POLICY = {'version': 1, 'grid_quarters': .25, 'candidate_radius_quarters': .5,
          # 连续源拍序与人声联合重解通用修复：修改，保留首轮窄窗口；分轨延迟约两帧的同一次攻击不能冒充第二拍。
          # 'correlated_event_seconds_fraction': .055, 'maximum_component_gap_quarters': 4.,
          # 连续源拍序与人声联合重解通用修复：修改，旧两帧窗保留；三帧分轨延迟仍小于半个十六分拍，不能误计成第二次攻击。
          # 'correlated_event_seconds_fraction': .10, 'maximum_component_gap_quarters': 4.,
          'correlated_event_seconds_fraction': .12, 'maximum_component_gap_quarters': 4.,
          'minimum_component_events': 7, 'interval_sigma_quarters': .09,
          'prior_weight': .025, 'anchor_weight': 8., 'minimum_clock_change_quarters': .08,
          'minimum_sequence_improvement': .20, 'source_seconds_averaged': False,
          'vocal_notation_used_for_pulse_phase': False}


# 连续源拍序与人声联合重解通用修复：新增同源物理攻击身份；窗口副本和相关分轨不增加票数。
def source_events(windows, shift=0., nominal=1.):
    raw = []
    for window in windows:
        if not window.get('observations'):
            continue
        source = window.get('source', 'accompaniment')
        for row in window['observations']:
            raw.append({'seconds': row['seconds'], 'quarter': row['quarter'] + shift,
                        'source': source, 'family': 'bass' if source == 'bass' else 'harmonic_mix',
                        'strength': row.get('strength', 1.), 'period': window['period_seconds']})
    groups = []
    for row in sorted(raw, key=lambda r: (r['seconds'], r['source'], r['quarter'])):
        candidates = [g for g in groups[-5:] if g[0]['family'] == row['family']
                      and abs(g[0]['seconds'] - row['seconds']) <= nominal * POLICY['correlated_event_seconds_fraction']
                      and all(r['source'] != row['source'] or abs(r['seconds'] - row['seconds']) < 1e-7 for r in g)]
        if candidates:
            min(candidates, key=lambda g: abs(g[0]['seconds'] - row['seconds'])).append(row)
        else:
            groups.append([row])
    events = []
    for group in groups:
        by_source = defaultdict(list)
        for row in group:
            by_source[row['source']].append(row)
        # 连续源拍序与人声联合重解通用修复：新增优先完整原伴奏的真实秒，不平均分离轨攻击时间。
        source = min(by_source, key=lambda name: (name != 'accompaniment', name != 'bass', name))
        representative = max(by_source[source], key=lambda r: r['strength'])
        labels = sorted({r['quarter'] for r in group})
        events.append({'seconds': representative['seconds'], 'source': source,
                       'family': representative['family'], 'candidate_labels': labels,
                       'period': float(np.median([r['period'] for r in group])),
                       'strength': max(r['strength'] for r in group),
                       'related_sources': sorted(by_source), 'window_copies': len(group)})
    # 连续源拍序与人声联合重解通用修复：新增独立低音同拍旁证只作为锚证据，不制造相隔几毫秒的第二个脉冲。
    final = []
    for row in sorted(events, key=lambda r: r['seconds']):
        if final and abs(row['seconds'] - final[-1]['seconds']) < nominal * .08 and row['family'] != final[-1]['family']:
            old = final[-1]
            old['candidate_labels'] = sorted(set(old['candidate_labels'] + row['candidate_labels']))
            old['related_sources'] = sorted(set(old['related_sources'] + row['related_sources']))
        else:
            final.append(row)
    return final


# 连续源拍序与人声联合重解通用修复：新增候选保留；不先用“贴近当前整拍”筛掉推翻现有拍轴的证据。
def candidates(event):
    grid = POLICY['grid_quarters']; radius = round(POLICY['candidate_radius_quarters'] / grid)
    return sorted({round((round(q / grid) + delta) * grid, 7)
                   for q in event['candidate_labels'] for delta in range(-radius, radius + 1)})


# 连续源拍序与人声联合重解通用修复：新增连续间隔代价；允许漏攻击和合法十六分，不允许无证据多/少计一拍。
def interval_cost(left, right, q0, q1):
    dq = q1 - q0
    if dq <= 0:
        return math.inf
    period = float(np.median([left['period'], right['period']]))
    dt = right['seconds'] - left['seconds']
    error = (dt / period - dq) / POLICY['interval_sigma_quarters']
    return min(64., error * error)


# 连续源拍序与人声联合重解通用修复：新增局部先验只作软约束；独立根音/人工源锚才能固定绝对拍号。
def observation_cost(event, q, anchors):
    distance = min(abs(q - x) for x in event['candidate_labels'])
    prior = POLICY['prior_weight'] * (distance / .25) ** 2
    # 连续源拍序与人声联合重解通用修复：修改，原窄根音窗保留；来源根音与分离轨可差两帧，沿用同一攻击身份窗。
    # nearby = [a for a in anchors if abs(a['seconds'] - event['seconds']) < .065 * event['period']]
    nearby = [a for a in anchors if abs(a['seconds'] - event['seconds']) <= POLICY['correlated_event_seconds_fraction'] * event['period']]
    if nearby:
        prior += POLICY['anchor_weight'] * min(((q - a['quarter']) / .25) ** 2 for a in nearby)
    return prior


# 连续源拍序与人声联合重解通用修复：新增整段动态规划，序列结果独立于输入顺序、重复窗口数量与字面歌词。
def solve_component(events, anchors=()):
    if not events:
        return [], {'status': 'no_source_events'}
    states = {q: (observation_cost(events[0], q, anchors), (q,)) for q in candidates(events[0])}
    for left, right in zip(events, events[1:]):
        following = {}
        for q in candidates(right):
            options = [(cost + interval_cost(left, right, previous, q) + observation_cost(right, q, anchors), path + (q,))
                       for previous, (cost, path) in states.items() if q > previous]
            if options:
                following[q] = min(options, key=lambda r: (r[0], r[1]))
        if not following:
            return [], {'status': 'ambiguous_sequence_preserved', 'reason': 'no_monotonic_complete_path'}
        states = following
    # 连续源拍序与人声联合重解通用修复：新增软先验打破整个组件等价平移；不靠已量化的人声主音投票。
    options = []
    for cost, path in states.values():
        alignment = sum(min(abs(q - old) for old in e['candidate_labels']) ** 2 for e, q in zip(events, path))
        options.append((cost + .015 * alignment, path))
    options.sort(key=lambda r: (r[0], r[1])); chosen = options[0]
    # 连续源拍序与人声联合重解通用修复：新增强来源锚冲突拒改，不能把全组件错一拍/一小节当成小残差通过。
    for event, q in zip(events, chosen[1]):
        nearby = [a for a in anchors if abs(a['seconds'] - event['seconds']) <= .1 * event['period']]
        if nearby and all(abs(q - a['quarter']) > .125 for a in nearby):
            return [], {'status': 'independent_anchor_phase_conflict_preserved',
                        'source_seconds': event['seconds'], 'selected_quarter': q,
                        'anchor_quarters': sorted({a['quarter'] for a in nearby})}
    legacy = [min(e['candidate_labels'], key=lambda q: (abs(q - chosen[1][i]), q)) for i, e in enumerate(events)]
    legacy_cost = sum(observation_cost(e, q, anchors) for e, q in zip(events, legacy))
    legacy_cost += sum(interval_cost(a, b, qa, qb) for a, b, qa, qb in zip(events, events[1:], legacy, legacy[1:]))
    result = [dict(deepcopy(e), quarter=q, selected_label_changed=all(abs(q - old) > 1e-6 for old in e['candidate_labels']))
              for e, q in zip(events, chosen[1])]
    return result, {'status': 'continuous_source_sequence_selected', 'event_count': len(events),
                    'sequence_cost': float(chosen[0]), 'legacy_label_cost': float(legacy_cost),
                    'runner_up_margin': float(options[1][0] - options[0][0]) if len(options) > 1 else None,
                    'labels_reconstructed': sum(r['selected_label_changed'] for r in result)}


# 连续源拍序与人声联合重解通用修复：新增来源绑定的根音锚；没有整拍接近证据的攻击仍参与连续计数。
def source_anchors(vocal, shift):
    rows = vocal.get('source_meter_correction', {}).get('phase_evidence', {}).get('changes', [])
    return [{'seconds': r['seconds'], 'quarter': round(r['pulse']) + shift, 'kind': 'independent_bass_phase_anchor'}
            for r in rows if abs(r['pulse'] - round(r['pulse'])) < .09 and r.get('relative_strength', 0.) >= .3]


# 连续源拍序与人声联合重解通用修复：新增同一证据链的逐段拍轴重建，低覆盖单独报告而非全曲认证。
def infer_sequence_clock(vocal):
    evidence = vocal.get('performance_clock_correction', {}).get('clock_evidence', {})
    windows = evidence.get('periodic_windows', [])
    nominal = 60 / vocal['timing']['steady_tempo_bpm']
    phase = vocal.get('source_meter_correction', {}).get('phase_evidence', {})
    shift = (phase.get('shift_ticks', 0) + phase.get('padding_ticks', 0)) / PPQ
    events = source_events(windows, shift, nominal)
    components = []
    for event in events:
        if not components or event['seconds'] - components[-1][-1]['seconds'] > nominal * POLICY['maximum_component_gap_quarters']:
            components.append([event])
        else:
            components[-1].append(event)
    anchors = source_anchors(vocal, shift)
    clock = TempoMap(vocal['timing']['knots']); origin = vocal['timing']['score_start_quarter']
    knots = deepcopy(vocal['timing']['knots']); audits = []; selected = []
    for component in components:
        if len(component) < POLICY['minimum_component_events']:
            audits.append({'status': 'insufficient_source_coverage_preserved', 'event_count': len(component),
                           'start_seconds': component[0]['seconds'], 'end_seconds': component[-1]['seconds']})
            continue
        solution, audit = solve_component(component, anchors)
        if not solution:
            # 连续源拍序与人声联合重解通用修复：修改，旧只记录单点冲突保留；整段范围供后续人声拒改，不能在坏轴上继续改字。
            # audits.append(audit); continue
            audit.update(start_seconds=component[0]['seconds'], end_seconds=component[-1]['seconds'],
                         event_count=len(component), clock_rebuilt=False)
            audits.append(audit); continue
        deltas = [r['seconds'] - clock.quarters_to_seconds(r['quarter'] + origin) for r in solution]
        audit.update(start_seconds=solution[0]['seconds'], end_seconds=solution[-1]['seconds'],
                     first_quarter=solution[0]['quarter'], last_quarter=solution[-1]['quarter'],
                     maximum_previous_residual_seconds=max(map(abs, deltas)),
                     independent_anchor_count=sum(solution[0]['seconds'] <= a['seconds'] <= solution[-1]['seconds'] for a in anchors))
        # 连续源拍序与人声联合重解通用修复：新增只重建有成段攻击支持且实测偏差明显的区域，健康旧拍轴保持。
        # 连续源拍序与人声联合重解通用修复：修改，旧仅残差触发保留；低置信整段相位须有来源锚或明显序列优势。
        # apply = max(map(abs, deltas)) > POLICY['minimum_clock_change_quarters'] * nominal
        supported = audit['independent_anchor_count'] > 0 or (audit['runner_up_margin'] or 0.) >= .25
        apply = supported and max(map(abs, deltas)) > POLICY['minimum_clock_change_quarters'] * nominal
        if apply:
            a, b = solution[0]['quarter'] + origin, solution[-1]['quarter'] + origin
            kept = [k for k in knots if k['quarter'] < a or k['quarter'] > b]
            additions = [{'quarter': r['quarter'] + origin, 'seconds': r['seconds'],
                          'source': 'continuous_original_attack_sequence'} for r in solution]
            revised = sorted(kept + additions, key=lambda r: r['quarter'])
            if any(x['quarter'] >= y['quarter'] or x['seconds'] >= y['seconds'] for x, y in zip(revised, revised[1:])):
                audit['status'] = 'boundary_or_phase_conflict_preserved'; apply = False
            else:
                knots = revised
        audit['clock_rebuilt'] = apply
        selected.extend(solution); audits.append(audit)
    revised = TempoMap(knots)
    for row in selected:
        row['new_residual_seconds'] = row['seconds'] - revised.quarters_to_seconds(row['quarter'] + origin)
    return knots, {'version': 1, 'policy': deepcopy(POLICY), 'components': audits,
                   'observations': selected, 'source_anchors': anchors,
                   'source_audio_seconds_preserved': True, 'reference_score_used': False,
                   'status': 'sequence_clock_rebuilt' if knots != vocal['timing']['knots'] else 'retained_clock',
                   'low_coverage_is_music_certification': False}
