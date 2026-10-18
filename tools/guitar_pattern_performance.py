"""4/4可选右手与实时谱面试听：单次扫弦的受约束逐弦发声投影。"""
# 4/4可选右手与实时谱面试听：新增谱面保留同一拍位，MIDI和试听共用方向展开；旧音符原样通过。
from copy import deepcopy


def notation_notes(arrangement):
    # 4/4可选右手与实时谱面试听：新增已保护旧音的自然释放记谱视图，不把微小结束差画成32／64分动作。
    projections={p['note_id']:p for p in arrangement.get('natural_release_notation',[])}
    if not projections:return arrangement['notes']
    output=[]
    for note in arrangement['notes']:
        projection=projections.get(note['id'])
        if projection is None:
            output.append(note);continue
        actual,end=projection['actual_end_tick'],projection['notation_end_tick']
        if (note['end_tick']!=actual or note['start_tick']%120 or not 0<end-actual<120
                or end%120 or note['end_tick']-note['start_tick']<120):
            raise ValueError('自然余音的记谱投影无效')
        output.append({**note,'end_tick':end})
    return output


def performance_notes(arrangement):
    # 4/4可选右手与实时谱面试听：新增独立由实际弦序重建微时差，不接受调用方自填偏移规避十六分限制。
    actions = arrangement.get('selected_pattern_actions', [])
    if not actions:
        if any(n.get('selection_action_id') for n in arrangement['notes']):
            raise ValueError('可选右手的实际动作缺失，不能丢标记后按普通音符播放')
        return arrangement['notes']
    notes = {n['id']: n for n in arrangement['notes']}
    offsets = {}
    ids = set()
    for event in actions:
        if event['id'] in ids:
            raise ValueError('重复右手动作')
        ids.add(event['id'])
        actual = [notes.get(identity) for identity in event['note_ids']]
        if any(n is None for n in actual):
            raise ValueError('扫弦／合拨动作与实际音符脱节')
        if [n['string'] for n in actual] != event['strings'] or len(set(event['strings'])) != len(actual):
            raise ValueError('一次动作的实际弦组错误或同弦重复')
        if any(n['start_tick'] != event['start_tick'] or n.get('selection_action_id') != event['id'] for n in actual):
            raise ValueError('一次动作不能隐藏不同拍位的独立拨弦')
        if event['kind'] == 'strum':
            order = sorted(event['strings'], reverse=event['direction'] == 'down')
            if event['direction'] not in ('up', 'down') or order != event['strings'] or event['action_span_ticks'] < 120:
                raise ValueError('扫弦方向、弦序或十六分下限错误')
            if event['direction'] == 'down' and order != list(range(max(order), min(order)-1, -1)):
                raise ValueError('下扫弦组中间存在未说明的空弦')
            for rank, note in enumerate(actual):
                offset = rank * 4
                if offset > 20 or note['end_tick'] - note['start_tick'] < 120:
                    raise ValueError('扫弦的发声展开越界')
                offsets[note['id']] = offset
        elif event['kind'] not in ('pluck', 'pinch', 'hold', 'air', 'stop'):
            raise ValueError('未支持的右手发声动作')
    if any(n.get('selection_action_id') not in ids for n in notes.values() if n.get('selection_action_id')):
        raise ValueError('实际右手音符缺少对应动作')
    return [{**n, 'start_tick': n['start_tick'] + offsets.get(n['id'], 0)} for n in arrangement['notes']]


def action_signature(arrangement, start, end):
    # 4/4可选右手与实时谱面试听：新增复用签名包括方向、弦组、空扫及制音；相同音高不等于同一手势。
    return [(e['start_tick']-start, e['action_span_ticks'], e['kind'], e['token'], e['direction'], e['strings'])
            for e in arrangement.get('selected_pattern_actions', []) if start <= e['start_tick'] < end]


