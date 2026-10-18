"""节奏符号说明与声部对齐：共同记谱拍点、独立字形留白及可见坐标核查。"""
# 节奏符号说明与声部对齐：新增显示层时间网格，不改工程音符及实际播放时间。
from bisect import bisect_left
from collections import defaultdict
import math
import re
import xml.etree.ElementTree as ET
from score_export import PPQ, jianpu_pitch, notation_at

NS = '{http://www.w3.org/2000/svg}'
MODE = 'shared_notation_ticks'


# 节奏符号说明与声部对齐：新增派生约定，倚音左前置是记谱装饰而非新增拍数。
def prepare_alignment(arrangement):
    arrangement['time_alignment_display'] = {
        'mode': MODE, 'simultaneous_onsets': 'one_horizontal_center',
        'glyph_spacing': 'preserve_local_offsets', 'grace': 'before_notated_anchor',
        'tolerance_pixels': .02,
    }


# 节奏符号说明与声部对齐：新增按时间槽共同预留指型、歌词、升降号及倚音的空间。
def layout_shared_time(scene, arrangement, bar):
    # 结构稳定伴奏与人声合播：修改，旧整行统一最大宽度保留；四小节逐小节按实际密度留白。
    # plans = {}; measure_width = 344
    plans = {}; widths = {}
    for number, box in scene.measure_boxes.items():
        origin = (number - 1) * bar
        onsets = {n['start_tick'] - origin for n in arrangement['notes']
                  if origin <= n['start_tick'] < origin + bar}
        markers = {d['draw_tick'] - origin for d in arrangement.get('_row_diagram_markers', [])
                   if origin <= d['draw_tick'] < origin + bar}
        grace_ids = {e['id'] for e in box['events'] if e['grace']}
        beats = []
        for beat in box['beats']:
            by_tick = defaultdict(list)
            for glyph in beat['glyphs']: by_tick[glyph['tick']].append(glyph)
            ticks = sorted(set(by_tick) | {beat['start_tick']} |
                           {t for t in onsets | markers if beat['start_tick'] <= t < beat['end_tick']})
            # 重复乐句折叠与多遍挂词：新增多遍联合留白的时间槽，原单遍输入不受影响。
            shared_cells = arrangement.get('_repeat_cells', {}).get(number, {})
            ticks = sorted(set(ticks) | {t for t in shared_cells if beat['start_tick'] <= t < beat['end_tick']})
            cells = []
            for tick in ticks:
                units = by_tick[tick]; main = [g for g in units if g['id'] not in grace_ids]
                graces = [g for g in units if g['id'] in grace_ids]
                left = max([17.] + [g['x'] - g['left'] for g in main])
                right = max([17.] + [g['right'] - g['x'] for g in main])
                # 节奏符号说明与声部对齐：新增逐个倚音间距，避免零记谱时值使中心塌缩。
                offsets = {}; edge = left
                for glyph in reversed(graces):
                    delta = edge + glyph['right'] - glyph['x'] + 6
                    offsets[(glyph['id'], glyph['part'])] = -delta
                    edge = delta + glyph['x'] - glyph['left']
                left = max(left, edge)
                if tick in markers: left = max(left, 49.); right = max(right, 49.)
                # 重复乐句折叠与多遍挂词：新增各遍最大字形／歌词／倚音留白，确保简谱与共用TAB同刻同列。
                if tick in shared_cells:
                    left = max(left, shared_cells[tick]['left']); right = max(right, shared_cells[tick]['right'])
                cells.append({'tick': tick, 'left': left, 'right': right, 'graces': offsets})
            minimum = 16 + sum(c['left'] + c['right'] + 8 for c in cells) - 8
            beats.append((beat, cells, minimum))
        plans[number] = beats
        # 结构稳定伴奏与人声合播：修改，原最大宽度保留；避免一个密集小节把其它三个同时拉宽。
        # measure_width = max(measure_width, 36 + 28 * (len(beats) - 1) + sum(b[2] for b in beats))
        widths[number] = max(344,36 + 28 * (len(beats) - 1) + sum(b[2] for b in beats))

    anchors = {}; boxes = {}; records = {}
    # 结构稳定伴奏与人声合播：新增累积真实小节宽度，仍共用全部声部的时间列。
    cursor_x = 52
    for index, (number, old) in enumerate(scene.measure_boxes.items()):
        # 结构稳定伴奏与人声合播：修改，原统一宽度坐标保留。
        # new_x = 52 + index * measure_width; beats = plans[number]
        measure_width = widths[number]; new_x = cursor_x; cursor_x += measure_width; beats = plans[number]
        spare = (measure_width - 36 - 28 * (len(beats) - 1) - sum(b[2] for b in beats)) / len(beats)
        anchors[old['x']] = new_x; anchors[old['x'] + old['width']] = new_x + measure_width
        cursor = new_x + 18; positions = {}; new_beats = []; by_id = defaultdict(list)
        grace_ids = {e['id'] for e in old['events'] if e['grace']}
        for beat, cells, minimum in beats:
            used = 0; offsets = {}; width = minimum + spare
            anchors[beat['x']] = cursor; anchors[beat['x'] + beat['width']] = cursor + width
            for cell in cells:
                positions[cell['tick']] = cursor + 8 + used + cell['left'] + spare / 2
                offsets.update(cell['graces']); used += cell['left'] + cell['right'] + 8
            glyphs = []
            for glyph in beat['glyphs']:
                identity = (glyph['id'], glyph['part'])
                center = positions[glyph['tick']] + offsets.get(identity, 0)
                delta = center - glyph['x']; anchors[glyph['x']] = center
                moved = {**glyph, 'x': center, 'left': glyph['left'] + delta, 'right': glyph['right'] + delta}
                glyphs.append(moved); by_id[glyph['id']].append(moved)
                records[identity] = {'id': glyph['id'], 'part': glyph['part'], 'x': center,
                                     'old_x': glyph['x'], 'tick': (number - 1) * bar + glyph['tick'],
                                     # 节奏符号说明与声部对齐：修改，旧记录保留；用原基线区分中心字形与升降号。
                                     # 'grace': glyph['id'] in grace_ids, 'measure': number}
                                     'grace': glyph['id'] in grace_ids, 'measure': number,
                                     'old_y': old['y'] - 132 - (12 if glyph['id'] in grace_ids else 0)}
            new_beats.append({**beat, 'x': cursor, 'width': width, 'glyphs': glyphs}); cursor += width + 28
        events = []
        for event in old['events']:
            units = by_id[event['id']]
            events.append({**event, 'x': units[0]['x'], 'left': min(g['left'] for g in units),
                           'right': max(g['right'] for g in units)})
        positions[bar] = new_x + measure_width - 12
        boxes[number] = {**old, 'x': new_x, 'width': measure_width, 'beats': new_beats,
                         'events': events, 'tick_positions': positions}
    # 结构稳定伴奏与人声合播：修改，原整行终点保留；使用逐小节累积终点。
    # anchors[scene.width - 46] = 52 + len(boxes) * measure_width - 12
    anchors[scene.width - 46] = cursor_x - 12
    xs = sorted(anchors)

    # 节奏符号说明与声部对齐：新增局部平移，附点/升降号/横线端点不随空白一起拉伸。
    def move_x(x):
        at = bisect_left(xs, x); candidates = xs[max(0, at - 1):min(len(xs), at + 1)]
        anchor = min(candidates, key=lambda a: abs(a - x))
        return anchors[anchor] + x - anchor

    # 节奏符号说明与声部对齐：修改，旧无归属映射保留；符号按渲染顺序绑定所属音符。
    # by_old_x = {r['old_x']: r for r in records.values()}; changed = []; drawn = {}
    by_old_x = {r['old_x']: r for r in records.values()}; changed = []; drawn = {}; active = None
    glyph_xs = sorted(by_old_x)

    # 节奏符号说明与声部对齐：新增横线/弧线端点只跟随邻近音符，精确小节边界单独保留。
    def move_endpoint(x):
        if x in anchors: return anchors[x]
        at = bisect_left(glyph_xs, x); candidates = glyph_xs[max(0, at-1):min(len(glyph_xs), at+1)]
        if not candidates: return move_x(x)
        anchor = min(candidates, key=lambda a: abs(a-x))
        return by_old_x[anchor]['x'] + x-anchor

    for item in scene.items:
        value = list(item); record = by_old_x.get(item[1]) if item[0] == 'text' else None
        size = 19 if record and record['grace'] else 24 if record and record['part'] else 28
        # 节奏符号说明与声部对齐：修改，旧按最近边界移动保留；音符装饰明确沿所属中心平移。
        # is_glyph = record is not None and item[4] == size and item[6] == 'middle'
        # if item[0] in ('text', 'dot'): value[1] = move_x(value[1])
        # elif item[0] in ('line', 'arc'): value[1] = move_x(value[1]); value[3] = move_x(value[3])
        is_glyph = record is not None and item[4] == size and item[6] == 'middle' and item[2] == record['old_y']
        if item[0] in ('group_start', 'group_end'): active = None
        if is_glyph: active = record
        if item[0] in ('text', 'dot'):
            if is_glyph: value[1] = record['x']
            elif active and abs(item[1]-active['old_x']) <= 28 and abs(item[2]-active['old_y']) <= 70:
                value[1] = active['x'] + item[1]-active['old_x']
            else: value[1] = move_endpoint(value[1])
        elif item[0] in ('line', 'arc'): value[1] = move_endpoint(value[1]); value[3] = move_endpoint(value[3])
        if is_glyph:
            identity = f"vocal-glyph-{record['id']}-p{record['part']}"
            changed.extend([('group_start', identity), tuple(value), ('group_end',)])
            drawn[identity] = record
        else: changed.append(tuple(value))
    scene.items = changed; scene.measure_boxes = boxes
    # 结构稳定伴奏与人声合播：修改，原总宽度保留。
    # scene.width = 52 + len(boxes) * measure_width + 42; scene.vocal_glyphs = drawn
    scene.width = cursor_x + 42; scene.vocal_glyphs = drawn
    return scene


