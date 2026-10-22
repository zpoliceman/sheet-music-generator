"""参考常见弹唱谱：行内指型图、上方TAB、下方演唱简谱及歌词。只重排源矢量图。"""
from __future__ import annotations
from collections import defaultdict
from copy import deepcopy
import math
import re
from .notation import (NS,node,text_width,bold_width,original_parts,mapping,warp,
    vocal_bounds,tab_y,draw_repeat,row_partition)

LYRIC_SIZE=26
TAB_SIZE=26
NUMERAL_SIZE=28
CHART_SCALE=1.30
CHART_NAME_SIZE=24


def monochrome(root):
    for e in root.iter():
        for name in ('fill','stroke'):
            value=e.get(name)
            if value and value not in ('none','white','#fff','#ffffff'):
                e.set(name,'#111')
    return root


def chart_extents(chart):
    # 起始品数字位于指板左边；名称与实际指板共用中心。
    name=chart['name']
    return max(53.,bold_width(name,CHART_NAME_SIZE)/2+3),max(40.,bold_width(name,CHART_NAME_SIZE)/2+3)


def actual_chart_extents(chart):
    start=next((e.text for e in chart['node'] if e.get('class')=='position-label'),None)
    fret=''.join(re.findall(r'\d+',start or ''))
    left=max(45.,bold_width(chart['name'],CHART_NAME_SIZE)/2+3)
    if fret and fret!='1':left=max(left,46+text_width(fret,18)+2)
    return left,max(45.,bold_width(chart['name'],CHART_NAME_SIZE)/2+3)

def chart_slot(charts,padding=24):
    bottom=0
    for chart in charts:
        for e in chart['node'].iter():
            if e.tag==NS+'text':continue
            for attr in ('y','y1','y2','cy'):
                if e.get(attr) is not None:
                    y=float(e.get(attr))+(float(e.get('height',0)) if attr=='y' else float(e.get('r',0)) if attr=='cy' else 0)
                    bottom=max(bottom,44+(y-70)*.9*CHART_SCALE)
    return max(129.,math.ceil(bottom+padding))

def tab_top_padding(tab):
    above=0.
    for e in tab.iter():
        if e.tag==NS+'text' and float(e.get('y',400))<337:
            y=float(e.get('y'));size=float(e.get('font-size',13));above=max(above,(337-y+size*1.1)*19/18)
        elif e.tag==NS+'circle' and float(e.get('cy',400))<337:
            above=max(above,(337-float(e.get('cy'))+float(e.get('r',0)))*19/18)
    return max(24.,above+5)