def add_xml_actions(root, arrangement, bar_ticks):
    # 4/4可选右手与实时谱面试听：新增XML动作说明与标准琶音方向，保留实际持续音和原有连线。
    import xml.etree.ElementTree as ET
    measures = root.findall('part/measure')
    for event in arrangement.get('selected_pattern_actions', []):
        index = event['start_tick'] // bar_ticks
        if not 0 <= index < len(measures):
            continue
        node = measures[index]
        direction = ET.Element('direction', placement='above', id=event['id'] + '_action')
        kind = ET.SubElement(direction, 'direction-type')
        label = {'strum': '下扫' if event['direction'] == 'down' else '上扫', 'pinch': '合拨',
                 'pluck': '拨弦', 'air': '空扫（自然延续）', 'hold': '延续', 'stop': '消音休止'}[event['kind']]
        ET.SubElement(kind, 'words').text = label + ' ' + event['token'] + ' · 动作' + str(event['action_span_ticks']/480) + '拍'
        ET.SubElement(direction, 'offset').text = str(event['start_tick'] % bar_ticks)
        node.insert(1, direction)
        if event['kind'] == 'strum':
            for note in node.findall('note'):
                if note.find("tie[@type='stop']") is not None:
                    continue
                if any((note.get('id') or '').startswith(identity + '_fragment_') for identity in event['note_ids']):
                    notation = note.find('notations')
                    if notation is None:
                        notation = ET.SubElement(note, 'notations')
                    ET.SubElement(notation, 'arpeggiate', direction='up' if event['direction'] == 'down' else 'down')


def rhythm_events(arrangement, start, end, attacks):
    # 4/4可选右手与实时谱面试听：新增动作节奏行；空扫保留动作时值，余音不冒充下一次拨弦。
    events = [e for e in arrangement.get('selected_pattern_actions', [])
              if e['start_tick'] < end and e['start_tick'] + e['action_span_ticks'] > start]
    if not events:
        projected={n['id']:n for n in notation_notes(arrangement)}
        attacks={t:[projected[n['id']] for n in notes] for t,notes in attacks.items()}
        ticks = sorted(attacks)
        return [(tick, min(min(n['end_tick'] for n in attacks[tick]),
                           ticks[i+1] if i+1 < len(ticks) else end, end)-tick) for i,tick in enumerate(ticks)]
    result = []
    for event in events:
        tick, finish = max(start, event['start_tick']), min(end, event['start_tick'] + event['action_span_ticks'])
        while tick < finish:
            length = min(finish-tick, 480-(tick-start)%480)
            result.append((tick, length))
            tick += length
    return sorted(result)


def strum_sustain_spans(arrangement, start, end):
    # 扫弦延音简化与右手候选扩充：新增明确空扫／停拨及长动作的成组延续区间，普通扫弦余音不逐弦标线。
    notes={n['id']:n for n in arrangement['notes']}
    events=sorted(arrangement.get('selected_pattern_actions',[]),key=lambda e:e['start_tick'])
    spans=[];previous=None
    for event in events:
        kind=event['kind'];tick=event['start_tick'];finish=tick+event['action_span_ticks']
        if kind in ('strum','pluck','pinch','stop'):
            previous=event if kind=='strum' else None
            if kind=='strum' and event['action_span_ticks']>480:
                release=max((notes[i]['end_tick'] for i in event['note_ids']),default=tick)
                if min(finish,release)>tick+480:
                    spans.append({'action_id':event['id'],'start_tick':tick,'end_tick':min(finish,release),'reason':'long_action'})
            continue
        if kind not in ('air','hold') or previous is None:
            continue
        alive=[notes[i] for i in previous['note_ids'] if notes[i]['end_tick']>tick]
        if not alive:
            continue
        release=min(finish,max(n['end_tick'] for n in alive))
        if (spans and spans[-1]['action_id']==previous['id'] and spans[-1]['end_tick']==tick):
            spans[-1]['end_tick']=release
            spans[-1]['reason']='explicit_gap'
        else:
            spans.append({'action_id':previous['id'],'start_tick':tick,'end_tick':release,'reason':'explicit_gap'})
    # 扫弦延音简化与右手候选扩充：新增真实窗口裁剪，跨小节／换行只提示当前可见的延续部分。
    return [{**span,'start_tick':max(start,span['start_tick']),'end_tick':min(end,span['end_tick'])}
            for span in spans if span['start_tick']<end and span['end_tick']>start]


