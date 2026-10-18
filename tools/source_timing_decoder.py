"""最小拍轴与词音伴奏修复：原混音激活的连续四拍候选解码。"""
# 最小拍轴与词音伴奏修复：新增仅节拍的动态规划，约束四拍连续计数，不继承模型多报／漏报的拍号。
import numpy as np
from numba import njit
from scipy.special import expit

POLICY = {'version': 1, 'frames_per_second': 50, 'period_ratio_bounds': [.82, 1.20],
          'tempo_transition_cost': 100., 'minimum_initial_beat_probability': .15,
          'old_notes_chords_or_lyrics_used': False, 'phase_candidate_is_not_music_certificate': True,
          # 最小拍轴与词音伴奏修复：新增开发修订指纹，避免把初版强首拍偏置的实验与最终候选混为同一政策。
          'decoder_revision': 2, 'downbeat_log_odds_weight': .25, 'initialization': 'first_model_pulse_window_only'}


# 最小拍轴与词音伴奏修复：修改内部递推参数，原签名保留；新增经过来源核对的局部首拍屏障。
# @njit(cache=False)
# def _decode(emissions, periods, transition, initial, tail):
@njit(cache=False)
# 最小拍轴与词音伴奏修复：修改内部参数，原签名保留；允许有代价的两拍过渡，不用突然加速凑满四拍。
# def _decode(emissions, periods, transition, initial, tail, barriers):
def _decode(emissions, periods, transition, initial, tail, barriers, short_bar_penalty):
    # 最小拍轴与词音伴奏修复：新增只在真实候选拍点间转移的Viterbi；拍长可局部变化，四拍组号始终连续。
    frames, beats = emissions.shape
    count = len(periods)
    values = np.full((frames, beats, count), -1e12)
    parents = np.full((frames, beats, count), -2, dtype=np.int16)
    for frame in range(frames):
        for beat in range(beats):
            previous_beat = (beat - 1) % beats
            for target in range(count):
                earlier = frame - periods[target]
                best = -1e12
                predecessor = -2
                if initial[frame]:
                    best = -frame * .0001
                    predecessor = -1
                # 最小拍轴与词音伴奏修复：修改跨审查点转移，原条件保留；路径不能跳过已确认首拍窗口。
                # if earlier >= 0:
                if earlier >= 0 and earlier >= barriers[frame]:
                    for source in range(count):
                        score = values[earlier, previous_beat, source] - transition[source, target]
                        if score > best:
                            best = score
                            # 最小拍轴与词音伴奏修复：修改回溯编码，原周期索引保留为注释；同时记录实际前一拍位置。
                            # predecessor = source
                            predecessor = source * beats + previous_beat
                    if beat == 0 and short_bar_penalty >= 0:
                        for source in range(count):
                            score = values[earlier, 1, source] - transition[source, target] - short_bar_penalty
                            if score > best:
                                best = score
                                predecessor = source * beats + 1
                if predecessor != -2:
                    values[frame, beat, target] = best + emissions[frame, beat]
                    parents[frame, beat, target] = predecessor
    best = -1e12
    final_frame, final_beat, final_period = -1, -1, -1
    for frame in range(max(0, frames - tail), frames):
        for beat in range(beats):
            for period in range(count):
                if values[frame, beat, period] > best:
                    best = values[frame, beat, period]
                    final_frame, final_beat, final_period = frame, beat, period
    path = []
    while final_frame >= 0:
        path.append((final_frame, final_beat, final_period))
        source = parents[final_frame, final_beat, final_period]
        if source < 0:
            break
        final_frame -= periods[final_period]
        # 最小拍轴与词音伴奏修复：修改回溯以保留短小节，原固定四拍回溯注释保留。
        # final_beat = (final_beat - 1) % beats
        # final_period = source
        final_beat = source % beats
        final_period = source // beats
    return path[::-1], best


