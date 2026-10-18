"""规整分解节奏与延音显示：跨小节持续图形及实际弦品/时间回读。"""
# 规整分解节奏与延音显示：新增延音续段，括号品数提示沿用旧音，不产生新拨弦。
import xml.etree.ElementTree as ET
import numpy as np
# 结构稳定伴奏与人声合播：修改，原代码注释保留。
# from guitar_time_alignment import visible_x
from guitar_time_alignment import visible_x
# 结构稳定伴奏与人声合播：新增续音相对品数。
from guitar_capo import fret_at
NS = '{http://www.w3.org/2000/svg}'


def draw_continuations(scene, arrangement, first, last, bar, x_at):
    records = {}
    for measure in range(first, last+1):
        begin = (measure-1)*bar; box = scene.measure_boxes[measure]
        for note in arrangement['notes']:
            if not note['start_tick'] < begin < note['end_tick']: continue
            finish = min(note['end_tick'], begin+bar); x = x_at(box, 0)
            end_x = x_at(box, min(bar-1, finish-begin)); y = 226+(note['string']-1)*17
            identity = f"tab-held-{measure}-{note['id']}"
            color = '#147264' if note['role']=='instrumental_melody' else '#8b5b28' if note['role']=='bass' else '#18334b'
            # 结构稳定伴奏与人声合播：修改，原代码注释保留。
            # scene.items.extend([('group_start', identity), ('text', x, y, f"({note['fret']})", 14, color, 'middle', 'normal'),
            scene.items.extend([('group_start', identity), ('text', x, y, f"({fret_at(note,arrangement,begin)})", 14, color, 'middle', 'normal'),
                                ('line', x+13, y+5, max(x+13, end_x-3), y+5, color, .9), ('group_end',)])
            records[identity] = {'note': note, 'begin': begin, 'end': finish, 'x': x, 'y': y}
    return records


# 规整分解节奏与延音显示：新增续音节点身份，与带data-string的新起音节点严格分开。
def annotate_continuations(root, records):
    for group in root.iter(NS+'g'):
        record = records.get(group.get('id'))
        if not record: continue
        note = record['note']; group.set('class', 'tab-continuation')
        for name, value in {'data-held-note-id': note['id'], 'data-string-number': note['string'],
                            'data-from-tick': record['begin'], 'data-to-tick': record['end']}.items(): group.set(name, str(value))
        group.insert(0, ET.Element(NS+'rect', {'x': str(record['x']-13), 'y': str(record['y']-9),
                                             'width': '26', 'height': '18', 'fill': 'white'}))
        ET.SubElement(group, NS+'title').text = '上一小节的音继续响；括号品数仅作提示，无需重新拨弦。'


# 规整分解节奏与延音显示：新增从实际谱面拍号位置/音符中心复算续音起点和结束位置。
def validate_continuations(rows, arrangement):
    if not arrangement.get('tab_display', {}).get('cross_bar_sustain'): return None
    bar = arrangement['rhythm_display']['bar_ticks']; notes = {n['id']: n for n in arrangement['notes']}
    expected = {(m, n['id']): ((m-1)*bar, min(m*bar, n['end_tick'])) for n in notes.values()
                for m in range(n['start_tick']//bar+2, (n['end_tick']-1)//bar+2)}
    observed = {}; errors = []
    for row in rows:
        try:
            root = ET.fromstring(row['guitar']); first = int(root.get('data-first-measure')); last = int(root.get('data-last-measure'))
            # 规整分解节奏与延音显示：修改，旧单表保留；行内下一小节起点和上一小节终点分别处理。
            # parents = {c:p for p in root.iter() for c in p}; anchors = {}
            parents = {c:p for p in root.iter() for c in p}; anchors = {}; beat_anchors = {}
            labels = sorted((visible_x(t, parents), int(t.text)) for t in root.iter(NS+'text')
                            if float(t.get('y', '-1'))==376 and t.text in ('1','2','3','4','5','6','7','8','9'))
            beats = arrangement['rhythm_display']['bar_ticks']//arrangement['rhythm_display']['beat_ticks']
            if len(labels) != (last-first+1)*beats: raise ValueError('拍号定位数量不符。')
            for index, (x, beat) in enumerate(labels):
                measure = first+index//beats; anchors[(measure-1)*bar+(beat-1)*arrangement['rhythm_display']['beat_ticks']] = x
                beat_anchors[(measure-1)*bar+(beat-1)*arrangement['rhythm_display']['beat_ticks']] = x
            bars = sorted({float(n.get('x1')) for n in root.iter(NS+'line') if n.get('x1')==n.get('x2') and float(n.get('y1'))==222})
            for index, measure in enumerate(range(first, last+1)): anchors[measure*bar] = bars[index+1]-12
            for group in root.iter(NS+'g'):
                if group.get('data-string') or group.get('class')=='vocal-time-glyph' and group.get('data-grace')!='true':
                    anchors[int(group.get('data-start-tick'))] = visible_x(group.find(NS+'text'), parents)
                elif group.get('class')=='chord-diagram':
                    anchors[int(group.get('data-start-tick'))] = visible_x(group.find(NS+'text'), parents)
            # 规整分解节奏与延音显示：新增起点使用该小节可见拍号，不能被前小节终点的留白覆盖。
            anchors.update(beat_anchors)
            for group in root.iter(NS+'g'):
                if group.get('class')!='tab-continuation': continue
                begin, finish = int(group.get('data-from-tick')), int(group.get('data-to-tick')); identity = group.get('data-held-note-id')
                key = begin//bar+1, identity; note = notes[identity]; text = group.find(NS+'text'); line = group.find(NS+'line')
                # 结构稳定伴奏与人声合播：修改，原代码注释保留。
                # if key in observed or expected.get(key)!=(begin, finish) or text.text!=f"({note['fret']})": raise ValueError('延音身份/区间/品数不符。')
                if key in observed or expected.get(key)!=(begin, finish) or text.text!=f"({fret_at(note,arrangement,begin)})": raise ValueError('延音身份/区间/品数不符。')
                x = visible_x(text, parents)
                if abs(x-anchors[begin])>.02 or float(text.get('y'))!=226+(note['string']-1)*17 or int(group.get('data-string-number'))!=note['string']:
                    raise ValueError('延音未画在小节起点或实际弦上。')
                if group.get('data-string'): raise ValueError('延音被误作新拨弦。')
                local = {t:a for t,a in anchors.items() if begin<=t<=begin+bar}
                local[begin+bar] = bars[key[0]-first+1]-12
                ts = sorted(local); at = min(finish, begin+bar-1)
                end_x = float(np.interp(at, ts, [local[t] for t in ts]))
                if abs(float(line.get('x1'))-x-13)>.02 or abs(float(line.get('x2'))-max(x+13, end_x-3))>.12 or float(line.get('y1'))!=float(text.get('y'))+5 or line.get('y1')!=line.get('y2'):
                    raise ValueError('可见延音线长度或弦位不符。')
                observed[key] = begin, finish
        except (ValueError, KeyError, TypeError, AttributeError, IndexError) as exc: errors.append('visible_continuation_invalid:'+str(exc))
    if observed!=expected: errors.append('cross_bar_continuations_missing_or_extra')
    return {'valid': not errors, 'errors': errors, 'visible_continuations': len(observed), 'not_new_attacks': True}
