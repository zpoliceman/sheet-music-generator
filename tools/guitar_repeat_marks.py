"""吉他长段反复与流畅阅读：新增实际反复线、房子及长段D.S.边界符号。"""
from collections import defaultdict
import re
import xml.etree.ElementTree as ET

NS = '{http://www.w3.org/2000/svg}'


# 吉他长段反复与流畅阅读：新增从音乐段落计算实际印刷边界，不在四小节续行重复标回跳。
def marker_specs(plan):
    result = defaultdict(list)
    for group in plan['repeat_groups']:
        a, z, b, end = (group[k] for k in ['canonical_first', 'canonical_last', 'second_first', 'second_last'])
        for block in plan['blocks']:
            first, last = block['canonical_first'], block['canonical_last']
            def add(kind, text='', target=None, pass_number=None):
                result[block['id']].append({'kind': kind, 'repeat_id': group['id'], 'text': text,
                                           'first': first, 'last': last, 'target': target, 'pass': pass_number})
            if group['method'] in ('repeat', 'volta'):
                if first == a: add('repeat_start', '反复起点')
                stop = z if group['method'] == 'repeat' else b - 1
                if last == stop: add('repeat_end', '反复至' + group['label'] + '，奏第二遍', a, 1)
                for number, key in [(1, 'first_ending'), (2, 'second_ending')]:
                    span = group[key]
                    if span and span[0] <= first <= span[1]:
                        add('volta_' + str(number), str(number) + ('.' if first == span[0] else '.（续）'),
                            span[1], number)
            else:
                if first == a: add('segno', group['label'], a)
                if last == b - 1:
                    add('ds', 'D.S. al ' + ('Coda' if end < plan['expanded_bars'] else 'Fine') + '：回' + group['label'], a)
                if last == z:
                    add('to_coda' if end < plan['expanded_bars'] else 'fine',
                        ('To Coda：回跳后转后续段' if end < plan['expanded_bars'] else 'Fine：回跳后结束'),
                        end + 1 if end < plan['expanded_bars'] else None, 2)
                if first == end + 1: add('coda', '后续段', end + 1, 2)
    return dict(result)


# 吉他长段反复与流畅阅读：新增实际弦线坐标回读，反复线和双点落在六线谱边界。
def tab_bounds(root):
    parents = {child: parent for parent in root.iter() for child in parent}
    lines = []
    for node in root.iter(NS + 'line'):
        if node.get('class') != 'tab-string-line': continue
        dx = dy = 0.; parent = parents.get(node)
        while parent is not None:
            found = re.search(r'translate\(([-\d.]+)(?:[, ]+([-\d.]+))?\)', parent.get('transform', ''))
            if found: dx += float(found[1]); dy += float(found[2] or 0)
            parent = parents.get(parent)
        lines.append((float(node.get('x1')) + dx, float(node.get('x2')) + dx, float(node.get('y1')) + dy))
    if not lines: raise ValueError('反复线缺少实际六线谱边界。')
    return min(x for x, _, _ in lines), max(x for _, x, _ in lines), min(y for _, _, y in lines), max(y for _, _, y in lines)


