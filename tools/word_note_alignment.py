"""字音归属修复：新增所有音段的联合单调匹配，发音与音高证据分开保存。"""
import copy
import math
import numpy as np

# 字音归属修复：新增通用容差，单位为秒；不包含歌名、词字或参考音高。
VERSION = 2
PARAMETERS = {'candidate_margin_seconds': .28, 'phoneme_edge_seconds': .025,
              # 字音归属修复：新增音素时间扰动复核，不将路径差值当正确率。
              'minimum_shared_nucleus_seconds': .055, 'uncertain_margin': .35,
              'sensitivity_seconds': .08}
SHORT_NUCLEUS_POLICY = {'version': 1, 'minimum_observed_nucleus_seconds': .03,
                        'minimum_covered_fraction': .5, 'only_after_strict_path_failed': True}
ROLE_WEIGHT = {'nucleus': 1.0, 'voiced_initial': .45, 'initial': .20, 'unknown': .65}

# 字音归属修复：新增正长度音素校验；缺音素时显式以字界近似，保留复核提示。
def regions(char):
    result = []
    for phone in char.get('phonemes', []):
        a, b = phone['start_seconds'], phone['end_seconds']
        if not math.isfinite(a) or not math.isfinite(b) or b < a:
            raise ValueError('音素时间无效。')
        if b > a and not phone.get('skipped'):
            result.append((a, b, ROLE_WEIGHT.get(phone.get('role'), .65), phone.get('role', 'unknown')))
    if result:
        if any(b[0] < a[1] - 1e-5 for a, b in zip(result, result[1:])):
            raise ValueError('同一字的音素重叠或逆序。')
        return result, True
    return [(char['start_seconds'], char['end_seconds'], .65, 'unknown')], False

# 字音归属修复：新增核音跨字检查；只有一个完整音确实覆盖多个核音时才拆同音。
def expand_same_pitch(notes, chars, spans, allow_short_nuclei=False):
    output = []
    for original in notes:
        start, end = original['start_seconds'], original['end_seconds']
        covered = []
        short_evidence = []
        for ci, reg in enumerate(spans):
            nuclei = [(a, b) for a, b, _, role in reg if role in ('nucleus', 'unknown')]
            if not nuclei:
                continue
            amount = sum(max(0, min(end, b) - max(start, a)) for a, b in nuclei)
            center = sum((a + b) * (b - a) / 2 for a, b in nuclei) / sum(b - a for a, b in nuclei)
            threshold = PARAMETERS['minimum_shared_nucleus_seconds']
            nucleus_seconds = sum(b - a for a, b in nuclei)
            observed_nuclei = all(role == 'nucleus' for _, _, _, role in reg if role in ('nucleus', 'unknown'))
            if allow_short_nuclei and observed_nuclei and nucleus_seconds >= SHORT_NUCLEUS_POLICY['minimum_observed_nucleus_seconds']:
                threshold = min(threshold, nucleus_seconds * SHORT_NUCLEUS_POLICY['minimum_covered_fraction'] + 1e-9)
            if start < center < end and amount >= threshold:
                covered.append(ci)
                if amount < PARAMETERS['minimum_shared_nucleus_seconds']:
                    short_evidence.append({'character_index': chars[ci]['index'], 'nucleus_seconds': nucleus_seconds,
                                           'covered_nucleus_seconds': amount, 'policy_version': SHORT_NUCLEUS_POLICY['version']})
        # 字音归属修复：新增只拆相邻字，跨休止、跨句或仅擦过边缘的核音不生成重发。
        if len(covered) >= 2 and all(b == a + 1 for a, b in zip(covered, covered[1:])):
            cuts = [start]
            for left, right in zip(covered, covered[1:]):
                left_end = max(b for _, b, _, _ in spans[left])
                right_start = min(a for a, _, _, _ in spans[right])
                cuts.append((left_end + right_start) / 2)
            cuts.append(end)
            if all(b - a >= .035 for a, b in zip(cuts, cuts[1:])):
                for i, (a, b) in enumerate(zip(cuts, cuts[1:])):
                    output.append(dict(original, id=original['id'] + f'.syllable{i}',
                                       start_seconds=a, end_seconds=b,
                                       boundary_source='same_pitch_phoneme_boundary',
                                       lyric_boundary_evidence='multiple_nuclei_in_one_source_note',
                                       **({'short_nucleus_recovery': copy.deepcopy(short_evidence)} if short_evidence else {})))
                continue
        output.append(copy.deepcopy(original))
    return output

