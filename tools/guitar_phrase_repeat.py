"""完整乐句与实际时长复用：与小节计数无关的只读候选和共同阅读验收。"""
# 完整乐句与实际时长复用：新增纯读取评估；绝不修改拍轴、音符、和声或实际演奏顺序。
from collections import Counter
from copy import deepcopy

from accompaniment_analysis import SongClock
from phrase_harmony_plan import melody_signature, similarity

POLICY = {
    'version': 1, 'length_basis': 'complete_phrase_and_performed_seconds',
    'minimum_shared_note_duration_ratio': .8,
    'navigation_glyph_cost': {'repeat': 4., 'volta': 8., 'ds': 12.},
    'navigation_attention_seconds': {'repeat': 1., 'volta': 2., 'ds': 3.},
    # 完整乐句与实际时长复用：修改散落变奏的阅读负担，每个连续片段包含定位与替换两项操作；旧值保留。
    # 'variant_region_glyph_cost': 2.,
    'variant_region_glyph_cost': 4.,
    'music': 'read_only_exact_or_explicit_full_variants',
}


class Candidates(list):
    # 完整乐句与实际时长复用：新增拒绝原因随规划保留，不把全部未选解释为长度不足。
    def __init__(self):
        super().__init__()
        self.audit = {'policy': deepcopy(POLICY), 'rejections': {}, 'examples': [], 'evaluated_complete_pairs': 0}

    def reject(self, reason, first, second, size, details=None):
        self.audit['rejections'][reason] = self.audit['rejections'].get(reason, 0) + 1
        if len(self.audit['examples']) < 32:
            self.audit['examples'].append({'reason': reason, 'first': first, 'second': second,
                                          'length_bars_for_location_only': size, 'details': details})


def fixed_timeline(vocal):
    # 完整乐句与实际时长复用：新增真实时间范围；短小节使用实际表，绝不用等宽索引估算秒数。
    if vocal['timing'].get('measure_timeline'):
        return deepcopy(vocal['timing']['measure_timeline'])
    clock = SongClock(vocal); bar = vocal['statistics']['bar_ticks']
    return [{'number': i + 1, 'start_tick': i * bar, 'end_tick': (i + 1) * bar,
             'meter': list(vocal['timing']['meter']),
             'pickup': i == 0 and bool(vocal['timing'].get('initial_pickup_measure')),
             'start_seconds': clock.seconds(i * bar), 'end_seconds': clock.seconds((i + 1) * bar)}
            for i in range(vocal['statistics']['measure_count'])]


def _notes(arrangement, measure):
    # 完整乐句与实际时长复用：新增真实起音／完整延音／弦品签名；力度仍由各遍原播放保留。
    a, b = measure['start_tick'], measure['end_tick']
    rows = [n for n in arrangement['notes'] if n['start_tick'] < b and n['end_tick'] > a]
    tokens = Counter((n['start_tick'] - a, n['end_tick'] - a, n['pitch_midi'], n['string'], n['fret'],
                      n.get('finger'), n.get('role'), bool(n.get('melody_accent'))) for n in rows)
    return tokens, len([n for n in rows if n['start_tick'] >= a])


def _weight(token, length):
    # 完整乐句与实际时长复用：新增按实际持续区间加权，合并／拆分小节不改变同一音符的总权重。
    return max(0, min(length, token[1]) - max(0, token[0]))


def _variant_regions(offsets):
    # 完整乐句与实际时长复用：新增连续变奏片段数量，不把每条小节线当一次新阅读操作。
    return sum(i == 0 or value != offsets[i - 1] + 1 for i, value in enumerate(offsets))


