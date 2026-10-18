"""自动拍层级与首拍盲测：只用匿名原声证据比较四拍候选，允许拒绝判断。"""
# 自动拍层级与首拍盲测：新增独立选择层；不接收旧谱、歌词对齐、人工答案或曲目身份。
from copy import deepcopy
import hashlib
import json
import math
import numpy as np
from scipy.signal import find_peaks
from scipy.special import expit
from source_timing_decoder import decode_four_beat_candidate


# 自动拍层级与首拍盲测：新增首轮实曲预测前固定的通用规则；分数不是校准后的准确率。
POLICY = {
    # 自动拍层级与首拍盲测：修改安全修订版本，首次盲测源码和失败报告另存，原式保留。
    # 'version': 1, 'meter': [4, 4], 'window_seconds': 32.,
    'version': 2, 'meter': [4, 4], 'window_seconds': 32.,
    'model_frames_per_second': 50, 'peak_tolerance_seconds': .08,
    'minimum_windows': 3, 'minimum_bars_per_window': 3,
    'minimum_level_margin': .10, 'minimum_phase_margin': .10,
    'minimum_window_margin': .04, 'minimum_window_win_fraction': .70,
    'minimum_model_downbeat_f1': .65, 'minimum_beat_probability': .65,
    # 自动拍层级与首拍盲测：新增既有原声上下文的下尾概率门槛，阻止高平均值掩盖假拍；非针对某首曲子的拍速偏好。
    'beat_probability_lower_quantile': .05, 'minimum_lower_quantile_beat_probability': .85,
    'minimum_source_support_fraction': .60,
    'source_contrast_scale': .10, 'minimum_source_contrast': .025,
    'weights': {'model': .60, 'harmonic': .25, 'drum': .10, 'phrase': .05},
    'human_answers_allowed': False, 'score_timing_allowed': False,
    'normal_publication_allowed': False, 'downstream_timing_revision_allowed': False,
    'confidence_kind': 'evidence_margin_not_calibrated_accuracy',
}
ROLES = ('accompaniment', 'bass', 'six_guitar', 'six_piano', 'drums', 'vocals')
RAW_MODEL_KEYS = ('beats', 'downbeats', 'beat_logits', 'downbeat_logits')


def fingerprint(value):
    # 自动拍层级与首拍盲测：新增规范化策略／预测指纹，便于先封存预测、再打开标签。
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def validate_evidence(meta, arrays):
    # 自动拍层级与首拍盲测：新增白名单；多出的旧谱／人工字段直接报错，不能静默参与推断。
    allowed = {'version', 'duration_seconds', 'mix_sha256', 'model_archive_sha256',
               'tracks', 'array_sha256', 'raw_only'}
    if (set(meta) != allowed or meta['version'] != 1 or meta['raw_only'] is not True
            or not isinstance(meta['duration_seconds'], (float, int))
            or not math.isfinite(meta['duration_seconds']) or meta['duration_seconds'] <= 0):
        raise ValueError('匿名证据字段不合法；禁止混入人工答案或旧谱拍轴')
    expected = set(RAW_MODEL_KEYS)
    seen = set()
    for track in meta['tracks']:
        if (set(track) != {'role', 'source_sha256', 'prefix'} or track['role'] not in ROLES
                or track['role'] in seen or track['prefix'] != 't' + str(len(seen))):
            raise ValueError('原声分轨白名单或匿名编号不合法')
        seen.add(track['role'])
        prefix = track['prefix']
        expected.update(prefix + '_' + key for key in ('times', 'novelty', 'onset_low',
                                                       'onset_high', 'rms', 'phrase'))
    if set(arrays) != expected:
        raise ValueError('匿名原声数组字段不合法')
    for key, value in arrays.items():
        if np.asarray(value).ndim != 1 or not np.all(np.isfinite(value)):
            raise ValueError('匿名原声数组含非数、维度错误或无穷值：' + key)
    if (len(arrays['beats']) < 16 or np.any(np.diff(arrays['beats']) <= 0)
            or len(arrays['beat_logits']) != len(arrays['downbeat_logits'])):
        raise ValueError('原始节拍数组不足或逆序')
    for track in meta['tracks']:
        prefix = track['prefix']
        times = arrays[prefix + '_times']
        if len(times) < 16 or np.any(np.diff(times) <= 0):
            raise ValueError('原声时间帧不足或逆序')
        if any(len(arrays[prefix + '_' + key]) != len(times)
               for key in ('novelty', 'onset_low', 'onset_high', 'rms', 'phrase')):
            raise ValueError('原声特征帧不一致')


