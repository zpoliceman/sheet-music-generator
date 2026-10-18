"""重复乐句折叠与多遍挂词：从实际音乐生成独立的吉他阅读路线，不改播放音乐。"""
from collections import defaultdict
from copy import deepcopy
import hashlib
import json
from accompaniment_analysis import SongClock
from guitar_capo import capo_at
from guitar_chord_diagrams import visible_diagrams
from phrase_harmony_plan import arrangement_view
# 重复乐句折叠与多遍挂词：新增音乐匹配后备，弥补源乐句边界长短不同，仍不使用歌词答案。
from phrase_harmony_plan import melody_signature, similarity
from score_export import notation_at

# 吉他长段反复与流畅阅读：修改策略，原碎片折叠策略逐行注释保留。
# POLICY = {'version': 1, 'candidate': 'musically_matched_phrase_family',
#           'accompaniment': 'exact_frets_pitches_attacks_holds_and_grip',
#           'different_vocals': 'stack_complete_notation_per_occurrence',
#           'max_bars_per_line': 4, 'max_vocal_layers': 6,
#           'audio': 'unchanged_chronological_recording'}
from guitar_repeat_readability import POLICY



# 重复乐句折叠与多遍挂词：新增稳定序列摘要，显示层不改上游声学／器乐来源账本。
def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(',', ':')).encode('utf-8')).hexdigest()


