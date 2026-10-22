"""和弦指型与X六线谱：实际弦品指型、黑点网格及独立几何解码。"""
# 和弦指型与X六线谱：新增离线SVG图式，参考SVGuitar的position/black fingers/barres约定。
from __future__ import annotations
from collections import Counter
from functools import lru_cache
from itertools import product
import math
import re
import xml.etree.ElementTree as ET
from accompaniment_arrange import TUNING,grip_info
from accompaniment_analysis import CHORD_TYPES,chord_name,pc_name
from score_export import key_definition

NS='http://www.w3.org/2000/svg'
PREFIX='{'+NS+'}'
TOP_SPACE=158


# 和弦指型与X六线谱：新增实际手位内搜索，已发声音符优先锚定，允许省略普通五度。
@lru_cache(maxsize=512)
def candidates(root,quality,bass,capo,position,anchors):
    allowed={(root+i)%12 for i in CHORD_TYPES[quality]}|{bass}
    required={(root+i)%12 for i in CHORD_TYPES[quality] if i!=7}|{bass}
    anchor_map=dict(anchors);options=[]
    for string in range(6,0,-1):
        values=[-1]
        if (TUNING[string]+capo)%12 in allowed:values.append(0)
        values.extend(f for f in range(position,min(position+5,20)+1) if (TUNING[string]+capo+f)%12 in allowed)
        if string in anchor_map:
            values=[anchor_map[string]] if anchor_map[string] in values else []
        options.append(values)
    result=[]
    for values in product(*options):
        frets={s:f for s,f in zip(range(6,0,-1),values) if f>=0}
        pitches=[TUNING[s]+capo+f for s,f in frets.items()]
        if not pitches or not required.issubset({p%12 for p in pitches}) or min(pitches)%12!=bass:continue
        grip=grip_info(frets)
        if grip is not None:result.append((frets,grip))
    return tuple(result)


# 和弦指型与X六线谱：新增临时数字音覆盖同弦基础按法后仍须单手可覆盖。
def fits(frets,active,position):
    effective={int(s):f for s,f in frets.items() if f>=0}
    effective.update({n['string']:n['fret'] for n in active})
    positive=[f for f in effective.values() if f>0]
    return grip_info(effective) is not None and all(position<=f<=position+5 for f in positive)


# 和弦指型与X六线谱：新增按实际上下文择图，非和弦旋律保留数字，不强制塞入和弦图。
def choose_diagram(chord,active,future,capo,position):
    position=max(1,int(position))
    allowed=set(chord['pitch_classes'])|{chord['bass_pc']}
    anchors=tuple(sorted((n['string'],n['fret']) for n in active if n['pitch_midi']%12 in allowed))
    weights=Counter()
    for note in future:
        weights[(note['string'],note['fret'])]+=1.6 if note['role']=='bass' else 1.
    best=None
    for constrained in (anchors,()):
        for frets,grip in candidates(chord['root_pc'],chord['quality'],chord['bass_pc'],capo,position,constrained):
            if not fits(frets,active,position):continue
            covered=sum(weight for (s,f),weight in weights.items() if frets.get(s)==f and f>0)
            now=sum(frets.get(n['string'])==n['fret'] and n['fret']>0 for n in active)
            cost=-covered-24*now+.08*sum(frets.values())+.15*grip['finger_count']+.025*len(frets)
            if best is None or cost<best[0]:best=(cost,frets,grip)
        if best is not None:break
    simplified=False
    if best is None:
        # 和弦指型与X六线谱：新增单人受限时的部分指型，保留真实按弦，数字承担其它音。
        frets={n['string']:n['fret'] for n in active if n['pitch_midi']%12 in allowed}
        grip=grip_info(frets)
        if grip is None or not fits(frets,active,position):raise ValueError('指型与实际持续音不可同时覆盖。')
        simplified=True
    else:_,frets,grip=best
    positive=[f for f in frets.values() if f>0]
    first=min(positive) if positive else 1
    # 和弦指型与X六线谱：新增低把位保持完整上弦枕，高把位第一行明确起始品。
    if first<=3 and max(positive,default=0)<=4:first=1
    from accompaniment_arrange import capo_shape_key
    key=capo_shape_key(chord['key'],capo)
    return {'frets':{str(s):int(f) for s,f in frets.items()},'position':first,
            'shape_name':chord_name(chord['root_pc']-capo,chord['quality'],chord['bass_pc']-capo,key),
            'sounding_name':chord['name'],'capo':capo,'barre':grip['barre'],'finger_count':grip['finger_count'],
            'simplified':simplified,'source':'actual_string_fret_context'}


