"""紧凑吉他印刷排版：按原矢量图的共同时间列重新留白，原音乐只读。"""
from __future__ import annotations
from bisect import bisect_left
from collections import Counter, defaultdict
from copy import deepcopy
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path
import re
import xml.etree.ElementTree as ET
from PIL import ImageFont

NS = '{http://www.w3.org/2000/svg}'
ET.register_namespace('', NS[1:-1])
FONT = 'C:/Windows/Fonts/msyh.ttc'


def node(kind, text=None, **attrs):
    result=ET.Element(NS+kind,{k.replace('_','-'):str(v) for k,v in attrs.items()})
    if text is not None:result.text=str(text)
    return result


@lru_cache(maxsize=128)
def font(size):
    return ImageFont.truetype(FONT, max(1,round(size)))


def text_width(text, size):
    return float(font(float(size)).getlength(text or ''))


@lru_cache(maxsize=128)
def bold_font(size):
    return ImageFont.truetype('C:/Windows/Fonts/msyhbd.ttc',max(1,round(size)))


def bold_width(text,size):
    return float(bold_font(float(size)).getlength(text or ''))


def translate_path(d,mx,my):
    tokens=re.findall(r'[A-Za-z]|[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?',d)
    out=[];i=0;command=None;current=(0.,0.)
    arity={'M':2,'L':2,'Q':4,'C':6,'S':4,'T':2,'H':1,'V':1,'Z':0}
    while i<len(tokens):
        if tokens[i].isalpha():
            command=tokens[i];i+=1
            if command=='Z':out.append(command);continue
        if command not in arity:raise ValueError('不支持的矢量路径：'+str(command))
        n=arity[command];old=list(map(float,tokens[i:i+n]));i+=n
        if command=='H':values=[mx(old[0])];current=(old[0],current[1])
        elif command=='V':values=[my(old[0])];current=(current[0],old[0])
        else:
            end=(old[-2],old[-1]);values=[]
            for j in range(0,n,2):
                x,y=old[j],old[j+1]
                if j<n-2 and command in ('Q','C','S') and end[0]!=current[0]:
                    proportion=(x-current[0])/(end[0]-current[0])
                    xx=mx(current[0])+(mx(end[0])-mx(current[0]))*proportion
                else:xx=mx(x)
                if command=='Q' and j==0:
                    baseline=(current[1]+end[1])/2
                    limit=max(5.,abs(mx(end[0])-mx(current[0]))*.42)
                    y=baseline+max(-limit,min(limit,y-baseline))
                values.extend([xx,my(y)])
            current=end
        out.append(command+' '.join(f'{v:g}' for v in values))
        if command=='M':command='L'
    return ' '.join(out)


def warp(element,mx,my=lambda y:y,tab=False):
    result=deepcopy(element)
    for parent in list(result.iter()):
        for child in list(parent):
            if child.tag==NS+'rect' and not child.get('stroke') and (('%' in child.get('width','') or '%' in child.get('height','')) or (child.get('fill') in ('white','#fff','#ffffff') and float(child.get('height',0))>40)):
                parent.remove(child)
    parents={child:parent for parent in result.iter() for child in parent}
    for e in result.iter():
        kind=e.tag.split('}')[-1]
        if kind=='text':
            if tab and e.get('font-size')=='18':e.set('font-size','24');e.set('font-family','Arial');e.set('fill','#111')
            for attr,fn in (('x',mx),('y',my)):
                if e.get(attr) is not None:e.set(attr,f'{fn(float(e.get(attr))):g}')
        elif kind=='line':
            for attr,fn in (('x1',mx),('x2',mx),('y1',my),('y2',my)):
                e.set(attr,f'{fn(float(e.get(attr))):g}')
        elif kind in ('circle','ellipse'):
            e.set('cx',f"{mx(float(e.get('cx'))):g}");e.set('cy',f"{my(float(e.get('cy'))):g}")
        elif kind=='rect':
            x=float(e.get('x',0));y=float(e.get('y',0));w=float(e.get('width',0));h=float(e.get('height',0))
            small=e.get('fill')=='white' and w<=40
            if small and tab:
                parent_text=parents[e].find(NS+'text')
                w=max(16.,text_width(parent_text.text,24)+3) if parent_text is not None else 18.
                h=19
            if small:
                e.set('x',f'{mx(x+float(e.get("width",0))/2)-w/2:g}')
                e.set('y',f'{my(y+float(e.get("height",0))/2)-h/2:g}')
            else:
                x2=mx(x+w);y2=my(y+h);e.set('x',f'{mx(x):g}');e.set('y',f'{my(y):g}');w=x2-mx(x);h=y2-my(y)
            e.set('width',f'{w:g}');e.set('height',f'{h:g}')
        elif kind=='path':e.set('d',translate_path(e.get('d',''),mx,my))
        elif kind in ('polygon','polyline'):
            values=list(map(float,re.findall(r'[-+]?[\d.]+',e.get('points',''))))
            e.set('points',' '.join(f'{mx(x):g},{my(y):g}' for x,y in zip(values[::2],values[1::2])))
    return result


