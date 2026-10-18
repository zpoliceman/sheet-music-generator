"""局部时序与弱证据通用修复：版本2，保留谱面与原录音，联合局部演奏观察及可信边界。"""
from collections import defaultdict
from copy import deepcopy
from pathlib import Path
import math
import numpy as np
from score_export import PPQ, TempoMap, read_json, save_json
import performance_beat_clock as legacy

VERSION = 2
POLICY = {'version': VERSION, 'baseline_strategy': 1, 'local_window_quarters': 3.,
          # 局部时序与弱证据通用修复：新增长短窗共同覆盖短持续偏差，单个长窗会把短句两侧正确音稀释。
          'short_window_quarters': 1.5,
          'minimum_heads': 3, 'minimum_head_span_quarters': .5, 'minimum_direction_fraction': .75,
          # 局部时序与弱证据通用修复：修改，旧方向门限恰等常见40毫秒起声会放大浮点临界及速度差异；原值保留。
          # 'median_change_quarters': .08, 'direction_change_quarters': .04,
          'median_change_quarters': .08, 'direction_change_quarters': .05,
          'minimum_change_seconds': .045, 'head_uncertainty_quarters': .025,
          'phone_uncertainty_limit_quarters': .06, 'minimum_phone_agreement_quarters': .25,
          'padding_quarters': 2., 'boundary_search_bars': 2.,
          'head_weight': 1.5, 'interior_weight': .65,
          'independent_review_quarters': .10, 'retain_notation_ticks': True,
          'retain_source_seconds': True, 'harmonic_quality_version': 1}


# 局部时序与弱证据通用修复：新增整字入口含前置倚音，字内音段严格使用借时后的实际播放坐标。
def vocal_points(vocal):
    nominal = 60 / vocal['timing']['steady_tempo_bpm']
    by_word = defaultdict(list)
    for n in vocal['quantized_notes']:
        if n.get('lyric_index') is not None:
            by_word[n['lyric_index']].append(n)
    heads, interiors = [], []
    for c in vocal.get('lyrics', {}).get('characters', []):
        ns = by_word.get(c['index'], [])
        if not ns or c.get('start_seconds') is None:
            continue
        ordered = sorted(ns, key=lambda n: (n.get('playback_start_tick', n['start_tick']), n['start_seconds']))
        first = ordered[0]
        raw = float(first['start_seconds'])
        phone = float(c['start_seconds'])
        agreement = abs(raw - phone) <= POLICY['minimum_phone_agreement_quarters'] * nominal
        uncertainty = POLICY['head_uncertainty_quarters'] * nominal + min(
            POLICY['phone_uncertainty_limit_quarters'] * nominal, abs(raw - phone) * .35)
        q = first.get('playback_start_tick', first['start_tick']) / PPQ
        head = {'quarter': float(q), 'seconds': raw, 'raw_seconds': raw, 'phone_seconds': phone,
                'nucleus_seconds': next((ph.get('start_seconds') for ph in c.get('phonemes', [])
                                         if ph.get('role') == 'nucleus' and not ph.get('skipped')), None),
                'character_index': c['index'], 'line_index': c['line_index'],
                'weight': POLICY['head_weight'] if agreement else .35, 'reliable': agreement,
                'uncertainty_seconds': uncertainty, 'includes_grace': bool(first.get('grace')),
                'kind': 'word_performance_entry', 'source_note_id': first.get('source_note_id', first['id'])}
        heads.append(head)
        for n in ordered[1:]:
            at = n.get('playback_start_tick', n['start_tick']) / PPQ
            if (at <= q or n.get('grace') or not agreement
                    or n.get('confidence', 1.) < .55 or n['end_seconds'] - n['start_seconds'] < .05 * nominal):
                continue
            interiors.append({'quarter': float(at), 'seconds': float(n['start_seconds']),
                              'character_index': c['index'], 'line_index': c['line_index'],
                              'weight': POLICY['interior_weight'], 'kind': 'syllable_internal_performance',
                              'source_note_id': n.get('source_note_id', n['id']),
                              'nominal_quarter': n['start_tick'] / PPQ,
                              'uses_actual_playback_tick': True})
    return sorted(heads, key=lambda r: r['quarter']), interiors


