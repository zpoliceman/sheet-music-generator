"""慢拍单位与两曲最小修订：逐候选原声顺序比较，分开单位、首拍与覆盖。"""
# 慢拍单位与两曲最小修订：新增第二版证据的通用选择器；旧选择器保留原样用于历史重放。
from copy import deepcopy
import numpy as np
from scipy.signal import find_peaks
from scipy.special import expit
from source_meter_selection import fingerprint, _model_scores, _sample, _source_scores
from source_meter_sequence import VECTOR_KEYS, sequence_profile, validate_ordered_evidence

POLICY = {
    'version': 3, 'meter': [4, 4], 'window_seconds': 32.,
    'minimum_windows': 3, 'minimum_bars_per_window': 3,
    'minimum_mean_beat_support': .65, 'minimum_group_compatibility': .60,
    'minimum_level_margin': .04, 'minimum_window_win_fraction': .65,
    'minimum_window_margin': .015, 'minimum_phase_margin': .08,
    'minimum_ordered_support': .25, 'minimum_source_activity': .015,
    'weights': {'model': .30, 'ordered': .35, 'drum': .35},
    'harmonic_half_beat_template': [1., 0., .4, 0., .8, 0., .4, 0.],
    'downbeat_at_third_is_not_a_missed_bar': True,
    'candidate_qualification_before_ranking': True,
    'model_lower_tail_is_window_evidence_not_global_veto': True,
    'human_answers_allowed': False, 'score_timing_allowed': False,
    'normal_publication_allowed': False,
    'confidence_kind': 'ordered_source_evidence_not_accuracy_probability',
}


def _correlation(values, template):
    # 慢拍单位与两曲最小修订：新增不封顶的时序形状比较，幅度小的平坦变化不给强证据。
    a, b = np.asarray(values, float), np.asarray(template, float)
    if np.std(a) < .015 or np.std(b) < 1e-9:
        return 0.
    return float(np.corrcoef(a, b)[0, 1])


def _contrast(a, b):
    # 慢拍单位与两曲最小修订：新增相对能量差，避免几乎恒定的噪声被相关系数放大。
    return float((a - b) / max(.1, a + b))


def _compatible_groups(beats, phase, arrays, interval, model):
    # 慢拍单位与两曲最小修订：新增层级比较中的1／3拍覆盖，第三拍模型峰不再自动算漏划小节。
    seconds = np.array([row['seconds'] for row in beats])
    labels = (np.array([row['beat'] for row in beats]) - 1 + phase) % 4
    times = np.arange(len(arrays['beat_logits'])) / 50.
    bp = expit(arrays['beat_logits'])
    dp = np.minimum(bp, expit(arrays['downbeat_logits']))
    peaks, values = find_peaks(dp, height=.5, distance=6)
    chosen = (times[peaks] >= interval[0]) & (times[peaks] < interval[1])
    peak_times, strength = times[peaks][chosen], values['peak_heights'][chosen]
    hit = np.zeros(len(peak_times), bool)
    first_hit = hit.copy()
    for second, label in zip(seconds, labels):
        if label in (0, 2):
            match = abs(peak_times - second) <= .08
            hit |= match
            if label == 0:
                first_hit |= match
    recall = float(strength[hit].sum() / max(1e-9, strength.sum()))
    precision = model['precision']
    f1 = 2 * precision * recall / max(1e-9, precision + recall)
    return {'first_or_third_recall': recall, 'group_f1': f1,
            'third_peak_weight': float(strength[hit & ~first_hit].sum()),
            'off_group_peak_weight': float(strength[~hit].sum()),
            'original_first_only_f1': model['f1']}