def prepare_reference(unit,charts):
    left=unit['left'];centers=unit['centers'];bands=defaultdict(dict)
    def take(x,lo,hi,band):
        at=min(centers,key=lambda a:abs(a-x));old=bands[band].get(at,(0.,0.))
        bands[band][at]=(min(old[0],x+lo-at),max(old[1],x+hi-at))
    def text(text,x,size,anchor,band):
        width=text_width(text,size);lo=-{'start':0,'middle':.5,'end':1}.get(anchor,.5)*width
        take(x,lo-1.8,lo+width+1.8,band)
    for i,layer in enumerate(unit['voices']):
        off=float(layer.get('x'))-float(layer.get('viewBox').split()[0])-left
        for e in layer.iter(NS+'text'):
            y=float(e.get('y',0));size=float(e.get('font-size',20))
            if y>=160 and size==24:e.set('font-size',str(LYRIC_SIZE));size=LYRIC_SIZE
            elif size==28:e.set('font-size',str(NUMERAL_SIZE));size=NUMERAL_SIZE
            if 50<=y<=185:text(e.text or '',float(e.get('x'))+off,size,e.get('text-anchor','middle'),f'voice{i}_'+('lyric' if y>=160 else 'note'))
        for circle in layer.iter(NS+'circle'):
            y=float(circle.get('cy',0))
            if 50<=y<=160:
                x=float(circle.get('cx'))+off;r=float(circle.get('r'))
                take(x,-r-1,r+1,f'voice{i}_note')
        monochrome(layer)
    for e in unit['tab'].iter(NS+'text'):
        if e.get('y')=='489':continue
        size=TAB_SIZE if e.get('font-size')=='18' else float(e.get('font-size',18))
        string=round((float(e.get('y',343))-343)/18)
        text(e.text or '',float(e.get('x'))-left,size,e.get('text-anchor','middle'),f'string{string}')
    for chart in unit['charts']:
        lo,hi=chart_extents(charts[chart['key']]);take(chart['old_x'],35-lo,35+hi,'inline_diagram')
    for vi,variant in enumerate(unit.get('variants',[])):
        for e in variant['tab'].iter(NS+'text'):
            if e.get('y')=='489':continue
            size=TAB_SIZE if e.get('font-size')=='18' else float(e.get('font-size',18))
            string=round((float(e.get('y',343))-343)/18)
            text(e.text or '',float(e.get('x'))+variant['offset'],size,e.get('text-anchor','middle'),f'variant{vi}_string{string}')
        for chart in variant['charts']:
            lo,hi=chart_extents(charts[chart['key']]);take(chart['old_x'],35-lo,35+hi,f'variant{vi}_diagram')
    positions={};last={}
    for i,x in enumerate(centers):
        position=positions[centers[i-1]]+7.5 if i else 19.
        for band,items in bands.items():
            if x not in items:continue
            lo,hi=items[x];previous=last.get(band)
            if previous is None:position=max(position,7-lo)
            else:
                old,old_hi=previous;position=max(position,positions[old]+old_hi-lo+3)
        positions[x]=position
        for band,items in bands.items():
            if x in items:last[band]=(x,items[x][1])
    width=max(115.,max(positions[x]+max([8.]+[v[x][1] for v in bands.values() if x in v]) for x in centers)+10)
    # 用实际可见起始品和弦状态补足相邻图的少量避让；宽度已充足的小节保持。
    for diagram_set in [unit['charts'],*[v['charts'] for v in unit.get('variants',[])]]:
        values=sorted(diagram_set,key=lambda c:c['old_x'])
        for a,b in zip(values,values[1:]):
            xa=min(centers,key=lambda x:abs(x-a['old_x']));xb=min(centers,key=lambda x:abs(x-b['old_x']))
            needed=actual_chart_extents(charts[a['key']])[1]+actual_chart_extents(charts[b['key']])[0]+3
            delta=needed-(positions[xb]-positions[xa])
            if delta>0:
                for x in centers:
                    if x>=xb:positions[x]+=delta
                width+=delta
    unit.update(positions=positions,width=width,bands=dict(bands))


def diagram_anchor(unit,instance,targets):
    # 预留宽度和绘图必须使用同一音符时间列；避让后的图心可能靠近小节线。
    x=instance['old_x'];at=min(unit['centers'],key=lambda center:abs(center-x))
    return targets[at]+x-at+35


def inline_chart(chart,instance,x,y):
    root=node('g',transform=f'translate({x:g},{y:g})',data_inline_chart='true',data_chart_key=instance['key'],data_chord_name=chart['name'],data_start_tick=instance['node'].get('data-start-tick'),data_plan_id=instance['node'].get('data-plan-id'))
    root.append(node('text',chart['name'],x=0,y=20,font_size=CHART_NAME_SIZE,font_weight='bold',font_family='Arial, Microsoft YaHei, sans-serif',text_anchor='middle',fill='#111',data_chord_label='true'))
    copied=deepcopy(instance['node']);start=None
    for e in list(copied):
        if e.tag==NS+'text' and e.get('class') not in ('string-status',):
            if e.get('class')=='position-label':start=e.text
            copied.remove(e)
    center=float(instance['node'].find(NS+'text').get('x'))
    copied=warp(copied,lambda value:value-center,lambda value:(value-70)*.9)
    copied.set('transform',f'translate(0,44) scale({CHART_SCALE:g})')
    root.append(monochrome(copied))
    if start and ''.join(re.findall(r'\d+',start))!='1':
        value=''.join(re.findall(r'\d+',start))
        root.append(node('text',value,x=-46,y=58,font_size=18,font_family='Arial',text_anchor='end',fill='#111',data_start_fret='true'))
    return root