# 局部时序与弱证据通用修复：新增局部强脉冲覆盖判别，不把弱轨或重复字内音当独立证人。
def pulse_near(pulse, q):
    return any(abs(p['quarter'] - q) < .30 and p['weight'] >= legacy.POLICY['minimum_reliable_pulse_weight'] for p in pulse)


# 局部时序与弱证据通用修复：新增沿用源记谱复核状态，不用时钟拟合掩盖未确认的音值。
def notation_uncertain(vocal, selected):
    indices = {r['character_index'] for r in selected}
    return any(g.get('needs_review') and any((g.get('first_character_index') or 0) <= i <= (g.get('last_character_index') or -1) for i in indices)
               for g in vocal['statistics'].get('phrase_rhythm', {}).get('phrases', []))


# 局部时序与弱证据通用修复：新增按局部四分拍长与字界不确定性评估同向偏差，适应其它速度。
def window_stats(mapping, origin, nominal, selected):
    residual = np.array([r['seconds'] - mapping.quarters_to_seconds(r['quarter'] + origin) for r in selected])
    periods = [mapping.quarters_to_seconds(r['quarter'] + origin + .5) - mapping.quarters_to_seconds(r['quarter'] + origin) for r in selected]
    period = min(1.75 * nominal, max(.6 * nominal, 2 * float(np.median(periods))))
    threshold = max(POLICY['minimum_change_seconds'], POLICY['median_change_quarters'] * period,
                    2 * float(np.median([r['uncertainty_seconds'] for r in selected])))
    side = max(.025, POLICY['direction_change_quarters'] * period)
    positive, negative = int(np.sum(residual >= side)), int(np.sum(residual <= -side))
    return {'first_quarter': selected[0]['quarter'], 'last_quarter': selected[-1]['quarter'],
            'character_indices': [r['character_index'] for r in selected], 'word_count': len(selected),
            'median_residual_seconds': float(np.median(residual)), 'threshold_seconds': threshold,
            'witness_count': max(positive, negative), 'maximum_residual_seconds': float(np.max(np.abs(residual))),
            'direction': 'later' if positive >= negative else 'earlier',
            'same_direction_supported': max(positive, negative) >= math.ceil(len(selected) * POLICY['minimum_direction_fraction'])}


