"""首次生成自动拍轴交接：匿名选拍、局部分组与覆盖组成同一可重放决定。"""
# 首次生成自动拍轴交接：新增版本化决定；历史选择器和已认可工程的单位修订政策保持原样。
from copy import deepcopy
import numpy as np
from source_meter_selection import (RAW_MODEL_KEYS, fingerprint, period_candidates, select_meter)
from source_meter_sequence import VECTOR_KEYS, validate_ordered_evidence
from source_timing_decoder import decode_four_beat_candidate
from source_meter_hierarchy import POLICY as SELECTION_POLICY, score_candidate_window
from source_meter_bar_groups import group_fixed_pulses

# 首次生成自动拍轴交接：修改策略版本仅清除未启用的分布阈值，实际门禁／得分／拍点不改变；草稿已归档。
# POLICY = {'version': 1, 'mode': 'first_generation_source_clock',
POLICY = {'version': 2, 'mode': 'first_generation_source_clock',
          'selection_policy': deepcopy(SELECTION_POLICY), 'grouping_version': 3,
          'maximum_unobserved_edge_seconds': 4.,
          # 首次生成自动拍轴交接：删除未使用字段并保留原行，不能让政策元数据冒充实际执行。
          # 'counterfactual_margin': .03, 'minimum_counterfactual_window_fraction': .65,
          # 'minimum_counterfactual_windows': 3,
          'counterfactual_margin': .03,
          'fixed_pulse_seconds_preserved': True, 'human_answers_or_score_timing_used': False,
          'pitch_chord_and_lyric_decoder_called': False, 'normal_publication_allowed': False}


def evidence_tracks(meta, arrays):
    # 首次生成自动拍轴交接：新增匿名数据读取；保留原声顺序和音区，不接收工程、歌词或曲名。
    keys = ('times', 'novelty', 'onset_low', 'onset_high', 'rms', 'phrase') + VECTOR_KEYS
    return {row['role']: {key: arrays[row['prefix'] + '_' + key] for key in keys} for row in meta['tracks']}


def cycle_counterfactual(candidate, tracks, windows):
    # 首次生成自动拍轴交接：新增实际相邻半小节内容反证；同强只表示多解，不据此一律选择快拍。
    # 首次生成自动拍轴交接：修改新层半拍采样，必须读取实际小节标签，不能在两拍过渡后继续全曲模四。
    # from source_meter_sequence import cosine_distance, sample_grid
    from source_meter_sequence import cosine_distance
    seconds = np.array([beat['seconds'] for beat in candidate['beats']])
    grid = np.arange(0., len(seconds) - 1, .5)
    points = np.interp(grid, np.arange(len(seconds)), seconds)
    base = np.floor(grid).astype(int)
    positions = np.array([beat['beat'] - 1 for beat in candidate['beats']])
    actual_labels = (2 * positions[base] + np.rint((grid - base) * 2).astype(int)) % 8
    rows = []
    for begin, end in windows:
        details, contrasts = {}, []
        for role in ('bass', 'accompaniment', 'six_guitar', 'six_piano'):
            if role not in tracks:
                continue
            track = tracks[role]
            # 首次生成自动拍轴交接：修改仅本次新反证的坐标；历史固定分组采样保持可重放。
            # at, labels = sample_grid(candidate['beats'], 0, track, begin, end)
            within = (points >= begin) & (points < end)
            at, labels = points[within], actual_labels[within]
            if len(at) < 24:
                continue
            period = float(np.median(np.diff([b['seconds'] for b in candidate['beats']])))
            vectors = np.stack([np.interp(at + .2 * period, track['times'], track[key]) for key in VECTOR_KEYS], axis=-1)
            # 首次生成自动拍轴交接：新增用同一物理片段比较2／4拍返回，不把变化幅度再投一次独立票。
            two = float(np.mean(cosine_distance(vectors[4:, :12], vectors[:-4, :12])))
            four = float(np.mean(cosine_distance(vectors[8:, :12], vectors[:-8, :12])))
            register_two = float(np.mean(cosine_distance(vectors[4:, 12:], vectors[:-4, 12:])))
            register_four = float(np.mean(cosine_distance(vectors[8:, 12:], vectors[:-8, 12:])))
            novelty = np.interp(at, track['times'], track['novelty'])
            first = novelty[labels == 0]; third = novelty[labels == 4]
            if len(first) < 2 or len(third) < 2:
                continue
            contrast = float(np.mean(first) - np.mean(third))
            details[role] = {'two_beat_content_distance': two, 'four_beat_content_distance': four,
                             'two_beat_register_distance': register_two, 'four_beat_register_distance': register_four,
                             'first_minus_third_change': contrast}
            contrasts.append((role, contrast))
        bass = [value for role, value in contrasts if role == 'bass']
        harmony = [value for role, value in contrasts if role != 'bass']
        # 首次生成自动拍轴交接：新增组内合并；原伴奏和分离乐器不能作为多份独立支持。
        grouped = ([float(np.mean(bass))] if bass else []) + ([float(np.median(harmony))] if harmony else [])
        source_contrast = float(np.mean(grouped)) if grouped else 0.
        rows.append({'start_seconds': begin, 'end_seconds': end, 'source_first_minus_third': source_contrast,
                     'first_role_supported': bool(grouped and source_contrast >= POLICY['counterfactual_margin']),
                     'third_role_supported': bool(grouped and source_contrast <= -POLICY['counterfactual_margin']),
                     'content_and_register': details})
    # 首次生成自动拍轴交接：新增保守语义；内容循环描述与模型首拍不同，不凭相关模板给快慢盖章。
    return {'windows': rows, 'comparison': 'actual_two_and_four_beat_content_and_source_roles',
            'level_truth_inferred_from_repetition_alone': False,
            'opposing_first_role_windows': sum(row['third_role_supported'] for row in rows)}