def styled_tab(original,xmap,top):
    tab=deepcopy(original);tab.attrib.pop('transform',None)
    for e in list(tab):
        if e.tag==NS+'text' and e.get('y')=='489':tab.remove(e)
    # 传统弹唱六线谱的节奏竖线从本次拨弦的最低音头接出。
    for stem in tab.iter(NS+'line'):
        if stem.get('data-rhythm-tick') is None:continue
        x=float(stem.get('x1'));heads=[]
        for note in tab.iter(NS+'g'):
            if not note.get('data-note-id') or note.get('data-continuation')=='true':continue
            t=note.find(NS+'text')
            if t is not None and abs(float(t.get('x'))-x)<.01:heads.append(float(t.get('y'))-6)
        if heads:stem.set('y1',str(max(heads)+7.5))
    tab=warp(tab,xmap,tab_y,tab=True)
    for note in tab.iter(NS+'g'):
        if not note.get('data-note-id'):continue
        t=note.find(NS+'text')
        if t is None:continue
        t.set('y',str(float(t.get('y'))-6*19/18));t.set('dominant-baseline','central')
    for line in tab.iter(NS+'line'):
        if line.get('class')=='tab-string-line':line.set('stroke-width','1.35')
    for e in tab.iter(NS+'text'):
        if e.get('font-size')=='24':e.set('font-size',str(TAB_SIZE))
        if e.text=='x':e.set('font-family','Arial');e.text='×';e.set('font-size',str(TAB_SIZE+1))
    for e in tab.iter(NS+'rect'):
        if e.get('fill')=='white':
            # 临时品数留白略宽于字形；不遮相邻拍的符号。
            w=float(e.get('width'));e.set('x',str(float(e.get('x'))-1));e.set('width',str(w+2))
    tab.set('transform',f'translate(0,{top:g})');return monochrome(tab)