def assess_candidate(timeline, first, second, size, method, shared_weight, total_weight,
                     saved_attacks, variant_offsets, phrase_evidence):
    # 完整乐句与实际时长复用：新增时长与内容共同评估，不使用另一小节数／固定秒数硬门槛。
    spans = []
    for start in (first, second):
        a = timeline[start - 1]['start_seconds']; b = timeline[start + size - 2]['end_seconds']
        spans.append({'start_seconds': a, 'end_seconds': b, 'duration_seconds': b - a})
    continuous = spans[1]['duration_seconds']
    ratio = shared_weight / total_weight if total_weight > 0 else 0.
    regions = _variant_regions(variant_offsets)
    # 完整乐句与实际时长复用：新增导航注意力折算成重复TAB的阅读量，短时回跳代价更高，音符多不等于长段。
    base = POLICY['navigation_glyph_cost'][method]
    attention = POLICY['navigation_attention_seconds'][method]
    # 完整乐句与实际时长复用：修改注意力按实际连续时长折算有效阅读收益，不能用密集短音抵消频繁回跳。
    # navigation = base * (1. + 2. * attention / max(continuous, .001))
    # gain = saved_attacks - navigation - regions * POLICY['variant_region_glyph_cost']
    usable_fraction = max(0., 1. - 2. * attention / max(continuous, .001))
    navigation = base
    gain = saved_attacks * usable_fraction - navigation - regions * POLICY['variant_region_glyph_cost']
    reasons = []
    if not phrase_evidence: reasons.append('incomplete_or_unsupported_phrase')
    if min(s['duration_seconds'] for s in spans) <= 0: reasons.append('invalid_source_duration')
    if ratio + 1e-9 < POLICY['minimum_shared_note_duration_ratio']: reasons.append('too_much_actual_music_difference')
    if gain <= 0: reasons.append('navigation_or_variant_reading_cost_exceeds_saved_tab')
    return {'version': POLICY['version'], 'valid': not reasons, 'reasons': reasons,
            'policy': deepcopy(POLICY), 'phrase_evidence': deepcopy(phrase_evidence),
            'occurrences': spans, 'continuous_return_seconds': continuous,
            'shared_note_duration_ratio': ratio, 'saved_attack_glyphs': saved_attacks,
            'variant_regions': regions, 'navigation_cost_glyph_equivalents': navigation,
            'uninterrupted_attention_fraction': usable_fraction,
            'reading_gain': gain, 'duration_is_whole_music_certification': False}


