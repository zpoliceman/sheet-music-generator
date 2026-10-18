"""扫弦箭头与实际弦组记谱修正：TAB直箭头及独立可见几何回读。"""
# 扫弦箭头与实际弦组记谱修正：新增只负责记谱的模块，实际音符及上下扫发声顺序仍由演奏层处理。
import math
import xml.etree.ElementTree as ET

NS = '{http://www.w3.org/2000/svg}'


def swept_note_ids(arrangement):
    # 扫弦箭头与实际弦组记谱修正：新增仅替换显式扫弦攻击，合拨和跨小节续音不受影响。
    return {identity for event in arrangement.get('selected_pattern_actions', [])
            if event['kind'] == 'strum' for identity in event['note_ids']}


def draw_strum_arrow(group, event, at):
    # 扫弦箭头与实际弦组记谱修正：新增从实际弦组定端点；六线谱上低弦在下，下扫因此向上。
    strings = event['strings']
    top, bottom = 337 + (min(strings)-1)*18, 337 + (max(strings)-1)*18
    tail, tip = (bottom, top) if event['direction'] == 'down' else (top, bottom)
    ET.SubElement(group, NS+'line', {'class':'strum-shaft','x1':f'{at:g}','x2':f'{at:g}',
        'y1':str(tail),'y2':str(tip),'stroke':'#163a45','stroke-width':'1.6'})
    back = tip + (7 if tip < tail else -7)
    ET.SubElement(group, NS+'polyline', {'class':'strum-head',
        'points':f'{at-4:g},{back:g} {at:g},{tip:g} {at+4:g},{back:g}',
        'fill':'none','stroke':'#163a45','stroke-width':'1.6','stroke-linejoin':'round','stroke-linecap':'round'})
    ET.SubElement(group, NS+'title').text = ('下扫' if event['direction']=='down' else '上扫') + '：' + '、'.join(map(str,strings)) + '弦'