# 常用指型与器乐独奏：修改，原强制为每个和弦搜索实际指型的过程保留为注释。
# def prepare_diagrams(shared,arrangement):
#     notes=arrangement['notes'];capo=arrangement['configuration']['capo_fret'];plan=[]
#     path=arrangement.get('hand_positions',[])
#     def position(tick,active):
#         known=next((p['position'] for p in reversed(path) if p['tick']<=tick),None)
#         return max(1,known if known is not None else min((n['fret'] for n in active if n['fret']>0),default=1))
#     for chord in shared['harmony']:
#         if chord['name']=='N.C.':continue
#         start,end=chord['start_tick'],chord['end_tick']
#         future=[n for n in notes if start<=n['start_tick']<end]
#         ticks=sorted({start,*[n['start_tick'] for n in future]})
#         current=None
#         for tick in ticks:
#             active=[n for n in notes if n['start_tick']<=tick<n['end_tick']]
#             probe=tick
#             if not active and tick==start and future:
#                 probe=min(n['start_tick'] for n in future)
#                 active=[n for n in notes if n['start_tick']<=probe<n['end_tick']]
#             pos=position(probe,active)
#             if current is None or not fits(current['frets'],active,pos):
#                 chart=choose_diagram(chord,active,[n for n in future if n['start_tick']>=probe],capo,pos)
#                 if current is not None:current['end_tick']=tick
#                 chart.update({'id':f"grip_{len(plan)+1:04}",'chord_id':chord['id'],'start_tick':tick,'end_tick':end,
#                               'reason':'chord_change' if tick==start else 'actual_position_change'})
#                 plan.append(chart);current=chart
#     arrangement['fingering_diagrams']=plan
#     set_tab_display(arrangement)
#     return plan


# 常用指型与器乐独奏：新增常用优先及器乐独奏分区，完整导出时同步核查持握后的换把时序。
def prepare_diagrams(shared,arrangement,vocal=None):
    from guitar_grip_policy import prepare_common_diagrams
    plan=prepare_common_diagrams(shared,arrangement,vocal)
    set_tab_display(arrangement)
    return plan


# 空弦沿用指型X表示：新增显示约定，数字只表示相对于图的临时左手调整。
def set_tab_display(arrangement):
    arrangement['tab_display']={'mode':'chord_grip_x','display_rule':'unchanged_left_hand',
                                'positive_same_string_and_fret':'x','open_string':'x_when_unfretted_else_0',
                                'other_notes':'numeric_fret','fret_origin':'capo_is_zero',
                                # 结构稳定伴奏与人声合播：修改，原代码注释保留。
                                # 'rows_measures':2,'diagram_model':'actual_string_fret_context',
                                'rows_measures':int(arrangement['configuration'].get('rows_measures',4)),
                                'diagram_model':'actual_string_fret_context',
                                'barre_covered_strings_are_pressed':True,
                                'numeric_musicxml_and_midi_preserved':True}
    # 规整分解节奏与延音显示：新增图式必须对应实际起音或需要保持的按指，不为空弦延响重复图。
    arrangement['tab_display']['diagram_placement']='actual_attack_or_fretted_sustain'
    arrangement['tab_display']['cross_bar_sustain']='parenthesized_fret_and_hold_line_no_new_attack'
    # 常用指型与器乐独奏：新增混合显示约定，没有和弦图的区间一律写数字，0代表空弦。
    if arrangement['configuration'].get('grip_policy',{}).get('name')=='common_open_and_instrumental_solo':
        arrangement['tab_display'].update({'diagram_model':'sourced_common_grip_or_actual_vocal_context',
                                          'without_diagram':'numeric_frets_including_open_zero',
                                          'instrumental_rows':'tab_only_when_vocal_absent'})


# 空弦沿用指型X表示：新增每根弦的实际基础按位，通常不拨的弦也受横按覆盖。
def left_hand_fret(chart,string):
    frets=chart['frets'];fret=max(0,frets.get(str(string),frets.get(string,-1)))
    barre=chart.get('barre')
    if barre and min(barre[0],barre[1])<=string<=max(barre[0],barre[1]):fret=max(fret,barre[2])
    return fret


# 和弦指型与X六线谱：新增每处和弦/行首及必要换把重复图，绑定明确时间区间。
# 规整分解节奏与延音显示：修改，原行首一律重标算法注释保留，供旧工程核验参考。
# def visible_diagrams(shared,arrangement,first,last):
#     bar=shared['statistics']['bar_ticks'];begin=(first-1)*bar;end=last*bar
#     points={d['start_tick'] for d in arrangement['fingering_diagrams'] if begin<=d['start_tick']<end}
#     points.update((m-1)*bar for m in range(first,last+1))
#     result=[]
#     for tick in sorted(points):
#         diagram=next((d for d in arrangement['fingering_diagrams'] if d['start_tick']<=tick<d['end_tick']),None)
#         if diagram is None:continue
#         result.append({**diagram,'draw_tick':tick,'display_id':f'diagram_{first}_{tick}'})
#     for index,item in enumerate(result):
#         item['display_end_tick']=min(item['end_tick'],result[index+1]['draw_tick'] if index+1<len(result) else end)
#     return result

