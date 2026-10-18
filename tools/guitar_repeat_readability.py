"""吉他长段反复与流畅阅读：完整音乐段落、简单反复和独立印刷路线解释器。"""
from copy import deepcopy
# 吉他长段反复与流畅阅读：删除不再使用的递归缓存导入，原导入注释保留。
# from functools import lru_cache
from phrase_harmony_plan import arrangement_view, melody_signature, similarity

# 吉他长段反复与流畅阅读：新增阅读优先策略，行宽只在路线确定后参与切行。
# 完整乐句与实际时长复用：修改旧小节计数策略；原代码注释保留。
# POLICY = {'version': 2, 'candidate': 'complete_contiguous_musical_sections',
POLICY = {'version': 3, 'candidate': 'complete_phrases_actual_seconds_and_reading_gain',
          'accompaniment': 'exact_frets_pitches_attacks_holds_and_grip',
          'different_vocals': 'stack_complete_notation_per_occurrence',
          # 完整乐句与实际时长复用：修改旧小节计数策略；原代码注释保留。
          # 'minimum_reused_bars': 8, 'minimum_uninterrupted_bars': 8,
          'repeat_length_basis': 'complete_phrase_actual_seconds',
          'max_bars_per_line': 4, 'max_vocal_layers': 6, 'max_ds_routes': 1,
          'reading_cost': {'repeat': 2, 'volta': 4, 'ds': 6},
          'audio': 'unchanged_chronological_recording'}