def period_candidates(arrays):
    # 自动拍层级与首拍盲测：新增仅从原模型推导倍／半拍候选，候选顺序不带A／B答案或慢拍偏好。
    intervals = np.diff(np.asarray(arrays['beats'], float))
    valid = intervals[(intervals >= .15) & (intervals <= 2.4)]
    if len(valid) < 12:
        raise ValueError('原始脉冲不足以比较快慢层级')
    center = float(np.median(valid))
    options = [center * scale for scale in (.5, 1., 2.)]
    probability = expit(arrays['downbeat_logits'])
    peaks, _ = find_peaks(probability, height=.5, distance=6)
    down_intervals = np.diff(peaks / POLICY['model_frames_per_second'])
    if len(down_intervals) >= 12:
        options.append(float(np.median(down_intervals)) / 4.)
    result = []
    for value in sorted(options):
        if .15 <= value <= 2.4 and not any(abs(math.log(value / prior)) < .08 for prior in result):
            result.append(float(value))
    return result


def _sample(times, values, points, tolerance=None):
    # 自动拍层级与首拍盲测：新增有限声学容差；只读采样，不改变候选拍点或任何音符。
    points = np.asarray(points, float)
    if not len(points):
        return np.zeros(0)
    tolerance = POLICY['peak_tolerance_seconds'] if tolerance is None else tolerance
    offsets = np.linspace(-tolerance, tolerance, 5)
    return np.max([np.interp(points + offset, times, values, left=0., right=0.)
                   for offset in offsets], axis=0)


def _model_scores(beats, phase, arrays, interval):
    # 自动拍层级与首拍盲测：新增首拍精确率与召回率共同检查，避免快拍多报首拍或慢拍漏掉隔组首拍。
    begin, end = interval
    seconds = np.asarray([row['seconds'] for row in beats])
    labels = (np.asarray([row['beat'] for row in beats]) - 1 + phase) % 4
    selected = (seconds >= begin) & (seconds < end)
    first = seconds[selected & (labels == 0)]
    fps = POLICY['model_frames_per_second']
    times = np.arange(len(arrays['beat_logits'])) / fps
    bp = expit(arrays['beat_logits'])
    dp = np.minimum(bp, expit(arrays['downbeat_logits']))
    sampled = _sample(times, dp, first)
    precision = float(np.mean(sampled)) if len(sampled) else 0.
    peaks, values = find_peaks(dp, height=.5, distance=6)
    within = (times[peaks] >= begin) & (times[peaks] < end)
    peak_times, strength = times[peaks][within], values['peak_heights'][within]
    hit = np.zeros(len(peak_times), bool)
    for second in first:
        hit |= abs(peak_times - second) <= POLICY['peak_tolerance_seconds']
    recall = float(strength[hit].sum() / max(1e-9, strength.sum()))
    f1 = 2 * precision * recall / max(1e-9, precision + recall)
    ordinary = _sample(times, bp, seconds[selected])
    return {'precision': precision, 'recall': recall, 'f1': f1,
            'beat_probability': float(np.mean(ordinary)) if len(ordinary) else 0.,
            # 自动拍层级与首拍盲测：新增逐拍低证据比例，不用平均值代替持续可信的原曲拍点。
            'lower_quantile_beat_probability': float(np.quantile(ordinary, POLICY['beat_probability_lower_quantile'])) if len(ordinary) else 0.,
            'bar_count': len(first), 'model_downbeat_peak_count': len(peak_times)}