# 局部时序与弱证据通用修复：新增滑动音乐短窗而非整行投票，少数拖字及可靠伴奏上的唱法进入复核。
def local_disagreements(vocal, mapping, heads, pulse):
    origin = vocal['timing']['score_start_quarter']
    nominal = 60 / vocal['timing']['steady_tempo_bpm']
    reliable = [r for r in heads if r['reliable']]
    triggers, audit = [], []
    for span in legacy.singing_spans(vocal):
        local = [r for r in reliable if span['first_quarter'] <= r['quarter'] < span['last_quarter']]
        for head in local:
            # 局部时序与弱证据通用修复：修改，单个3拍窗原型保留；长短窗口独立检查且相同字组只计一次。
            # selected = [r for r in local if head['quarter'] <= r['quarter'] <= head['quarter'] + POLICY['local_window_quarters']]
            # if len(selected) < POLICY['minimum_heads'] or selected[-1]['quarter'] - selected[0]['quarter'] < POLICY['minimum_head_span_quarters']:
            #     continue
            # row = window_stats(mapping, origin, nominal, selected)
            # strong = sum(pulse_near(pulse, r['quarter']) for r in selected)
            # row.update(periodic_pulse_word_count=strong, status='within_local_performance_tolerance')
            # if row['same_direction_supported'] and abs(row['median_residual_seconds']) >= row['threshold_seconds']:
            #     if strong >= len(selected) * .5:
            #         row['status'] = 'vocal_expression_or_notation_conflict_periodic_pulse_kept'
            #     elif notation_uncertain(vocal, selected):
            #         row['status'] = 'uncertain_notation_keep_clock_for_review'
            #     else:
            #         row['status'] = 'local_coherent_vocal_time_disagreement'
            #         triggers.append({'first_quarter': row['first_quarter'], 'last_quarter': row['last_quarter'],
            #                          'reason': row['status'], 'character_indices': row['character_indices']})
            # audit.append(row)
            seen = set()
            for length in [POLICY['short_window_quarters'], POLICY['local_window_quarters']]:
                selected = [r for r in local if head['quarter'] <= r['quarter'] <= head['quarter'] + length]
                ids = tuple(r['character_index'] for r in selected)
                if (ids in seen or len(selected) < POLICY['minimum_heads']
                        or selected[-1]['quarter'] - selected[0]['quarter'] < POLICY['minimum_head_span_quarters']):
                    continue
                seen.add(ids)
                row = window_stats(mapping, origin, nominal, selected)
                strong = sum(pulse_near(pulse, r['quarter']) for r in selected)
                row.update(window_quarters=length, periodic_pulse_word_count=strong, status='within_local_performance_tolerance')
                if row['same_direction_supported'] and abs(row['median_residual_seconds']) >= row['threshold_seconds']:
                    if strong >= len(selected) * .5:
                        row['status'] = 'vocal_expression_or_notation_conflict_periodic_pulse_kept'
                    elif notation_uncertain(vocal, selected):
                        row['status'] = 'uncertain_notation_keep_clock_for_review'
                    else:
                        row['status'] = 'local_coherent_vocal_time_disagreement'
                        triggers.append({'first_quarter': row['first_quarter'], 'last_quarter': row['last_quarter'],
                                         'reason': row['status'], 'character_indices': row['character_indices']})
                audit.append(row)
    return triggers, audit


# 局部时序与弱证据通用修复：新增优先寻找真实脉冲边界；不足时使用连续唱段外边界并明确其先验身份。
def joint_regions(vocal, mapping, triggers, pulse):
    origin = vocal['timing']['score_start_quarter']
    bar = vocal['statistics']['bar_ticks'] / PPQ
    strong = sorted({p['quarter'] for p in pulse if p['weight'] >= legacy.POLICY['minimum_reliable_pulse_weight']})
    max_q = vocal['statistics']['total_ticks'] / PPQ
    regions = []
    for trigger in sorted(triggers, key=lambda r: r['first_quarter']):
        first, last = trigger['first_quarter'], trigger['last_quarter']
        span = next((s for s in legacy.singing_spans(vocal) if s['first_quarter'] <= first < s['last_quarter']), None)
        if span is None:
            continue
        left = [q for q in strong if max(0., span['first_quarter']) <= q < first - .25 and first - q <= POLICY['boundary_search_bars'] * bar]
        right = [q for q in strong if last + .25 < q <= min(max_q, span['last_quarter']) and q - last <= POLICY['boundary_search_bars'] * bar]
        # 局部时序与弱证据通用修复：新增边界先验只能放在整个连续唱段外侧，不能锁在任意整数拍截断待校准短句。
        lo = max(left) if left else max(0., math.floor(span['first_quarter']))
        hi = min(right) if right else min(max_q, math.ceil(span['last_quarter']))
        if hi <= lo:
            continue
        row = {'first_quarter': float(lo), 'last_quarter': float(hi), 'span_first_quarter': span['first_quarter'],
               'reasons': [trigger['reason']], 'character_indices': list(trigger['character_indices']),
               'left_boundary_kind': 'periodic_source_anchor' if left else 'outer_singing_span_prior',
               'right_boundary_kind': 'periodic_source_anchor' if right else 'outer_singing_span_prior',
               'unverified_integer_boundary_fixed': False}
        if regions and regions[-1]['span_first_quarter'] == span['first_quarter'] and lo <= regions[-1]['last_quarter']:
            previous = regions[-1]
            if hi > previous['last_quarter']:
                previous.update(last_quarter=float(hi), right_boundary_kind=row['right_boundary_kind'])
            previous['reasons'].extend(row['reasons'])
            previous['character_indices'] = sorted(set(previous['character_indices']) | set(row['character_indices']))
        else:
            regions.append(row)
    return regions