# 字音归属修复：新增核音优先的覆盖分数；声学置信度不决定音段属于哪个字。
def note_cost(note, reg):
    start, end = note['start_seconds'], note['end_seconds']
    low, high = min(a for a, _, _, _ in reg), max(b for _, b, _, _ in reg)
    gap = max(low - end, start - high, 0)
    if gap > PARAMETERS['candidate_margin_seconds']:
        return math.inf
    duration = end - start
    covered = sum(max(0, min(end, b) - max(start, a)) * weight for a, b, weight, _ in reg)
    nuclei = [(a, b) for a, b, _, role in reg if role in ('nucleus', 'unknown')]
    nucleus_covered = sum(max(0, min(end, b) - max(start, a)) for a, b in nuclei)
    # 字音归属修复：新增长度加权，避免多个极短候选淹没一个持续核音；不删音。
    seconds_weight = min(duration, .6) / .18
    mismatch = 1 - min(1, covered / duration)
    return seconds_weight * (2.0 * mismatch - .8 * min(1, nucleus_covered / duration)) + 2.0 * gap / .10

# 字音归属修复：新增跨字转移分数，核查音符起点、音素起点及独立词起音预测。
def transition_cost(left, right, previous, current, word_onsets):
    boundary = (left['end_seconds'] + right['start_seconds']) / 2
    a = min(x[0] for x in current)
    b = max(x[1] for x in previous)
    # 字音归属修复：新增休止间换字不要求两边时间重合，也不把休止填成声音。
    if right['start_seconds'] - left['end_seconds'] > .12:
        return 0.0
    first_nucleus = min((x[0] for x in current if x[3] in ('nucleus', 'unknown')), default=a)
    tolerance = max(.09, min(.20, first_nucleus - a + .065))
    distance = max(a - boundary, boundary - max(a, first_nucleus), 0)
    score = .30 * min(9, (distance / tolerance) ** 2)
    candidates = [v for v in word_onsets if abs(v - a) <= .10]
    if candidates:
        # 字音归属修复：新增仅作弱证据，词模型的音高转折不能强制成为换字。
        score += .08 * min(9, (min(abs(boundary - v) for v in candidates) / .10) ** 2)
    return score