def _ordered_scores(beats, phase, tracks, interval):
    # 慢拍单位与两曲最小修订：新增低音与和声组的有序内容，以及鼓击整拍／半拍、强拍／反拍分工。
    details, harmony, bass, drum = {}, [], [], 0.
    activity = []
    for role, track in tracks.items():
        local = (track['times'] >= interval[0]) & (track['times'] < interval[1])
        threshold = max(1e-7, np.percentile(track['rms'], 85) * POLICY['minimum_source_activity'])
        active = bool(local.any() and np.percentile(track['rms'][local], 80) > threshold)
        profiles = sequence_profile(beats, phase, track, interval)
        row = {'active': active, 'half_beat_profiles': profiles}
        if role in ('bass', 'accompaniment', 'six_guitar', 'six_piano') and active:
            changes = profiles.get('pitch_changes', [0.] * 8)
            correlation = _correlation(changes, POLICY['harmonic_half_beat_template'])
            row['ordered_harmonic_correlation'] = correlation
            (bass if role == 'bass' else harmony).append(correlation)
            activity.append(max(changes) > .03)
        if role == 'drums' and active:
            lo, hi = np.asarray(profiles['onset_low']), np.asarray(profiles['onset_high'])
            pulse = _contrast(float(np.mean(lo[::2] + hi[::2])), float(np.mean(lo[1::2] + hi[1::2])))
            back = (_contrast(float(np.mean(hi[[2, 6]])), float(np.mean(hi[[0, 4]]))) +
                    _contrast(float(np.mean(lo[[0, 4]])), float(np.mean(lo[[2, 6]])))) / 2
            # 慢拍单位与两曲最小修订：修改鼓证据合成，明确四拍脉冲不会因没有独立反拍而被稀释。
            # drum = .6 * pulse + .4 * back
            drum = pulse + .5 * (1 - abs(pulse)) * back
            row.update(quarter_vs_half_attack_contrast=pulse, kick_snare_role_contrast=back,
                       ordered_drum_support=drum)
        details[role] = row
    groups = []
    if bass:
        groups.append(float(np.mean(bass)))
    if harmony:
        groups.append(float(np.median(harmony)))
    ordered = float(np.mean(groups)) if groups else 0.
    return {'ordered': ordered, 'drum': drum, 'source_has_changes': any(activity), 'tracks': details}


def score_candidate_window(beats, phase, arrays, tracks, interval):
    # 慢拍单位与两曲最小修订：新增所有候选相同窗口评分，模型与原声支持分开，缺证不等于错拍。
    model = _model_scores(beats, phase, arrays, interval)
    groups = _compatible_groups(beats, phase, arrays, interval, model)
    ordered = _ordered_scores(beats, phase, tracks, interval)
    w = POLICY['weights']
    model_score = float(np.sqrt(max(0., model['beat_probability'] * groups['group_f1'])))
    score = w['model'] * model_score + w['ordered'] * (.5 + .5 * ordered['ordered']) + w['drum'] * (.5 + .5 * ordered['drum'])
    legacy_source = _source_scores(beats, phase, tracks, interval)
    # 慢拍单位与两曲最小修订：新增独立的条件首拍分数；拍单位比较允许第三拍，首拍比较仍区别第1／3拍。
    phase_source = []
    for role, row in legacy_source['tracks'].items():
        if role in ('bass', 'accompaniment', 'six_guitar', 'six_piano') and row['active']:
            profile = row['novelty_by_beat']
            phase_source.append(_contrast(profile[0], max(profile[1:])))
    phase_score = .65 * model['f1'] + .35 * (.5 + .5 * (float(np.median(phase_source)) if phase_source else 0.))
    eligible = model['bar_count'] >= POLICY['minimum_bars_per_window'] and ordered['source_has_changes']
    conflicts = []
    if eligible and model['beat_probability'] < POLICY['minimum_mean_beat_support']:
        conflicts.append('model_pulses_weak_in_active_window')
    if eligible and groups['group_f1'] < POLICY['minimum_group_compatibility']:
        conflicts.append('model_groups_fall_outside_first_and_third')
    if eligible and ordered['ordered'] < 0. and ordered['drum'] <= 0.:
        conflicts.append('ordered_source_events_fall_between_candidate_beats')
    return {'score': float(score), 'phase_score': float(phase_score), 'eligible': eligible,
            'model': model, 'model_group_compatibility': groups, 'ordered_source': ordered,
            'conflicts': conflicts, 'source': legacy_source}