# 局部时序与弱证据通用修复：新增独立半小节覆盖检查；验收不复用触发短窗，也不把未知音乐报成准确。
def independent_review(vocal, mapping, heads, pulse):
    origin = vocal['timing']['score_start_quarter']
    nominal = 60 / vocal['timing']['steady_tempo_bpm']
    bar = vocal['statistics']['bar_ticks'] / PPQ
    total = vocal['statistics']['total_ticks'] / PPQ
    windows, unresolved, review, uncovered = [], [], [], []
    for first in np.arange(0., total, bar / 2):
        # 局部时序与弱证据通用修复：修改，原重叠整小节检查保留；真正独立按半小节检查，防止两侧正确音稀释。
        # selected = [r for r in heads if first <= r['quarter'] < first + bar]
        selected = [r for r in heads if first <= r['quarter'] < first + bar / 2]
        if not selected:
            continue
        reliable = [r for r in selected if r['reliable']]
        strong = sum(pulse_near(pulse, r['quarter']) for r in selected)
        # 局部时序与弱证据通用修复：修改，保留旧终点；审计范围与实际半小节选择一致。
        # row = {'first_quarter': float(first), 'last_quarter': float(min(total, first + bar)),
        row = {'first_quarter': float(first), 'last_quarter': float(min(total, first + bar / 2)),
               'word_count': len(selected), 'reliable_head_count': len(reliable),
               'periodic_pulse_word_count': strong, 'status': 'source_evidence_available'}
        if len(reliable) < POLICY['minimum_heads'] and strong < POLICY['minimum_heads']:
            row['status'] = 'insufficient_local_source_coverage_requires_review'
            uncovered.append(deepcopy(row))
        if len(reliable) >= POLICY['minimum_heads']:
            stats = window_stats(mapping, origin, nominal, reliable)
            row.update(median_residual_seconds=stats['median_residual_seconds'], maximum_residual_seconds=stats['maximum_residual_seconds'])
            threshold = max(POLICY['independent_review_quarters'] * nominal, stats['threshold_seconds'])
            if stats['same_direction_supported'] and abs(stats['median_residual_seconds']) > threshold:
                row['status'] = 'vocal_expression_or_notation_requires_review' if strong >= len(selected) * .5 or notation_uncertain(vocal, reliable) else 'unresolved_local_vocal_residual'
                (review if row['status'] != 'unresolved_local_vocal_residual' else unresolved).append(deepcopy(row))
        windows.append(row)
    return {'windows': windows, 'unresolved': unresolved, 'expression_or_notation_review': review, 'uncovered': uncovered,
            'scope': '独立半小节源覆盖与多字绝对残差；单字唱法及稀疏证据明确复核，不声称整曲音乐认证'}