# 吉他长段反复与流畅阅读：新增自然乐句边界，来源不足或半小节不强切成共用段。
def musical_boundaries(shared, vocal):
    bar = vocal['statistics']['bar_ticks']; count = vocal['statistics']['measure_count']
    starts, ends = set(), set()
    phrases = shared.get('phrase_harmony_plan', {}).get('phrases', [])
    for phrase in phrases:
        if phrase.get('action') == 'preserve_source_insufficient_evidence': continue
        if phrase['start_tick'] % bar == 0: starts.add(phrase['start_tick'] // bar + 1)
        if phrase['end_tick'] % bar == 0: ends.add(phrase['end_tick'] // bar)
    # 吉他长段反复与流畅阅读：新增无和声乐句工程的自然停顿后备，不枚举任意四小节窗口。
    if not phrases:
        notes = sorted((e for e in vocal['events'] if e.get('pitch_midi') is not None), key=lambda e: e['start_tick'])
        groups = []
        for note in notes:
            finish = note['start_tick'] + note['duration_ticks']
            if not groups or note['start_tick'] - groups[-1][1] >= bar / 2:
                groups.append([note['start_tick'], finish])
            else: groups[-1][1] = max(groups[-1][1], finish)
        for start, end in groups:
            if start % bar == 0: starts.add(start // bar + 1)
            if end % bar == 0: ends.add(end // bar)
    if vocal['timing'].get('initial_pickup_measure'): starts.discard(1)
    return {m for m in starts if 1 <= m <= count}, {m for m in ends if 1 <= m <= count}


# 吉他长段反复与流畅阅读：新增跨多行完整匹配候选，不从散落的相同小节拼长段。
# 完整乐句与实际时长复用：修改旧小节计数策略；原代码注释保留。
# def candidates(shared, vocal, signatures):
#     bar = vocal['statistics']['bar_ticks']; count = len(signatures)
#     starts, ends = musical_boundaries(shared, vocal); proposed = []
#     minimum = POLICY['minimum_reused_bars']; melody_cache = {}
#     def melody(first, length):
#         key = (first, length)
#         if key not in melody_cache:
#             melody_cache[key] = melody_signature(shared, vocal, (first - 1) * bar, (first + length - 1) * bar)
#         return melody_cache[key]
#     for first in sorted(starts):
#         for second in sorted(m for m in starts if m >= first + minimum):
#             length = 0
#             while second + length <= count and first + length < second:
#                 if signatures[first + length - 1] != signatures[second + length - 1]: break
#                 length += 1
#             for size in range(minimum, length + 1):
#                 if first + size - 1 not in ends or second + size - 1 not in ends: continue
#                 if not similarity(melody(first, size), melody(second, size))['accepted']: continue
#                 gap = second - first - size
#                 tail_ends = sorted(m for m in ends if m >= second + size)
#                 tail_end = tail_ends[0] if tail_ends else count
#                 if not gap: method = 'repeat'
#                 elif gap <= size and second + size <= count: method = 'volta'
#                 else: method = 'ds'
#                 proposed.append({'first': first, 'second': second, 'length': size, 'method': method,
#                                  'last': second + size - 1,
#                                  'second_ending_last': tail_end if method == 'volta' else None,
#                                  'reading_gain': size - POLICY['reading_cost'][method]})
#     return proposed
def candidates(shared, vocal, signatures, arrangement=None):
    # 完整乐句与实际时长复用：新增旧固定小节入口也使用共同只读评估，不保留第二套八小节门槛。
    if arrangement is None:
        raise ValueError('乐句时长复用需要真实伴奏，不得仅凭小节签名估计阅读收益')
    from guitar_phrase_repeat import propose
    return propose(shared, vocal, signatures, arrangement)


# 吉他长段反复与流畅阅读：新增整曲区间规划，长范围收益扣除跳转成本，禁止嵌套及多条D.S.绕路。
def select_candidates(proposed, count):
    starts = {}
    for candidate in proposed: starts.setdefault(candidate['first'], []).append(candidate)
    for choices in starts.values():
        # 完整乐句与实际时长复用：修改旧小节计数策略；原代码注释保留。
        # choices.sort(key=lambda c: (-c['length'], POLICY['reading_cost'][c['method']], c['second']))
        choices.sort(key=lambda c: (-c['phrase_reuse_assessment']['continuous_return_seconds'], POLICY['reading_cost'][c['method']], c['second']))
    # 吉他长段反复与流畅阅读：修改递归求解，原代码逐行注释保留。
    # @lru_cache(None)
    # def solve(cursor, ds_left):
    #     if cursor > count: return (0, 0, 0), ()
    #     best_score, best = solve(cursor + 1, ds_left)
    #     for candidate in starts.get(cursor, []):
    #         if candidate['method'] == 'ds' and not ds_left: continue
    #         # 吉他长段反复与流畅阅读：新增房子也占用完整区间，防止另一个反复插进结尾。
    #         finish = candidate['second_ending_last'] or candidate['last']
    #         score, rest = solve(finish + 1, ds_left - int(candidate['method'] == 'ds'))
    #         score = (score[0] + candidate['reading_gain'], score[1] - 1, score[2] + candidate['length'])
    #         if score > best_score: best_score, best = score, (candidate,) + rest
    #     return best_score, best
    # return list(solve(1, POLICY['max_ds_routes'])[1])
    # 相似长段复用与默认阅读修复：修改相同阅读收益时优先较少变奏，再选更长段；原精确候选的选择顺序保持。
    # table = {(count + 1, remaining): ((0, 0, 0), ()) for remaining in range(POLICY['max_ds_routes'] + 1)}
    table = {(count + 1, remaining): ((0, 0, 0, 0), ()) for remaining in range(POLICY['max_ds_routes'] + 1)}
    for cursor in range(count, 0, -1):
        for remaining in range(POLICY['max_ds_routes'] + 1):
            best_score, best = table[cursor + 1, remaining]
            for candidate in starts.get(cursor, []):
                use_ds = int(candidate['method'] == 'ds')
                if use_ds > remaining: continue
                finish = candidate['second_ending_last'] or candidate['last']
                score, rest = table[finish + 1, remaining - use_ds]
                # 相似长段复用与默认阅读修复：修改平收益比较不为多共用一小节引入更多变奏。
                # score = (score[0] + candidate['reading_gain'], score[1] - 1, score[2] + candidate['length'])
                # 完整乐句与实际时长复用：修改旧小节计数策略；原代码注释保留。
                # score = (score[0] + candidate['reading_gain'], score[1] - 1,
                #          score[2]-len(candidate.get('variant_bars',[])),score[3]+candidate['length'])
                score = (score[0] + candidate['reading_gain'], score[1] - 1,
                         score[2] - candidate['phrase_reuse_assessment']['variant_regions'],
                         score[3] + candidate['phrase_reuse_assessment']['continuous_return_seconds'])
                if score > best_score: best_score, best = score, (candidate,) + rest
            table[cursor, remaining] = best_score, best
    return list(table[1, POLICY['max_ds_routes']][1])


# 吉他长段反复与流畅阅读：新增显示块与音乐段落分离，跨行共用段仍只有一组反复。
# 保音持续按弦与整句八度衔接：新增逐行宽度预算，仅决定显示行尾；重复候选和音乐段落边界仍独立。
def reading_line_end(arrangement, first, last):
    config = arrangement.get('configuration', {})
    maximum = config.get('maximum_bars_per_reading_line', POLICY['max_bars_per_line'])
    if not isinstance(maximum, int) or not 1 <= maximum <= POLICY['max_bars_per_line']:
        raise ValueError('阅读行小节数必须在1至4之间，不得改变长段复用门槛。')
    finish = min(last, first + maximum - 1)
    widths = config.get('reading_measure_widths', {})
    budget = config.get('reading_maximum_native_width')
    if not widths or not budget:
        return finish
    consumed, chosen = 0., first
    for number in range(first, finish + 1):
        width = float(widths.get(str(number), widths.get(number, budget)))
        if number > first and consumed + width > budget:
            break
        consumed += width
        chosen = number
    return chosen


# 相似长段复用与默认阅读修复：修改允许真实小节适配器提供有明确变奏的长段候选，旧出口仍用原精确规则。
# def build_plan(storage_shared, vocal, arrangement, signature_fn, fingerprint_fn, label_fn):
# 完整乐句与实际时长复用：修改适配器显式提供实际时间表，索引表不再冒充真实时长。
# def build_plan(storage_shared, vocal, arrangement, signature_fn, fingerprint_fn, label_fn, candidate_fn=None):
def build_plan(storage_shared, vocal, arrangement, signature_fn, fingerprint_fn, label_fn, candidate_fn=None, actual_timeline=None):
    shared = arrangement_view(storage_shared, vocal)
    count = vocal['statistics']['measure_count']
    signatures = [signature_fn(shared, vocal, arrangement, m) for m in range(1, count + 1)]
    # 相似长段复用与默认阅读修复：修改候选来源可注入，不能将差异小节静默认作相同。
    # proposed = candidates(shared, vocal, signatures)
    # 完整乐句与实际时长复用：修改旧小节计数策略；原代码注释保留。
    # proposed = (candidate_fn or candidates)(shared, vocal, signatures)
    proposed = candidate_fn(shared, vocal, signatures) if candidate_fn else candidates(shared, vocal, signatures, arrangement)
    selected = select_candidates(proposed, count)
    # 保音持续按弦与整句八度衔接：新增显示每行可少于4小节；音乐候选及至少8小节的长段规则先独立计算，不能被排版切碎。
    line_bars = arrangement.get('configuration', {}).get('maximum_bars_per_reading_line', POLICY['max_bars_per_line'])
    if not isinstance(line_bars, int) or not 1 <= line_bars <= POLICY['max_bars_per_line']:
        raise ValueError('阅读行小节数必须在1至4之间，不得改变长段复用门槛。')
    groups = []; boundaries = {1, count + 1}; omitted = set()
    for index, candidate in enumerate(selected, 1):
        a, b, size = candidate['first'], candidate['second'], candidate['length']
        group = {'id': f'repeat_{index:03}', 'label': f'共用段{index}', 'method': candidate['method'],
                 'canonical_first': a, 'canonical_last': a + size - 1,
                 'second_first': b, 'second_last': b + size - 1,
                 'length_bars': size, 'passes': 2,
                 'first_ending': [a + size, b - 1] if candidate['method'] == 'volta' else None,
                 'second_ending': [b + size, candidate['second_ending_last']] if candidate['method'] == 'volta' else None}
        # 相似长段复用与默认阅读修复：新增变奏仅为本遍本小节的实际替换，不建立额外回跳。
        # 完整乐句与实际时长复用：修改旧小节计数策略；原代码注释保留。
        # if candidate.get('variant_bars'):
        #     group['variant_bars']=deepcopy(candidate['variant_bars'])
        #     group['melody_evidence']=deepcopy(candidate['melody_evidence'])
        group['phrase_reuse_assessment'] = deepcopy(candidate['phrase_reuse_assessment'])
        if candidate.get('variant_bars'):
            group['variant_bars']=deepcopy(candidate['variant_bars'])
            group['melody_evidence']=deepcopy(candidate['melody_evidence'])
        groups.append(group); omitted.update(range(b, b + size))
        boundaries.update([a, a + size, b, b + size])
        if group['second_ending']: boundaries.add(group['second_ending'][1] + 1)
    blocks = []; cursor = 1
    while cursor <= count:
        if cursor in omitted: cursor += 1; continue
        boundary = min(m for m in boundaries if m > cursor)
        # 保音持续按弦与整句八度衔接：修改仅显示分行，原固定4小节保留；音乐回跳仍共用完整长段。
        # finish = min(boundary - 1, cursor + POLICY['max_bars_per_line'] - 1)
        # 保音持续按弦与整句八度衔接：修改按本行实际宽度选行尾，个别密集小节不能迫使整首一小节一行。
        # finish = min(boundary - 1, cursor + line_bars - 1)
        finish = reading_line_end(arrangement, cursor, boundary - 1)
        if cursor == 1 and vocal['timing'].get('initial_pickup_measure'): finish = 1
        # 吉他长段反复与流畅阅读：新增演唱／器乐边界切行，保持器乐隐藏参考声部的原规则。
        textures = shared.get('measure_textures', [])
        for m in range(cursor + 1, finish + 1):
            # 吉他长段反复与流畅阅读：修改无反复时的行范围，原条件注释保留；与保留的完整展开页一致。
            # if textures and textures[m - 1]['section'] != textures[cursor - 1]['section']:
            if selected and textures and textures[m - 1]['section'] != textures[cursor - 1]['section']:
                finish = m - 1; break
        identity = label_fn(len(blocks)); group = next((g for g in groups if g['canonical_first'] <= cursor <= g['canonical_last']), None)
        spans = [(cursor, finish)]
        if group:
            shift = group['second_first'] - group['canonical_first']; spans.append((cursor + shift, finish + shift))
        block = {'id': identity, 'family_id': group['id'] if group else None,
                 'canonical_first': cursor, 'canonical_last': finish, 'length_bars': finish - cursor + 1,
                 'repeat_group': group['id'] if group else None,
                 'display_label': (group['label'] + (' · 续' if cursor > group['canonical_first'] else '')) if group else '',
                 'occurrences': [{'id': f'{identity}_{i + 1}', 'pass': i + 1, 'block_id': identity,
                                  'first': a, 'last': z} for i, (a, z) in enumerate(spans)]}
        blocks.append(block); cursor = finish + 1
    route = sorted((deepcopy(o) for b in blocks for o in b['occurrences']), key=lambda o: o['first'])
    by_first = {o['first']: o for o in route}; by_last = {o['last']: o for o in route}
    for index, occurrence in enumerate(route):
        target = route[index + 1]['id'] if index + 1 < len(route) else None
        occurrence['exit'] = {'kind': 'continue' if target else 'end', 'target_occurrence': target}
    jumps = []
    for group in groups:
        start, finish, second, end = (group[k] for k in ['canonical_first', 'canonical_last', 'second_first', 'second_last'])
        origin = finish if group['method'] == 'repeat' else second - 1
        from_item, to_item = by_last[origin], by_first[second]
        kind = 'repeat' if group['method'] in ('repeat', 'volta') else ('ds_al_coda' if end < count else 'ds_al_fine')
        jump = {'id': group['id'], 'method': group['method'], 'from_occurrence': from_item['id'],
                'to_occurrence': to_item['id'], 'until_occurrence': by_last[end]['id'],
                'continue_occurrence': by_first[end + 1]['id'] if end < count else None,
                # 完整乐句与实际时长复用：修改旧小节计数策略；原代码注释保留。
                # 'kind': kind, 'uninterrupted_bars': group['length_bars']}
                'kind': kind, 'uninterrupted_bars': group['length_bars'],
                'uninterrupted_seconds': group['phrase_reuse_assessment']['continuous_return_seconds']}
        from_item['exit'] = {'kind': kind, 'target_occurrence': to_item['id'], 'jump_id': group['id']}
        if group['method'] == 'volta':
            by_last[end]['exit'] = {'kind': 'volta_skip', 'target_occurrence': jump['continue_occurrence'], 'jump_id': group['id']}
        elif group['method'] == 'ds':
            by_last[end]['exit'] = {'kind': 'to_coda' if end < count else 'fine', 'target_occurrence': jump['continue_occurrence'], 'jump_id': group['id']}
        jumps.append(jump)
    # 吉他长段反复与流畅阅读：新增简短段落路线，试听定位仍使用逐行原时间，不让大段概览变碎。
    reading = []; cursor = 1
    for group in groups:
        if cursor < group['canonical_first']: reading.append({'first': cursor, 'last': group['canonical_first'] - 1, 'label': '顺奏'})
        reading.append({'first': group['canonical_first'], 'last': group['canonical_last'], 'label': group['label'] + ' · 第一遍'})
        if group['canonical_last'] + 1 < group['second_first']:
            reading.append({'first': group['canonical_last'] + 1, 'last': group['second_first'] - 1,
                            'label': '第一结尾' if group['method'] == 'volta' else '过渡段'})
        reading.append({'first': group['second_first'], 'last': group['second_last'], 'label': group['label'] + ' · 第二遍'})
        cursor = group['second_last'] + 1
        if group['second_ending']:
            reading.append({'first': cursor, 'last': group['second_ending'][1], 'label': '第二结尾'})
            cursor = group['second_ending'][1] + 1
    if cursor <= count: reading.append({'first': cursor, 'last': count, 'label': '顺奏至结束'})
    for item in reading: item['occurrence_id'] = by_first[item['first']]['id']
    # 相似长段复用与默认阅读修复：新增印刷变奏占用也计入实际书写量，不能虚报节省小节。
    # 完整乐句与实际时长复用：新增最终路线独立计秒，包括普通反复后的顺奏部分。
    from guitar_phrase_repeat import annotate_route_seconds
    annotate_route_seconds(groups, route, jumps, vocal, actual_timeline)
    variant_count=sum(len(g.get('variant_bars',[])) for g in groups)
    # 完整乐句与实际时长复用：修改旧小节计数策略；原代码注释保留。
    # return {'version': 2, 'policy': deepcopy(POLICY), 'blocks': blocks, 'route': route, 'jumps': jumps,
    return {'version': 3, 'policy': deepcopy(POLICY), 'blocks': blocks, 'route': route, 'jumps': jumps,
            'phrase_candidate_audit': deepcopy(getattr(proposed, 'audit', {})),
            'repeat_groups': groups, 'reading_route': reading, 'lines': [[b['id']] for b in blocks],
            'source_music_sha256': fingerprint_fn([storage_shared, vocal, arrangement]),
            # 相似长段复用与默认阅读修复：修改旧仅主谱计数式，保持原代码可查。
            # 'expanded_bars': count, 'printed_bars': sum(b['length_bars'] for b in blocks),
            # 'saved_bars': sum(g['length_bars'] for g in groups), 'folded_blocks': len(groups),
            'expanded_bars': count, 'printed_bars': sum(b['length_bars'] for b in blocks)+variant_count,
            'saved_bars': sum(g['length_bars'] for g in groups)-variant_count, 'folded_blocks': len(groups),
            'candidate_count': len(proposed), 'reading_priority': 'complete_sections_then_fewer_jumps_then_space'}


# 吉他长段反复与流畅阅读：新增从印刷小节和普通反复／房子语义独立展开，不使用route.exit执行答案。
def expand_printed_bars(plan):
    printed = [m for b in plan['blocks'] for m in range(b['canonical_first'], b['canonical_last'] + 1)]
    if len(printed) != len(set(printed)): raise ValueError('印刷小节重复。')
    positions = {m: i for i, m in enumerate(printed)}; passes = {}; result = []; visited = set(); index = 0
    groups = plan['repeat_groups']
    for _ in range(plan['expanded_bars'] + 1):
        if index >= len(printed): return result
        state = (index, tuple(sorted(passes.items())))
        if state in visited: raise ValueError('印刷反复路线存在无穷循环。')
        visited.add(state); number = printed[index]
        common = next((g for g in groups if g['canonical_first'] <= number <= g['canonical_last']), None)
        if common:
            pass_number = passes.setdefault(common['id'], 1)
            result.append(number + (common['second_first'] - common['canonical_first'] if pass_number == 2 else 0))
        else: result.append(number)
        jumped = False
        for group in groups:
            pass_number = passes.get(group['id'], 1)
            if group['method'] == 'repeat' and number == group['canonical_last'] and pass_number == 1:
                passes[group['id']] = 2; index = positions[group['canonical_first']]; jumped = True; break
            if group['method'] in ('volta', 'ds') and number == group['second_first'] - 1 and pass_number == 1:
                passes[group['id']] = 2; index = positions[group['canonical_first']]; jumped = True; break
            if group['method'] in ('volta', 'ds') and number == group['canonical_last'] and pass_number == 2:
                destination = group['second_last'] + 1
                if destination > plan['expanded_bars']: return result
                index = positions[destination]; jumped = True; break
        if not jumped: index += 1
    raise ValueError('印刷反复路线过长或没有结束。')


# 吉他长段反复与流畅阅读：新增公开路线接口，将独立演奏小节转换为各遍试听身份并核对边界指令。
def expand_route(plan):
    bars = expand_printed_bars(plan); by_first = {o['first']: o for o in plan['route']}; result = []; cursor = 0
    while cursor < len(bars):
        occurrence = by_first.get(bars[cursor])
        if not occurrence: raise ValueError('反复目标或来源小节无效。')
        expected = list(range(occurrence['first'], occurrence['last'] + 1))
        if bars[cursor:cursor + len(expected)] != expected: raise ValueError('印刷符号与各遍范围不符。')
        result.append(occurrence['id']); cursor += len(expected)
    lookup = {o['id']: o for o in plan['route']}
    for i, identity in enumerate(result):
        target = result[i + 1] if i + 1 < len(result) else None
        if lookup[identity]['exit']['target_occurrence'] != target: raise ValueError('边界指令目标与实际印刷路线不符。')
    for jump in plan['jumps']:
        if lookup[jump['from_occurrence']]['exit'].get('jump_id') != jump['id']:
            raise ValueError('反复符号缺少对应起点。')
        if lookup[jump['from_occurrence']]['exit']['target_occurrence'] != jump['to_occurrence']:
            raise ValueError('回跳目标无效。')
    return result


# 吉他长段反复与流畅阅读：新增音乐、整曲顺序和阅读门槛联合验收，不以重建一致代替实际展开。
def validate_plan(plan, shared, vocal, arrangement, build_fn):
    errors = []
    if plan != build_fn(shared, vocal, arrangement): errors.append('折叠计划与当前输入音乐重建不一致。')
    try:
        if expand_printed_bars(plan) != list(range(1, vocal['statistics']['measure_count'] + 1)):
            errors.append('实际印刷反复小节与原曲顺序不符。')
        if expand_route(plan) != [o['id'] for o in plan['route']]: errors.append('各遍路线与印刷符号不符。')
        blocks = {b['id']: b for b in plan['blocks']}
        for line in plan['lines']:
            if sum(blocks[b]['length_bars'] for b in line) > POLICY['max_bars_per_line']:
                errors.append('一行超过四小节。')
        # 完整乐句与实际时长复用：修改旧小节计数策略；原代码注释保留。
        # for group in plan['repeat_groups']:
        #     if group['length_bars'] < POLICY['minimum_reused_bars']: errors.append('回跳复用范围不足八小节。')
        # for jump in plan['jumps']:
        #     if jump['uninterrupted_bars'] < POLICY['minimum_uninterrupted_bars']: errors.append('回跳后连续演奏不足八小节。')
        from guitar_phrase_repeat import validate_route_evidence
        errors.extend(validate_route_evidence(plan, vocal)['errors'])
        for jump in plan['jumps']:
            source = next(o for o in plan['route'] if o['id'] == jump['from_occurrence'])
            target = next(o for o in plan['route'] if o['id'] == jump['to_occurrence'])
            if list(blocks).index(target['block_id']) >= list(blocks).index(source['block_id']):
                errors.append('前向转接被误当回跳。')
        if sum(g['method'] == 'ds' for g in plan['repeat_groups']) > POLICY['max_ds_routes']:
            errors.append('D.S.主回跳路线超过阅读预算。')
    except (ValueError, KeyError, TypeError, StopIteration) as exc: errors.append(str(exc))
    return {'valid': not errors, 'errors': errors, 'expanded_bars': plan['expanded_bars'],
            'printed_bars': plan['printed_bars'], 'saved_bars': plan['saved_bars'],
            'folded_blocks': plan['folded_blocks'], 'backward_jumps': len(plan['jumps']),
            'ds_routes': sum(g['method'] == 'ds' for g in plan['repeat_groups']),
            'minimum_uninterrupted_bars': min((j['uninterrupted_bars'] for j in plan['jumps']), default=None),
            'route_covers_recording_once': not errors, 'printed_symbols_unfold_to_original_order': not errors}