# 节奏符号说明与声部对齐：新增可追溯字形标记，验证读取可见text坐标而不信任隐藏x。
def annotate_vocal_glyphs(root, scene):
    root.set('data-time-alignment', MODE)
    for node in root.iter(NS + 'g'):
        record = scene.vocal_glyphs.get(node.get('id'))
        if not record: continue
        node.set('class', 'vocal-time-glyph'); node.set('data-event-id', record['id'])
        node.set('data-part', str(record['part'])); node.set('data-start-tick', str(record['tick']))
        node.set('data-grace', 'true' if record['grace'] else 'false')


# 节奏符号说明与声部对齐：新增包括祖先位移的实际横坐标读回，防止整声部偏移蒙混通过。
def visible_x(node, parents):
    x, y = float(node.get('x')), float(node.get('y')); current = node
    while current is not None:
        transform = current.get('transform', '')
        operations = re.findall(r'(translate|scale|matrix)\s*\(([^)]+)\)', transform)
        if transform and re.sub(r'(translate|scale|matrix)\s*\([^)]+\)', '', transform).strip():
            raise ValueError('不支持的字形变换。')
        for kind, values in reversed(operations):
            nums = [float(n) for n in re.split(r'[\s,]+', values.strip())]
            if kind == 'translate' and len(nums) in (1, 2): x += nums[0]; y += nums[1] if len(nums) == 2 else 0
            elif kind == 'scale' and len(nums) in (1, 2): x *= nums[0]; y *= nums[1] if len(nums) == 2 else nums[0]
            elif kind == 'matrix' and len(nums) == 6:
                a, b, c, d, e, f = nums; x, y = a*x+c*y+e, b*x+d*y+f
            else: raise ValueError('字形变换参数错误。')
        current = parents.get(current)
    if not math.isfinite(x): raise ValueError('字形横坐标非有限值。')
    return x