def _source_scores(beats, phase, tracks, interval):
    # 自动拍层级与首拍盲测：新增原伴奏／低音／吉他／钢琴的反相位比较；相关分轨不按票数累加。
    seconds = np.asarray([row['seconds'] for row in beats])
    labels = (np.asarray([row['beat'] for row in beats]) - 1 + phase) % 4
    within = (seconds >= interval[0]) & (seconds < interval[1])
    rows, harmonic, drums, phrases = {}, [], [], []
    for role, track in tracks.items():
        times = track['times']
        local = (times >= interval[0]) & (times < interval[1])
        floor = max(1e-7, float(np.percentile(track['rms'], 85)) * .015)
        active = bool(local.any() and np.percentile(track['rms'][local], 80) > floor)
        values = _sample(times, track['novelty'], seconds)
        profile = [float(np.mean(values[within & (labels == i)]))
                   if np.any(within & (labels == i)) else 0. for i in range(4)]
        contrast = profile[0] - float(np.median(profile[1:]))
        half_bar_counterevidence = profile[2] - profile[0]
        row = {'active': active, 'novelty_by_beat': profile, 'contrast': contrast,
               'third_minus_first': half_bar_counterevidence}
        if role in ('accompaniment', 'bass', 'six_guitar', 'six_piano') and active:
            harmonic.append(float(np.clip(contrast / POLICY['source_contrast_scale'], -1., 1.)))
        if role == 'drums' and active:
            low = _sample(times, track['onset_low'], seconds)
            high = _sample(times, track['onset_high'], seconds)
            down = within & np.isin(labels, [0, 2])
            back = within & np.isin(labels, [1, 3])
            if np.any(down) and np.any(back):
                low_delta = float(np.mean(low[down]) - np.mean(low[back]))
                high_delta = float(np.mean(high[back]) - np.mean(high[down]))
                norm = max(.1, float(np.mean(low[within]) + np.mean(high[within])))
                backbeat = float(np.clip((low_delta + high_delta) / norm, -1., 1.))
                drums.append(backbeat)
                row['backbeat_support'] = backbeat
        if role == 'vocals' and active:
            # 自动拍层级与首拍盲测：新增乐句入口的弱辅助；固定的弱起也可一致，绝不要求歌词字头落第1拍。
            voice = track['phrase'][local]
            at = times[local][voice > .5]
            if len(at) >= 2:
                q = np.interp(at, seconds, np.arange(len(seconds)))
                regularity = abs(np.mean(np.exp(2j * np.pi * q / 4)))
                phrases.append(float(regularity))
                row['phrase_group_consistency'] = float(regularity)
        rows[role] = row
    # 自动拍层级与首拍盲测：新增分轨组内中位数，原伴奏和分离乐器不能冒充多份独立模型。
    harmonic_score = (.5 + .5 * float(np.median(harmonic))) if harmonic else .5
    drum_score = (.5 + .5 * float(np.mean(drums))) if drums else .5
    phrase_score = float(np.mean(phrases)) if phrases else .5
    supporting = [role for role, row in rows.items()
                  if role in ('accompaniment', 'bass', 'six_guitar', 'six_piano')
                  and row['active'] and row['contrast'] >= POLICY['minimum_source_contrast']]
    return {'harmonic': harmonic_score, 'drum': drum_score, 'phrase': phrase_score,
            'supporting_harmonic_roles': supporting, 'tracks': rows}


def _score(beats, phase, arrays, tracks, interval):
    # 自动拍层级与首拍盲测：新增同一时间范围的多证据评分，按每拍／每小节归一，不能靠多放拍点得高分。
    model = _model_scores(beats, phase, arrays, interval)
    source = _source_scores(beats, phase, tracks, interval)
    w = POLICY['weights']
    value = (w['model'] * model['f1'] + w['harmonic'] * source['harmonic']
             + w['drum'] * source['drum'] + w['phrase'] * source['phrase'])
    return {'score': float(value), 'model': model, 'source': source}