def propose(shared, vocal, signatures, arrangement, *, project=None, timeline=None, allow_variants=False):
    # 完整乐句与实际时长复用：新增按原自然乐句范围比较，候选不再从八小节起步。
    from guitar_repeat_readability import musical_boundaries
    timeline = timeline or fixed_timeline(vocal)
    actual_voice = project['accepted_vocal_project'] if project else vocal
    count = len(signatures); proposed = Candidates()
    starts, ends = musical_boundaries(shared, vocal)
    phrases = [p for p in shared.get('phrase_harmony_plan', {}).get('phrases', [])
               if p.get('action') != 'preserve_source_insufficient_evidence']
    grid = vocal['statistics']['bar_ticks']
    regular = {}
    if allow_variants and project:
        from guitar_repeat_variants import _regular_bars
        regular = _regular_bars(project, timeline)
    notes = [_notes(arrangement, measure) for measure in timeline]
    melody_cache = {}
    pair_cache = {}

    def pair(a, b):
        # 完整乐句与实际时长复用：新增逐小节缓存仅为定位，匹配比率按真实音符持续累计。
        key = (a, b)
        if key not in pair_cache:
            left, right = timeline[a - 1], timeline[b - 1]
            length = left['end_tick'] - left['start_tick']
            compatible = (length == right['end_tick'] - right['start_tick']
                          and left['meter'] == right['meter'] and left.get('pickup') == right.get('pickup'))
            l, _ = notes[a - 1]; r, attacks = notes[b - 1]
            common = sum(_weight(token, length) * n for token, n in (l & r).items())
            total = max(sum(_weight(token, length) * n for token, n in l.items()),
                        sum(_weight(token, length) * n for token, n in r.items()))
            exact = signatures[a - 1] == signatures[b - 1]
            variant = not exact and a in regular and b in regular and regular[a] == regular[b]
            pair_cache[key] = compatible, exact, variant, common, total, attacks
        return pair_cache[key]

    def melody(first, size):
        # 完整乐句与实际时长复用：新增沿真实时间轴的旋律证据，候选不会因旧索引每格1920而挪动源音符。
        key = (first, size)
        if key not in melody_cache:
            if project:
                actual_shared = {**project['shared_analysis'], '_phrase_harmony_view': True}
                a, b = timeline[first - 1]['start_tick'], timeline[first + size - 2]['end_tick']
                melody_cache[key] = melody_signature(actual_shared, actual_voice, a, b)
            else:
                melody_cache[key] = melody_signature(shared, vocal, (first - 1) * grid, (first + size - 1) * grid)
        return melody_cache[key]

    def evidence(first, size):
        # 完整乐句与实际时长复用：新增乐句连续覆盖证明，不由几个离散相同小节拼成所谓完整段落。
        a, b = (first - 1) * grid, (first + size - 1) * grid
        rows = [p for p in phrases if p['start_tick'] < b and p['end_tick'] > a]
        if not phrases:
            return {'source': 'vocal_pause_boundaries', 'first': first, 'last': first + size - 1}
        cursor = a
        for p in sorted(rows, key=lambda p: p['start_tick']):
            if p['start_tick'] > cursor: return None
            cursor = max(cursor, p['end_tick'])
        return {'source': 'existing_phrase_boundaries', 'phrase_ids': [p.get('id') for p in rows],
                'first': first, 'last': first + size - 1} if cursor >= b else None

    for first in sorted(starts):
        for second in sorted(m for m in starts if m > first):
            variants = []; common = total = saved = 0
            for offset in range(min(second - first, count - second + 1)):
                a, b = first + offset, second + offset
                compatible, exact, variant, match, weight, attacks = pair(a, b)
                if not compatible or (not exact and not variant):
                    proposed.reject('incompatible_meter_or_unprintable_performance_difference', first, second, offset + 1)
                    break
                if not exact: variants.append(offset)
                common += match; total += weight
                # 完整乐句与实际时长复用：新增完整变奏TAB已经另画，因此该小节不能冒充省掉的书写量。
                saved += attacks if exact else 0
                size = offset + 1
                if a not in ends or b not in ends: continue
                proposed.audit['evaluated_complete_pairs'] += 1
                phrase_evidence = [evidence(first, size), evidence(second, size)]
                if not all(phrase_evidence):
                    proposed.reject('incomplete_or_unsupported_phrase', first, second, size); continue
                musical = similarity(melody(first, size), melody(second, size))
                if not musical['accepted']:
                    proposed.reject('melody_phrase_not_supported', first, second, size); continue
                gap = second - first - size
                # 完整乐句与实际时长复用：新增房子候选仍保留两个结尾，方法选择按真实间隔时长而非小节数。
                gap_seconds = timeline[second - 1]['start_seconds'] - timeline[first + size - 2]['end_seconds']
                phrase_seconds = timeline[first + size - 2]['end_seconds'] - timeline[first - 1]['start_seconds']
                method = 'repeat' if not gap else 'volta' if gap_seconds <= phrase_seconds and second + size <= count else 'ds'
                check = assess_candidate(timeline, first, second, size, method, common, total, saved, variants, phrase_evidence)
                if not check['valid']:
                    proposed.reject(check['reasons'][0], first, second, size, check); continue
                tail_ends = sorted(m for m in ends if m >= second + size)
                proposed.append({'first': first, 'second': second, 'length': size, 'method': method,
                    'last': second + size - 1, 'second_ending_last': (tail_ends[0] if tail_ends else count) if method == 'volta' else None,
                    'reading_gain': check['reading_gain'], 'phrase_reuse_assessment': check,
                    'variant_bars': [{'canonical_measure': first + i, 'source_measure': second + i, 'pass': 2} for i in variants],
                    'melody_evidence': musical})
    return proposed