def _coverage(beats, arrays, tracks, duration):
    # 首次生成自动拍轴交接：新增独立覆盖，尾窗取足上下文，但末端未观察范围仍单独阻止通过。
    first, last = beats[0]['seconds'], beats[-1]['seconds']
    period = float(np.median(np.diff([b['seconds'] for b in beats])))
    windows, issues = [], []
    for start in np.arange(0., duration, SELECTION_POLICY['window_seconds']):
        end = min(duration, float(start) + SELECTION_POLICY['window_seconds'])
        context_start = max(0., min(float(start), end - (SELECTION_POLICY['minimum_bars_per_window'] + 1) * 4 * period))
        row = score_candidate_window(beats, 0, arrays, tracks, (context_start, end))
        reasons = list(row['conflicts'])
        if not row['eligible']:
            reasons.append('source_activity_or_observed_bars_insufficient')
        windows.append({'start_seconds': float(start), 'end_seconds': end, 'context_start_seconds': context_start,
                        'observed_bars': row['model']['bar_count'], 'model': row['model'],
                        'source_has_changes': row['ordered_source']['source_has_changes'], 'issues': reasons})
        if reasons:
            issues.append({'kind': 'source_window_unresolved', 'start_seconds': float(start),
                           'end_seconds': end, 'reasons': reasons})
    edge = []
    for name, begin, end in (('head', 0., first), ('tail', last, duration)):
        gap = max(0., end - begin)
        within_existing_bound = gap <= POLICY['maximum_unobserved_edge_seconds']
        edge.append({'kind': name, 'start_seconds': begin, 'end_seconds': end, 'duration_seconds': gap,
                     'status': 'bounded_edge_mapping' if within_existing_bound else 'needs_review',
                     'new_beats_inserted': False, 'unmetered_music_claimed': False})
        if not within_existing_bound:
            issues.append({'kind': name + '_not_observed', 'start_seconds': begin, 'end_seconds': end})
    return {'status': 'supported' if not issues else 'needs_review', 'windows': windows,
            'edge_ranges': edge, 'issues': issues, 'full_audio_duration_seconds': duration}


def decide_first_generation(meta, arrays):
    # 首次生成自动拍轴交接：新增完整候选决定，先重放既有层级比较，再核验每个候选的分组和覆盖。
    validate_ordered_evidence(meta, arrays)
    legacy = select_meter(meta, arrays)
    model = {key: arrays[key] for key in RAW_MODEL_KEYS}
    decoded = [decode_four_beat_candidate(model, period) for period in period_candidates(model)]
    tracks = evidence_tracks(meta, arrays)
    duration = float(meta['duration_seconds'])
    intervals = [(float(s), min(duration, float(s) + SELECTION_POLICY['window_seconds']))
                 for s in np.arange(0., duration, SELECTION_POLICY['window_seconds'])]
    candidates = []
    for item in legacy['ranked_candidates']:
        pulse = decoded[item['candidate_index']]
        grouping = group_fixed_pulses([beat['seconds'] for beat in pulse['beats']], arrays, tracks, version=3)
        candidate = deepcopy(pulse)
        candidate['beats'] = deepcopy(grouping['beats'])
        counter = cycle_counterfactual(candidate, tracks, intervals)
        coverage = _coverage(candidate['beats'], arrays, tracks, duration)
        # 首次生成自动拍轴交接：新增分组后反相位挑战；单一模板高分不能替代原伴奏组头支持。
        counter_issues = []
        if grouping['status'] == 'supported':
            for row in counter['windows']:
                if row['third_role_supported']:
                    counter_issues.append({'kind': 'source_roles_support_third_over_group_start',
                                           'start_seconds': row['start_seconds'], 'end_seconds': row['end_seconds']})
        candidates.append({'candidate_index': item['candidate_index'], 'bpm': item['bpm'], 'score': item['score'],
                           'qualification': deepcopy(item['qualification']), 'grouping': grouping,
                           'cycle_counterfactual': counter, 'counterfactual_issues': counter_issues,
                           'coverage': coverage, 'clock': candidate})
    chosen_index = legacy['best_supported_hypothesis']['candidate_index']
    chosen = next(row for row in candidates if row['candidate_index'] == chosen_index)
    level = deepcopy(legacy['notation_level'])
    phase_issues = deepcopy(chosen['grouping']['issues']) + deepcopy(chosen['counterfactual_issues'])
    if level['status'] != 'selected':
        phase_issues.append({'kind': 'grouping_conditional_on_unresolved_level'})
    phase_status = 'selected' if not phase_issues else 'needs_review'
    issues = ([{'kind': 'notation_level_unresolved', 'reasons': level['issues']}] if level['status'] != 'selected' else [])
    issues += phase_issues + deepcopy(chosen['coverage']['issues'])
    allowed = not issues
    return {'version': 1, 'policy': deepcopy(POLICY), 'policy_sha256': fingerprint(POLICY),
            'mix_sha256': meta['mix_sha256'], 'raw_evidence_sha256': meta['array_sha256'],
            'legacy_selection_sha256': fingerprint(legacy), 'notation_level': level,
            'bar_first_beat': {'status': phase_status, 'issues': phase_issues,
                               'local_short_bars': deepcopy(chosen['grouping']['short_bars'])},
            'coverage': deepcopy(chosen['coverage']), 'candidates': candidates,
            'selected_candidate_index': chosen_index, 'issues': issues,
            'status': 'passed' if allowed else 'needs_review', 'downstream_timing_revision_allowed': allowed,
            'normal_publication_allowed': False, 'pitch_chord_or_lyric_mutation_performed': False}