# 字音归属修复：新增全音段动态规划，每个字连续分组且至少一个音，避免事后强制改索引。
# 字音归属修复：修改原签名以支持有界扰动复核，旧签名保留。
# def align_notes(notes, lyrics, analysis=None):
def align_notes(notes, lyrics, analysis=None, check_sensitivity=True, _recover_short_nuclei=False, _allow_short_nucleus_recovery=True):
    # 字音归属修复：新增API级来源校验，命令行之外也不能串用两条时间轴。
    source = lyrics.get('source', {})
    acoustic_source = (analysis or {}).get('source', {})
    if source.get('sha256') and acoustic_source.get('sha256'):
        if source['sha256'] != acoustic_source['sha256'] or abs(source.get('offset_seconds', 0) - acoustic_source.get('offset_seconds', 0)) > 1e-6:
            raise ValueError('音素歌词与声学分析来源或偏移不一致。')
    chars = copy.deepcopy(lyrics.get('characters', []))
    chars.sort(key=lambda c: c['index'])
    if not chars:
        return [dict(n, lyric_index=None, role='main', anchor=True) for n in notes], chars, []
    if len({c['index'] for c in chars}) != len(chars):
        raise ValueError('歌词索引重复。')
    if any(c.get('start_seconds') is None or c.get('end_seconds') is None or
           not math.isfinite(c['start_seconds']) or not math.isfinite(c['end_seconds']) or
           c['end_seconds'] <= c['start_seconds'] for c in chars):
        raise ValueError('存在未对齐或无效歌词，不能伪造字音。')
    if any(b['start_seconds'] < a['start_seconds'] for a, b in zip(chars, chars[1:])):
        raise ValueError('歌词时间逆序。')
    if any(n['end_seconds'] <= n['start_seconds'] for n in notes):
        raise ValueError('音段必须为正时值。')
    if any(b['start_seconds'] < a['end_seconds'] - 1e-6 for a, b in zip(notes, notes[1:])):
        raise ValueError('音段重叠或逆序。')
    spans, available = [], []
    for char in chars:
        reg, valid = regions(char)
        spans.append(reg); available.append(valid)
    expanded = expand_same_pitch(notes, chars, spans, allow_short_nuclei=_recover_short_nuclei)
    # 字音归属修复：新增空候选的明确诊断，避免空矩阵造成不明错误。
    if not expanded:
        raise ValueError('没有声学音段，不能伪造字音。')
    costs = np.array([[note_cost(n, reg) for reg in spans] for n in expanded])
    active = np.flatnonzero(np.isfinite(costs).any(axis=1))
    if len(active) < len(chars):
        if not _recover_short_nuclei and _allow_short_nucleus_recovery:
            return align_notes(notes, lyrics, analysis, check_sensitivity, _recover_short_nuclei=True)
        raise ValueError('候选少于歌词字数，需复核声学分段。')
    costs = costs[active]
    onsets = sorted({float(w['start_seconds']) for w in (analysis or {}).get('predicted_word_segments', [])})
    count, size = len(chars), len(active)
    # 字音归属修复：新增所有音的stay/advance路径，不能贪心分配细节后再改字序。
    dp = np.full((size, count), np.inf)
    parent = np.full((size, count), -1, dtype=int)
    dp[0, 0] = costs[0, 0]
    for ni in range(1, size):
        left, right = expanded[active[ni - 1]], expanded[active[ni]]
        for ci in range(min(ni + 1, count)):
            stay = dp[ni - 1, ci]
            advance = math.inf
            if ci:
                advance = dp[ni - 1, ci - 1] + transition_cost(left, right, spans[ci - 1], spans[ci], onsets)
            if stay <= advance:
                dp[ni, ci], parent[ni, ci] = costs[ni, ci] + stay, ci
            else:
                dp[ni, ci], parent[ni, ci] = costs[ni, ci] + advance, ci - 1
    if not np.isfinite(dp[-1, -1]):
        # 原可行结果保持；只有整句无解才复核有实测短元音支持的同音分字。
        if not _recover_short_nuclei and _allow_short_nucleus_recovery:
            return align_notes(notes, lyrics, analysis, check_sensitivity, _recover_short_nuclei=True)
        raise ValueError('音素/音段无法联合单调覆盖歌词，请复核句窗。')
    owners = np.full(size, -1, dtype=int)
    ci = count - 1
    for ni in range(size - 1, -1, -1):
        owners[ni] = ci
        ci = parent[ni, ci]
    owner_map = dict(zip(active.tolist(), owners.tolist()))
    # 字音归属修复：新增完整反向代价，保存真正影响整句路径的替代归属分数。
    backward = np.full_like(dp, np.inf)
    backward[-1, -1] = costs[-1, -1]
    for ni in range(size - 2, -1, -1):
        left, right = expanded[active[ni]], expanded[active[ni + 1]]
        for ci in range(count):
            stay = backward[ni + 1, ci]
            advance = math.inf
            if ci + 1 < count:
                advance = backward[ni + 1, ci + 1] + transition_cost(left, right, spans[ci], spans[ci + 1], onsets)
            backward[ni, ci] = costs[ni, ci] + min(stay, advance)
    total = float(dp[-1, -1]); issues = []; pieces = []
    anchor_indices = {}
    for ci in range(count):
        choices = np.flatnonzero(owners == ci)
        anchor_indices[ci] = int(active[min(choices, key=lambda ni: costs[ni, ci])])
    active_order = {idx: ni for ni, idx in enumerate(active.tolist())}
    for idx, original in enumerate(expanded):
        ci = owner_map.get(idx)
        anchor = ci is not None and anchor_indices[ci] == idx
        piece = dict(original, lyric_index=chars[ci]['index'] if ci is not None else None,
                     line_index=chars[ci].get('line_index') if ci is not None else None,
                     role='main' if anchor else ('detail' if ci is not None else 'unassigned'), anchor=anchor)
        if ci is not None:
            ni = active_order[idx]
            alternatives = []
            for other in range(max(0, ci - 1), min(count, ci + 2)):
                if other == ci or not np.isfinite(costs[ni, other]):
                    continue
                path = dp[ni, other] + backward[ni, other] - costs[ni, other]
                if np.isfinite(path):
                    alternatives.append({'character_index': chars[other]['index'], 'path_extra_cost': max(0., float(path - total))})
            margin = min((a['path_extra_cost'] for a in alternatives), default=None)
            piece['word_alignment'] = {'method': 'phoneme_joint_monotonic' if available[ci] else 'character_interval_joint_fallback',
                                       'cost': float(costs[ni, ci]), 'alternative_margin': margin,
                                       'alternatives': alternatives, 'confidence_kind': 'uncalibrated_path_evidence',
                                       'requires_review': bool(piece.get('short_nucleus_recovery')) or not available[ci] or (margin is not None and margin < PARAMETERS['uncertain_margin'])}
            if piece.get('short_nucleus_recovery'):
                piece['word_alignment']['short_nucleus_recovery'] = copy.deepcopy(piece['short_nucleus_recovery'])
                piece['word_alignment']['strict_global_path_was_infeasible'] = True
            if piece['word_alignment']['requires_review']:
                issues.append({'type': 'word_ownership_uncertain', 'piece_id': piece['id'],
                               'character_index': chars[ci]['index'], 'alternatives': alternatives,
                               # 字音归属修复：原提示末尾注释保留。
                               # 'phonemes_available': available[ci], 'requires_review': True})
                               # 字音归属修复：新增声段时间和来源，避免同字归并后提示无法试听。
                               'phonemes_available': available[ci], 'requires_review': True,
                               'start_seconds':piece['start_seconds'], 'end_seconds':piece['end_seconds'],
                               'source_note_id':piece.get('source_note_id',piece['id'])})
        pieces.append(piece)
    # 字音归属修复：原返回行注释保留；增加不稳定候选后再返回。
    # return pieces, chars, issues
    # 字音归属修复：新增自动局部不稳定标记；再算两条路径，不覆盖真实模型时间或音符。
    if check_sensitivity:
        variants = []
        for delta in (-PARAMETERS['sensitivity_seconds'], PARAMETERS['sensitivity_seconds']):
            shifted = copy.deepcopy(lyrics)
            for char in shifted.get('characters', []):
                char['start_seconds'] += delta; char['end_seconds'] += delta
                for phone in char.get('phonemes', []):
                    phone['start_seconds'] += delta; phone['end_seconds'] += delta
            try:
                candidate, _, _ = align_notes(notes, shifted, analysis, check_sensitivity=False,
                                               _allow_short_nucleus_recovery=_recover_short_nuclei)
                variants.append((delta, candidate, None))
            except ValueError as error:
                variants.append((delta, [], str(error)))
        for piece in pieces:
            candidates = []
            for delta, variant, error in variants:
                if error:
                    candidates.append({'delta_seconds': delta, 'status': 'path_failed', 'error': error})
                    continue
                matching = [n for n in variant if n['id'] == piece['id']]
                if not matching:
                    # 字音归属修复：新增同音拆符变化时按原声段/覆盖范围找候选，不按序号硬配。
                    matching = [n for n in variant if n.get('source_note_id', n['id']) == piece.get('source_note_id', piece['id'])
                                and n['pitch_midi'] == piece['pitch_midi']
                                and max(0, min(n['end_seconds'], piece['end_seconds']) - max(n['start_seconds'], piece['start_seconds']))
                                    >= .5 * min(n['end_seconds']-n['start_seconds'], piece['end_seconds']-piece['start_seconds'])]
                # 字音归属修复：修改，原只比较字索引的循环头注释保留。
                # for alternate in matching:
                #     if alternate['lyric_index'] != piece['lyric_index']:
                for alternate in matching:
                    # 字音归属修复：新增同音拆符的边界时间敏感度；字索引相同也不能掩盖时值边界变化。
                    if piece.get('boundary_source') == 'same_pitch_phoneme_boundary' and max(
                            abs(alternate['start_seconds']-piece['start_seconds']), abs(alternate['end_seconds']-piece['end_seconds'])) > .04:
                        candidates.append({'delta_seconds':delta,'character_index':alternate['lyric_index'],
                                           'boundary_time_sensitive':True,'start_seconds':alternate['start_seconds'],
                                           'end_seconds':alternate['end_seconds']})
                    if alternate['lyric_index'] != piece['lyric_index']:
                        candidates.append({'delta_seconds': delta, 'character_index': alternate['lyric_index'],
                                           'evidence': 'phoneme_time_sensitivity_not_ground_truth'})
            if candidates:
                detail = piece.setdefault('word_alignment', {'method':'unassigned', 'confidence_kind':'uncalibrated_path_evidence'})
                detail.update(requires_review=True, boundary_sensitive=True, sensitivity_alternatives=candidates)
                issues.append({'type':'word_ownership_boundary_sensitive', 'piece_id':piece['id'],
                               'character_index':piece['lyric_index'], 'alternatives':candidates,
                               # 字音归属修复：原敏感提示末尾注释保留。
                               # 'sensitivity_seconds':PARAMETERS['sensitivity_seconds'], 'requires_review':True})
                               # 字音归属修复：新增敏感声段原时间、来源，提示可独立试听。
                               'sensitivity_seconds':PARAMETERS['sensitivity_seconds'], 'requires_review':True,
                               'start_seconds':piece['start_seconds'],'end_seconds':piece['end_seconds'],
                               'source_note_id':piece.get('source_note_id',piece['id'])})
    return pieces, chars, issues