def compare_ordered_candidates(meta, arrays, decoded):
    # 慢拍单位与两曲最小修订：新增先逐候选核验再竞争；单位、首拍和整曲覆盖各有明确结果。
    validate_ordered_evidence(meta, arrays)
    keys = ('times', 'novelty', 'onset_low', 'onset_high', 'rms', 'phrase') + VECTOR_KEYS
    tracks = {r['role']: {k: arrays[r['prefix'] + '_' + k] for k in keys} for r in meta['tracks']}
    duration = float(meta['duration_seconds'])
    windows = [(float(start), min(duration, float(start) + POLICY['window_seconds']))
               for start in np.arange(0., duration, POLICY['window_seconds'])]
    options = []
    for index, candidate in enumerate(decoded):
        phases = []
        for phase in range(4):
            local = [score_candidate_window(candidate['beats'], phase, arrays, tracks, interval) for interval in windows]
            whole = score_candidate_window(candidate['beats'], phase, arrays, tracks, (0., duration))
            phases.append({'phase_rotation': phase, **whole, 'windows': local})
        phases.sort(key=lambda p: -p['phase_score'])
        best = phases[0]
        # 慢拍单位与两曲最小修订：新增单位证据的相位边缘化；只作比较，不拼接或旋转真实拍轴。
        unit_windows = [max((p['windows'][i] for p in phases), key=lambda r: r['score']) for i in range(len(windows))]
        # eligible = [r for r in best['windows'] if r['eligible']]
        eligible = [r for r in unit_windows if r['eligible']]
        supported = [r for r in eligible if not r['conflicts'] and
                     (r['ordered_source']['ordered'] >= POLICY['minimum_ordered_support'] or r['ordered_source']['drum'] >= .15)]
        fraction = len(supported) / max(1, len(eligible))
        issues = []
        if len(eligible) < POLICY['minimum_windows']:
            issues.append('too_few_source_windows')
        if best['model']['beat_probability'] < POLICY['minimum_mean_beat_support']:
            issues.append('weak_pulses_across_candidate')
        if best['model_group_compatibility']['group_f1'] < POLICY['minimum_group_compatibility']:
            issues.append('candidate_grouping_disagrees_with_model_and_source')
        if fraction < POLICY['minimum_window_win_fraction']:
            issues.append('positive_source_support_not_distributed')
        period = float(np.median(np.diff([r['seconds'] for r in candidate['beats']])))
        options.append({'candidate_index': index, 'period_seconds': period, 'bpm': 60 / period,
                        # 慢拍单位与两曲最小修订：修改单位比较分数为各相位证据上限，首拍仍另行验收。
                        # 'score': best['score'], 'phases': phases,
                        'score': max(p['score'] for p in phases), 'phases': phases, 'unit_windows': unit_windows,
                        'qualification': {'eligible': not issues, 'issues': issues,
                                          'positive_window_fraction': fraction, 'supported_windows': len(supported)}})
    if len(options) < 2:
        raise ValueError('独立快慢候选不足，不允许唯一候选自动通过')
    options.sort(key=lambda row: (not row['qualification']['eligible'], -row['score']))
    best, runner = options[:2]
    phase = best['phases'][0]
    rivals = [r for r in options[1:] if r['qualification']['eligible']]
    margin = best['score'] - max((r['score'] for r in rivals), default=runner['score'])
    local_rows, wins, phase_wins, thirds = [], [], [], set()
    unresolved = []
    for i, interval in enumerate(windows):
        # 慢拍单位与两曲最小修订：修改单位与首拍窗口分离，首拍不确定不会自动否认已稳定的拍长。
        # row = phase['windows'][i]
        row, phase_row = best['unit_windows'][i], phase['windows'][i]
        # 慢拍单位与两曲最小修订：新增候选缺证说明；不合格候选仍留报告，不能无条件抢走合格者的优势。
        # competitors = [r['phases'][0]['windows'][i]['score'] for r in (rivals or options[1:])
        #                if not r['phases'][0]['windows'][i]['conflicts']]
        competitors = [r['unit_windows'][i]['score'] for r in (rivals or options[1:])
                       if not r['unit_windows'][i]['conflicts']]
        delta = row['score'] - max(competitors, default=0.)
        # phase_delta = row['phase_score'] - max(p['windows'][i]['phase_score'] for p in best['phases'][1:])
        phase_delta = phase_row['phase_score'] - max(p['windows'][i]['phase_score'] for p in best['phases'][1:])
        okay = row['eligible'] and not row['conflicts']
        # 慢拍单位与两曲最小修订：修改全候选都缺少原模型支持的窗口处理，登记覆盖未决而非投快慢反对票。
        # if row['eligible']:
        observable = any(r['unit_windows'][i]['eligible'] and not r['unit_windows'][i]['conflicts'] for r in options)
        if row['eligible'] and observable:
            wins.append(okay and delta >= POLICY['minimum_window_margin'])
            phase_wins.append(phase_delta >= POLICY['minimum_window_margin'])
            if okay and delta >= POLICY['minimum_window_margin']:
                thirds.add(min(2, int(np.mean(interval) / duration * 3)))
        reasons = []
        if not row['eligible']:
            reasons.append('quiet_or_too_few_observed_bars')
        reasons += row['conflicts']
        if phase_delta < -POLICY['minimum_window_margin']:
            reasons.append('local_first_versus_third_conflict')
        if reasons:
            unresolved.append({'start_seconds': interval[0], 'end_seconds': interval[1], 'reasons': reasons})
        local_rows.append({'start_seconds': interval[0], 'end_seconds': interval[1],
                           'level_margin': delta, 'phase_margin': phase_delta, **row})
    fraction = float(np.mean(wins)) if wins else 0.
    issues = list(best['qualification']['issues'])
    if margin < POLICY['minimum_level_margin']:
        issues.append('ordered_candidates_not_separated')
    # 慢拍单位与两曲最小修订：修改单位与覆盖分离；至少两个时间区间支持单位，缺证尾段仍由覆盖门禁阻止生成。
    # if fraction < POLICY['minimum_window_win_fraction'] or len(thirds) < 3:
    if fraction < POLICY['minimum_window_win_fraction'] or len(thirds) < 2:
        issues.append('ordered_level_not_stable_across_song')
    phase_margin = phase['phase_score'] - best['phases'][1]['phase_score']
    phase_issues = []
    if issues:
        phase_issues.append('phase_is_conditional_on_unresolved_level')
    if phase_margin < POLICY['minimum_phase_margin']:
        phase_issues.append('first_versus_third_not_separated')
    if any('local_first_versus_third_conflict' in r['reasons'] for r in unresolved):
        phase_issues.append('local_phase_conflicts_need_source_review')
    level_ok, phase_ok = not issues, not phase_issues
    return {'version': 2, 'policy': deepcopy(POLICY), 'policy_sha256': fingerprint(POLICY),
        'mix_sha256': meta['mix_sha256'], 'raw_evidence_sha256': meta['array_sha256'],
        'status': 'selected' if level_ok and phase_ok else 'needs_review',
        'notation_level': {'status': 'selected' if level_ok else 'needs_review', 'bpm': best['bpm'] if level_ok else None,
                           'margin': margin, 'window_win_fraction': fraction, 'issues': issues,
                           'supported_temporal_thirds': sorted(thirds), 'scope': 'supported_regions_not_unobserved_full_song'},
        'bar_first_beat': {'status': 'selected' if phase_ok else 'needs_review',
                           'phase_rotation': phase['phase_rotation'] if phase_ok else None,
                           'margin': phase_margin, 'window_win_fraction': float(np.mean(phase_wins)) if phase_wins else 0.,
                           'issues': phase_issues},
        'coverage': {'status': 'supported' if not unresolved else 'needs_review', 'unresolved_windows': unresolved},
        'best_supported_hypothesis': {'candidate_index': best['candidate_index'], 'bpm': best['bpm'], 'phase_rotation': phase['phase_rotation']},
        'ranked_candidates': options, 'local_windows': local_rows, 'unresolved_windows': unresolved,
        'full_clock_music_accepted': False, 'normal_publication_allowed': False,
        'downstream_timing_revision_allowed': False, 'pitch_chord_or_lyric_mutation_performed': False}
