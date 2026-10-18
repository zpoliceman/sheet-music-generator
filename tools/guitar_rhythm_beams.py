"""六线谱同拍节奏连线：从真实攻击时值派生按拍横梁并读回可见几何。"""
# 六线谱同拍节奏连线：新增离线节奏绘图，实际发声音符、持续线及标准导出不变。
from collections import defaultdict
import xml.etree.ElementTree as ET
from score_export import PPQ,DURATIONS
NS='{http://www.w3.org/2000/svg}'
BEAM_Y=352
BEAM_GAP=6
FLAGS={'eighth':1,'16th':2,'32nd':3}


# 六线谱同拍节奏连线：新增简单拍/复拍分组，4/4以四分音符为一拍。
def beat_ticks(meter):
    numerator,denominator=meter
    unit=PPQ*4//denominator
    return unit*3 if denominator==8 and numerator>3 and numerator%3==0 else unit


# 六线谱同拍节奏连线：新增同刻多弦共用攻击符干，以最短新起音的时值显示节奏。
# 规整分解节奏与延音显示：修改，原入口保留；允许明确右手拍格独立于各弦响多久。
# def rhythm_events(notes,meter,bar_ticks):
def rhythm_events(notes,meter,bar_ticks,attack_durations=None):
    by_tick=defaultdict(list)
    for note in notes:by_tick[note['start_tick']].append(note)
    events=[];beat=beat_ticks(meter)
    for tick,values in sorted(by_tick.items()):
        # 规整分解节奏与延音显示：修改，原最短持续值保留；有明确模板时使用右手起音拍格。
        # duration=min(n['end_tick']-tick for n in values)
        sounding=min(n['end_tick']-tick for n in values)
        duration=(attack_durations or {}).get(tick,sounding)
        part=next((p for p in DURATIONS if p[0]<=duration),None)
        if part is None:raise ValueError('攻击时值小于现有最小记谱网格。')
        length,kind,dots=part
        events.append({'tick':tick,'duration':duration,'type':kind,'dots':dots,'flags':FLAGS.get(kind,0),
                       'composite_duration':length!=duration,'measure':tick//bar_ticks+1,
                       # 规整分解节奏与延音显示：修改，原结束字段保留；实际发声持续另存并由细线说明。
                       # 'beat':(tick%bar_ticks)//beat,'note_ids':sorted(n['id'] for n in values)})
                       'beat':(tick%bar_ticks)//beat,'note_ids':sorted(n['id'] for n in values),
                       'sounding_duration_ticks':sounding})
    return events


# 六线谱同拍节奏连线：新增四分以上/真实间隙/拍界断开；跨拍持续仍用原TAB延音线。
def adjacent(left,right):
    return (left['measure'],left['beat'])==(right['measure'],right['beat']) and left['tick']+left['duration']>=right['tick']


def prepare_rhythm(vocal,arrangement):
    # 六线谱同拍节奏连线：新增派生显示约定，不修改notes与attack_events。
    meter=vocal['timing']['meter']
    arrangement['rhythm_display']={'mode':'beat_beams','meter':list(meter),'bar_ticks':vocal['statistics']['bar_ticks'],
                                  'beat_ticks':beat_ticks(meter),'eighth_lines':1,'sixteenth_lines':2,
                                  'simultaneous_notes':'one_stem','attack_duration':'shortest_new_note',
                                  'sustained_notes':'existing_tab_hold_lines','rest_gaps':'break_beams'}
    # 规整分解节奏与延音显示：新增普通右手模板拍格的声明，独奏时值按原谱保留。
    if arrangement.get('regular_rhythm'):
        arrangement['rhythm_display']['attack_duration']='right_hand_slots_for_regular_patterns'
        arrangement['rhythm_display']['sounding_duration']='independent_per_string_hold_lines'


# 规整分解节奏与延音显示：新增导出/回读共同解析真实右手事件，旧工程保持原时值规则。
def arrangement_rhythm_events(arrangement,meter,bar_ticks,notes=None):
    durations={e['start_tick']:e['right_hand_duration_ticks'] for e in arrangement.get('attack_events',[])
               # 器乐声部恢复与规整节奏：修改，原仅普通伴奏槽保留；器乐槽也来自真实新起音，不改变持音。
               # if e.get('right_hand_duration_source')=='regular_pattern_slot'}
               # 器乐低弦分解填充：修改，旧来源白名单保留；新增低弦共同攻击时值与实际持音分别绘制。
               # if e.get('right_hand_duration_source') in ('regular_pattern_slot','instrumental_regular_grid')}
               if e.get('right_hand_duration_source') in ('regular_pattern_slot','instrumental_regular_grid','instrumental_flow_grid')}
    return rhythm_events(arrangement['notes'] if notes is None else notes,meter,bar_ticks,durations)