def chart_key(chart):
    center=float(chart.find(NS+'text').get('x'))
    normalized=warp(chart,lambda x:x-center)
    for e in normalized.iter():
        for key in list(e.attrib):
            if key.startswith('data-') or key=='id':del e.attrib[key]
    return hashlib.sha256(ET.tostring(normalized)).hexdigest()


def original_parts(source):
    plan=json.loads((source/'guitar/repeat_plan.json').read_text(encoding='utf-8'))
    units=[];charts={};markers=[];source_hashes={}
    for index,block in enumerate(plan['blocks'],1):
        path=source/'guitar/rows'/f'repeat_{index:03}.svg'
        raw=path.read_bytes();source_hashes[str(path)]=hashlib.sha256(raw).hexdigest()
        root=ET.fromstring(raw)
        wrapper=next(g for g in root if g.get('class')=='repeat-block')
        body=next(g for g in wrapper if g.tag==NS+'g' and g.get('transform','').startswith('translate'))
        columns=[e for e in body if e.tag==NS+'svg' and e.get('data-vocal-pass')=='1']
        tabs=[e for e in body if e.get('data-shared-tab')=='true']
        assert len(columns)==len(tabs)
        for c,(column,tab) in enumerate(zip(columns,tabs)):
            number=int(column.get('data-shared-measure'));left=float(column.get('x'))
            right=float(columns[c+1].get('x')) if c+1<len(columns) else float(root.get('width'))
            voices=[e for e in body if e.tag==NS+'svg' and e.get('data-shared-measure')==str(number) and e.get('data-vocal-pass')]
            diagrams=[];extras=[]
            for e in body:
                if e.get('class')=='chord-diagram':
                    center=float(e.find(NS+'text').get('x'))
                    if left<=center<right:
                        key=chart_key(e)
                        charts.setdefault(key,{'node':deepcopy(e),'name':e.find(NS+'text').text,'center':center})
                        diagrams.append({'key':key,'old_x':center-left,'node':e})
                elif e.tag==NS+'text' and e.get('y')!='19' and e.get('x') is not None and left<=float(e.get('x'))<right:
                    extras.append(e)
            variants=[]
            for alt in wrapper.iter(NS+'svg'):
                if alt.get('data-variant-canonical-measure')!=str(number):continue
                alt_tab=next(e for e in alt if e.get('data-shared-tab')=='true')
                offset=float(alt.get('x'))-left
                alt_charts=[]
                for e in alt:
                    if e.get('class')=='chord-diagram':
                        center=float(e.find(NS+'text').get('x'));key=chart_key(e)
                        charts.setdefault(key,{'node':deepcopy(e),'name':e.find(NS+'text').text,'center':center})
                        alt_charts.append({'key':key,'old_x':center+offset,'node':e})
                variants.append({'tab':alt_tab,'offset':offset,'charts':alt_charts,'pass':int(alt.get('data-repeat-variant-pass')),'source_measure':int(alt.get('data-variant-source-measure'))})
            units.append({'number':number,'left':left,'voices':voices,'tab':tab,'charts':diagrams,'extras':extras,'block':block,'variants':variants})
        for e in wrapper:
            if e.get('class')=='repeat-print-symbol':
                title=e.find(NS+'title')
                markers.append({'kind':e.get('data-marker-kind'),'first':int(e.get('data-first')),'last':int(e.get('data-last')),'text':title.text if title is not None else '', 'target':e.get('data-target')})
    names=defaultdict(list)
    for key,value in charts.items():names[value['name']].append(key)
    for key,value in charts.items():
        group=names[value['name']]
        value['label']=value['name']+(str(group.index(key)+1).translate(str.maketrans('0123456789','⁰¹²³⁴⁵⁶⁷⁸⁹')) if len(group)>1 else '')
    pickup_offset=int(plan['actual_measure_timeline'][0].get('pickup',False))
    for unit in units:
        timing=plan['actual_measure_timeline'][unit['number']-1]
        previous=plan['actual_measure_timeline'][unit['number']-2] if unit['number']>1 else None
        unit['pickup']=bool(timing.get('pickup',False))
        unit['pickup_offset']=pickup_offset
        unit['display_number']=unit['number']-pickup_offset
        unit['meter']=timing['meter']
        unit['show_meter']=timing['meter']!=(previous['meter'] if previous else [4,4])
        unit['markers']=[m for m in markers if unit['number']==(m['first'] if m['kind'] in ('segno','coda','repeat_start','volta_1','volta_2') else m['last'])]
        unit['volta_spans']=[m for m in markers if m['kind'].startswith('volta_') and m['first']<=unit['number']<=m['last']]
        for layer in unit['voices']:
            for t in layer.iter(NS+'text'):
                if float(t.get('y',0))>=160 and t.get('font-size')=='20':t.set('font-size','24')
        prepare_unit(unit,charts)
    return units,charts,plan,source_hashes,markers