# 局部时序与弱证据通用修复：新增版本1校准后的通用局部联合拟合，所有推断仍从绑定源确定重建。
# 跨歌曲和弦复用与器乐准备：修改，旧入口／基线保留；新版本显式注入源解析与局部权重，不改变历史重建。
# def infer_refined_clock(base, binding, cache):
#     baseline_knots, baseline_audit = legacy.infer_performance_clock(base, binding, cache)
def infer_refined_clock(base, binding, cache, *, source_pulse_resolver=None, local_observation_weights=None, evidence_policy=None):
    if source_pulse_resolver is None:
        baseline_knots, baseline_audit = legacy.infer_performance_clock(base, binding, cache)
    else:
        baseline_knots, baseline_audit = legacy.infer_performance_clock(base, binding, cache, source_pulse_resolver)
    initial = deepcopy(base)
    initial['timing']['knots'] = baseline_knots
    mapping = TempoMap(baseline_knots)
    origin = base['timing']['score_start_quarter']
    nominal = 60 / base['timing']['steady_tempo_bpm']
    pulse = baseline_audit['source_pulse_residuals']
    heads, interiors = vocal_points(base)
    triggers, before = local_disagreements(base, mapping, heads, pulse)
    regions = joint_regions(base, mapping, triggers, pulse)
    knots = {k['quarter']: deepcopy(k) for k in baseline_knots}
    regional = []
    for region in regions:
        # 局部时序与弱证据通用修复：新增弱窗内所有可靠字首作共同约束，可靠脉冲上的演唱表现不强拉拍轴。
        local_heads = [r for r in heads if r['reliable'] and region['first_quarter'] < r['quarter'] < region['last_quarter']
                       and not pulse_near(pulse, r['quarter']) and not notation_uncertain(base, [r])]
        allowed = {r['character_index'] for r in local_heads}
        local_interiors = [r for r in interiors if r['character_index'] in allowed and not pulse_near(pulse, r['quarter'])]
        # 跨歌曲和弦复用与器乐准备：修改，旧联合权重完整保留；可靠多字触发的新区域才协调弱证据权重。
        # points, evidence = legacy.fit_region(mapping, origin, region, pulse + local_heads + local_interiors, nominal)
        fit_observations = pulse + local_heads + local_interiors
        weight_evidence = None
        if local_observation_weights is not None:
            fit_observations, weight_evidence = local_observation_weights(region, pulse, local_heads, local_interiors)
        points, evidence = legacy.fit_region(mapping, origin, region, fit_observations, nominal)
        if weight_evidence is not None:
            evidence['observation_weight_resolution'] = weight_evidence
        evidence.update(head_observation_count=len(local_heads), interior_observation_count=len(local_interiors))
        regional.append(evidence)
        for k in points:
            knots[k['quarter']] = k
    updated = [knots[q] for q in sorted(knots)]
    revised = TempoMap(updated)
    _, after = local_disagreements(base, revised, heads, pulse)
    coverage = independent_review(base, revised, heads, pulse)
    def residuals(rows):
        return [dict(r, before_seconds=mapping.quarters_to_seconds(r['quarter'] + origin),
                     after_seconds=revised.quarters_to_seconds(r['quarter'] + origin),
                     after_residual_seconds=r['seconds'] - revised.quarters_to_seconds(r['quarter'] + origin)) for r in rows]
    pulses = [dict(r, residual_seconds=r['seconds'] - revised.quarters_to_seconds(r['quarter'] + origin)) for r in pulse]
    unresolved_pulses = [r for r in pulses if r['weight'] >= legacy.POLICY['minimum_reliable_pulse_weight']
                         and abs(r['residual_seconds']) > legacy.POLICY['residual_review_quarters'] * nominal]
    phase = baseline_audit['source_event_phase_resolution']
    expression = baseline_audit['music_residual_check']['vocal_expression_or_notation_review'] + coverage['expression_or_notation_review']
    check = {'valid': not unresolved_pulses and not coverage['unresolved'] and not phase['unresolved_phase_conflicts'],
             'pulse_count': len(pulses), 'unresolved_pulses': unresolved_pulses,
             'unresolved_vocal_regions': coverage['unresolved'], 'unresolved_source_phase_conflicts': phase['unresolved_phase_conflicts'],
             'vocal_expression_or_notation_review': expression, 'insufficient_source_coverage_review': coverage['uncovered'],
             'source_evidence_accuracy_claimed': False,
             'maximum_pulse_residual_seconds': max((abs(r['residual_seconds']) for r in pulses), default=0.)}
    # 跨歌曲和弦复用与器乐准备：修改，旧版本2标记保留为默认；新版单独记录显式策略，不静默改写历史工程。
    # audit = {'version': VERSION, 'policy': deepcopy(POLICY),
    active_policy = POLICY if evidence_policy is None else evidence_policy
    audit = {'version': active_policy['version'], 'policy': deepcopy(active_policy),
             'status': 'performance_time_reconciled' if regional or baseline_audit['status'] != 'retained_clock' else 'retained_clock',
             'baseline_strategy_version': 1, 'baseline_evidence': baseline_audit,
             'local_vocal_before': before, 'local_vocal_after': after, 'regions': regional,
             'periodic_windows': baseline_audit['periodic_windows'], 'source_pulse_residuals': pulses,
             'source_event_phase_resolution': phase, 'vocal_residuals': residuals(heads),
             'vocal_interior_residuals': residuals(interiors), 'independent_local_review': coverage,
             'music_residual_check': check, 'notation_ticks_unchanged': True, 'original_source_seconds_unchanged': True,
             'human_answers_used': False, 'related_tracks_counted_once': True}
    return updated, audit