# 规整分解节奏与延音显示：新增按实际拨弦定位图式，只有带品数的持续按指可提前重标。
def visible_diagrams(shared,arrangement,first,last):
    bar=shared['statistics']['bar_ticks'];begin=(first-1)*bar;end=last*bar
    points={d['start_tick'] for d in arrangement['fingering_diagrams'] if begin<=d['start_tick']<end}
    points.update((m-1)*bar for m in range(first,last+1))
    result=[]
    for tick in sorted(points):
        diagram=next((d for d in arrangement['fingering_diagrams'] if d['start_tick']<=tick<d['end_tick']),None)
        if diagram is None:continue
        # 规整分解节奏与延音显示：新增限定本指型本小节的用途，后半小节才拨弦则图也移到起音。
        if arrangement.get('tab_display',{}).get('diagram_placement')=='actual_attack_or_fretted_sustain':
            finish=min(diagram['end_tick'],(tick//bar+1)*bar,end)
            attacks=[n['start_tick'] for n in arrangement['notes'] if tick<=n['start_tick']<finish]
            pressed=any(n['fret']>0 and n['start_tick']<tick<n['end_tick'] for n in arrangement['notes'])
            if not attacks and not pressed:continue
            if not pressed:tick=min(attacks)
        result.append({**diagram,'draw_tick':tick,'display_id':f'diagram_{first}_{tick}'})
    # 结构稳定伴奏与人声合播：修改，原代码注释保留。
    # for index,item in enumerate(result):
        # item['display_end_tick']=min(item['end_tick'],result[index+1]['draw_tick'] if index+1<len(result) else end)
    # return result
    if arrangement['configuration'].get('structure_policy'):
        stable=[]
        for item in result:
            signature=(item['shape_name'],item['capo'],tuple(sorted(item['frets'].items())))
            before=stable[-1] if stable else None
            old_signature=(before['shape_name'],before['capo'],tuple(sorted(before['frets'].items()))) if before else None
            if before and signature==old_signature and before['draw_tick']//bar==item['draw_tick']//bar and before['end_tick']>=item['draw_tick']:
                before['end_tick']=max(before['end_tick'],item['end_tick']);before.setdefault('source_harmony_ids',[before['chord_id']]).append(item['chord_id'])
            else:stable.append(item)
        result=stable
    for index,item in enumerate(result):
        item['display_end_tick']=min(item['end_tick'],result[index+1]['draw_tick'] if index+1<len(result) else end)
    return result


# 和弦指型与X六线谱：新增实心黑点/横按图，无指号数字；品位标在第一行。
def draw_diagram(chart,center):
    group=ET.Element(PREFIX+'g',id=chart['display_id'],attrib={'class':'chord-diagram',
          'data-start-tick':str(chart['draw_tick']),'data-end-tick':str(chart['display_end_tick']),
          'data-plan-id':chart['id'],'data-chord-id':chart['chord_id']})
    def node(name,**attrs):return ET.SubElement(group,PREFIX+name,{key.replace('_','-'):str(value) for key,value in attrs.items()})
    title=node('text',x=center,y=40,fill='#111',font_family='Microsoft YaHei, sans-serif',
               font_size=12 if len(chart['shape_name'])>8 else 15,text_anchor='middle',font_weight='bold')
    title.text=chart['shape_name']+('（简）' if chart['simplified'] else '')
    left,top,dx,dy=center-27.5,70.,11.,13.
    frets={int(s):f for s,f in chart['frets'].items()};position=chart['position']
    rows=max(4,max(frets.values(),default=0)-position+1)
    label=node('text',x=left-7,y=top+8,fill='#111',font_family='Microsoft YaHei, sans-serif',
               font_size=10,text_anchor='end',class_='position-label')
    label.set('class','position-label');label.attrib.pop('class-',None);label.text=str(position)+'品'
    for i in range(6):
        line=node('line',x1=left+i*dx,y1=top,x2=left+i*dx,y2=top+rows*dy,stroke='#111',stroke_width=.9)
        line.set('class','string-line')
    for i in range(rows+1):
        line=node('line',x1=left,y1=top+i*dy,x2=left+5*dx,y2=top+i*dy,stroke='#111',
                  stroke_width=2.3 if i==0 and position==1 else .9)
        line.set('class','fret-line')
    for string in range(6,0,-1):
        x=left+(6-string)*dx;fret=frets.get(string,-1)
        if fret<=0:
            status=node('text',x=x,y=top-9,fill='#111',font_family='Microsoft YaHei, sans-serif',font_size=11,text_anchor='middle')
            status.set('class','string-status');status.text='○' if fret==0 else '×'
        else:
            circle=node('circle',cx=x,cy=top+(fret-position+.5)*dy,r=3.5,fill='#000')
            circle.set('class','pressed-string')
    if chart.get('barre'):
        a,b,fret=chart['barre'];y=top+(fret-position+.5)*dy
        line=node('line',x1=left+(6-a)*dx,y1=y,x2=left+(6-b)*dx,y2=y,stroke='#000',stroke_width=6,stroke_linecap='round')
        line.set('class','barre')
    description=ET.SubElement(group,PREFIX+'title')
    description.text=f"{chart['shape_name']}，相对变调夹第{position}品起，实际和弦{chart['sounding_name']}"
    return group


# 和弦指型与X六线谱：新增独立读取可见网格、品数和黑点坐标，不使用隐藏弦品答案。
def read_diagram(group):
    lines=[n for n in group if n.tag==PREFIX+'line']
    xs=sorted({float(n.get('x1')) for n in lines if n.get('class')=='string-line'})
    ys=sorted({float(n.get('y1')) for n in lines if n.get('class')=='fret-line'})
    if len(xs)!=6 or len(ys)<5:raise ValueError('指型图必须有六弦及至少四品格。')
    label=next(n for n in group if n.get('class')=='position-label')
    match=re.fullmatch(r'(\d+)品',label.text or '')
    if not match or int(match[1])<1:raise ValueError('第一行起始品数无效。')
    position=int(match[1]);dy=ys[1]-ys[0];frets={}
    def string_at(x):
        index=min(range(6),key=lambda i:abs(xs[i]-x))
        if abs(xs[index]-x)>.02:raise ValueError('按弦点不在弦线上。')
        return 6-index
    for node in group:
        if node.get('class')=='string-status':
            # 和弦指型与X六线谱：修改，原任意非空弦符号视为禁用弦保留；严格核对可见约定。
            # string=string_at(float(node.get('x')));frets[string]=0 if node.text=='○' else -1
            string=string_at(float(node.get('x')))
            if node.text not in ('○','×') or string in frets:raise ValueError('空弦/禁用弦标记无效或重复。')
            frets[string]=0 if node.text=='○' else -1
        elif node.get('class')=='pressed-string':
            string=string_at(float(node.get('cx')));y=float(node.get('cy'))
            index=round((y-ys[0])/dy-.5)
            if index<0 or index>=len(ys)-1 or abs(y-(ys[0]+(index+.5)*dy))>.02:raise ValueError('黑点不在品格中。')
            if string in frets:raise ValueError('同弦重复按弦或空弦与按弦冲突。')
            frets[string]=position+index
    if len(frets)!=6:raise ValueError('指型图缺少弦状态。')
    if grip_info({s:f for s,f in frets.items() if f>=0}) is None:raise ValueError('指型图按法超出单手跨度/指数。')
    # 空弦沿用指型X表示：新增独立读取可见横按端点及品格，不能把跨过的弦当未按。
    barres=[n for n in lines if n.get('class')=='barre'];barre=None
    if len(barres)>1:raise ValueError('当前图出现多个不支持的横按。')
    if barres:
        line=barres[0];a=string_at(float(line.get('x1')));b=string_at(float(line.get('x2')))
        y=float(line.get('y1'));index=round((y-ys[0])/dy-.5)
        if abs(y-float(line.get('y2')))>.02 or index<0 or index>=len(ys)-1 or abs(y-(ys[0]+(index+.5)*dy))>.02:
            raise ValueError('横按不在同一品格中。')
        barre=[min(a,b),max(a,b),position+index]
        for string in range(barre[0],barre[1]+1):
            if 0<=frets[string]<barre[2]:raise ValueError('可见横按与空弦/较低按弦冲突。')
    # 空弦沿用指型X表示：修改，原仅含黑点的回读结果保留；增加真实横按。
    # return {'frets':frets,'position':position,'start_tick':int(group.get('data-start-tick')),
    #         'end_tick':int(group.get('data-end-tick')),'plan_id':group.get('data-plan-id')}
    return {'frets':frets,'barre':barre,'position':position,'start_tick':int(group.get('data-start-tick')),
            'end_tick':int(group.get('data-end-tick')),'plan_id':group.get('data-plan-id')}