def draw_action_marks(parent, arrangement, start, end, x):
    # 4/4可选右手与实时谱面试听：新增TAB方向、空扫／制音和逐弦余音弧；不改变项目x及旋律突出黑点语义。
    import xml.etree.ElementTree as ET
    ns = '{http://www.w3.org/2000/svg}'
    # 扫弦延音简化与右手候选扩充：新增本次渲染的动作索引，逐音查询不重复遍历整曲动作。
    actions_by_id={e['id']:e for e in arrangement.get('selected_pattern_actions',[])}
    def node(parent, tag, **attrs):
        return ET.SubElement(parent, ns+tag, {k.replace('_','-'):str(v) for k,v in attrs.items()})
    for event in arrangement.get('selected_pattern_actions', []):
        if not start <= event['start_tick'] < end:
            continue
        at = x(event['start_tick'])
        group = node(parent, 'g', **{'class':'right-hand-action','data-action-id':event['id'],
            'data-action-tick':event['start_tick'],'data-action-kind':event['kind'],
            'data-action-duration':event['action_span_ticks'],'data-direction':event['direction'] or '',
            'data-strings':','.join(map(str,event['strings']))})
        # 扫弦箭头与实际弦组记谱修正：停用谱线上方孤立方向字形，改为真实弦组内的直箭头。
        # label = {'strum':'↓' if event['direction']=='down' else '↑','pinch':'合','pluck':'',
        #          'air':'空','hold':'延','stop':'止'}[event['kind']]
        label = {'strum':'','pinch':'合','pluck':'',
                 'air':'空','hold':'延','stop':'止'}[event['kind']]
        if event['kind']=='strum':
            from guitar_strum_notation import draw_strum_arrow
            draw_strum_arrow(group,event,at)
        if label:
            text = node(group, 'text', x=at, y=322, font_size=15, text_anchor='middle', fill='#245e76')
            text.text = label
        if event['kind'] in ('air','stop'):
            node(group, 'line', x1=at, y1=333, x2=at, y2=429, stroke='#7e9ca8', stroke_dasharray='3 4', opacity='.55')
    for note in arrangement['notes']:
        if not note.get('selection_action_id') or note['start_tick'] >= end or note['end_tick'] <= start:
            continue
        # 扫弦延音简化与右手候选扩充：新增扫弦攻击排除，保留分解／合拨原来的逐弦延音说明。
        # 扫弦延音简化与右手候选扩充：保留初稿线性查询，改为同一渲染内的索引读取。
        # action=next((e for e in arrangement.get('selected_pattern_actions',[]) if e['id']==note['selection_action_id']),None)
        action=actions_by_id.get(note['selection_action_id'])
        if action is not None and action['kind']=='strum':
            continue
        if note['end_tick'] <= note['start_tick'] + note.get('right_hand_duration_ticks',120):
            continue
        a, b = max(start,note['start_tick']), min(end,note['end_tick'])
        left, right = x(a)+7, x(b)-7
        if right-left < 12:
            continue
        y = 346+(note['string']-1)*18
        node(parent, 'path', d=f'M {left:g} {y:g} Q {(left+right)/2:g} {y+9:g} {right:g} {y:g}',
             stroke='#698995', fill='none', stroke_width='.9', **{'class':'right-hand-sustain',
             'data-sustain-note-id':note['id'],'data-sustain-start':a,'data-sustain-end':b})
    # 扫弦延音简化与右手候选扩充：新增每段明确延续只画一条短弧，位于TAB上方，不穿过六根弦。
    for span in strum_sustain_spans(arrangement,start,end):
        left,right=x(span['start_tick'])+5,x(span['end_tick'])-5
        if right-left<8:
            continue
        group=node(parent,'g',**{'class':'right-hand-sustain-group','data-sustain-action-id':span['action_id'],
            'data-sustain-start':span['start_tick'],'data-sustain-end':span['end_tick'],'data-sustain-reason':span['reason']})
        node(group,'path',d=f'M {left:g} 330 Q {(left+right)/2:g} 336 {right:g} 330',
            stroke='#698995',fill='none',stroke_width='1.1')
        node(group,'title').text='前音自然延续，此处不重新扫弦'