# 局部时序与弱证据通用修复：新增版本2派生元数据，旧版本1的源重建和函数保持原语义。
def apply_refined_clock(base, knots, audit, correction=None):
    vocal = legacy.apply_performance_clock(base, knots, audit, correction)
    # 跨歌曲和弦复用与器乐准备：修改，旧版本号保留；实际派生版本与审计一致，旧调用仍为2。
    # vocal['timing']['performance_beat_clock']['version'] = VERSION
    # vocal['decoder']['performance_beat_clock']['version'] = VERSION
    vocal['timing']['performance_beat_clock']['version'] = audit.get('version', VERSION)
    vocal['decoder']['performance_beat_clock']['version'] = audit.get('version', VERSION)
    vocal['decoder']['performance_beat_clock']['review_required'] = bool(
        audit['music_residual_check']['vocal_expression_or_notation_review'] or audit['music_residual_check']['insufficient_source_coverage_review'])
    return vocal


# 局部时序与弱证据通用修复：新增严格版本2源指纹、策略和完整观察重放，历史版本按旧路径读取。
def derive_refined_vocal(original, binding, correction):
    if (correction.get('version') != VERSION or correction.get('policy') != POLICY
            or correction.get('source_vocal_project_sha256') != binding['vocal_project_sha256']
            or correction.get('source_fingerprints') != {k: s['sha256'] for k, s in binding['sources'].items()}):
        raise ValueError('局部演奏拍轴派生策略或源指纹不一致。')
    base = legacy.reconstruct_base(original, binding, correction)
    knots, audit = infer_refined_clock(base, binding, Path(correction['feature_cache']))
    if audit != correction.get('clock_evidence'):
        raise ValueError('局部演奏拍轴证据不能由绑定原轨确定重建。')
    return apply_refined_clock(base, knots, audit, correction)