# 吉他长段反复与流畅阅读：新增无需外部音乐字体的印刷反复符号；正文仅在实际边界写指令。
def draw_annotations(root, specs, draw_marker):
    if not specs: return
    left, right, top, bottom = tab_bounds(root); height = float(root.get('height'))
    for spec in specs:
        attrs = {'class': 'repeat-print-symbol', 'data-marker-kind': spec['kind'],
                 'data-repeat-id': spec['repeat_id'], 'data-first': str(spec['first']), 'data-last': str(spec['last']),
                 'data-target': str(spec['target']), 'data-pass': str(spec['pass'])}
        node = ET.SubElement(root, NS + 'g', attrs); kind = spec['kind']
        ET.SubElement(node, NS + 'title').text = spec['text']
        if kind in ('repeat_start', 'repeat_end'):
            start = kind == 'repeat_start'; x = left + 2 if start else right - 2
            for offset, width in [(0, 3), (7 if start else -7, 1.2)]:
                ET.SubElement(node, NS + 'line', {'x1': str(x + offset), 'x2': str(x + offset),
                    'y1': str(top), 'y2': str(bottom), 'stroke': '#14243b', 'stroke-width': str(width)})
            for y in [(top + bottom) / 2 - 8.5, (top + bottom) / 2 + 8.5]:
                ET.SubElement(node, NS + 'circle', {'cx': str(x + (15 if start else -15)), 'cy': str(y), 'r': '2.5', 'fill': '#14243b'})
            if not start:
                ET.SubElement(node, NS + 'text', {'x': str(right), 'y': str(height - 5), 'text-anchor': 'end',
                    'font-size': '14', 'font-family': 'Microsoft YaHei, sans-serif'}).text = spec['text']
        elif kind.startswith('volta_'):
            ET.SubElement(node, NS + 'path', {'d': f'M{left:g},32 V23 H{right:g}' + (' V32' if spec['last'] == spec['target'] else ''),
                'stroke': '#14243b', 'fill': 'none', 'stroke-width': '1.3'})
            ET.SubElement(node, NS + 'text', {'x': str(left + 5), 'y': '18', 'font-size': '15',
                'font-family': 'Microsoft YaHei, sans-serif'}).text = spec['text']
        elif kind in ('segno', 'coda'):
            draw_marker(node, kind, 16, '' if kind == 'segno' else spec['text'])
        else:
            ET.SubElement(node, NS + 'text', {'x': str(right), 'y': str(height - 5), 'text-anchor': 'end',
                'font-size': '14', 'font-family': 'Microsoft YaHei, sans-serif'}).text = spec['text']


# 吉他长段反复与流畅阅读：新增实际SVG符号验收，删符号、改房子／去向或只留元数据均拒绝。
def validate_marks(plan, rows):
    specs = marker_specs(plan); expected = []; actual = []; errors = []
    for name, items in specs.items():
        for spec in items: expected.append((name, spec['kind'], spec['repeat_id'], str(spec['first']), str(spec['last']), str(spec['target']), str(spec['pass'])))
    for row in rows:
        root = ET.fromstring(row['guitar'])
        for block in root.iter(NS + 'g'):
            if block.get('class') != 'repeat-block': continue
            name = block.get('data-block-id')
            for node in block.iter(NS + 'g'):
                if node.get('class') != 'repeat-print-symbol': continue
                kind = node.get('data-marker-kind')
                actual.append((name, kind, node.get('data-repeat-id'), node.get('data-first'), node.get('data-last'), node.get('data-target'), node.get('data-pass')))
                spec = next((s for s in specs.get(name, []) if s['kind'] == kind and s['repeat_id'] == node.get('data-repeat-id')), None)
                if not spec: errors.append('额外的印刷反复符号。'); continue
                title = node.find(NS + 'title')
                if title is None or title.text != spec['text']: errors.append('印刷反复符号说明不符。')
                if kind in ('repeat_start', 'repeat_end'):
                    if len(node.findall(NS + 'line')) != 2 or len(node.findall(NS + 'circle')) != 2:
                        errors.append('实际反复线或双点缺失。')
                elif kind.startswith('volta_'):
                    if node.find(NS + 'path') is None or node.find(NS + 'text') is None or node.find(NS + 'text').text != spec['text']:
                        errors.append('实际房子括号或遍次缺失／改变。')
                elif kind in ('segno', 'coda'):
                    if node.find('.//' + NS + 'path') is None: errors.append('实际Segno／Coda符号缺失。')
                elif node.find(NS + 'text') is None or node.find(NS + 'text').text != spec['text']:
                    errors.append('实际D.S.／转尾／结束文案改变。')
    if sorted(expected) != sorted(actual): errors.append('实际印刷反复符号存在缺失／额外项。')
    return {'valid': not errors, 'errors': errors, 'visible_symbols': len(actual), 'all_boundary_symbols_preserved': not errors}