# 节奏符号说明与声部对齐：新增从原工程独立推导普通音/休止/长音横线的记谱时间。
def validate_time_alignment(rows, arrangement, vocal, shared):
    if arrangement.get('time_alignment_display', {}).get('mode') != MODE: return None
    bar = vocal['statistics']['bar_ticks']; events = {e['id']: e for e in vocal['events']}
    errors = []; seen = set(); row_measures = set(); paired = 0; glyph_count = 0; grace_count = 0; max_error = 0.
    for row in rows:
        try:
            root = ET.fromstring(row['guitar']); parents = {c: p for p in root.iter() for c in p}
            first, last = int(root.get('data-first-measure')), int(root.get('data-last-measure'))
            numbers = set(range(first, last + 1))
            if numbers & row_measures: raise ValueError('行小节重复。')
            row_measures.update(numbers); begin, end = (first - 1) * bar, last * bar
            if root.get('data-time-alignment') != MODE: raise ValueError('缺少共同拍点标记。')
            # 节奏符号说明与声部对齐：新增按原声部及区段重判隐藏条件，不信任SVG隐藏声明。
            has_section = any(s['kind'] == 'vocal' and s['start_tick'] < end and s['end_tick'] > begin
                              for s in shared.get('sections', []))
            has_voice = any(n.get('start_tick', 0) < end and n.get('end_tick', n.get('start_tick', 0) + n.get('duration_ticks', 0)) > begin
                            for n in vocal.get('quantized_notes', []))
            instrumental = all(shared['measure_textures'][m-1]['section'] in ('intro', 'interlude', 'outro') for m in numbers)
            hidden = bool(arrangement.get('notation_regions')) and instrumental and not has_section and not has_voice
            if (root.get('data-instrumental-tab-only') == 'true') != hidden: raise ValueError('人声行隐藏条件不符。')
            expected = {}
            if not hidden:
                for event in vocal['events']:
                    if event['measure'] not in numbers: continue
                    for part in range({'whole': 4, 'half': 2}.get(event['type'], 1)):
                        expected[(event['id'], part)] = event['start_tick'] + part * PPQ
            tab_x = defaultdict(list)
            for group in root.iter(NS + 'g'):
                if not group.get('data-string'): continue
                text = group.find(NS + 'text'); tab_x[int(group.get('data-start-tick'))].append(visible_x(text, parents))
            actual = {}; regular = defaultdict(list)
            for group in root.iter(NS + 'g'):
                if group.get('class') != 'vocal-time-glyph': continue
                identity = group.get('data-event-id'), int(group.get('data-part'))
                if identity not in expected or identity in actual or identity in seen: raise ValueError('字形身份缺失/多余/重复。')
                event = events[identity[0]]; tick = expected[identity]; text = group.find(NS + 'text')
                if tick != int(group.get('data-start-tick')) or (group.get('data-grace') == 'true') != event['grace']:
                    raise ValueError('字形时间或倚音身份不符。')
                label = '–' if identity[1] else jianpu_pitch(event['pitch_midi'], *notation_at(vocal, measure=event['measure']))[0]
                size = 19 if event['grace'] else 24 if identity[1] else 28
                if text.text != label or float(text.get('font-size')) != size or text.get('text-anchor') != 'middle':
                    raise ValueError('可见字形或中心锚点不符。')
                x = visible_x(text, parents); actual[identity] = x; seen.add(identity); glyph_count += 1
                if event['grace']: grace_count += 1
                else: regular[tick].append(x)
            if set(actual) != set(expected): raise ValueError('有简谱字形未显示或未绑定时间。')
            for identity, x in actual.items():
                event = events[identity[0]]
                if not event['grace']: continue
                anchor = next((e for e in vocal['events'] if e.get('piece_id') == event.get('anchor_id') and not e['grace']), None)
                if anchor and (anchor['id'], 0) in actual and actual[(anchor['id'], 0)] - x < 29:
                    raise ValueError('倚音与主音重叠。')
            # 节奏符号说明与声部对齐：新增同tick所有可见中心比较，包含长音横线和多弦合拨。
            combined = defaultdict(list)
            for tick, values in tab_x.items(): combined[tick].extend(values)
            for tick, values in regular.items():
                combined[tick].extend(values)
                if tick in tab_x: paired += len(values)
            previous = None
            for tick, values in sorted(combined.items()):
                error = max(values) - min(values); max_error = max(max_error, error)
                if error > .02: raise ValueError(f'同拍字形未对齐：{tick}，偏移{error:.3f}px。')
                center = sum(values) / len(values)
                if previous is not None and center <= previous: raise ValueError('不同时间的起音重叠或逆序。')
                previous = center
        except (ValueError, KeyError, TypeError, AttributeError, StopIteration) as exc:
            errors.append('visible_time_alignment_invalid:' + str(exc))
    if row_measures != set(range(1, vocal['statistics']['measure_count'] + 1)): errors.append('score_row_coverage_invalid')
    return {'valid': not errors, 'errors': errors, 'vocal_glyphs': glyph_count, 'grace_glyphs': grace_count,
            'simultaneous_vocal_tab_columns': paired, 'maximum_center_error_pixels': round(max_error, 6),
            'includes': ['notes', 'rests', 'long_note_dashes', 'simultaneous_strings', 'ancestor_transforms']}