# 局部时序与弱证据通用修复：新增明确升级，另算共有和声/两套编配，旧录音和历史谱不覆盖。
# 跨歌曲和弦复用与器乐准备：修改，旧升级入口保留；新策略显式提供推断、应用与版本，普通编辑不升级。
# def correct_refined_project(shared, vocal, arrangements, cache_dir):
def correct_refined_project(shared, vocal, arrangements, cache_dir, strategy=None):
    active_policy = POLICY if strategy is None else strategy.POLICY
    infer = infer_refined_clock if strategy is None else strategy.infer_evidence_clock
    apply = apply_refined_clock if strategy is None else strategy.apply_evidence_clock
    previous = vocal.get('performance_clock_correction', {})
    # 跨歌曲和弦复用与器乐准备：修改，旧版本相等条件保留；仅在显式策略已经应用时保留。
    # if previous.get('version') == VERSION:
    if previous.get('version') == active_policy['version']:
        return shared, vocal, arrangements
    from accompaniment_analysis import analyze
    # 渴首次吉他编配：修改，重建阶段继承绑定的乐器范围；原代码注释保留。
    # from accompaniment_arrange import arrange_guitar, arrange_piano
    # 渴首次吉他编配：新增按所选乐器执行，保留各乐器原验证。
    from accompaniment_arrange import arrange_requested
    from accompaniment_texture_policy import add_block_support
    from beat_phase_alignment import seed_existing_music
    # 局部时序与弱证据通用修复：新增钢琴低音与换和弦拍位的共同校准，和新吉他使用同一拍轴。
    from beat_phase_alignment import align_piano_bass
    from local_beat_clock import reusable_guitar_configuration
    binding = shared['input_binding']
    cache = Path(cache_dir).resolve()
    legacy.copy_features(binding, cache, [previous.get('feature_cache'), vocal.get('structural_clock_correction', {}).get('feature_cache')])
    base = legacy.reconstruct_base(read_json(binding['vocal_project']), binding, previous) if previous else deepcopy(vocal)
    # 跨歌曲和弦复用与器乐准备：修改，旧推断保留为默认策略。
    # knots, audit = infer_refined_clock(base, binding, cache)
    knots, audit = infer(base, binding, cache)
    save_json(cache.parent / 'performance_clock_evidence.json', audit)
    # 跨歌曲和弦复用与器乐准备：修改，旧策略字典保留；新派生明确记录版本并可严格重放。
    # correction = {'version': VERSION, 'policy': deepcopy(POLICY), 'source_vocal_project_sha256': binding['vocal_project_sha256'],
    correction = {'version': active_policy['version'], 'policy': deepcopy(active_policy), 'source_vocal_project_sha256': binding['vocal_project_sha256'],
                  'source_fingerprints': {k: s['sha256'] for k, s in binding['sources'].items()},
                  'base_structural_correction': deepcopy(base.get('structural_clock_correction')),
                  'base_local_correction': deepcopy(base.get('local_clock_correction')),
                  'base_phase_correction': deepcopy(base.get('beat_phase_correction')),
                  'base_grid_correction': deepcopy(base.get('grid_correction')),
                  'feature_cache': str(cache), 'clock_evidence': audit}
    # 跨歌曲和弦复用与器乐准备：修改，旧应用保留为默认策略。
    # updated = apply_refined_clock(base, knots, audit, correction)
    updated = apply(base, knots, audit, correction)
    fresh_shared = add_block_support(analyze(binding, updated, cache, harmonic_quality=True), updated, cache)
    for field in ('arrangement_policy', 'musical_structure', 'melodic_motif_matches'):
        if field in shared:
            fresh_shared[field] = deepcopy(shared[field])
    fresh_shared['performance_beat_clock'] = deepcopy(audit)
    # 渴首次吉他编配：修改，避免未请求乐器阻塞所选乐器；原代码注释保留。
    # fresh = {'guitar': arrange_guitar(fresh_shared, updated, arrangements['guitar']['configuration']['capo_fret']),
    #          'piano': arrange_piano(fresh_shared, updated)}
    # 渴首次吉他编配：新增按所选乐器执行，保留各乐器原验证。
    fresh = arrange_requested(fresh_shared, updated, arrangements['guitar']['configuration']['capo_fret'])
    fresh = seed_existing_music(shared, vocal, arrangements, fresh_shared, updated, fresh, source_time_sections=True)
    fresh = legacy.restore_synthetic_seed_ticks(shared, vocal, arrangements, fresh_shared, updated, fresh)
    fresh['guitar']['configuration'].update(reusable_guitar_configuration(arrangements['guitar']['configuration']))
    fresh['guitar']['configuration']['beat_synchronous_patterns'] = True
    # 渴首次吉他编配：修改，仅对已选择钢琴校准钢琴低音；原代码注释保留。
    # align_piano_bass(fresh_shared, updated, fresh['piano'])
    # 渴首次吉他编配：新增按所选乐器执行，保留各乐器原验证。
    if 'piano' in fresh:
        align_piano_bass(fresh_shared, updated, fresh['piano'])
    return fresh_shared, updated, fresh