def make_reference_row(row_units,charts,native_width):
    # TAB字母占一小列，时间列和小节边界随后共同排布。
    prefix=36.;available=native_width-prefix;total=sum(u['width'] for u in row_units)
    widths=[u['width']+(available-total)*u['width']/total for u in row_units]
    layers=[v for u in row_units for v in u['voices']]
    vmin,vmax=vocal_bounds(layers);vheight=vmax-vmin
    passes=max(len(u['voices']) for u in row_units)
    has_charts=any(u['charts'] for u in row_units)
    top_mark=30 if any(m['kind'] in ('segno','coda','volta_1','volta_2') for u in row_units for m in [*u['markers'],*u.get('volta_spans',[])]) else 0
    other_cues=[e for u in row_units for e in u['extras'] if e.get('data-pass-label') is None and e.get('data-unpitched-lyric') is None and e.get('data-pitch-motion') is None]
    chart_top=24+top_mark+(30 if other_cues else 0)
    slot=chart_slot([charts[c['key']] for u in row_units for c in u['charts']],max(tab_top_padding(u['tab']) for u in row_units))
    tab_top=chart_top+(slot if has_charts else 19)
    voice_top=tab_top+139
    extra_tail=31 if any(e.get('data-unpitched-lyric') is not None or e.get('data-pitch-motion') is not None for u in row_units for e in u['extras']) else 0
    route_tail=29 if any(m['kind'] in ('ds','to_coda','fine') for u in row_units for m in u['markers']) else 0
    voice_bottom=voice_top+passes*(vheight+6)
    variant_count=max(len(u.get('variants',[])) for u in row_units)
    variant_slot=max([300.]+[chart_slot([charts[c['key']] for c in v['charts']],tab_top_padding(v['tab']))+171 for u in row_units for v in u.get('variants',[])])
    height=voice_bottom+extra_tail+route_tail+5+variant_count*variant_slot
    root=node('svg',viewBox=f'0 0 {native_width:g} {height:g}',width=native_width,height=height,data_layout='inline-tab-vocal')
    left=prefix;semantic=[]
    for index,(unit,width) in enumerate(zip(row_units,widths)):
        mx,targets=mapping(unit,width)
        group=node('g',transform=f'translate({left:g},0)',data_print_measure=unit['number'],data_bar_width=width)
        label='弱起' if unit['pickup'] else str(unit['display_number'])
        if len(unit['voices'])>1:
            label+=' / '+','.join(str(o['first']+unit['number']-unit['block']['canonical_first']-unit['pickup_offset']) for o in unit['block']['occurrences'][1:])
        group.append(node('text',label,x=3,y=16,font_size=16,fill='#333',data_measure_label='true'))
        for chart in unit['charts']:
            group.append(inline_chart(charts[chart['key']],chart,diagram_anchor(unit,chart,targets),chart_top))
        group.append(styled_tab(unit['tab'],lambda x:mx(x-unit['left']),tab_top))
        if unit['show_meter']:
            num,den=unit['meter']
            meter=node('g',transform=f'translate(4,{tab_top-57:g})',data_meter_change='true',data_meter=f'{num}/{den}')
            meter.append(node('text',num,x=0,y=20,font_size=24,text_anchor='middle',fill='#111'))
            meter.append(node('text',den,x=0,y=45,font_size=24,text_anchor='middle',fill='#111'))
            meter.append(node('line',x1=-10,y1=25,x2=10,y2=25,stroke='#111'))
            group.append(meter)
        for p,layer in enumerate(unit['voices']):
            off=float(layer.get('x'))-float(layer.get('viewBox').split()[0])-unit['left']
            copied=warp(layer,lambda x:mx(x+off));copied.set('x','0');copied.set('y',f'{voice_top+p*(vheight+6):g}')
            copied.set('viewBox',f'0 {vmin:g} {width:g} {vheight:g}')
            copied.set('width',f'{width:g}');copied.set('height',f'{vheight:g}')
            copied.set('style',f'width:{width:g}px;height:{vheight:g}px;overflow:visible')
            group.append(copied)
            if len(unit['voices'])>1 and (index==0 or len(row_units[index-1]['voices'])!=len(unit['voices'])):group.append(node('text',f'{p+1}.',x=-16 if index==0 else 0,y=voice_top+p*(vheight+6)+20,font_size=16,fill='#111',data_pass_label=p+1))
        for e in unit['extras']:
            if e.get('data-unpitched-lyric') is not None or e.get('data-pitch-motion') is not None:
                copied=deepcopy(e);copied.set('x',f'{mx(float(e.get("x"))-unit["left"]):g}');copied.set('y',f'{voice_bottom+22:g}');copied.set('font-size','21');group.append(monochrome(copied))
        for e in unit['extras']:
            if e.get('data-pass-label') is None and e.get('data-unpitched-lyric') is None and e.get('data-pitch-motion') is None:
                copied=deepcopy(e);copied.set('x',f'{mx(float(e.get("x"))-unit["left"]):g}');copied.set('y',f'{chart_top-5:g}');copied.set('font-size','20');group.append(monochrome(copied))
        for vi,variant in enumerate(unit.get('variants',[])):
            top=voice_bottom+extra_tail+route_tail+12+vi*variant_slot
            group.append(node('text',f"第{variant['pass']}遍用下方奏法（第{variant['source_measure']-unit['pickup_offset']}小节）",x=width/2,y=top+18,font_size=17,text_anchor='middle',fill='#111',data_variant_caption=variant['source_measure']))
            alt_group=node('g',data_variant_source_measure=variant['source_measure'],data_variant_canonical_measure=unit['number'],data_variant_pass=variant['pass'])
            for chart in variant['charts']:alt_group.append(inline_chart(charts[chart['key']],chart,diagram_anchor(unit,chart,targets),top+25))
            alt_group.append(styled_tab(variant['tab'],lambda x:mx(x+variant['offset']),top+25+chart_slot([charts[c['key']] for c in variant['charts']],tab_top_padding(variant['tab']))))
            group.append(alt_group)
        for mark in unit['markers']:
            kind=mark['kind']
            group.append(node('g',data_print_marker=kind,data_at_measure=unit['number'],data_first=mark['first'],data_last=mark['last'],data_target=mark.get('target') or ''))
            if kind in ('segno','coda'):
                draw_repeat(group,kind,4,21,mark['text']);group.append(node('text',mark['text'],x=32,y=38,font_size=21,fill='#111'))
            elif kind in ('ds','to_coda','fine'):
                draw_repeat(group,kind,width-2,voice_bottom+extra_tail+2,mark['text'],True)
            elif kind in ('repeat_start','repeat_end'):
                x=2 if kind=='repeat_start' else width-2
                for dx,sw in ((0,2.4),(6 if kind=='repeat_start' else -6,1.1)):
                    group.append(node('line',x1=x+dx,y1=tab_top,x2=x+dx,y2=tab_top+95,stroke='#111',stroke_width=sw))
                for yy in (36,59):group.append(node('circle',cx=x+(12 if kind=='repeat_start' else -12),cy=tab_top+yy,r=2,fill='#111'))
        root.append(group);left+=width
        semantic.append({'number':unit['number'],'allocated_width':width,'source_width':unit['width'],'anchor_positions':[[x,targets[x]] for x in unit['centers']],'diagram_count':len(unit['charts'])})
    for y in (0,19,38,57,76,95):root.append(node('line',x1=0,y1=tab_top+y,x2=prefix,y2=tab_top+y,stroke='#111',stroke_width=1.05))
    for char,y in zip('TAB',(24,51,78)):root.append(node('text',char,x=17,y=tab_top+y,font_size=21,font_family='Georgia',text_anchor='middle',fill='#111'))
    # 一二房子横跨实际结束段，跨谱行时延续；普通反复保留原位置。
    spans={(m['kind'],m['first'],m['last']) for u in row_units for m in u.get('volta_spans',[])}
    for kind,first,last in sorted(spans):
        selected=[i for i,u in enumerate(row_units) if first<=u['number']<=last]
        if not selected:continue
        start=prefix+sum(widths[:selected[0]])+3;end=prefix+sum(widths[:selected[-1]+1])-3
        bracket=node('g',data_volta_kind=kind,data_first=first,data_last=last)
        bracket.append(node('line',x1=start,y1=28,x2=end,y2=28,stroke='#111',stroke_width=1.5))
        if row_units[selected[0]]['number']==first:bracket.append(node('line',x1=start,y1=28,x2=start,y2=43,stroke='#111',stroke_width=1.5))
        if row_units[selected[-1]]['number']==last:bracket.append(node('line',x1=end,y1=28,x2=end,y2=43,stroke='#111',stroke_width=1.5))
        bracket.append(node('text',kind.rsplit('_',1)[-1]+'.',x=start+6,y=49,font_size=21,fill='#111'))
        root.append(bracket)
    root.append(node('line',x1=0,y1=tab_top,x2=0,y2=voice_bottom-6,stroke='#111',stroke_width=1.15))
    return root,height,semantic

def reference_partition(units,row_count):
    # 参考谱中密集行采用三小节；其余优先四至五小节。
    dp={(0,0):(0.,0.,[])}
    for count in range(1,row_count+1):
        for end in range(1,len(units)+1):
            best=None
            for length in ((1,2,3,4,5) if len(units)<6 or row_count>math.ceil(len(units)/3) else (3,4,5)):
                begin=end-length;previous=dp.get((count-1,begin))
                if previous is None:continue
                width=sum(u['width'] for u in units[begin:end])
                crossings=sum(units[k]['block'].get('repeat_group')!=units[k-1]['block'].get('repeat_group') for k in range(begin+1,end))
                candidate=(max(previous[0],width),previous[1]+width*width+crossings*10000+(5000 if length==3 else 0),previous[2]+[(begin,end)])
                if best is None or candidate[:2]<best[:2]:best=candidate
            if best:dp[count,end]=best
    return dp.get((row_count,len(units)))
