"""慢拍单位与两曲最小修订：固定已有拍秒，只比较连续四拍与有证据的两拍过渡。"""
# 慢拍单位与两曲最小修订：新增重记谱用分组器；不加速凑拍，不移动任何原音符。
import numpy as np
from scipy.special import expit
from source_meter_selection import _sample

POLICY = {'version': 1, 'short_bar_penalty': 8., 'minimum_endpoint_probability': .85,
          'minimum_endpoint_novelty': .10, 'minimum_stable_beats_each_side': 12,
          'minimum_spacing_between_short_bars': 32, 'pitch_chord_or_lyric_recognition': False}
# 慢拍单位与两曲最小修订：新增可重放第二版分组规则，用前后连续对比而非单点必须接近1。
# 两拍过渡的间距是证据上下文长度，不是长段反复的8小节门槛；历史v1保持可重放。
CONTEXT_POLICY = {**POLICY, 'version': 2, 'minimum_endpoint_probability': .65,
    'minimum_context_first_probability': .65, 'minimum_context_first_third_margin': .45,
    'minimum_spacing_between_short_bars': 12}
# 慢拍单位与两曲最小修订：新增先筛过渡再解码，尾音无后续证据不能胜出后才假定变成两拍。
QUALIFIED_CONTEXT_POLICY = {**CONTEXT_POLICY, 'version': 3, 'qualify_transitions_before_decoding': True}