def _returned_intervals(route, jump):
    # 完整乐句与实际时长复用：新增真正沿路线走到下一次转向；普通反复后的顺奏尾段也属于连续阅读。
    cursor = jump['to_occurrence']; intervals = []; visited = set()
    while cursor is not None:
        if cursor in visited: raise ValueError('repeat_return_cycle')
        visited.add(cursor); occurrence = route[cursor]
        intervals.append((occurrence['first'], occurrence['last']))
        if occurrence['exit']['kind'] != 'continue': break
        cursor = occurrence['exit']['target_occurrence']
    return intervals


def annotate_route_seconds(groups, route, jumps, vocal, timeline=None):
    # 完整乐句与实际时长复用：新增最终路线真实时长；候选阶段保守使用共用段时长，两者分别记录。
    timeline = timeline or fixed_timeline(vocal)
    lookup = {o['id']: o for o in route}; by_id = {g['id']: g for g in groups}
    for jump in jumps:
        intervals = _returned_intervals(lookup, jump)
        seconds = sum(timeline[b - 1]['end_seconds'] - timeline[a - 1]['start_seconds'] for a, b in intervals)
        jump['uninterrupted_seconds'] = seconds
        by_id[jump['id']]['actual_continuous_return_seconds'] = seconds


def validate_route_evidence(plan, vocal):
    # 完整乐句与实际时长复用：新增按实际印刷回跳到下一次转向独立计秒，拒绝复制／伪造时长和过期规则。
    errors = []; timeline = plan.get('actual_measure_timeline') or fixed_timeline(vocal)
    groups = {g['id']: g for g in plan['repeat_groups']}
    route = {o['id']: o for o in plan['route']}
    for jump in plan['jumps']:
        group = groups.get(jump['id']); assessment = group.get('phrase_reuse_assessment', {}) if group else {}
        if assessment.get('policy') != POLICY or not assessment.get('valid'):
            errors.append('phrase_duration_assessment_missing_or_stale'); continue
        start = route[jump['to_occurrence']]['first']; finish = route[jump['until_occurrence']]['last']
        # 完整乐句与实际时长复用：修改复用段时长与回跳后全部连续时长分开，普通反复不会被误判。
        # cursor = jump['to_occurrence']; intervals = []; visited = set()
        # while cursor is not None:
        #     if cursor in visited: errors.append('repeat_return_cycle'); break
        #     visited.add(cursor); occurrence = route[cursor]
        #     intervals.append((occurrence['first'], occurrence['last']))
        #     if occurrence['exit']['kind'] != 'continue': break
        #     cursor = occurrence['exit']['target_occurrence']
        try:
            intervals = _returned_intervals(route, jump)
        except ValueError as exc:
            errors.append(str(exc)); continue
        actual = sum(timeline[b - 1]['end_seconds'] - timeline[a - 1]['start_seconds'] for a, b in intervals)
        expected = timeline[finish - 1]['end_seconds'] - timeline[start - 1]['start_seconds']
        # 完整乐句与实际时长复用：修改逐项核对保守候选和最终路线，允许普通反复后继续顺奏。
        # if abs(actual - expected) > 1e-6 or abs(actual - assessment.get('continuous_return_seconds', -1)) > 1e-6:
        if actual + 1e-6 < expected or abs(expected - assessment.get('continuous_return_seconds', -1)) > 1e-6:
            errors.append('repeat_actual_continuous_seconds_mismatch')
        if abs(actual - group.get('actual_continuous_return_seconds', -1)) > 1e-6:
            errors.append('repeat_group_actual_seconds_mismatch')
        if abs(jump.get('uninterrupted_seconds', -1) - actual) > 1e-6:
            errors.append('repeat_jump_seconds_missing_or_changed')
    return {'valid': not errors, 'errors': errors, 'scope': 'actual_route_seconds_and_phrase_policy_not_whole_music_certificate'}