# 重复乐句折叠与多遍挂词：新增只比较实际可见／可弹音乐，音量变体留在各遍原音源中。
def bar_signature(shared, vocal, arrangement, number):
    bar = vocal['statistics']['bar_ticks']; begin = (number - 1) * bar; end = begin + bar
    clock = SongClock(vocal)
    notes = sorted((n['start_tick'] - begin, n['end_tick'] - begin,
                    n['pitch_midi'], n['string'], n['fret'], n['role'],
                    n.get('right_hand_duration_ticks'), bool(n.get('melody_accent')))
                   for n in arrangement['notes'] if n['start_tick'] < end and n['end_tick'] > begin)
    attacks = sorted((e['start_tick'] - begin, e.get('kind'), e.get('stroke'),
                      e.get('right_hand_duration_ticks')) for e in arrangement.get('attack_events', [])
                     if begin <= e['start_tick'] < end)
    chords = []
    for h in shared['harmony']:
        if h['start_tick'] >= end or h['end_tick'] <= begin: continue
        item = (max(0, h['start_tick'] - begin), min(bar, h['end_tick'] - begin),
                h['root_pc'], h['quality'], h['bass_pc'])
        if chords and chords[-1][1] == item[0] and chords[-1][2:] == item[2:]:
            chords[-1] = (chords[-1][0], item[1], *item[2:])
        else: chords.append(item)
    diagrams = [(d['draw_tick'] - begin, d['display_end_tick'] - begin,
                 d['shape_name'], d['sounding_name'], d['position'], d['capo'],
                 sorted(d['frets'].items()), d.get('barre'), bool(d.get('simplified')))
                for d in visible_diagrams(shared, arrangement, number, number)]
    regions = [(max(0, r['start_tick'] - begin), min(bar, r['end_tick'] - begin), r['mode'])
               for r in arrangement.get('notation_regions', [])
               if r['start_tick'] < end and r['end_tick'] > begin]
    # 重复乐句折叠与多遍挂词：新增局部转调／换夹保护，跨界小节不能与普通小节共用一张谱。
    key_points = {begin} | {s['start_tick'] for s in vocal['notation'].get('key_segments', [])
                           if begin < s['start_tick'] < end}
    capo_points = {begin} | {s['start_tick'] for s in arrangement['configuration'].get('capo_segments', [])
                            if begin < s['start_tick'] < end}
    # 重复乐句折叠与多遍挂词：修改基准音查询，旧不存在的tick参数保留；沿用正式小节接口。
    # keys = [(tick - begin, clock.key(tick), notation_at(vocal, tick=tick)) for tick in sorted(key_points)]
    keys = [(tick - begin, clock.key(tick), notation_at(vocal, measure=tick // bar + 1)) for tick in sorted(key_points)]
    capos = [(tick - begin, capo_at(arrangement, tick)) for tick in sorted(capo_points)]
    return fingerprint([notes, attacks, chords, diagrams, regions, keys, capos])


# 重复乐句折叠与多遍挂词：新增不限26段的清楚定位字母，每个符号有唯一可见目标。
def block_label(index):
    value = ''
    while index >= 0:
        value = chr(65 + index % 26) + value; index = index // 26 - 1
    return value


# 重复乐句折叠与多遍挂词：新增配套D.S.／To Coda／Coda路线，只在回跳后的指定遍触发。
# 吉他长段反复与流畅阅读：替换旧碎片规划／D.S.连接器，原函数全部逐行注释保留。
# def compile_jumps(blocks, route):
#     positions = {b['id']: i for i, b in enumerate(blocks)}
#     for item in route: item['exit'] = {'kind': 'continue', 'target_occurrence': None}
#     for left, right in zip(route, route[1:]): left['exit']['target_occurrence'] = right['id']
#     route[-1]['exit'] = {'kind': 'end', 'target_occurrence': None}
#     jumps = []; index = 1
#     while index < len(route):
#         left, current = route[index - 1], route[index]
#         if positions[current['block_id']] == positions[left['block_id']] + 1:
#             index += 1; continue
#         # 重复乐句折叠与多遍挂词：新增向后复用的最长连续印刷区间；不把全曲各处独立跳转误当单个反复。
#         finish = index
#         while finish + 1 < len(route) and positions[route[finish + 1]['block_id']] == positions[route[finish]['block_id']] + 1:
#             finish += 1
#         target = route[finish + 1] if finish + 1 < len(route) else None
#         identity = f'jump_{len(jumps) + 1:03}'
#         jump = {'id': identity, 'from_occurrence': left['id'], 'to_occurrence': current['id'],
#                 'until_occurrence': route[finish]['id'],
#                 'continue_occurrence': target['id'] if target else None,
#                 'kind': 'ds_al_coda' if target else 'ds_al_fine'}
#         left['exit'] = {'kind': jump['kind'], 'target_occurrence': current['id'], 'jump_id': identity}
#         route[finish]['exit'] = {'kind': 'to_coda' if target else 'fine',
#                                  'target_occurrence': target['id'] if target else None, 'jump_id': identity}
#         jumps.append(jump)
#         index = finish + 2
#     return jumps
# 
# 
# # 重复乐句折叠与多遍挂词：新增通用折叠规划，乐句家族只是候选，伴奏任一实音差异即分开。
# def build_repeat_plan(storage_shared, vocal, arrangement):
#     shared = arrangement_view(storage_shared, vocal)
#     bar = vocal['statistics']['bar_ticks']; count = vocal['statistics']['measure_count']
#     signatures = {m: bar_signature(shared, vocal, arrangement, m) for m in range(1, count + 1)}
#     phrases = shared.get('phrase_harmony_plan', {}).get('phrases', [])
#     families = defaultdict(list)
#     # 重复乐句折叠与多遍挂词：新增仅使用完整小节候选；弱起、半小节边界与来源不足范围保留原谱。
#     for phrase in phrases:
#         if (phrase.get('action') == 'preserve_source_insufficient_evidence' or
#                 phrase['start_tick'] % bar or phrase['end_tick'] % bar): continue
#         start, end = phrase['start_tick'] // bar + 1, phrase['end_tick'] // bar
#         if start <= end: families[(phrase['family_id'], end - start + 1)].append((start, end))
#     proposed = []; seen = set()
#     for (family, length), spans in sorted(families.items(), key=lambda pair: min(x[0] for x in pair[1])):
#         spans = sorted(set(spans))
#         if len(spans) < 2: continue
#         # 重复乐句折叠与多遍挂词：新增逐相对小节的等价成员分组，保留不同结尾／低音／右手型。
#         partitions = []
#         for offset in range(length):
#             by_signature = defaultdict(list)
#             for member, (start, end) in enumerate(spans):
#                 if 1 <= start + offset <= count: by_signature[signatures[start + offset]].append(member)
#             partitions.append({tuple(members) for members in by_signature.values() if len(members) > 1})
#         for offset, partition in enumerate(partitions):
#             for members in sorted(partition):
#                 if offset and members in partitions[offset - 1]: continue
#                 finish = offset + 1
#                 while finish < length and members in partitions[finish]: finish += 1
#                 for left in range(offset, finish, POLICY['max_bars_per_line']):
#                     right = min(finish, left + POLICY['max_bars_per_line'])
#                     for layer in range(0, len(members), POLICY['max_vocal_layers']):
#                         selected = members[layer:layer + POLICY['max_vocal_layers']]
#                         if len(selected) < 2: continue
#                         occurrences = [(spans[i][0] + left, spans[i][0] + right - 1) for i in selected]
#                         covered = {m for a, z in occurrences for m in range(a, z + 1)}
#                         if covered & seen: continue
#                         proposed.append({'family_id': family, 'occurrences': occurrences}); seen.update(covered)
#     # 重复乐句折叠与多遍挂词：新增完整2–4小节音乐候选，长块优先，避免把连续乐句切成许多单小节反复。
#     for length in (4, 3, 2):
#         matching = defaultdict(list)
#         for start in range(1, count - length + 2):
#             if all(shared['measure_textures'][m - 1]['section'] == 'vocal' for m in range(start, start + length)):
#                 matching[tuple(signatures[m] for m in range(start, start + length))].append(start)
#         for starts in matching.values():
#             clusters = []
#             for start in starts:
#                 music = melody_signature(shared, vocal, (start - 1) * bar, (start + length - 1) * bar)
#                 selected = next((cluster for cluster in clusters if len(cluster) < POLICY['max_vocal_layers'] and
#                                  all(start >= old + length and similarity(old_music, music)['accepted']
#                                      for old, old_music in cluster)), None)
#                 if selected is None: clusters.append([(start, music)])
#                 else: selected.append((start, music))
#             for cluster in clusters:
#                 if len(cluster) > 1:
#                     proposed.append({'family_id': 'display_music_' + fingerprint([start for start, music in cluster])[:12],
#                                      'occurrences': [(start, start + length - 1) for start, music in cluster]})
#     # 重复乐句折叠与多遍挂词：修改候选选择，旧先到先得保留；长完整乐句优先，其次实际节省量。
#     # blocks = proposed[:]
#     seen = set(); blocks = []
#     # 重复乐句折叠与多遍挂词：修改优先级，旧全局长块保留；已识别自然乐句先行，后备不跨句抢占。
#     # proposed.sort(key=lambda b: (-(b['occurrences'][0][1] - b['occurrences'][0][0] + 1),
#     #                               -len(b['occurrences']), b['occurrences'][0][0]))
#     proposed.sort(key=lambda b: (b['family_id'].startswith('display_music_'),
#                                   -(b['occurrences'][0][1] - b['occurrences'][0][0] + 1),
#                                   -len(b['occurrences']), b['occurrences'][0][0]))
#     for candidate in proposed:
#         # 重复乐句折叠与多遍挂词：修改候选边界，旧无弱起保护保留；独立预备小节必须原样单列。
#         # free = [(a, z) for a, z in candidate['occurrences'] if not set(range(a, z + 1)) & seen]
#         free = [(a, z) for a, z in candidate['occurrences'] if not set(range(a, z + 1)) & seen and
#                 not (vocal['timing'].get('initial_pickup_measure') and a == 1)]
#         if len(free) < 2: continue
#         blocks.append({**candidate, 'occurrences': free})
#         seen.update(m for a, z in free for m in range(a, z + 1))
#     # 重复乐句折叠与多遍挂词：新增未折叠音乐的连续覆盖，器乐／转调及各个分支均不能消失。
#     cursor = 1
#     while cursor <= count:
#         if cursor in seen: cursor += 1; continue
#         finish = cursor
#         while (finish + 1 <= count and finish + 1 not in seen and finish - cursor < 3 and
#                not (vocal['timing'].get('initial_pickup_measure') and cursor == 1) and
#                shared['measure_textures'][finish]['section'] == shared['measure_textures'][cursor - 1]['section']):
#             finish += 1
#         blocks.append({'family_id': None, 'occurrences': [(cursor, finish)]}); cursor = finish + 1
#     blocks.sort(key=lambda b: b['occurrences'][0][0]); route = []
#     for index, block in enumerate(blocks):
#         block['id'] = block_label(index); block['canonical_first'], block['canonical_last'] = block['occurrences'][0]
#         block['length_bars'] = block['canonical_last'] - block['canonical_first'] + 1
#         block['occurrences'] = [{'id': f"{block['id']}_{i + 1}", 'pass': i + 1, 'block_id': block['id'],
#                                  'first': a, 'last': z} for i, (a, z) in enumerate(block['occurrences'])]
#         route.extend(deepcopy(block['occurrences']))
#     route.sort(key=lambda o: o['first']); jumps = compile_jumps(blocks, route)
#     lines = []; line = []; used = 0
#     for block in blocks:
#         if used + block['length_bars'] > 4 or (line and vocal['timing'].get('initial_pickup_measure') and line[0] == 'A'):
#             lines.append(line); line = []; used = 0
#         line.append(block['id']); used += block['length_bars']
#     if line: lines.append(line)
#     return {'version': 1, 'policy': deepcopy(POLICY), 'blocks': blocks, 'route': route, 'jumps': jumps, 'lines': lines,
#             'source_music_sha256': fingerprint([storage_shared, vocal, arrangement]),
#             'expanded_bars': count, 'printed_bars': sum(b['length_bars'] for b in blocks),
#             'saved_bars': count - sum(b['length_bars'] for b in blocks),
#             'folded_blocks': sum(len(b['occurrences']) > 1 for b in blocks)}
# 
# 
# # 重复乐句折叠与多遍挂词：新增独立路线展开与跳转解释器，检查重入、收尾、无丢失和无循环。
# def expand_route(plan):
#     route = {o['id']: o for o in plan['route']}; jumps = {j['id']: j for j in plan['jumps']}
#     current = plan['route'][0]['id']; active = None; result = []
#     for _ in range(len(route) + 1):
#         if current is None: return result
#         if current not in route or current in result: raise ValueError('反复路线存在无效目标或无穷循环。')
#         item = route[current]; result.append(current); exit = item['exit']
#         if active and current == jumps[active]['until_occurrence']:
#             current = jumps[active]['continue_occurrence']; active = None
#         elif exit['kind'] in ('ds_al_coda', 'ds_al_fine'):
#             active = exit['jump_id']; current = jumps[active]['to_occurrence']
#         elif exit['kind'] in ('to_coda', 'fine'):
#             raise ValueError('To Coda／Fine缺少配对回跳。')
#         else: current = exit['target_occurrence']
#     raise ValueError('反复路线没有终止。')
# 
# 
# # 重复乐句折叠与多遍挂词：新增按输入实际音乐重建，不信任生成器自报的节省数或等价声明。
# def validate_repeat_plan(plan, shared, vocal, arrangement):
#     errors = []; expected = build_repeat_plan(shared, vocal, arrangement)
#     if plan != expected: errors.append('折叠计划与当前输入音乐重建不一致。')
#     try:
#         expanded = expand_route(plan)
#         if expanded != [o['id'] for o in plan['route']]: errors.append('反复标记展开与原曲演奏顺序不符。')
#         coverage = [m for o in plan['route'] for m in range(o['first'], o['last'] + 1)]
#         if coverage != list(range(1, vocal['statistics']['measure_count'] + 1)): errors.append('原曲小节重复或遗漏。')
#         blocks = {b['id']: b for b in plan['blocks']}
#         for line in plan['lines']:
#             if sum(blocks[b]['length_bars'] for b in line) > 4: errors.append('一行超过四小节。')
#     except (ValueError, KeyError, TypeError) as exc: errors.append(str(exc))
#     return {'valid': not errors, 'errors': errors, 'expanded_bars': plan['expanded_bars'],
#             'printed_bars': plan['printed_bars'], 'saved_bars': plan['saved_bars'],
#             'folded_blocks': plan['folded_blocks'], 'route_covers_recording_once': not errors}


# 吉他长段反复与流畅阅读：新增正式通用入口，仍沿用严格实音摘要及来源音乐指纹。
def build_repeat_plan(storage_shared, vocal, arrangement):
    from guitar_repeat_readability import build_plan
    return build_plan(storage_shared, vocal, arrangement, bar_signature, fingerprint, block_label)


# 吉他长段反复与流畅阅读：新增按实际印刷反复语义执行的来源路线接口。
def expand_route(plan):
    from guitar_repeat_readability import expand_route as expand_printed_route
    return expand_printed_route(plan)


# 吉他长段反复与流畅阅读：新增整曲阅读门槛及独立展开验收。
def validate_repeat_plan(plan, shared, vocal, arrangement):
    from guitar_repeat_readability import validate_plan
    return validate_plan(plan, shared, vocal, arrangement, build_repeat_plan)