def prepare_unit(unit,charts):
    centers=[];left=unit['left']
    for layer in unit['voices']:
        off=float(layer.get('x'))-float(layer.get('viewBox').split()[0])-left
        for g in layer.iter(NS+'g'):
            if g.get('class')=='vocal-time-glyph':
                t=g.find(NS+'text')
                if t is not None:centers.append(float(t.get('x'))+off)
    for e in unit['tab'].iter():
        if e.get('data-rhythm-tick') is not None:centers.append(float(e.get('x1'))-left)
        if e.get('data-note-id') and e.tag==NS+'g':
            t=e.find(NS+'text')
            if t is not None:centers.append(float(t.get('x'))-left)
    centers=sorted(set(round(x,3) for x in centers))
    assert centers,'小节缺少音符时间列'
    bands=defaultdict(dict)
    def take(text,x,size,anchor,band):
        at=min(centers,key=lambda a:abs(a-x));width=text_width(text,size)
        x0=x-({'start':0,'middle':.5,'end':1}.get(anchor,.5))*width
        old=bands[band].get(at,(0.,0.))
        bands[band][at]=(min(old[0],x0-at-1.5),max(old[1],x0+width-at+1.5))
    for index,layer in enumerate(unit['voices']):
        off=float(layer.get('x'))-float(layer.get('viewBox').split()[0])-left
        for e in layer.iter(NS+'text'):
            y=float(e.get('y',0))
            if 50<=y<=185:
                band=f'voice{index}_'+('lyric' if y>=160 else 'note')
                take(e.text or '',float(e.get('x'))+off,float(e.get('font-size',20)),e.get('text-anchor','middle'),band)
        for circle in layer.iter(NS+'circle'):
            y=float(circle.get('cy',0))
            if 50<=y<=160:
                x=float(circle.get('cx'))+off;r=float(circle.get('r'))
                at=min(centers,key=lambda a:abs(a-x));old=bands[f'voice{index}_note'].get(at,(0.,0.))
                bands[f'voice{index}_note'][at]=(min(old[0],x-r-at-1),max(old[1],x+r-at+1))
    for e in unit['tab'].iter(NS+'text'):
        if e.get('y')=='489':continue
        size=24 if e.get('font-size')=='18' else float(e.get('font-size',18))
        string=round((float(e.get('y',343))-343)/18)
        take(e.text or '',float(e.get('x'))-left,size,e.get('text-anchor','middle'),f'string{string}')
    positions={};last_in_band={}
    for index,x in enumerate(centers):
        position=positions[centers[index-1]]+7.5 if index else 16.
        for band,items in bands.items():
            if x not in items:continue
            low,high=items[x]
            previous=last_in_band.get(band)
            if previous is None:position=max(position,7-low)
            else:
                old,old_right=previous
                position=max(position,positions[old]+old_right-low+1.5)
        positions[x]=position
        for band,items in bands.items():
            if x in items:last_in_band[band]=(x,items[x][1])
    width=max(110.,max(positions[x]+max([6.]+[v[x][1] for v in bands.values() if x in v]) for x in centers)+8.)
    chord_positions=sorted(unit['charts'],key=lambda c:c['old_x'])
    for i,chart in enumerate(chord_positions):
        chart['anchor']='start' if i==0 else 'end' if i==len(chord_positions)-1 else 'middle'
    def chart_extent(chart):
        w=bold_width(charts[chart['key']]['label'],23)
        anchor=chart['anchor']
        return (0,w) if anchor=='start' else (-w,0) if anchor=='end' else (-w/2,w/2)
    for a,b in zip(chord_positions,chord_positions[1:]):
        xa=min(centers,key=lambda x:abs(x-a['old_x']));xb=min(centers,key=lambda x:abs(x-b['old_x']))
        required=chart_extent(a)[1]-chart_extent(b)[0]+6
        shortage=required-(positions[xb]-positions[xa])
        if shortage>0:
            for x in centers:
                if x>=xb:positions[x]+=shortage
            width+=shortage
    for chart in chord_positions:
        at=min(centers,key=lambda x:abs(x-chart['old_x']))
        low,high=chart_extent(chart)
        if positions[at]+low<3:
            delta=3-positions[at]-low
            for x in centers:positions[x]+=delta
            width+=delta
        width=max(width,positions[at]+high+4)
    unit.update({'centers':centers,'positions':positions,'width':width,'bands':dict(bands)})