# 慢拍单位与两曲最小修订：修改增加显式版本，旧决定仍用v1，不能偷换已经封存的验收含义。
# def group_fixed_pulses(seconds, arrays, tracks):
def group_fixed_pulses(seconds, arrays, tracks, version=1):
    # 慢拍单位与两曲最小修订：新增首拍标签动态规划，路径只能走同一拍序，不更改秒或拍长。
    seconds = np.asarray(seconds, float)
    # 慢拍单位与两曲最小修订：修改v1／v2可重放，v3将相同音乐上下文门槛提前到候选生成。
    # policy = POLICY if version == 1 else CONTEXT_POLICY if version == 2 else None
    policy = {1: POLICY, 2: CONTEXT_POLICY, 3: QUALIFIED_CONTEXT_POLICY}.get(version)
    if policy is None or len(seconds) < 16 or not np.all(np.diff(seconds) > 0):
        raise ValueError('固定拍序版本未知或脉冲不足／逆序')
    times = np.arange(len(arrays['beat_logits'])) / 50.
    bp = _sample(times, expit(arrays['beat_logits']), seconds)
    dp = _sample(times, np.minimum(expit(arrays['beat_logits']), expit(arrays['downbeat_logits'])), seconds)
    probability = np.clip(dp / np.maximum(.05, bp), 1e-5, 1 - 1e-5)
    # 慢拍单位与两曲最小修订：新增可靠整拍才参与相位；无信心头尾不以噪声决定分组。
    weight = np.clip((bp - .5) / .4, 0., 1.)
    first = np.log(probability) * weight
    ordinary = np.log(1 - probability) * weight
    novelty = {}
    for role, track in tracks.items():
        if role in ('bass', 'accompaniment', 'six_guitar', 'six_piano'):
            novelty[role] = _sample(track['times'], track['novelty'], seconds)
    endpoint = np.zeros(len(seconds), bool)
    for values in novelty.values():
        # 慢拍单位与两曲最小修订：修改仅使用本次明确选定的版本参数。
        # endpoint |= values >= POLICY['minimum_endpoint_novelty']
        endpoint |= values >= policy['minimum_endpoint_novelty']
    # endpoint &= dp >= POLICY['minimum_endpoint_probability']
    endpoint &= dp >= policy['minimum_endpoint_probability']
    # 慢拍单位与两曲最小修订：新增每个潜在过渡先检查前后连续相位，低证据尾段保持连续四拍而不创造短小节。
    qualified_cuts = np.ones(len(seconds), bool)
    if version == 3:
        qualified_cuts[:] = False
        for i in range(2, len(seconds)):
            before = np.array([i - 14, i - 10, i - 6])
            after = np.array([i, i + 4, i + 8])
            valid = True
            for downs in (before, after):
                downs = downs[(downs >= 0) & (downs + 2 < len(seconds))]
                others = downs + 2
                if (len(downs) < 2 or np.median(dp[downs]) < policy['minimum_context_first_probability']
                        or np.median(dp[others]) >= .5
                        or np.median(dp[downs]) - np.median(dp[others]) < policy['minimum_context_first_third_margin']):
                    valid = False
            qualified_cuts[i] = valid
    scores = np.full((len(seconds), 4), -1e12)
    parents = np.full((len(seconds), 4), -1, dtype=int)
    scores[0] = [first[0], ordinary[0], ordinary[0], ordinary[0]]
    for i in range(1, len(seconds)):
        for beat in range(4):
            source = (beat - 1) % 4
            best = scores[i - 1, source]
            # 慢拍单位与两曲最小修订：修改先排除证据不合格的过渡，禁止先选错误尾段再靠事后放宽。
            # if beat == 0 and i >= 2 and endpoint[i] and endpoint[i - 2]:
            if beat == 0 and i >= 2 and endpoint[i] and endpoint[i - 2] and qualified_cuts[i]:
                # 慢拍单位与两曲最小修订：修改保持显式版本的换拍代价。
                # alternate = scores[i - 1, 1] - POLICY['short_bar_penalty']
                alternate = scores[i - 1, 1] - policy['short_bar_penalty']
                if alternate > best:
                    source, best = 1, alternate
            parents[i, beat] = source
            scores[i, beat] = best + (first[i] if beat == 0 else ordinary[i])
    labels = [int(np.argmax(scores[-1]))]
    for i in range(len(seconds) - 1, 0, -1):
        labels.append(int(parents[i, labels[-1]]))
    labels = np.array(labels[::-1])
    transitions, issues = [], []
    for i in range(1, len(seconds)):
        if labels[i - 1] == 1 and labels[i] == 0:
            # 慢拍单位与两曲最小修订：修改前后各三小节作为过渡证据，不能靠单个强音切短小节。
            # side = POLICY['minimum_stable_beats_each_side']
            side = policy['minimum_stable_beats_each_side']
            before = np.arange(max(0, i - 2 - side), i - 2)
            after = np.arange(i, min(len(seconds), i + side))
            context = []
            for selected in (before, after):
                downs = selected[labels[selected] == 0]
                others = selected[labels[selected] == 2]
                # 慢拍单位与两曲最小修订：修改v2同时要求稳定首拍绝对支持和相对第三拍优势，旧v1阈值保持。
                # support = bool(len(downs) >= 2 and len(others) >= 2 and np.median(dp[downs]) >= .85
                #                and np.median(dp[others]) < .5)
                support = bool(len(downs) >= 2 and len(others) >= 2
                    and np.median(dp[downs]) >= policy.get('minimum_context_first_probability', .85)
                    and np.median(dp[others]) < .5
                    and np.median(dp[downs]) - np.median(dp[others]) >= policy.get('minimum_context_first_third_margin', 0.))
                context.append({'supported': support, 'median_first': float(np.median(dp[downs])) if len(downs) else 0.,
                                'median_third': float(np.median(dp[others])) if len(others) else 0.})
            supported = bool(all(r['supported'] for r in context) and endpoint[i] and endpoint[i - 2])
            transitions.append({'start_index': i - 2, 'end_index': i, 'start_seconds': float(seconds[i - 2]),
                'end_seconds': float(seconds[i]), 'context': context, 'supported': supported,
                'endpoint_novelty': {role: [float(values[i - 2]), float(values[i])] for role, values in novelty.items()}})
            if not supported:
                issues.append({'kind': 'short_bar_context_insufficient', 'seconds': float(seconds[i])})
    # 慢拍单位与两曲最小修订：修改只按明确选定分组版本核对间隔，不混入读谱回跳长度。
    # if any(b['start_index'] - a['end_index'] < POLICY['minimum_spacing_between_short_bars']
    if any(b['start_index'] - a['end_index'] < policy['minimum_spacing_between_short_bars']
           for a, b in zip(transitions, transitions[1:])):
        issues.append({'kind': 'short_bars_too_close_requires_musical_review'})
    # 慢拍单位与两曲最小修订：新增局部明确模型相反的分组留证，不以选中一条路径代替音乐通过。
    for start in range(0, len(seconds), 32):
        selected = np.arange(start, min(len(seconds), start + 32))
        downs = selected[labels[selected] == 0]
        thirds = selected[labels[selected] == 2]
        # 慢拍单位与两曲最小修订：修改模型单独否决；原伴奏仍支持固定首拍时保留连续分组，相关分轨只作一组证据。
        # if len(downs) >= 3 and len(thirds) >= 3 and np.median(dp[thirds]) > np.median(dp[downs]) + .25:
        #     issues.append({'kind': 'fixed_grid_phase_conflict', 'seconds': [float(seconds[selected[0]]), float(seconds[selected[-1]])]})
        if len(downs) >= 3 and len(thirds) >= 3 and np.median(dp[thirds]) > np.median(dp[downs]) + .25:
            contrast = [float(np.mean(v[downs]) - np.mean(v[thirds])) for role, v in novelty.items()
                        if role != 'bass' and np.mean(v[selected]) > .015]
            if not contrast or float(np.median(contrast)) < .025:
                issues.append({'kind': 'fixed_grid_phase_conflict', 'seconds': [float(seconds[selected[0]]), float(seconds[selected[-1]])],
                               'source_first_minus_third': float(np.median(contrast)) if contrast else None})
    # 慢拍单位与两曲最小修订：新增无活动或首／三拍完全无法区分时不得仅凭最优路径认证。
    # 慢拍单位与两曲最小修订：修改v3继承同一无证据拒绝规则。
    # if version == 2:
    if version >= 2:
        reliable = bp >= .65
        firsts = (labels == 0) & reliable; thirds = (labels == 2) & reliable
        if (firsts.sum() < 3 or thirds.sum() < 3 or not novelty
                or np.median(dp[firsts]) - np.median(dp[thirds]) < .10
                or not any(np.count_nonzero(v > .10) >= 3 for v in novelty.values())):
            issues.append({'kind': 'insufficient_independent_grouping_support'})
    # return {'version': 1, 'policy': POLICY.copy(), 'beats': [
    return {'version': version, 'policy': policy.copy(), 'beats': [
            {'seconds': float(s), 'beat': int(label + 1), 'model_beat_probability': float(b), 'model_downbeat_probability': float(d)}
            for s, label, b, d in zip(seconds, labels, bp, dp)],
            'short_bars': transitions, 'issues': issues, 'status': 'supported' if not issues else 'needs_review',
            'seconds_changed': False, 'full_music_accepted': False}