def validate_action_artifacts(project, output_dir):
    # 4/4可选右手与实时谱面试听：新增独立读回真实SVG字形及XML方向／空扫，删箭头或改方向不能凭计划通过。
    from collections import Counter
    from pathlib import Path
    import xml.etree.ElementTree as ET
    from guitar_variable_repeat import measure_timeline
    folder=Path(output_dir)/'guitar'
    arrangement=project['arrangements']['guitar']
    events=arrangement.get('selected_pattern_actions',[])
    if not events:
        return {'valid':True,'status':'not_requested_for_preserved_legacy_music'}
    errors=[];actual=[];ns='{http://www.w3.org/2000/svg}'
    # 扫弦箭头与实际弦组记谱修正：新增独立读取实际箭头方向、跨度和可见指型，替代Unicode字形检查。
    from guitar_strum_notation import read_visible_strums
    swept=[]
    for path in sorted((folder/'rows').glob('voice_*.svg')):
        # for group in ET.parse(path).getroot().iter(ns+'g'):
        root=ET.parse(path).getroot()
        decoded,failures=read_visible_strums(root,arrangement)
        swept.extend(decoded);errors.extend(failures)
        for group in root.iter(ns+'g'):
            if group.get('class')!='right-hand-action':continue
            kind=group.get('data-action-kind');direction=group.get('data-direction') or None
            strings=tuple(int(s) for s in group.get('data-strings','').split(',') if s)
            actual.append((int(group.get('data-action-tick')),kind,int(group.get('data-action-duration')),direction,strings))
            # 扫弦箭头与实际弦组记谱修正：扫弦只认跨弦矢量箭头，合拨／空扫等仍核实际文字。
            # label={'strum':'↓' if direction=='down' else '↑','pinch':'合','pluck':'','air':'空','hold':'延','stop':'止'}.get(kind)
            label={'strum':'','pinch':'合','pluck':'','air':'空','hold':'延','stop':'止'}.get(kind)
            text=group.find(ns+'text')
            if label is None or (label and (text is None or text.text!=label)):
                errors.append('visible_action_glyph_missing_or_wrong')
    wanted=[(e['start_tick'],e['kind'],e['action_span_ticks'],e['direction'],tuple(e['strings'])) for e in events]
    if Counter(actual)!=Counter(wanted):errors.append('actual_svg_actions_differ_from_selected_performance')
    # 扫弦箭头与实际弦组记谱修正：新增完整音符覆盖检查，删箭头不能靠动作属性通过。
    wanted_swept=Counter(identity for e in events if e['kind']=='strum' for identity in e['note_ids'])
    if Counter(note[0] for note in swept)!=wanted_swept:
        errors.append('actual_visible_strum_notes_differ_from_performance')
    xml=ET.parse(folder/'score.musicxml').getroot();xml_actions=[];timeline=measure_timeline(project)
    expected_words=[]
    for e in events:
        label={'strum':'下扫' if e['direction']=='down' else '上扫','pinch':'合拨','pluck':'拨弦',
               'air':'空扫（自然延续）','hold':'延续','stop':'消音休止'}[e['kind']]
        expected_words.append((e['start_tick'],label+' '+e['token']+' · 动作'+str(e['action_span_ticks']/480)+'拍'))
    for row,measure in zip(timeline,xml.findall('part/measure')):
        for direction in measure.findall('direction'):
            if not direction.get('id','').endswith('_action'):continue
            xml_actions.append((row['start_tick']+int(direction.findtext('offset','0')),direction.findtext('direction-type/words')))
        for e in events:
            if e['kind']!='strum' or not row['start_tick']<=e['start_tick']<row['end_tick']:continue
            for identity in e['note_ids']:
                nodes=[n for n in measure.findall('note') if identity+'_fragment_' in n.get('id','') and n.find("tie[@type='stop']") is None]
                if len(nodes)!=1 or nodes[0].find('notations/arpeggiate') is None or nodes[0].find('notations/arpeggiate').get('direction')!=('up' if e['direction']=='down' else 'down'):
                    errors.append('xml_actual_strum_direction_missing_or_wrong')
    if Counter(xml_actions)!=Counter(expected_words):errors.append('actual_xml_actions_differ_from_selected_performance')
    return {'valid':not errors,'errors':sorted(set(errors)),'actual_svg_actions':len(actual),
            'expected_actions':len(events),'actual_xml_actions':len(xml_actions)}