# 六线谱同拍节奏连线：新增主横梁及混合时值次横梁，单独级别显示短横钩。
def draw_rhythm(events,x_at):
    nodes=[];runs=[];run=[]
    for event in events:
        tick=event['tick'];x=x_at(tick)
        group=ET.Element(NS+'g',{'id':f'tab-rhythm-{tick}','class':'tab-rhythm-event',
              'data-start-tick':str(tick),'data-duration-ticks':str(event['duration']),
              'data-type':event['type'],'data-beam-count':str(event['flags']),
              'data-note-ids':' '.join(event['note_ids'])})
        ET.SubElement(group,NS+'line',{'class':'tab-rhythm-stem','x1':str(x),'x2':str(x),
                      'y1':'328','y2':str(BEAM_Y),'stroke':'#344c60','stroke-width':'1.3'})
        for dot in range(event['dots']):
            ET.SubElement(group,NS+'circle',{'class':'tab-rhythm-dot','cx':str(x+10+dot*6),
                          'cy':'336','r':'2.2','fill':'#344c60'})
        if event['type'] in ('half','whole'):
            ET.SubElement(group,NS+'circle',{'class':'tab-rhythm-open-head','cx':str(x),'cy':'360',
                          'r':'3','fill':'white','stroke':'#344c60','stroke-width':'1.1'})
        # 规整分解节奏与延音显示：修改，原提示保留；读谱解释起音节奏与实际延音分开。
        # title=ET.SubElement(group,NS+'title');title.text=f"本次攻击 {event['duration']} ticks；持续音见TAB横线"
        title=ET.SubElement(group,NS+'title');title.text='符干与横梁表示拨弦节奏；持续发声见沿弦细线。'
        nodes.append(group)
        if run and (not event['flags'] or not adjacent(run[-1],event)):
            runs.append(run);run=[]
        if event['flags']:run.append(event)
    if run:runs.append(run)
    beams=ET.Element(NS+'g',{'class':'tab-rhythm-beams'})
    for run in runs:
        for level in range(1,max(e['flags'] for e in run)+1):
            spans=[];span=[]
            for event in run:
                if event['flags']>=level:span.append(event)
                elif span:spans.append(span);span=[]
            if span:spans.append(span)
            for span in spans:
                first,last=span[0],span[-1];x1=x_at(first['tick']);x2=x_at(last['tick'])
                kind='beam'
                if len(span)==1:
                    kind='hook';index=run.index(first)
                    if index:
                        direction=-1;distance=x1-x_at(run[index-1]['tick'])
                    elif len(run)>1:
                        direction=1;distance=x_at(run[1]['tick'])-x1
                    else:
                        direction=-1 if first['beat'] and first['tick']%PPQ>=PPQ//2 else 1;distance=48
                    x2=x1+direction*min(16,distance*.35)
                y=BEAM_Y-(level-1)*BEAM_GAP
                ET.SubElement(beams,NS+'line',{'class':'tab-rhythm-'+kind,'data-level':str(level),
                              'x1':str(x1),'x2':str(x2),'y1':str(y),'y2':str(y),
                              'stroke':'#344c60','stroke-width':'3','stroke-linecap':'butt'})
    nodes.append(beams)
    return nodes