def read_visible_strums(root, arrangement):
    # 扫弦箭头与实际弦组记谱修正：新增独立读回真正线段、箭头尖、弦线和可见指型；不以方向属性自证字形。
    from guitar_chord_diagrams import read_diagram, left_hand_fret
    parents = {child:parent for parent in root.iter() for child in parent}
    events = {e['id']:e for e in arrangement.get('selected_pattern_actions',[]) if e['kind']=='strum'}
    notes = {n['id']:n for n in arrangement['notes']}
    charts, decoded, errors = [], [], []
    for node in root.iter(NS+'g'):
        if node.get('class') == 'chord-diagram':
            try:
                charts.append((node,read_diagram(node)))
            except (KeyError,ValueError,TypeError,AttributeError):
                errors.append('strum_visible_chord_invalid')

    def visible(node):
        while node is not None:
            style = node.get('style','').replace(' ','').lower()
            if (node.get('display')=='none' or node.get('visibility') in ('hidden','collapse')
                    or 'display:none' in style or 'visibility:hidden' in style):
                return False
            try:
                if float(node.get('opacity','1'))<=0 or 'opacity:0;' in style or style.endswith('opacity:0'):
                    return False
            except ValueError:
                return False
            node = parents.get(node)
        return True

    def number(node, attr):
        value = float(node.get(attr))
        if not math.isfinite(value):
            raise ValueError('非有限几何坐标')
        return value

    for group in root.iter(NS+'g'):
        if group.get('data-action-kind') != 'strum':
            continue
        try:
            event = events[group.get('data-action-id')]
            if not visible(group):
                raise ValueError('扫弦箭头不可见')
            parent = parents[group]
            lines = [n for n in parent.findall(NS+'line') if n.get('class')=='tab-string-line']
            ys = sorted({number(n,'y1') for n in lines if n.get('y1')==n.get('y2')})
            if len(ys)!=6:
                raise ValueError('缺少同层六条实际弦线')
            strings = event['strings']
            if (len(strings)<2 or sorted(strings)!=list(range(min(strings),max(strings)+1))
                    or group.get('data-strings')!=','.join(map(str,strings))
                    or group.get('data-direction')!=event['direction']):
                raise ValueError('扫弦实际弦组／方向错误')
            shafts = [n for n in group if n.get('class')=='strum-shaft' and n.tag==NS+'line']
            heads = [n for n in group if n.get('class')=='strum-head' and n.tag==NS+'polyline']
            if len(shafts)!=1 or len(heads)!=1 or group.find(NS+'text') is not None:
                raise ValueError('必须绘制唯一跨弦直箭头')
            shaft,head=shafts[0],heads[0]
            if not all(visible(n) and n.get('stroke') not in (None,'none','transparent','white','#fff','#ffffff')
                       and float(n.get('stroke-width','1'))>0 for n in (shaft,head)):
                raise ValueError('箭头线段／箭头尖不可见')
            at=number(shaft,'x1');tail=number(shaft,'y1');tip=number(shaft,'y2')
            if abs(at-number(shaft,'x2'))>.02:
                raise ValueError('扫弦箭头不竖直')
            wanted_tail,wanted_tip=(ys[max(strings)-1],ys[min(strings)-1]) if event['direction']=='down' else (ys[min(strings)-1],ys[max(strings)-1])
            if abs(tail-wanted_tail)>.02 or abs(tip-wanted_tip)>.02:
                raise ValueError('箭头方向／跨度与实际扫弦不符')
            points=[tuple(map(float,point.split(','))) for point in head.get('points','').split()]
            if len(points)!=3 or any(not math.isfinite(v) for pair in points for v in pair):
                raise ValueError('箭头尖几何无效')
            left,peak,right=points
            sign=1 if tip<tail else -1
            if (abs(peak[0]-at)>.02 or abs(peak[1]-tip)>.02 or not left[0]<at<right[0]
                    or not 3<=(left[1]-tip)*sign<=10 or not 3<=(right[1]-tip)*sign<=10):
                raise ValueError('可见箭头尖指向错误')
            crossed=[i+1 for i,y in enumerate(ys) if min(tail,tip)-.02<=y<=max(tail,tip)+.02]
            if crossed!=sorted(strings) or any(not any(abs(number(line,'y1')-ys[s-1])<.02
                    and min(number(line,'x1'),number(line,'x2'))<=at<=max(number(line,'x1'),number(line,'x2'))
                    for line in lines) for s in crossed):
                raise ValueError('箭头未跨过真实目标弦线')
            # 扫弦箭头与实际弦组记谱修正：新增同拍时值符干作为横坐标证据，防止把箭头移到别的拍位。
            rhythms=[n for n in parent.findall(NS+'line') if n.get('data-rhythm-tick')==str(event['start_tick'])]
            if not rhythms or all(abs(number(n,'x1')-at)>.02 for n in rhythms):
                raise ValueError('箭头与真实节拍列错位')
            chart=next((chart for node,chart in charts if visible(node)
                and chart['start_tick']<=event['start_tick']<chart['end_tick']),None)
            if chart is None:
                raise ValueError('扫弦缺少实际可见指型')
            for identity in event['note_ids']:
                note=notes[identity]
                if note['string'] not in crossed or left_hand_fret(chart,note['string'])!=note['fret']:
                    raise ValueError('跨弦箭头／可见指型与实际音符不符')
                if any((n.get('data-note-id')==identity or n.get('id')==identity) and n.find(NS+'text') is not None
                       and n.get('data-continuation')!='true' for n in root.iter(NS+'g')):
                    raise ValueError('扫弦仍叠加柱式音头')
                decoded.append((identity,note['string'],note['fret'],note['start_tick']))
        except (KeyError,ValueError,TypeError,AttributeError,IndexError) as exc:
            errors.append('visible_strum_invalid:'+str(exc))
    return decoded,errors