def row_partition(units,row_count):
    # 在4至5小节间寻找最宽行最小的分组；不会按歌曲名写固定断行。
    dp={(0,0):(0.,0.,[])}
    for count in range(1,row_count+1):
        for end in range(1,len(units)+1):
            best=None
            for length in (4,5):
                begin=end-length
                previous=dp.get((count-1,begin))
                if previous is None:continue
                width=sum(u['width'] for u in units[begin:end])
                # 共用段边界作为断行偏好，字号仍优先。
                crossings=sum(units[k]['block'].get('repeat_group')!=units[k-1]['block'].get('repeat_group') for k in range(begin+1,end))
                candidate=(max(previous[0],width),previous[1]+width*width+crossings*10000,previous[2]+[(begin,end)])
                if best is None or candidate[:2]<best[:2]:best=candidate
            if best is not None:dp[count,end]=best
    return dp.get((row_count,len(units)))


def mapping(unit,width):
    centers=unit['centers'];stretch=(width-20)/(unit['width']-20)
    targets={x:10+(unit['positions'][x]-10)*stretch for x in centers}
    boundaries=[e for e in unit['tab'] if e.get('class')=='tab-string-line']
    old_left=float(boundaries[0].get('x1'))-unit['left'];old_right=float(boundaries[0].get('x2'))-unit['left']
    keys=[old_left]+centers+[old_right];values={**targets,old_left:0.,old_right:width}
    def mx(x):
        at=bisect_left(keys,x);candidates=keys[max(0,at-1):min(len(keys),at+1)]
        nearest=min(candidates,key=lambda a:abs(a-x))
        return values[nearest]+x-nearest
    return mx,targets


def vocal_bounds(layers):
    ys=[]
    for layer in layers:
        for e in layer.iter():
            kind=e.tag.split('}')[-1]
            if kind=='text':
                y=float(e.get('y',0));size=float(e.get('font-size',20))
                if 50<=y<=185:ys.extend([y-size*.55,y+size*.55])
            elif kind=='line':ys.extend([float(e.get('y1')),float(e.get('y2'))])
            elif kind=='circle':ys.extend([float(e.get('cy'))-float(e.get('r')),float(e.get('cy'))+float(e.get('r'))])
            elif kind=='path':
                vals=list(map(float,re.findall(r'[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?',e.get('d',''))))
                if 'Q' in e.get('d','') and len(vals)==6:
                    y0,yc,y1=vals[1],vals[3],vals[5];ys.extend([y0,y1])
                    den=y0-2*yc+y1
                    if den:
                        t=(y0-yc)/den
                        if 0<t<1:ys.append((1-t)**2*y0+2*t*(1-t)*yc+t*t*y1)
                else:ys.extend(vals[1::2])
    ys=[y for y in ys if 45<=y<=190]
    return max(45,math.floor(min(ys)-3)),min(190,math.ceil(max(ys)+3))


def tab_y(y):
    if y<=427:return (y-337)*19/18
    if y<=435:return 95+(y-427)*.8
    return 101.4+(y-435)*.72


def draw_repeat(root,kind,x,y,text,end=False):
    if kind=='segno':
        g=node('g',data_marker_kind=kind)
        g.append(node('text','S',x=x+7,y=y+16,font_size=21,font_style='italic',font_family='Georgia',fill='#111'))
        g.append(node('line',x1=x+2,y1=y+18,x2=x+21,y2=y+1,stroke='#111',stroke_width=1.3))
        for a,b in ((2,5),(21,15)):g.append(node('circle',cx=x+a,cy=y+b,r=1.4,fill='#111'))
        root.append(g)
    elif kind=='coda':
        g=node('g',data_marker_kind=kind)
        g.append(node('circle',cx=x+10,cy=y+10,r=6.4,fill='none',stroke='#111'))
        g.append(node('line',x1=x,y1=y+10,x2=x+20,y2=y+10,stroke='#111'))
        g.append(node('line',x1=x+10,y1=y,x2=x+10,y2=y+20,stroke='#111'))
        root.append(g)
    elif kind in ('ds','to_coda','fine'):
        root.append(node('text',text,x=x,y=y+15,font_size=23,text_anchor='end' if end else 'start',fill='#111',data_marker_kind=kind))
    elif kind.startswith('volta_'):
        root.append(node('text',text,x=x,y=y+15,font_size=13,fill='#111',data_marker_kind=kind))