def compare_candidates(meta, arrays, decoded):
    # 自动拍层级与首拍盲测：新增可直接测试的候选比较核心；候选只含原模型解码的秒和拍序。
    validate_evidence(meta, arrays)
    tracks = {row['role']: {key: arrays[row['prefix'] + '_' + key]
              for key in ('times', 'novelty', 'onset_low', 'onset_high', 'rms', 'phrase')}
              for row in meta['tracks']}
    duration = float(meta['duration_seconds'])
    windows = [(float(start), min(duration, float(start) + POLICY['window_seconds']))
               for start in np.arange(0., duration, POLICY['window_seconds'])]
    options = []
    for index, candidate in enumerate(decoded):
        beats = candidate['beats']
        if len(beats) < 16:
            continue
        phases = []
        for phase in range(4):
            local = [_score(beats, phase, arrays, tracks, interval) for interval in windows]
            global_score = _score(beats, phase, arrays, tracks, (0., duration))
            phases.append({'phase_rotation': phase, **global_score, 'windows': local})
        phases.sort(key=lambda row: -row['score'])
        period = float(np.median(np.diff([r['seconds'] for r in beats])))
        options.append({'candidate_index': index, 'period_seconds': period, 'bpm': 60. / period,
                        'phases': phases, 'score': phases[0]['score']})
    options.sort(key=lambda row: -row['score'])
    if len(options) < 2:
        raise ValueError('独立快慢候选不足，不允许只凭唯一候选判正确')
    best, runner = options[:2]
    phase = best['phases'][0]
    level_margin = best['score'] - runner['score']
    phase_margin = phase['score'] - best['phases'][1]['score']
    local_rows = []
    valid_windows, wins, source_support, phase_wins, temporal_thirds = [], [], [], [], set()
    for i, interval in enumerate(windows):
        current = phase['windows'][i]
        rivals = [max(p['windows'][i]['score'] for p in row['phases']) for row in options[1:]]
        other_phase = max(p['windows'][i]['score'] for p in best['phases'][1:])
        eligible = current['model']['bar_count'] >= POLICY['minimum_bars_per_window']
        supported = bool(current['source']['supporting_harmonic_roles'])
        local_margin = current['score'] - max(rivals)
        local_phase_margin = current['score'] - other_phase
        if eligible:
            valid_windows.append(i)
            wins.append(local_margin >= POLICY['minimum_window_margin'])
            phase_wins.append(local_phase_margin >= POLICY['minimum_window_margin'])
            source_support.append(supported)
            if local_margin >= POLICY['minimum_window_margin']:
                temporal_thirds.add(min(2, int((interval[0] + interval[1]) / 2 / duration * 3)))
        local_rows.append({'start_seconds': interval[0], 'end_seconds': interval[1],
                           'eligible': eligible, 'level_margin': local_margin,
                           'phase_margin': local_phase_margin, **current})
    win_fraction = float(np.mean(wins)) if wins else 0.
    phase_fraction = float(np.mean(phase_wins)) if phase_wins else 0.
    source_fraction = float(np.mean(source_support)) if source_support else 0.
    common = []
    if len(valid_windows) < POLICY['minimum_windows']:
        common.append('too_few_independent_time_windows')
    if phase['model']['beat_probability'] < POLICY['minimum_beat_probability']:
        common.append('original_beat_support_insufficient')
    # 自动拍层级与首拍盲测：新增严格附加门槛，首轮已知冲突只能停下，不用人工标签改选慢拍或快拍。
    if phase['model']['lower_quantile_beat_probability'] < POLICY['minimum_lower_quantile_beat_probability']:
        common.append('decoded_pulses_include_unsupported_events')
    if phase['model']['f1'] < POLICY['minimum_model_downbeat_f1']:
        common.append('original_model_grouping_ambiguous')
    if source_fraction < POLICY['minimum_source_support_fraction']:
        common.append('original_harmonic_context_insufficient')
    level_issues = list(common)
    if level_margin < POLICY['minimum_level_margin']:
        level_issues.append('half_double_time_margin_insufficient')
    if win_fraction < POLICY['minimum_window_win_fraction'] or len(temporal_thirds) < 3:
        level_issues.append('notation_level_not_stable_across_song')
    phase_issues = list(common)
    if phase_margin < POLICY['minimum_phase_margin']:
        phase_issues.append('bar_first_beat_margin_insufficient')
    if phase_fraction < POLICY['minimum_window_win_fraction']:
        phase_issues.append('bar_first_beat_not_stable_across_song')
    # 自动拍层级与首拍盲测：修改反例暴露的条件依赖；拍单位未定时，不把其条件下的组头当成已定首拍。
    # level_ok, phase_ok = not level_issues, not phase_issues
    level_ok = not level_issues
    if not level_ok:
        phase_issues.append('bar_first_beat_conditional_on_unresolved_level')
    phase_ok = not phase_issues
    # 自动拍层级与首拍盲测：新增局部缺证保留；全局首拍胜出不代表每个小节已经验收。
    unresolved = [dict(start_seconds=row['start_seconds'], end_seconds=row['end_seconds'],
                       reason='local_grouping_needs_context') for row in local_rows
                  # 自动拍层级与首拍盲测：修改缺证清单，原仅相位条件保留；局部快慢反例也必须显示。
                  # if not row['eligible'] or row['phase_margin'] < POLICY['minimum_window_margin']
                  if not row['eligible'] or row['phase_margin'] < POLICY['minimum_window_margin']
                  or row['level_margin'] < POLICY['minimum_window_margin']
                  or not row['source']['supporting_harmonic_roles']]
    return {'version': 1, 'policy': deepcopy(POLICY), 'policy_sha256': fingerprint(POLICY),
            'mix_sha256': meta['mix_sha256'], 'raw_evidence_sha256': meta['array_sha256'],
            'status': 'selected' if level_ok and phase_ok else 'needs_review',
            'notation_level': {'status': 'selected' if level_ok else 'needs_review',
                               'bpm': best['bpm'] if level_ok else None,
                               'margin': level_margin, 'window_win_fraction': win_fraction,
                               'issues': level_issues},
            'bar_first_beat': {'status': 'selected' if phase_ok else 'needs_review',
                               'phase_rotation': phase['phase_rotation'] if phase_ok else None,
                               'margin': phase_margin, 'window_win_fraction': phase_fraction,
                               'issues': phase_issues},
            'best_supported_hypothesis': {'candidate_index': best['candidate_index'], 'bpm': best['bpm'],
                                          'phase_rotation': phase['phase_rotation']},
            'source_support_window_fraction': source_fraction,
            'local_windows': local_rows, 'unresolved_windows': unresolved,
            'ranked_candidates': options,
            'full_clock_music_accepted': False, 'normal_publication_allowed': False,
            'downstream_timing_revision_allowed': False, 'pitch_chord_or_lyric_mutation_performed': False}