# 最小拍轴与词音伴奏修复：修改公开参数，原签名保留；审查约束来自输入数据，不含曲名／固定时间分支。
# def decode_four_beat_candidate(arrays, nominal_period, meter=(4, 4)):
# 最小拍轴与词音伴奏修复：修改可选的短小节参数；默认历史候选仍禁止短小节，复现原策略。
# def decode_four_beat_candidate(arrays, nominal_period, meter=(4, 4), phase_anchors=(), unmetered_ranges=()):
def decode_four_beat_candidate(arrays, nominal_period, meter=(4, 4), phase_anchors=(), unmetered_ranges=(), allow_short_bars=False):
    # 最小拍轴与词音伴奏修复：新增拍速与第1拍共同但分别可审查的候选；输入只含原音模型概率。
    fps = POLICY['frames_per_second']
    beats = int(meter[0])
    # 最小拍轴与词音伴奏修复：新增明确支持范围和数组校验；不把复合拍或坏缓存静默解释成四分拍。
    if tuple(meter) != (4, 4):
        raise ValueError('当前隔离解码仅支持4/4，其他拍号保留未决，不强制换拍。')
    if (nominal_period <= 0 or len(np.asarray(arrays.get('beats', []))) < 16
            or np.shape(arrays['beat_logits']) != np.shape(arrays['downbeat_logits'])
            or not np.all(np.isfinite(arrays['beat_logits'])) or not np.all(np.isfinite(arrays['downbeat_logits']))):
        raise ValueError('节拍模型数组或候选拍长不合法')
    beat = expit(np.asarray(arrays['beat_logits']).reshape(-1))
    down = np.minimum(beat, expit(np.asarray(arrays['downbeat_logits']).reshape(-1)))
    nonbeat = np.clip(1 - beat, 1e-5, 1.)
    ordinary = np.clip(beat - down, 1e-5, 1.)
    # 最小拍轴与词音伴奏修复：修改初版过强首拍偏置，原式保留；禁止为了迁就模型首拍而大幅挤压真实拍间隔。
    # emissions = np.repeat(np.log(ordinary / nonbeat)[:, None], beats, axis=1)
    # emissions[:, 0] = np.log(np.clip(down, 1e-5, 1.) / nonbeat)
    base = np.log(np.clip(beat, 1e-5, 1.) / nonbeat)
    # 最小拍轴与词音伴奏修复：修改实验常量为显式政策，原式保留。
    # emissions = np.repeat((base + .25 * np.log(ordinary / np.clip(beat, 1e-5, 1.)))[:, None], beats, axis=1)
    # emissions[:, 0] = base + .25 * np.log(np.clip(down, 1e-5, 1.) / np.clip(beat, 1e-5, 1.))
    weight = POLICY['downbeat_log_odds_weight']
    emissions = np.repeat((base + weight * np.log(ordinary / np.clip(beat, 1e-5, 1.)))[:, None], beats, axis=1)
    emissions[:, 0] = base + weight * np.log(np.clip(down, 1e-5, 1.) / np.clip(beat, 1e-5, 1.))
    low, high = [nominal_period * fps * r for r in POLICY['period_ratio_bounds']]
    periods = np.arange(max(2, int(np.floor(low))), int(np.ceil(high)) + 1)
    transition = POLICY['tempo_transition_cost'] * np.log(periods[:, None] / periods[None, :]) ** 2
    # 最小拍轴与词音伴奏修复：修改任意中途重启的风险，原调用保留；初始只允许最早原曲拍点附近，缺证头部明确留待复核。
    # path, score = _decode(emissions, periods, transition, beat >= POLICY['minimum_initial_beat_probability'], int(periods.max() * beats))
    times = np.arange(len(beat)) / fps
    # 最小拍轴与词音伴奏修复：修改自由引子内假拍造成初始化失败的问题，原取首拍式保留；首个允许拍点必须在无拍范围之外。
    # first = float(np.asarray(arrays['beats'])[0])
    eligible = [float(value) for value in np.asarray(arrays['beats']) if not any(
                r['start_seconds'] <= value < r['end_seconds'] for r in unmetered_ranges)]
    if not eligible:
        raise ValueError('无拍范围之外没有原曲拍点')
    first = eligible[0]
    initial = ((beat >= POLICY['minimum_initial_beat_probability']) & (times >= max(0., first - nominal_period))
               & (times < first + nominal_period * beats))
    # 最小拍轴与词音伴奏修复：修改递推调用，原式保留；约束只管已听片段，不替代后段独立验收。
    # path, score = _decode(emissions, periods, transition, initial, int(periods.max() * beats))
    barriers = np.full(len(beat), -1, dtype=np.int32)
    anchors = sorted(float(value) for value in phase_anchors)
    if anchors and any(b <= a for a, b in zip(anchors, anchors[1:])):
        raise ValueError('首拍审查锚点必须严格递增')
    for value in anchors:
        lower, upper = max(0, round((value - .09) * fps)), min(len(beat) - 1, round((value + .09) * fps))
        if lower >= upper:
            raise ValueError('首拍审查锚点超出原音范围')
        emissions[lower:upper + 1, 1:] = -1e10
        barriers[upper + 1:] = lower
        initial[upper + 1:] = False
    for interval in unmetered_ranges:
        lower = max(0, round(float(interval['start_seconds']) * fps))
        upper = min(len(beat), round(float(interval['end_seconds']) * fps))
        initial[lower:upper] = False
        emissions[lower:upper] = -1e10
    # 最小拍轴与词音伴奏修复：修改递推以比较两拍过渡和速度挤压，原调用保留；没有原声支持不得把短小节直接当真值。
    # path, score = _decode(emissions, periods, transition, initial, int(periods.max() * beats), barriers)
    path, score = _decode(emissions, periods, transition, initial, int(periods.max() * beats), barriers, 8. if allow_short_bars else -1.)
    if len(path) < 16:
        raise ValueError('连续四拍候选证据不足')
    return {'policy': POLICY.copy(), 'nominal_period_seconds': float(nominal_period),
            # 最小拍轴与词音伴奏修复：新增审查约束的显式版本和范围，基础无约束政策及旧候选仍可识别。
            'constraint_policy': {'version': 1, 'anchor_tolerance_seconds': .09, 'anchors_are_local_not_whole_song_certificate': True},
            'phase_anchor_seconds': anchors, 'unmetered_ranges': list(unmetered_ranges),
            'short_bar_policy': {'version': 1, 'enabled': bool(allow_short_bars), 'penalty': 8., 'requires_independent_audio_validation': True},
            'beats': [{'seconds': float(frame / fps), 'beat': int(index + 1),
                       'model_beat_probability': float(beat[frame]), 'model_downbeat_probability': float(down[frame]),
                       'preceding_period_seconds': float(periods[period] / fps)} for frame, index, period in path],
            'path_score': float(score), 'status': 'candidate_requires_original_audio_phase_validation'}
