"""多区间右手配置与网页完整成品：按谱面小节号编译独立区间。"""
# 多区间右手配置与网页完整成品：新增范围助手，旧默认／段落计划的格式和音乐保持兼容。
from copy import deepcopy
import re


def normalize_ranges(items, rows, normalize_choice):
    # 多区间右手配置与网页完整成品：新增闭区间及唯一标识检查；弱起编号只转换一次，禁止重叠静默覆盖。
    if not isinstance(items, list) or len(items) > 128:
        raise ValueError('小节区间应为列表，最多128条')
    offset = int(rows[0]['pickup'])
    minimum, maximum = rows[0]['number']-offset, rows[-1]['number']-offset
    result, seen = [], set()
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError('小节区间格式错误')
        identity = item.get('id', f'r{index+1:03}')
        start, end = item.get('start_measure'), item.get('end_measure')
        if not isinstance(identity, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', identity) or identity in seen:
            raise ValueError('小节区间标识无效或重复')
        if type(start) is not int or type(end) is not int or not minimum <= start <= end <= maximum:
            raise ValueError(f'第{index+1}条范围应为第{minimum}–{maximum}小节内的整数，起始不能大于结束')
        seen.add(identity)
        result.append({'id': identity, 'start_measure': start, 'end_measure': end,
                       'choice': normalize_choice(item['choice']) if item.get('choice') else None})
    ordered = sorted(result, key=lambda item: item['start_measure'])
    for previous, current in zip(ordered, ordered[1:]):
        if current['start_measure'] <= previous['end_measure']:
            raise ValueError(f"第{previous['start_measure']}–{previous['end_measure']}小节与第"
                             f"{current['start_measure']}–{current['end_measure']}小节重叠，请调整范围")
    return result


def range_assignments(ranges, rows):
    # 多区间右手配置与网页完整成品：新增以用户指定起始小节为循环原点；越过和弦或保留小节不重新起循环。
    offset = int(rows[0]['pickup'])
    result = []
    for item in ranges:
        start, end = item['start_measure']+offset, item['end_measure']+offset
        result.append(({'id': 'range_'+item['id'], 'range_id': item['id'],
                        'start_measure': item['start_measure'], 'end_measure': item['end_measure'],
                        'measures': list(range(start, end+1)),
                        'start_tick': rows[start-1]['start_tick'], 'end_tick': rows[end-1]['end_tick']}, item['choice']))
    return result


def protect_range_boundaries(project, rows, selected, exceptions):
    # 多区间右手配置与网页完整成品：新增双向保留跨选区边界的原完整延音，避免截短旧音或与新型冲突。
    from guitar_section_patterns import ordinary
    selected, exceptions = set(selected), deepcopy(exceptions)
    changed = True
    while changed:
        changed = False
        for note in project['arrangements']['guitar']['notes']:
            if not ordinary(note):
                continue
            covered = [row['number'] for row in rows
                       if note['start_tick'] < row['end_tick'] and note['end_tick'] > row['start_tick']]
            if any(number not in selected for number in covered):
                for number in covered:
                    if number in selected:
                        selected.remove(number)
                        exceptions.append({'measure': number, 'reason': 'preserve_range_boundary_sustain',
                                           'protected_note_ids': [note['id']]})
                        changed = True
    return selected, exceptions


def action_span(spec, tick, block, selected, rows):
    # 多区间右手配置与网页完整成品：新增截断末尾动作占时，不能让跨小节长格越过本条配置／受保护范围。
    limit = block['end_tick']
    for row in rows:
        if row['end_tick'] <= tick:
            continue
        if row['number'] not in selected:
            limit = min(limit, row['start_tick'])
            break
    return min(spec['action_span_ticks'], limit-tick)