# 六线谱同拍节奏连线：新增独立按可见线条高度/端点回读，不信任隐藏横梁层数。
def validate_rhythm(rows,arrangement):
    spec=arrangement.get('rhythm_display',{})
    if spec.get('mode')!='beat_beams':return None
    # 规整分解节奏与延音显示：修改，原按持续值核对保留；按真实模板事件复核可见右手节奏。
    # events=rhythm_events(arrangement['notes'],spec['meter'],spec['bar_ticks'])
    events=arrangement_rhythm_events(arrangement,spec['meter'],spec['bar_ticks'])
    expected={e['tick']:e for e in events};observed={};errors=[];edges=set();covered=set();beams=hooks=dots=0
    for row in rows:
        root=ET.fromstring(row['guitar']);xs={}
        for group in root.iter(NS+'g'):
            if group.get('data-string'):
                tick=int(group.get('data-start-tick'));x=float(group.find(NS+'text').get('x'))
                if tick in xs and abs(xs[tick]-x)>.02:errors.append('simultaneous_notes_have_different_rhythm_positions')
                xs[tick]=x
        for group in root.iter(NS+'g'):
            if group.get('class')!='tab-rhythm-event':continue
            try:
                tick=int(group.get('data-start-tick'));event=expected[tick];stem=group.find(NS+'line')
                if tick in observed:raise ValueError('重复攻击符干。')
                if any(abs(float(stem.get(key))-xs[tick])>.02 for key in ('x1','x2')):raise ValueError('符干没有对齐实际攻击音。')
                if float(stem.get('y1'))!=328 or float(stem.get('y2'))!=BEAM_Y:raise ValueError('节奏符干高度错误。')
                if int(group.get('data-duration-ticks'))!=event['duration'] or group.get('data-type')!=event['type']:
                    raise ValueError('节奏时值与实际起音不符。')
                if group.get('data-note-ids').split()!=event['note_ids']:raise ValueError('同刻多弦符干不一致。')
                dot_nodes=[n for n in group if n.get('class')=='tab-rhythm-dot'];dots+=len(dot_nodes)
                if len(dot_nodes)!=event['dots']:raise ValueError('节奏附点数量错误。')
                observed[tick]=event
            except (KeyError,TypeError,ValueError,AttributeError) as exc:errors.append('visible_rhythm_event_invalid:'+str(exc))
        ordered=sorted(xs)
        for line in root.iter(NS+'line'):
            kind=line.get('class')
            if kind not in ('tab-rhythm-beam','tab-rhythm-hook'):continue
            try:
                x1,x2,y1,y2=[float(line.get(k)) for k in ('x1','x2','y1','y2')]
                level=round((BEAM_Y-y1)/BEAM_GAP)+1
                if abs(y1-y2)>.02 or not 1<=level<=3 or abs(y1-(BEAM_Y-(level-1)*BEAM_GAP))>.02:
                    raise ValueError('节奏横梁必须水平且层高正确。')
                if int(line.get('data-level'))!=level:raise ValueError('标记层数与可见线条高度不符。')
                at=lambda x:next((tick for tick in ordered if abs(xs[tick]-x)<.02),None)
                if kind=='tab-rhythm-hook':
                    tick=at(x1)
                    if tick is None or not .2<abs(x2-x1)<=16.02 or at(x2) is not None:raise ValueError('短横钩起点或长度错误。')
                    items=[tick];hooks+=1
                else:
                    left,right=at(min(x1,x2)),at(max(x1,x2))
                    if left is None or right is None or left>=right:raise ValueError('横梁端点未对齐两个攻击。')
                    items=[tick for tick in ordered if left<=tick<=right];beams+=1
                    for a,b in zip(items,items[1:]):
                        if not adjacent(expected[a],expected[b]):raise ValueError('横梁跨拍、小节或休止间隙。')
                        edges.add((level,a,b))
                for tick in items:
                    if expected[tick]['flags']<level:raise ValueError('横梁数量超出实际音符时值。')
                    if (tick,level) in covered:raise ValueError('同一攻击有重复横梁。')
                    covered.add((tick,level))
            except (KeyError,TypeError,ValueError) as exc:errors.append('visible_rhythm_beam_invalid:'+str(exc))
    expected_edges={(level,a['tick'],b['tick']) for a,b in zip(events,events[1:]) if adjacent(a,b)
                    for level in range(1,min(a['flags'],b['flags'])+1)}
    expected_covered={(e['tick'],level) for e in events for level in range(1,e['flags']+1)}
    if set(observed)!=set(expected):errors.append('visible_rhythm_attack_count_mismatch')
    if edges!=expected_edges:errors.append('same_beat_short_notes_not_connected_correctly')
    if covered!=expected_covered:errors.append('visible_eighth_sixteenth_beam_count_mismatch')
    return {'valid':not errors,'errors':errors,'attack_stems':len(observed),'beam_segments':beams,
            'short_hooks':hooks,'dotted_attacks':dots,'beat_ticks':spec['beat_ticks'],
            'visible_horizontal_geometry_checked':True,'same_beat_and_measure_checked':True}