def select_meter(meta, arrays):
    # 自动拍层级与首拍盲测：新增公共选择入口，独立解码全部候选后再竞争，不读取历史拍轴或人工表单。
    # 慢拍单位与两曲最小修订：修改版本分流；旧匿名包按旧算法重放，新包必须真正运行有序比较。
    # validate_evidence(meta, arrays)
    if meta.get('version') == 2:
        from source_meter_sequence import validate_ordered_evidence
        validate_ordered_evidence(meta, arrays)
    else:
        validate_evidence(meta, arrays)
    model = {key: arrays[key] for key in RAW_MODEL_KEYS}
    decoded = [decode_four_beat_candidate(model, period) for period in period_candidates(model)]
    # 慢拍单位与两曲最小修订：修改比较入口，原调用保留；不可只增加未被使用的策略字段。
    # result = compare_candidates(meta, arrays, decoded)
    if meta.get('version') == 2:
        from source_meter_hierarchy import compare_ordered_candidates
        result = compare_ordered_candidates(meta, arrays, decoded)
    else:
        result = compare_candidates(meta, arrays, decoded)
    winner = result['best_supported_hypothesis']
    candidate = deepcopy(decoded[winner['candidate_index']])
    rotation = winner['phase_rotation']
    for beat in candidate['beats']:
        beat['beat'] = (beat['beat'] - 1 + rotation) % 4 + 1
    result['proposed_clock'] = candidate
    result['proposal_is_not_applied_to_any_score'] = True
    return result
