"""和弦弹唱与伴奏编配：六线谱、双手MusicXML与独立试听/复核导出。"""
# 和弦弹唱与伴奏编配：新增独立导出路径，不调用单声部五线谱的限制接口。
from __future__ import annotations
import copy
from collections import defaultdict
import html
import json
import math
import os
from pathlib import Path
from workspace_location import local_path
import re
from urllib.parse import quote
import xml.etree.ElementTree as ET
import numpy as np
import score_export as score
from score_export import PPQ, tag, save_json
from staff_export import staff_spelling, write_mxl, RENDER_OPTIONS
from accompaniment_analysis import SongClock, chord_name, pc_name
from accompaniment_arrange import TUNING, harmony_at
# 分解和弦优先：新增实际演奏织体标签，声学观察在复核页另列。
from accompaniment_texture_policy import arranged_texture_label
# 和弦指型与X六线谱：新增实际按法派生与可见黑点网格回读。
from guitar_chord_diagrams import prepare_diagrams,visible_diagrams,draw_diagram,read_diagram,TOP_SPACE
# 空弦沿用指型X表示：新增实际左手基础按位及新版显示配置。
from guitar_chord_diagrams import left_hand_fret,set_tab_display
# 六线谱同拍节奏连线：新增按真实时值的同拍横梁和独立几何读回。
from guitar_rhythm_beams import prepare_rhythm,rhythm_events,draw_rhythm,validate_rhythm
# 常用指型与器乐独奏：新增完整持握和器乐独奏策略的语义/时序验收。
from guitar_grip_policy import validate_grip_policy
# 常用指型与器乐独奏：修改，原仅同音换弦说明保留；联合最小释音保持音高、起音与力度。
# 常用指型与器乐独奏：新增严格持续时序失败时仅用精确同音换弦修复，保持全部发声参数。
from guitar_exact_positions import refinger_exact_positions
# 节奏符号说明与声部对齐：新增共同拍点、可见简谱身份及独立坐标验收。
from guitar_time_alignment import prepare_alignment,layout_shared_time,annotate_vocal_glyphs,validate_time_alignment
# 规整分解节奏与延音显示：新增右手拍格、跨小节续音和规整起音核查。
from guitar_rhythm_beams import arrangement_rhythm_events
from guitar_sustain_display import draw_continuations,annotate_continuations,validate_continuations
# 结构稳定伴奏与人声合播：修改，原代码注释保留。
# from guitar_regular_rhythm import validate_regular_rhythm
from guitar_regular_rhythm import validate_regular_rhythm
# 结构稳定伴奏与人声合播：新增分段夹位、原歌手合播与四小节验证。
from guitar_capo import capo_at,fret_at,validate_capo
from guitar_structure_validation import validate_structure
from accompaniment_vocal_playback import prepare_vocals,write_singing_preview,singing_player_html,validate_singing_preview
# 相似乐句和弦框架复用：新增导出共同进行视图；存储仍保留原始声学和声及派生计划。
from phrase_harmony_plan import arrangement_view

SVG_NS='http://www.w3.org/2000/svg'
ET.register_namespace('',SVG_NS)
# 器乐主旋律简化与规整节奏：新增标准xlink前缀；ns1:href嵌入HTML后不会被浏览器识别，导致钢琴符头/谱号消失。
ET.register_namespace('xlink','http://www.w3.org/1999/xlink')
QUALITY_XML={'':'major','m':'minor','dim':'diminished','aug':'augmented','sus2':'suspended-second',
             'sus4':'suspended-fourth','5':'power','7':'dominant','maj7':'major-seventh','m7':'minor-seventh',
             'm7b5':'half-diminished','dim7':'diminished-seventh','6':'major-sixth','m6':'minor-sixth',
             # 和弦弹唱与伴奏编配：修改，7sus4需省略三度，原dominant保留说明。
             # '7sus4':'dominant'
             'add9':'major','madd9':'minor','9':'dominant-ninth','maj9':'major-ninth','m9':'minor-ninth','7sus4':'suspended-fourth'}
KIND_LABELS={'arpeggio':'分解','block':'柱式','strum':'扫弦','sustain':'延音','silence':'休止'}
SECTION_LABELS={'intro':'前奏','interlude':'间奏','vocal':'演唱','outro':'尾奏'}


# 常用指型与器乐独奏：新增按精确时间查询展示模式，后台和声分析与演奏标记分开。
def guitar_region_at(arrangement,tick):
    return next((r for r in arrangement.get('notation_regions',[]) if r['start_tick']<=tick<r['end_tick']),None)


# 常用指型与器乐独奏：新增整行无演唱时只画TAB；边界小节有任何真实人声音符则保留简谱。
def instrumental_guitar_row(shared,vocal,first,last):
    bar=vocal['statistics']['bar_ticks'];start=(first-1)*bar;end=last*bar
    if any(s['kind']=='vocal' and s['start_tick']<end and s['end_tick']>start for s in shared.get('sections',[])):
        return False
    for note in vocal.get('quantized_notes',[]):
        begin=note.get('start_tick',0);finish=note.get('end_tick',begin+note.get('duration_ticks',0))
        if begin<end and finish>start:return False
    return all(shared['measure_textures'][m-1]['section'] in ('intro','interlude','outro') for m in range(first,last+1))


# 和弦弹唱与伴奏编配：新增谱面链接编码，兼容中文目录及另存输出。
def relative_url(path, base):
    try:return quote(Path(os.path.relpath(local_path(path).resolve(),Path(base).resolve())).as_posix(),safe='/')
    except ValueError:return local_path(path).resolve().as_uri()


# 和弦弹唱与伴奏编配：新增和弦符号的实际音高与扩展规范，不把指型当钢琴音高。
def xml_harmony(parent,chord):
    # 和弦弹唱与伴奏编配：修改，新增可追溯和弦ID，供SVG使用正常文本字体，原行保留。
    # node=tag(parent,'harmony');root=tag(node,'root')
    node=tag(parent,'harmony',id=chord['id']+'_measure_'+parent.get('number'));root=tag(node,'root')
    name=pc_name(chord['root_pc'],chord['key']);tag(root,'root-step',name[0])
    if len(name)>1:tag(root,'root-alter',name.count('#')-name.count('b'))
    # 和弦弹唱与伴奏编配：修改，XML的text属性与辅助函数正文形参分开，原行保留。
    # tag(node,'kind',QUALITY_XML[chord['quality']],text=chord['quality'] or '')
    kind=tag(node,'kind',QUALITY_XML[chord['quality']]);kind.set('text',chord['quality'] or '')
    if chord['bass_pc']!=chord['root_pc']:
        bass=tag(node,'bass');name=pc_name(chord['bass_pc'],chord['key']);tag(bass,'bass-step',name[0])
        if len(name)>1:tag(bass,'bass-alter',name.count('#')-name.count('b'))
    if chord['quality'] in ('add9','madd9','7sus4'):
        # 和弦弹唱与伴奏编配：修改，挂四七和弦在sus4基础加降七，原两行保留。
        # degree=tag(node,'degree');tag(degree,'degree-value',9 if 'add9' in chord['quality'] else 4)
        # tag(degree,'degree-alter',0);tag(degree,'degree-type','add' if 'add9' in chord['quality'] else 'alter')
        # 和弦弹唱与伴奏编配：修改，性质文字已包含加音，语义保留但不重复显示degree。
        # degree=tag(node,'degree');tag(degree,'degree-value',9 if 'add9' in chord['quality'] else 7)
        degree=tag(node,'degree',**{'print-object':'no'});tag(degree,'degree-value',9 if 'add9' in chord['quality'] else 7)
        tag(degree,'degree-alter',0 if 'add9' in chord['quality'] else -1);tag(degree,'degree-type','add')
    return node


# 和弦弹唱与伴奏编配：新增双手/六线谱属性，TAB只含六根弦，capo按MusicXML标准独立保存。
# 结构稳定伴奏与人声合播：修改，原代码注释保留。
# def xml_attributes(parent, key, meter, instrument, capo=0, initial=False):
def xml_attributes(parent, key, meter, instrument, capo=0, initial=False, capo_change=False):
    attrs=tag(parent,'attributes')
    if initial:tag(attrs,'divisions',PPQ)
    k=tag(attrs,'key');tag(k,'fifths',key['fifths']);tag(k,'mode',key['mode'])
    if initial:
        time_node=tag(attrs,'time');tag(time_node,'beats',meter[0]);tag(time_node,'beat-type',meter[1])
        if instrument=='piano':
            tag(attrs,'staves',2)
            for number,sign,line in ((1,'G',2),(2,'F',4)):
                clef=tag(attrs,'clef',number=number);tag(clef,'sign',sign);tag(clef,'line',line)
        else:
            clef=tag(attrs,'clef');tag(clef,'sign','TAB');tag(clef,'line',5)
            details=tag(attrs,'staff-details');tag(details,'staff-lines',6)
            for line,string in enumerate(range(6,0,-1),start=1):
                step,alter,octave=staff_spelling(TUNING[string],0)
                tuning=tag(details,'staff-tuning',line=line);tag(tuning,'tuning-step',step)
                if alter:tag(tuning,'tuning-alter',alter)
                tag(tuning,'tuning-octave',octave)
            # 结构稳定伴奏与人声合播：修改，原代码注释保留。
            # tag(details,'capo',capo)
    # return attrs
            tag(details,'capo',capo)
    elif instrument=='guitar' and capo_change:
        tag(tag(attrs,'staff-details'),'capo',capo)
    return attrs


# 和弦弹唱与伴奏编配：新增多声部切片，长音跨攻击/小节以真实延音保留，不缩成等长和弦。
def build_musicxml(shared,vocal,arrangement):
    # 4/4可选右手与实时谱面试听：新增自然余音只在记谱视图按拍写，实际工程及发声时刻不改。
    from guitar_pattern_performance import notation_notes
    if arrangement.get('natural_release_notation'):
        arrangement={**arrangement,'notes':notation_notes(arrangement)}
    # 相似乐句和弦框架复用：新增公开XML入口也读取实际和弦，避免直接调用仍打印旧标签。
    shared=arrangement_view(shared,vocal)
    root=ET.Element('score-partwise',version='4.0')
    instrument=arrangement['instrument'];clock=SongClock(vocal);bar=clock.bar_ticks
    title=vocal['title']+' · '+('吉他简谱/六线谱伴奏' if instrument=='guitar' else '钢琴双手伴奏')
    tag(tag(root,'work'),'work-title',title)
    identification=tag(root,'identification');tag(tag(identification,'encoding'),'software','sheet_music_generator accompaniment v1')
    misc=tag(identification,'miscellaneous')
    tag(misc,'miscellaneous-field',shared['input_binding']['vocal_project_sha256'],name='accepted-vocal-project-sha256')
    tag(misc,'miscellaneous-field','automatic_arrangement_requires_listening',name='quality-status')
    part_info=tag(tag(root,'part-list'),'score-part',id='P1');tag(part_info,'part-name','Guitar TAB' if instrument=='guitar' else 'Piano')
    tag(tag(part_info,'score-instrument',id='I1'),'instrument-name','Acoustic Guitar' if instrument=='guitar' else 'Piano')
    midi=tag(part_info,'midi-instrument',id='I1');tag(midi,'midi-channel',1);tag(midi,'midi-program',25 if instrument=='guitar' else 1)
    part=tag(root,'part',id='P1');notes=arrangement['notes'];fragment_map={};spellings={}
    for n in notes:
        spellings[n['id']]=staff_spelling(n['pitch_midi'],clock.key(n['start_tick'])['fifths'])
    # 和弦弹唱与伴奏编配：修改，记录已显示速度，避免同速时间轴锚点重复堆叠BPM文字。
    # previous_key=None
    # 结构稳定伴奏与人声合播：修改，原代码注释保留。
    # previous_key=None;previous_tempo=clock.mapping.tempo_at(clock.origin)
    previous_key=None;previous_tempo=clock.mapping.tempo_at(clock.origin);previous_capo=None
    for number in range(1,vocal['statistics']['measure_count']+1):
        start,end=(number-1)*bar,number*bar;key=clock.key(start)
        measure=tag(part,'measure',number=number,id=f'{instrument}_measure_{number}')
        # 强拍相位与伴奏同步纠错：新增显示编号不改变内部时间索引，预备弱起不计正式小节。
        if vocal['timing'].get('initial_pickup_measure'):
            from beat_phase_alignment import display_measure
            measure.set('text',display_measure(vocal,number))
            if number==1:measure.set('implicit','yes')
        # 结构稳定伴奏与人声合播：修改，原代码注释保留。
        # if number==1 or key['label']!=previous_key:
            # xml_attributes(measure,key,vocal['timing']['meter'],instrument,arrangement['configuration'].get('capo_fret',0),number==1)
        # previous_key=key['label']
        current_capo=capo_at(arrangement,start) if instrument=='guitar' else 0
        capo_change=instrument=='guitar' and current_capo!=previous_capo
        if number==1 or key['label']!=previous_key or capo_change:
            xml_attributes(measure,key,vocal['timing']['meter'],instrument,current_capo,number==1,capo_change=capo_change)
        previous_key=key['label'];previous_capo=current_capo
        # 强拍相位与伴奏同步纠错：修改，原四小节系统断点保留；弱起独立后从首个正式小节开始计四节。
        # if instrument=='guitar' and number>1 and (number-1)%arrangement['configuration'].get('rows_measures',4)==0:
        from beat_phase_alignment import score_row_ranges
        if (instrument=='guitar' or vocal['timing'].get('initial_pickup_measure')) and number>1 and number in {first for first,last in score_row_ranges(vocal,arrangement['configuration'].get('rows_measures',4))}:
            tag(measure,'print',**{'new-system':'yes'})
        if instrument=='guitar' and number>1 and capo_change:
            direction=tag(measure,'direction',placement='above')
            tag(tag(direction,'direction-type'),'words','变调夹移至'+str(current_capo)+'品')
        if number==1:
            direction=tag(measure,'direction',placement='above');dt=tag(direction,'direction-type')
            # 和弦弹唱与伴奏编配：修改，首个速度标记直接取实际播放时间轴，原显示保留。
            # tag(dt,'words','BPM '+format(vocal['timing'].get('steady_tempo_bpm',117),'.6g'))
            tag(dt,'words','BPM '+format(previous_tempo,'.6g'))
            tag(direction,'sound',tempo=clock.mapping.tempo_at(clock.origin))
        # 和弦弹唱与伴奏编配：新增按已继承音频时间轴写入全部tempo事件，导出不另定速度。
        for tempo in vocal['tempo_events']:
            if start<=tempo['tick']<end and tempo['tick']:
                # 和弦弹唱与伴奏编配：新增跳过冗余同速锚点，真实速度变化照常记谱，MIDI保留完整源事件。
                if math.isclose(tempo['bpm'],previous_tempo,rel_tol=0,abs_tol=1e-8):continue
                # 和弦弹唱与伴奏编配：修改，MusicXML不接受空direction-type，原行保留。
                # direction=tag(measure,'direction');tag(direction,'direction-type');tag(direction,'offset',tempo['tick']-start)
                # 局部拍轴与原唱同步纠错：修改，原逐点显示BPM注释保留；局部演奏时钟只影响播放，谱面避免每拍堆叠速度字样。
                # direction=tag(measure,'direction');tag(tag(direction,'direction-type'),'words','BPM '+format(tempo['bpm'],'.6g'));tag(direction,'offset',tempo['tick']-start)
                direction=tag(measure,'direction');dt=tag(direction,'direction-type')
                if vocal['timing'].get('local_beat_clock',{}).get('status')=='tracked':
                    tag(dt,'words','',**{'print-object':'no'})
                else:
                    tag(dt,'words','BPM '+format(tempo['bpm'],'.6g'))
                tag(direction,'offset',tempo['tick']-start,sound='yes')
                tag(direction,'sound',tempo=tempo['bpm'])
                previous_tempo=tempo['bpm']
        for pedal in arrangement.get('pedal',[]):
            if start<=pedal['tick']<end:
                direction=tag(measure,'direction',placement='below');dt=tag(direction,'direction-type')
                tag(dt,'pedal',type='start' if pedal['value'] else 'stop',line='yes',sign='no')
                tag(direction,'offset',pedal['tick']-start);tag(direction,'staff',2)
                tag(direction,'sound',**{'damper-pedal':'yes' if pedal['value'] else 'no'})
        sections=[s for s in shared['sections'] if start<=s['start_tick']<end]
        for section in sections:
            direction=tag(measure,'direction',placement='above');tag(tag(direction,'direction-type'),'words',section['label'])
            tag(direction,'offset',section['start_tick']-start)
        lanes=(('right',1),('left',2)) if instrument=='piano' else (('guitar',1),)
        for lane_index,(hand,staff) in enumerate(lanes):
            lane_primary=[]
            if lane_index:tag(tag(measure,'backup'),'duration',bar)
            lane=[n for n in notes if n['start_tick']<end and n['end_tick']>start and (instrument=='guitar' or n['hand']==hand)]
            chord_starts=[max(start,h['start_tick']) for h in shared['harmony'] if h['start_tick']<end and h['end_tick']>start]
            # 常用指型与器乐独奏：新增吉他XML同样只在实际采用指型的区域标和弦，钢琴循环保留。
            if instrument=='guitar' and arrangement.get('notation_regions'):
                # 常用指型与器乐独奏：修改，原将区段边界用于切分音符保留；非网格区段用XML和弦偏移表达。
                # chord_starts=[max(start,r['start_tick']) for r in arrangement['notation_regions']
                #               if r['mode']=='chord_grip' and r['start_tick']<end and r['end_tick']>start]
                for region in arrangement['notation_regions']:
                    if region['mode']!='chord_grip' or region['start_tick']>=end or region['end_tick']<=start:continue
                    tick=max(start,region['start_tick']);chord=harmony_at(shared,tick)
                    if chord['name']!='N.C.':
                        harmony=xml_harmony(measure,chord)
                        if tick!=start:tag(harmony,'offset',tick-start)
                # 常用指型与器乐独奏：新增图式边界只移动标签，不改变任何实际音符的切片和持续时间。
                chord_starts=[]
            boundaries=sorted({start,end,*[max(start,n['start_tick']) for n in lane],*[min(end,n['end_tick']) for n in lane],*chord_starts})
            accidentals={};default={c:0 for c in 'CDEFGAB'}
            for step in ('FCGDAEB'[:key['fifths']] if key['fifths']>0 else 'BEADGCF'[:-key['fifths']]):
                default[step]=1 if key['fifths']>0 else -1
            for a,b in zip(boundaries,boundaries[1:]):
                active=sorted((n for n in lane if n['start_tick']<=a<n['end_tick']),key=lambda n:n['pitch_midi'])
                if lane_index==0 and a in chord_starts:
                    chord=harmony_at(shared,a)
                    if chord['name']!='N.C.':xml_harmony(measure,chord)
                for duration in score.split_interval(a,b,bar):
                    tick=duration['start_tick'];length=duration['duration_ticks']
                    if not active:
                        node=tag(measure,'note',id=f'{instrument}_rest_{number}_{hand}_{tick}')
                        tag(node,'rest');tag(node,'duration',length);tag(node,'voice',staff);tag(node,'type',duration['type'])
                        for _ in range(duration['dots']):tag(node,'dot')
                        if instrument=='piano':tag(node,'staff',staff)
                        lane_primary.append((node,tick,length,0))
                        continue
                    for index,value in enumerate(active):
                        identity=f"{value['id']}_fragment_{tick}";node=tag(measure,'note',id=identity)
                        fragment_map[identity]=value['id']
                        if index:tag(node,'chord')
                        step,alter,octave=spellings[value['id']];pitch=tag(node,'pitch');tag(pitch,'step',step)
                        if alter:tag(pitch,'alter',alter)
                        tag(pitch,'octave',octave);tag(node,'duration',length)
                        stop=tick>value['start_tick'];begin=tick+length<value['end_tick']
                        if stop:tag(node,'tie',type='stop')
                        if begin:tag(node,'tie',type='start')
                        tag(node,'voice',staff);tag(node,'type',duration['type'])
                        for _ in range(duration['dots']):tag(node,'dot')
                        if instrument=='piano':
                            if not stop and alter!=accidentals.get((step,octave),default[step]):
                                tag(node,'accidental',{-2:'flat-flat',-1:'flat',0:'natural',1:'sharp',2:'double-sharp'}[alter])
                            accidentals[(step,octave)]=alter
                            tag(node,'stem','up' if staff==1 else 'down');tag(node,'staff',staff)
                        else:tag(node,'stem','down')
                        # 器乐背景休止与旋律突出：修改，旧仅含延音的记号节点保留；新起音写入标准重音，续音不重复加重。
                        # notations=tag(node,'notations')
                        notations=tag(node,'notations')
                        if value.get('melody_accent') and not stop:
                            tag(tag(notations,'articulations'),'accent',placement='above')
                        if stop:tag(notations,'tied',type='stop')
                        if begin:tag(notations,'tied',type='start')
                        technical=tag(notations,'technical')
                        # 和弦弹唱与伴奏编配：修改，建议指法改小号斜体，避免密集指号干扰节奏阅读，原行保留。
                        # if not stop and value.get('finger'):tag(technical,'fingering',value['finger'],placement='above')
                        # 常用指型与器乐独奏：修改，原单独音符指法保留；吉他改用完整持握后派生指法。
                        # if not stop and value.get('finger'):
                        #     tag(technical,'fingering',value['finger'],placement='above',**{'font-size':'8','font-style':'italic'})
                        finger=arrangement.get('grip_fingerings',{}).get(value['id'],value.get('finger',0)) if instrument=='guitar' else value.get('finger',0)
                        if not stop and finger:
                            tag(technical,'fingering',finger,placement='above',**{'font-size':'8','font-style':'italic'})
                        # 结构稳定伴奏与人声合播：修改，原代码注释保留。
                        # if instrument=='guitar':tag(technical,'fret',value['fret']);tag(technical,'string',value['string'])
                        if instrument=='guitar':tag(technical,'fret',fret_at(value,arrangement,tick));tag(technical,'string',value['string'])
                        if index==0:lane_primary.append((node,tick,length,{'eighth':1,'16th':2,'32nd':3}.get(duration['type'],0)))
            # 和弦弹唱与伴奏编配：新增每只手按拍连梁，backup和chord不参与假游标累计。
            runs=[];run=[]
            for row in lane_primary:
                # 原曲器乐旋律骨干重提取：新增修订段界的连梁分组，新器乐不改变已认可唱段的单旗／连梁。
                def revised_scope(tick):
                    return any(s['kind'] in ('intro','interlude','outro') and s['start_tick']<=tick<s['end_tick'] for s in shared['sections'])
                scope_change=arrangement.get('instrumental_source_backbone') and run and revised_scope(row[1])!=revised_scope(run[-1][1])
                # 原曲器乐旋律骨干重提取：修改，原仅按拍连续分组保留；本次独立器乐修订还需保持唱段边界。
                # if run and (not row[3] or row[1]//PPQ!=run[-1][1]//PPQ or run[-1][1]+run[-1][2]!=row[1]):
                if run and (scope_change or not row[3] or row[1]//PPQ!=run[-1][1]//PPQ or run[-1][1]+run[-1][2]!=row[1]):
                    runs.append(run);run=[]
                if row[3]:run.append(row)
            if run:runs.append(run)
            for run in runs:
                if len(run)<2:continue
                for index,(node,tick,length,flags) in enumerate(run):
                    for level in range(1,flags+1):
                        left=index>0 and run[index-1][3]>=level;right=index+1<len(run) and run[index+1][3]>=level
                        value='continue' if left and right else 'end' if left else 'begin' if right else ('backward hook' if index else 'forward hook')
                        beam=ET.Element('beam',number=str(level));beam.text=value
                        position=next((i for i,n in enumerate(node) if n.tag=='notations'),len(node));node.insert(position,beam)
        if number==vocal['statistics']['measure_count']:
            tag(tag(measure,'barline',location='right'),'bar-style','light-heavy')
    # 4/4可选右手与实时谱面试听：新增显式动作的XML方向与空扫说明，既有无选择输出不变。
    from guitar_pattern_performance import add_xml_actions
    add_xml_actions(root,arrangement,bar)
    return root,fragment_map


# 和弦弹唱与伴奏编配：新增独立多声部解析器，真实cursor/backup/chord/延音合并后与工程比较。
def parse_musicxml_notes(root):
    fragments=defaultdict(list);ids=set();errors=[];absolute=0;division=PPQ;voice_lengths=[]
    for measure in root.findall('part/measure'):
        if measure.find('attributes/divisions') is not None:division=int(measure.findtext('attributes/divisions'))
        cursor,last_start=0,0;maximum=0
        for child in measure:
            if child.tag in ('backup','forward'):
                length=int(child.findtext('duration'))*PPQ//division
                cursor+=length*(-1 if child.tag=='backup' else 1)
                if cursor<0:errors.append('negative_musicxml_cursor')
            elif child.tag=='note':
                identity=child.get('id')
                if not identity or identity in ids:errors.append('missing_or_duplicate_xml_id')
                ids.add(identity);length=int(child.findtext('duration','0'))*PPQ//division
                if child.find('chord') is not None:start=last_start
                else:start=cursor;last_start=cursor;cursor+=length
                maximum=max(maximum,cursor)
                if child.find('pitch') is not None:
                    midi=score.PITCH_CLASS[child.findtext('pitch/step')]+int(child.findtext('pitch/alter','0'))+12*(int(child.findtext('pitch/octave'))+1)
                    original=identity.split('_fragment_')[0]
                    fragments[original].append({'start_tick':absolute+start,'end_tick':absolute+start+length,'pitch_midi':midi,
                                                'staff':int(child.findtext('staff','1')),'string':child.findtext('notations/technical/string'),
                                                'fret':child.findtext('notations/technical/fret'),
                                                'ties':sorted(t.get('type') for t in child.findall('tie'))})
        voice_lengths.append(maximum);absolute+=maximum
    merged={}
    for identity,rows in fragments.items():
        rows.sort(key=lambda x:x['start_tick']);first=rows[0]
        for i,row in enumerate(rows):
            expected=sorted((['stop'] if i else [])+(['start'] if i<len(rows)-1 else []))
            if row['ties']!=expected:errors.append('invalid_tie_chain:'+identity)
            if row['pitch_midi']!=first['pitch_midi']:errors.append('tie_changed_pitch:'+identity)
            if i and rows[i-1]['end_tick']!=row['start_tick']:errors.append('tie_gap_or_overlap:'+identity)
        merged[identity]={**first,'end_tick':rows[-1]['end_tick']}
    return merged,{'valid':not errors,'errors':errors,'measure_lengths':voice_lengths,'total_ticks':absolute,'fragment_count':len(ids)}


# 和弦弹唱与伴奏编配：新增分通道试听MIDI，吉他逐弦通道避免同音异弦被提前关断。
def write_midi(path,arrangement,vocal):
    import mido
    midi=mido.MidiFile(type=1,ticks_per_beat=PPQ);conductor=mido.MidiTrack();midi.tracks.append(conductor)
    events=[]
    for tempo in vocal['tempo_events']:events.append((tempo['tick'],0,mido.MetaMessage('set_tempo',tempo=mido.bpm2tempo(tempo['bpm']))))
    numerator,denominator=vocal['timing']['meter']
    events.append((0,-2,mido.MetaMessage('time_signature',numerator=numerator,denominator=denominator)))
    segments=vocal['notation'].get('key_segments',[]) or [{'start_tick':0,'key':vocal['notation']['key']}]
    for segment in segments:
        key=segment['key'];events.append((segment.get('start_tick',0),-1,mido.MetaMessage('key_signature',key=key['tonic']+('m' if key['mode']=='minor' else ''))))
    def append_events(track,items):
        previous=0
        for tick,priority,message in sorted(items,key=lambda x:(x[0],x[1])):
            track.append(message.copy(time=tick-previous));previous=tick
        track.append(mido.MetaMessage('end_of_track',time=max(0,vocal['statistics']['total_ticks']-previous)))
    append_events(conductor,events)
    channels=range(6) if arrangement['instrument']=='guitar' else range(2)
    for channel in channels:
        track=mido.MidiTrack();midi.tracks.append(track)
        values=[(0,-4,mido.MetaMessage('track_name',name='String '+str(6-channel) if arrangement['instrument']=='guitar' else ('Right hand' if channel==0 else 'Left hand'))),
                (0,-3,mido.Message('program_change',channel=channel,program=24 if arrangement['instrument']=='guitar' else 0))]
        # 4/4可选右手与实时谱面试听：修改MIDI使用经方向和实际弦组验证的同一演奏投影。
        # for note in arrangement['notes']:
        from guitar_pattern_performance import performance_notes
        for note in performance_notes(arrangement):
            destination=6-note['string'] if arrangement['instrument']=='guitar' else (0 if note['hand']=='right' else 1)
            if destination!=channel:continue
            values.extend([(note['start_tick'],2,mido.Message('note_on',channel=channel,note=note['pitch_midi'],velocity=note['velocity'])),
                           (note['end_tick'],1,mido.Message('note_off',channel=channel,note=note['pitch_midi'],velocity=0))])
        for pedal in arrangement.get('pedal',[]):values.append((pedal['tick'],-1 if not pedal['value'] else 0,mido.Message('control_change',channel=channel,control=64,value=pedal['value'])))
        append_events(track,values)
    midi.save(str(path))


# 和弦弹唱与伴奏编配：新增真实MIDI独立读回，比较全部实际音高、时值、通道与曲终。
def validate_midi(path,arrangement,vocal):
    import mido
    midi=mido.MidiFile(str(path));active={};observed=[];end=0;errors=[];tempos=[]
    for track in midi.tracks:
        tick=0
        for msg in track:
            tick+=msg.time
            if msg.type=='set_tempo':tempos.append((tick,msg.tempo))
            if msg.type=='note_on' and msg.velocity:
                key=(msg.channel,msg.note)
                if key in active:errors.append('midi_same_channel_pitch_overlap')
                active[key]=tick
            elif msg.type=='note_off' or (msg.type=='note_on' and not msg.velocity):
                key=(msg.channel,msg.note)
                if key not in active:errors.append('midi_note_off_without_attack');continue
                observed.append((active.pop(key),tick,msg.note,msg.channel))
        end=max(end,tick)
    # 4/4可选右手与实时谱面试听：修改独立读回按同一受限扫弦顺序核对，谱面仍用原拍位。
    # expected=sorted((n['start_tick'],n['end_tick'],n['pitch_midi'],6-n['string'] if arrangement['instrument']=='guitar' else (0 if n['hand']=='right' else 1)) for n in arrangement['notes'])
    from guitar_pattern_performance import performance_notes
    expected=sorted((n['start_tick'],n['end_tick'],n['pitch_midi'],6-n['string'] if arrangement['instrument']=='guitar' else (0 if n['hand']=='right' else 1)) for n in performance_notes(arrangement))
    if sorted(observed)!=expected:errors.append('midi_pitch_interval_or_channel_differs_from_project')
    if active:errors.append('midi_unreleased_notes')
    if end!=vocal['statistics']['total_ticks']:errors.append('midi_total_duration_mismatch')
    expected_tempos=sorted((t['tick'],mido.bpm2tempo(t['bpm'])) for t in vocal['tempo_events'])
    if sorted(tempos)!=expected_tempos:errors.append('midi_tempo_map_mismatch')
    return {'valid':not errors,'errors':errors,'note_count':len(observed),'total_ticks':end,'ticks_per_beat':midi.ticks_per_beat,
            'exact_pitches_intervals_channels_and_tempo':not errors}


# 和弦弹唱与伴奏编配：新增离线简化音色试听WAV，非原录音乐器音色，踏板发声显式模拟。
 # 器乐背景休止与旋律突出：修改，旧合成入口拆分原始信号与输出归一化，原声明保留。
# def synthesize(path,arrangement,vocal,sample_rate=22050):
# 4/4可选右手与实时谱面试听：修改新增局部音频窗口；默认完整合成使用旧原点与样本公式。
# def _synthesis_buffer(arrangement,vocal,sample_rate=22050):
def _synthesis_buffer(arrangement,vocal,sample_rate=22050,start_tick=None,end_tick=None):
    import soundfile as sf
    # 原曲拍轴与歌词拍位通用修复：修改，旧试听以谱首拍为音频零点保留；新源层正首拍前补原曲前沿，与原唱共同时钟。
    # clock=SongClock(vocal);origin=clock.seconds(0);duration=clock.seconds(clock.total_ticks)-origin
    clock=SongClock(vocal);origin=clock.audio_origin_seconds;duration=clock.seconds(clock.total_ticks)-origin
    # 4/4可选右手与实时谱面试听：新增只合成预览选区，沿原拍轴变速映射，进入窗口的持续音保持相位。
    if start_tick is not None:
        origin=clock.seconds(start_tick)
        duration=clock.seconds(clock.total_ticks if end_tick is None else end_tick)-origin
    output=np.zeros(math.ceil(duration*sample_rate),dtype=np.float32)
    pedal=sorted(arrangement.get('pedal',[]),key=lambda x:(x['tick'],bool(x['value'])))
    # 4/4可选右手与实时谱面试听：修改音频与MIDI共用逐弦扫过的发声顺序，默认音符列表原样传递。
    # for note in arrangement['notes']:
    from guitar_pattern_performance import performance_notes
    for note in performance_notes(arrangement):
        start=clock.seconds(note['start_tick'])-origin;end=clock.seconds(note['end_tick'])-origin
        # 4/4可选右手与实时谱面试听：新增窗口外音符不占预览时间。
        if start_tick is not None and (end<=0 or start>=duration):continue
        if arrangement['instrument']=='piano':
            state=0
            for mark in pedal:
                if mark['tick']<=note['end_tick']:state=mark['value']
                else:break
            if state:
                lift=next((x['tick'] for x in pedal if x['tick']>note['end_tick'] and x['value']==0),clock.total_ticks)
                end=min(end+2.,clock.seconds(lift)-origin)
        a=max(0,round(start*sample_rate));b=min(len(output),round((end+.045)*sample_rate))
        if b<=a:continue
        t=np.arange(b-a,dtype=np.float32)/sample_rate;freq=440*2**((note['pitch_midi']-69)/12)
        # 4/4可选右手与实时谱面试听：新增续音使用已流逝时间，避免预览首拍把旧长音重拨一次。
        if start_tick is not None and start<0:t+=-start
        tone=np.zeros_like(t)
        partials=(1.,.42,.20,.09,.04) if arrangement['instrument']=='piano' else (1.,.48,.28,.16,.08,.04)
        for harmonic,weight in enumerate(partials,start=1):
            if freq*harmonic>=sample_rate*.48:break
            tone+=weight*np.sin(2*np.pi*freq*harmonic*t)*np.exp(-t*(1.8+.24*harmonic if arrangement['instrument']=='piano' else 2.8+.30*harmonic))
        attack=np.minimum(1,t/.008);release=np.minimum(1,np.maximum(0,(b-a)/sample_rate-t)/.045)
        # 4/4可选右手与实时谱面试听：新增窗口续音的释放按剩余采样长度计算，音色相位仍沿用完整音。
        if start_tick is not None and start<0:
            release=np.minimum(1,np.maximum(0,(b-a)/sample_rate-(t+start))/.045)
        output[a:b]+=tone*attack*release*(note['velocity']/127)*.09
    # 器乐背景休止与旋律突出：修改，原归一化／写文件移至公开包装，先保留未归一化信号供基准力度比较。
    # peak=float(np.max(np.abs(output))) if len(output) else 0
    # if peak>0:output*=.86/peak
    # if not np.isfinite(output).all():raise ValueError('试听合成非有限值。')
    # sf.write(str(path),output,sample_rate,subtype='PCM_16')
    # return {'sample_rate':sample_rate,'duration_seconds':len(output)/sample_rate,
    #         'origin_song_seconds':origin,'timbre':'local_additive_synthesis_preview_not_original_instrument',
    #         'finite_samples':True,'peak':float(np.max(np.abs(output)))}
    return output,origin


# 器乐背景休止与旋律突出：新增沿用原稿整体基准增益，避免删除背景音后把正文被动放大；所有试听仍来自实际音符。
def synthesize(path,arrangement,vocal,sample_rate=22050):
    import soundfile as sf
    output,origin=_synthesis_buffer(arrangement,vocal,sample_rate)
    peak=float(np.max(np.abs(output))) if len(output) else 0
    reference_peak=peak
    if arrangement.get('instrumental_expression'):
        from guitar_instrumental_expression import expression_parent
        original=expression_parent(arrangement)['arrangements']['guitar']
        reference,_=_synthesis_buffer(original,vocal,sample_rate)
        reference_peak=float(np.max(np.abs(reference))) if len(reference) else peak
        # 器乐背景休止与旋律突出：新增真实秒窗口内强制静音，合成响尾不能漏进已确认休止。
        for rest in arrangement['instrumental_expression']['settings']['rest_intervals']:
            a=max(0,math.floor((rest['start_seconds']-origin)*sample_rate))
            b=min(len(output),math.ceil((rest['end_seconds']-origin)*sample_rate))
            output[a:b]=0
        peak=float(np.max(np.abs(output))) if len(output) else 0
    normalization_gain=.86/reference_peak if reference_peak>0 else 1.
    headroom_scale=min(1.,.995/(peak*normalization_gain)) if peak>0 else 1.
    output*=normalization_gain*headroom_scale
    if not np.isfinite(output).all():raise ValueError('试听合成非有限值。')
    sf.write(str(path),output,sample_rate,subtype='PCM_16')
    return {'sample_rate':sample_rate,'duration_seconds':len(output)/sample_rate,
        'origin_song_seconds':origin,'timbre':'local_additive_synthesis_preview_not_original_instrument',
        'finite_samples':True,'peak':float(np.max(np.abs(output))),
        'normalization_gain':normalization_gain,'reference_peak':reference_peak,'headroom_scale':headroom_scale}


# 和弦弹唱与伴奏编配：新增复用认可简谱的参考行，仅提取已有绘图，不改音符歌词或原文件。
def vocal_row(vocal,first,last):
    scene=score.render_jianpu(vocal,first,last,True);out=score.Scene(scene.width)
    def move(item,dy):
        kind=item[0];v=list(item)
        if kind=='text':v[2]+=dy
        elif kind=='line':v[2]+=dy;v[4]+=dy
        elif kind in ('dot','arc'):v[2]+=dy
        elif kind=='group_start':v[1]='vocal-'+v[1]
        return tuple(v)
    for item in scene.items:
        if item[0]=='text' and (item[2]<160 or item[2]>=scene.height-30):continue
        if item[0]=='text' and item[2]==168 and item[3].isdigit():continue
        out.items.append(move(item,-132))
    out.height=190;out.measure_boxes=scene.measure_boxes
    return out


# 和弦弹唱与伴奏编配：新增根据人声拍组的真实坐标插值，TAB与人声共用横向拍位。
def tick_x(box,offset):
    if box.get('tick_positions'):
        ticks=sorted(box['tick_positions']);return float(np.interp(offset,ticks,[box['tick_positions'][t] for t in ticks]))
    beat=next((b for b in box['beats'] if b['start_tick']<=offset<b['end_tick']),box['beats'][-1])
    known={g['tick']:g['x'] for g in beat['glyphs']}
    known.setdefault(beat['start_tick'],beat['x']+8);known[beat['end_tick']]=beat['x']+beat['width']-8
    ticks=sorted(known)
    return float(np.interp(offset,ticks,[known[t] for t in ticks]))


# 和弦弹唱与伴奏编配：新增人声/TAB联合拍内留白，避免稀疏人声使密集双位品号重叠。
# 节奏符号说明与声部对齐：修改，完整注释保留原横向插值，避免装饰间距拉伸和倚音重叠。
# def joint_guitar_layout(scene,arrangement,bar,first,last):
#     plans={};new_width=344
#     for number,box in scene.measure_boxes.items():
#         onsets={n['start_tick']-(number-1)*bar for n in arrangement['notes'] if (number-1)*bar<=n['start_tick']<number*bar}
#         # 和弦指型与X六线谱：新增为每张指型留出横向空间，文字与音符仍共用拍位。
#         markers={d['draw_tick']-(number-1)*bar for d in arrangement.get('_row_diagram_markers',[]) if (number-1)*bar<=d['draw_tick']<number*bar}
#         onsets.update(markers)
#         beats=[]
#         for beat in box['beats']:
#             ticks=sorted({g['tick'] for g in beat['glyphs']}|{t for t in onsets if beat['start_tick']<=t<beat['end_tick']})
#             if not ticks:ticks=[beat['start_tick']]
#             # 和弦指型与X六线谱：修改，原固定音符格保留；指型格加宽避免相邻网格重叠。
#             # minimum=16+len(ticks)*34+max(0,len(ticks)-1)*8
#             # beats.append((beat,ticks,minimum))
#             cells=[106 if t in markers else 42 for t in ticks]
#             minimum=16+sum(cells)-8
#             beats.append((beat,ticks,minimum,cells))
#         plans[number]=beats;new_width=max(new_width,sum(x[2] for x in beats)+28*(len(beats)-1)+36)
#     old_points,new_points=[],[];boxes={}
#     for index,(number,old) in enumerate(scene.measure_boxes.items()):
#         new_x=52+index*new_width;beats=plans[number];spare=(new_width-36-28*(len(beats)-1)-sum(x[2] for x in beats))/len(beats)
#         cursor=new_x+18;positions={};new_beats=[]
#         old_points.extend([old['x'],old['x']+old['width']]);new_points.extend([new_x,new_x+new_width])
#         # 和弦指型与X六线谱：修改，原三元组保留，增加每个拍内格的宽度。
#         # for old_beat,ticks,minimum in beats:
#         for old_beat,ticks,minimum,cells in beats:
#             width=minimum+spare
#             old_points.extend([old_beat['x'],old_beat['x']+old_beat['width']]);new_points.extend([cursor,cursor+width])
#             # 和弦指型与X六线谱：修改，原等宽定位保留；中心对齐宽窄不同的格。
#             # for cell,tick in enumerate(ticks):positions[tick]=cursor+8+17+cell*42+spare/2
#             used=0
#             for tick,cell_width in zip(ticks,cells):
#                 positions[tick]=cursor+8+(cell_width-8)/2+used+spare/2;used+=cell_width
#             for glyph in old_beat['glyphs']:
#                 old_points.append(glyph['x']);new_points.append(positions[glyph['tick']])
#             new_beats.append({**old_beat,'x':cursor,'width':width});cursor+=width+28
#         positions[bar]=new_x+new_width-12
#         boxes[number]={**old,'x':new_x,'width':new_width,'beats':new_beats,'tick_positions':positions}
#     mapping=sorted(zip(old_points,new_points));unique={a:b for a,b in mapping};xs=sorted(unique)
#     def remap(x):return float(np.interp(x,xs,[unique[a] for a in xs]))
#     changed=[]
#     for item in scene.items:
#         v=list(item)
#         if item[0] in ('text','dot'):v[1]=remap(v[1])
#         elif item[0] in ('line','arc'):v[1]=remap(v[1]);v[3]=remap(v[3])
#         changed.append(tuple(v))
#     # 和弦指型与X六线谱：修改，原固定四小节画布保留；按实际行小节数计算。
#     # scene.items=changed;scene.measure_boxes=boxes;scene.width=52+4*new_width+42
#     scene.items=changed;scene.measure_boxes=boxes;scene.width=52+len(boxes)*new_width+42
#     return scene

# 节奏符号说明与声部对齐：新增同刻音符共用中心，非同时起音保留独立拍点。
def joint_guitar_layout(scene,arrangement,bar,first,last):
    return layout_shared_time(scene,arrangement,bar)


# 和弦弹唱与伴奏编配：新增六线谱与节奏/持续线/实际左手指法，不包含吉他五线谱。
# 和弦指型与X六线谱：修改，原数字六线谱函数保留为基础绘图，后续仅替换显示。
# def guitar_row(shared,vocal,arrangement,first,last):
def _numeric_guitar_row(shared,vocal,arrangement,first,last):
    # 器乐背景休止与旋律突出：修改，旧参考行保留；授权背景段的无歌词候选仅在参考视图休止，原人声快照不改。
    # scene=vocal_row(vocal,first,last);bar=vocal['statistics']['bar_ticks'];start=(first-1)*bar;end=last*bar
    from guitar_instrumental_expression import reference_vocal
    # 重复乐句折叠与多遍挂词：修改参考行入口，旧单遍生成保留；新版可提供已经共同对齐的第一遍。
    # scene=vocal_row(reference_vocal(vocal,arrangement),first,last);bar=vocal['statistics']['bar_ticks'];start=(first-1)*bar;end=last*bar
    scene=copy.deepcopy(arrangement['_repeat_scene']) if arrangement.get('_repeat_scene') is not None else vocal_row(reference_vocal(vocal,arrangement),first,last)
    bar=vocal['statistics']['bar_ticks'];start=(first-1)*bar;end=last*bar
    # 常用指型与器乐独奏：新增保留拍位布局而去除无演唱器乐行的空简谱层。
    if arrangement.get('_instrumental_tab_only'):scene.items=[]
    # 重复乐句折叠与多遍挂词：修改布局入口，旧单声部对齐保留；共同时间列不再次被单遍重排。
    # scene=joint_guitar_layout(scene,arrangement,bar,first,last)
    if arrangement.get('_repeat_scene') is None:scene=joint_guitar_layout(scene,arrangement,bar,first,last)
    # 和弦弹唱与伴奏编配：新增转调文字回到小节标题行，避开同一位置的和弦名。
    scene.items=[item for item in scene.items if not (item[0]=='text' and item[3].startswith('转1='))]
    # 重复乐句折叠与多遍挂词：新增仅在折叠视图分组人声，便于上叠各遍；原伴奏／和弦几何完全沿用。
    if arrangement.get('_repeat_scene') is not None:
        scene.items=[('group_start','repeat-vocal-main')]+scene.items+[('group_end',)]
    for measure,box in scene.measure_boxes.items():
        x,width=box['x'],box['width'];tick0=(measure-1)*bar
        scene.start_measure(measure)
        texture=shared['measure_textures'][measure-1]
        # 和弦弹唱与伴奏编配：修改，原标题保留，转调小节在标题上明确1的调号。
        # scene.text(x+5,16,str(measure)+' · '+SECTION_LABELS[texture['section']]+' · '+KIND_LABELS[texture['kind']],14,'#62757c','start')
        # 结构稳定伴奏与人声合播：修改，原代码注释保留。
        # key_label=' · 转1='+SongClock(vocal).key(tick0)['tonic'] if any(s['start_measure']==measure and measure>1 for s in vocal['notation'].get('key_segments',[])) else ''
        key_label=' · 转1='+SongClock(vocal).key(tick0)['tonic'] if any(s['start_measure']==measure and measure>1 for s in vocal['notation'].get('key_segments',[])) else ''
        for segment in arrangement['configuration'].get('capo_segments',[])[1:]:
            if segment['start_tick']==tick0:
                key_label+=' · 夹'+str(capo_at(arrangement,tick0-1))+'→'+str(segment['capo_fret'])+'品'
        # 分解和弦优先：修改，小节标题显示实际编配，原观察标签保留在共享分析。
        # scene.text(x+5,16,str(measure)+' · '+SECTION_LABELS[texture['section']]+' · '+KIND_LABELS[texture['kind']]+key_label,14,'#62757c','start')
        label=arranged_texture_label(arrangement,tick0,tick0+bar,texture['kind'])
        # 常用指型与器乐独奏：新增独奏标题，和弦仍可在匹配的短段出现，不将后台候选强标在谱上。
        regions=[r for r in arrangement.get('notation_regions',[]) if r['start_tick']<tick0+bar and r['end_tick']>tick0]
        if regions and all(r['mode']=='solo_tab' for r in regions) and texture['section'] in ('intro','interlude','outro'):
            label='独奏'
        # 器乐背景休止与旋律突出：新增真正无发声音的小节明确标休止，避免把已删除背景音仍称为独奏／延音。
        if arrangement.get('instrumental_expression') and not any(n['start_tick']<tick0+bar and n['end_tick']>tick0 for n in arrangement['notes']):
            label='休止'
            scene.text(x+width/2,344,'休止',14,'#62757c')
        # 强拍相位与伴奏同步纠错：修改，原内部编号保留；预备弱起不计入正式小节。
        # scene.text(x+5,16,str(measure)+' · '+SECTION_LABELS[texture['section']]+' · '+label+key_label,14,'#62757c','start')
        from beat_phase_alignment import display_measure
        scene.text(x+5,16,display_measure(vocal,measure)+' · '+SECTION_LABELS[texture['section']]+' · '+label+key_label,14,'#62757c','start')
        for string in range(1,7):
            scene.line(x,226+(string-1)*17,x+width,226+(string-1)*17,'#788895',.9)
        scene.line(x,222,x,315,'#788895',1.2);scene.line(x+width,222,x+width,315,'#788895',1.2)
        for beat in box['beats']:
            px=tick_x(box,beat['start_tick']);scene.text(px,376,str(beat['number']),11,'#8a989d')
        chords=[h for h in shared['harmony'] if tick0<=h['start_tick']<tick0+bar]
        if not chords or chords[0]['start_tick']>tick0:
            chords.insert(0,harmony_at(shared,tick0))
        for chord in chords:
            at=max(tick0,chord['start_tick']);px=tick_x(box,at-tick0)
            # 结构稳定伴奏与人声合播：修改，原代码注释保留。
            # shape_key=score.key_definition(pc_name(chord['key']['tonic_pc']-arrangement['configuration']['capo_fret'],chord['key'])+':major')
            # name='N.C.' if chord['name']=='N.C.' else chord_name(chord['root_pc']-arrangement['configuration']['capo_fret'],chord['quality'],chord['bass_pc']-arrangement['configuration']['capo_fret'],shape_key)
            current_capo=capo_at(arrangement,at)
            from accompaniment_arrange import capo_shape_key
            shape_key=capo_shape_key(chord['key'],current_capo)
            name='N.C.' if chord['name']=='N.C.' else chord_name(chord['root_pc']-current_capo,chord['quality'],chord['bass_pc']-current_capo,shape_key)
            scene.text(px,45,name,17,'#234945',weight='bold')
        scene.end_measure()
    # 规整分解节奏与延音显示：新增已经在上一小节发声的续段，不再次绘制攻击符干。
    continuations=draw_continuations(scene,arrangement,first,last,bar,tick_x)
    relevant=[n for n in arrangement['notes'] if start<=n['start_tick']<end]
    by_tick=defaultdict(list)
    for note in relevant:by_tick[note['start_tick']].append(note)
    last_position=None
    for tick,notes in sorted(by_tick.items()):
        number=tick//bar+1;box=scene.measure_boxes[number];px=tick_x(box,tick%bar)
        for note in notes:
            y=226+(note['string']-1)*17;color='#147264' if note['role']=='instrumental_melody' else '#8b5b28' if note['role']=='bass' else '#18334b'
            scene.items.append(('group_start',note['id']))
            scene.text(px,y,note['fret'],20,color,weight='bold')
            # 和弦弹唱与伴奏编配：新增小号指法贴近对应品号，取消会挤在一起的长指法串。
            if note['finger']:scene.text(px+12,y-7,note['finger'],8,'#62757c')
            scene.items.append(('group_end',))
            if note['end_tick']-tick>240:
                finish=min(note['end_tick'],number*bar)
                x2=tick_x(box,min(bar-1,finish-(number-1)*bar))
                if x2>px+14:scene.line(px+12,y+5,x2-3,y+5,color,.7)
        # 六线谱同拍节奏连线：修改，原逐音短斜旗保留；统一在SVG阶段画同拍横梁。
        # minimum=min(n['end_tick']-tick for n in notes);flags=2 if minimum<240 else 1 if minimum<480 else 0
        # scene.line(px,328,px,352,'#344c60',1.3)
        # for flag in range(flags):scene.line(px,352-flag*6,px+9,347-flag*6,'#344c60',2)
        # if minimum>=960:scene.dot(px,360,3,'#ffffff');scene.arc(px-3,361,px+3,-3,'#344c60')
        # 和弦弹唱与伴奏编配：修改，原指法串与每次重复手位数字保留，改为逐音小指法及变化时标手位。
        # fingers='/'.join(str(n['finger']) for n in sorted(notes,key=lambda n:n['string']) if n['finger'])
        # if fingers:scene.text(px,397,fingers,11,'#62757c')
        # scene.text(px,205,str(notes[0].get('hand_position','')),10,'#62757c')
        # 常用指型与器乐独奏：修改，原逐音手位保留；采用完整持握路径的真实攻击手位标记。
        # position=notes[0].get('hand_position')
        position=next((p['position'] for p in reversed(arrangement.get('grip_hand_positions',[])) if p['tick']<=tick),notes[0].get('hand_position'))
        if position!=last_position:scene.text(px,205,'位'+str(position),10,'#62757c');last_position=position
        event=next((e for e in arrangement['attack_events'] if e['start_tick']==tick),None)
        if event and event.get('stroke'):
            scene.text(px,319,'↓' if event['stroke']=='down' else '↑',17,'#62757c')
    # 和弦弹唱与伴奏编配：修改，指法已移至品号旁，原420高度保留。
    # scene.height=420
    scene.height=395
    root=ET.fromstring(scene.svg())
    # 节奏符号说明与声部对齐：新增绑定可见主音/休止/横线和倚音，便于按工程时间逐项回读。
    annotate_vocal_glyphs(root,scene)
    # 规整分解节奏与延音显示：新增续音的实际身份及“无需重拨”提示。
    annotate_continuations(root,continuations)
    by_id={n['id']:n for n in relevant}
    for group in root.iter('{'+SVG_NS+'}g'):
        if group.get('id') in by_id:
            note=by_id[group.get('id')];group.set('data-string',str(note['string']));group.set('data-start-tick',str(note['start_tick']));group.set('data-end-tick',str(note['end_tick']))
            text_node=group.find('{'+SVG_NS+'}text');x=float(text_node.get('x'));y=float(text_node.get('y'))
            group.insert(0,ET.Element('{'+SVG_NS+'}rect',x=str(x-12),y=str(y-10),width='24',height='20',fill='white'))
            tag(group,'{'+SVG_NS+'}title',f"{note['id']} · {note['role']} · 左手{note['finger']}指 · MIDI {note['pitch_midi']}")
    # 和弦指型与X六线谱：新增真实弦线标记和排版锚点，供图式绘制及独立几何校验。
    for line in root.iter('{'+SVG_NS+'}line'):
        y=float(line.get('y1','0'))
        if line.get('y1')==line.get('y2') and any(abs(y-(226+i*17))<.01 for i in range(6)):
            line.set('class','tab-string-line')
    for chart in arrangement.get('_row_diagram_markers',[]):
        tick=chart['draw_tick'];box=scene.measure_boxes[tick//bar+1]
        ET.SubElement(root,'{'+SVG_NS+'}g',{'class':'diagram-anchor','data-display-id':chart['display_id'],'data-x':str(tick_x(box,tick%bar))})
    # 六线谱同拍节奏连线：新增短音同拍水平连接；同刻多弦只画一个节奏符干。
    # 规整分解节奏与延音显示：修改，原按每弦持续值保留；普通分解使用实际右手拍格。
    # events=rhythm_events(relevant,vocal['timing']['meter'],bar)
    events=arrangement_rhythm_events(arrangement,vocal['timing']['meter'],bar,relevant)
    for node in draw_rhythm(events,lambda tick:tick_x(scene.measure_boxes[tick//bar+1],tick%bar)):
        root.append(node)
    return ET.tostring(root,encoding='unicode')


# 和弦指型与X六线谱：新增行内黑点指型与自定义x表示，实际音符/时值不变。
def guitar_row(shared,vocal,arrangement,first,last):
    # 常用指型与器乐独奏：修改，原空图列表视为未准备保留；整首纯数字谱允许零张图。
    # if not arrangement.get('fingering_diagrams'):prepare_diagrams(shared,arrangement)
    if 'fingering_diagrams' not in arrangement:prepare_diagrams(shared,arrangement,vocal)
    # 空弦沿用指型X表示：新增旧工程重导时更新显示规则，不重新编配指型或音符。
    set_tab_display(arrangement)
    # 六线谱同拍节奏连线：新增按真实拍号更新显示约定，保持原来的图/x派生过程。
    prepare_rhythm(vocal,arrangement)
    # 节奏符号说明与声部对齐：新增既有工程重导的显示配置，不重写伴奏音序。
    prepare_alignment(arrangement)
    charts=visible_diagrams(shared,arrangement,first,last)
    # 常用指型与器乐独奏：修改，原绘图配置保留；无演唱器乐行压缩为仅六线谱。
    # drawing={**arrangement,'_row_diagram_markers':charts}
    # 器乐背景休止与旋律突出：修改，旧含背景候选的器乐行判定保留，实际简谱参考仅使用授权清理视图。
    # tab_only=bool(arrangement.get('notation_regions')) and instrumental_guitar_row(shared,vocal,first,last)
    from guitar_instrumental_expression import reference_vocal
    tab_only=bool(arrangement.get('notation_regions')) and instrumental_guitar_row(shared,reference_vocal(vocal,arrangement),first,last)
    drawing={**arrangement,'_row_diagram_markers':charts,'_instrumental_tab_only':tab_only}
    root=ET.fromstring(_numeric_guitar_row(shared,vocal,drawing,first,last));ns='{'+SVG_NS+'}'
    anchors={n.get('data-display-id'):float(n.get('data-x')) for n in root if n.get('class')=='diagram-anchor'}
    headers=[]
    for parent in list(root.iter()):
        for node in list(parent):
            if node.get('class')=='diagram-anchor':parent.remove(node)
            elif node.tag==ns+'text' and float(node.get('y','-1')) in (16,45):
                y=float(node.get('y'));parent.remove(node)
                # 结构稳定伴奏与人声合播：修改，原代码注释保留。
                # if y==16:headers.append(node)
                if y==16:
                    # 强拍相位与伴奏同步纠错：修改，原把显示编号当时间索引保留；弱起和正式编号转回内部索引。
                    # number=int(node.text.split(' · ')[0])
                    measure_label=node.text.split(' · ')[0]
                    number=1 if measure_label=='弱起' else int(measure_label)+vocal['timing'].get('measure_number_offset',0)
                    segment=next((s for s in arrangement['configuration'].get('capo_segments',[])[1:] if s['start_measure']==number),None)
                    if segment:
                        marker=ET.Element(ns+'g',{'class':'capo-change-marker','data-start-tick':str(segment['start_tick']),'data-capo-fret':str(segment['capo_fret'])})
                        marker.append(node);headers.append(marker)
                    else:headers.append(node)
                # 常用指型与器乐独奏：修改，原无和弦提示保留；新版纯数字区不附和弦层文字。
                # elif node.text=='N.C.':node.set('y','40');headers.append(node)
                elif node.text=='N.C.' and not arrangement.get('notation_regions'):
                    node.set('y','40');headers.append(node)
    notes={n['id']:n for n in arrangement['notes']}
    for group in root.iter(ns+'g'):
        if not group.get('data-string'):continue
        note=notes[group.get('id')];text=group.find(ns+'text')
        chart=next((d for d in charts if d['draw_tick']<=note['start_tick']<d['display_end_tick']),None)
        # 空弦沿用指型X表示：修改，原仅正品位匹配保留；未按空弦与横按覆盖均按真实左手状态判断。
        # held=chart is not None and note['fret']>0 and chart['frets'].get(str(note['string']),-1)==note['fret']
        held=chart is not None and note['fret']==left_hand_fret(chart,note['string'])
        text.text='x' if held else str(note['fret'])
        # 器乐背景休止与旋律突出：新增只在主旋律的新起音上方画黑点；续音和填充不加，音值／连奏不变。
        if note.get('melody_accent'):
            ET.SubElement(root,ns+'circle',{'class':'melody-accent','data-note-id':note['id'],
                'data-start-tick':str(note['start_tick']),'cx':text.get('x'),'cy':'215','r':'3','fill':'black'})
        if chart:group.set('data-diagram-id',chart['display_id'])
        # 常用指型与器乐独奏：新增明确无图音符模式，无图空弦保持0，不能沿用上一段的x。
        if arrangement.get('notation_regions'):group.set('data-notation-mode','chord_grip' if chart else 'solo_tab')
        for finger in list(group.findall(ns+'text')):
            if finger is not text:group.remove(finger)
    # 常用指型与器乐独奏：修改，原固定预留简谱/指型高度保留；纯器乐行去除空白层。
    # width=float(root.get('width'));height=float(root.get('height'))+TOP_SPACE
    # 常用指型与器乐独奏：修改，原混合演唱行总预留指型高度保留；没有图式时移除空白指型层。
    # offset=(TOP_SPACE if charts or not tab_only else 0)-(170 if tab_only else 0)
    offset=(TOP_SPACE if charts else 0)-(170 if tab_only else 0)
    width=float(root.get('width'));height=float(root.get('height'))+offset
    root.set('height',str(height));root.set('viewBox',f'0 0 {width:g} {height:g}')
    # 常用指型与器乐独奏：修改，原统一上移层保留；内部弦线/节奏坐标不变，整体按行模式定位。
    # body=ET.Element(ns+'g',{'class':'score-body','transform':f'translate(0,{TOP_SPACE})'})
    body=ET.Element(ns+'g',{'class':'score-body','transform':f'translate(0,{offset})'})
    # 常用指型与器乐独奏：新增独立读回用的实际行范围，纯器乐行也保留六弦和按拍节奏。
    root.set('data-first-measure',str(first));root.set('data-last-measure',str(last))
    if tab_only:root.set('data-instrumental-tab-only','true')
    for node in list(root):root.remove(node);body.append(node)
    ET.SubElement(root,ns+'rect',{'x':'0','y':'0','width':str(width),'height':str(height),'fill':'white'})
    root.append(body)
    for node in headers:root.append(node)
    for chart in charts:root.append(draw_diagram(chart,anchors[chart['display_id']]))
    return ET.tostring(root,encoding='unicode')


# 和弦弹唱与伴奏编配：新增清楚的和弦图参考页，实际声部/换把以六线谱为准。
# 和弦指型与X六线谱：修改，原带指号参考图保留；新版统一用黑点和首行品数。
# def chord_chart_svg(chart):
def _numbered_chord_chart_svg(chart):
    # 和弦弹唱与伴奏编配：修改，跨度5品需显示6格，原5格画布保留。
    # scene=score.Scene(170);position=max(1,chart['position']);scene.height=178
    scene=score.Scene(170);position=max(1,chart['position']);scene.height=194
    scene.text(85,14,chart['shape_name'],19,'#234945',weight='bold')
    scene.text(85,36,chart['sounding_name'],11,'#62757c')
    # 和弦弹唱与伴奏编配：修改，原5格网格注释保留。
    # for i in range(6):scene.line(42+i*18,62,42+i*18,142,'#566a78',1)
    # for fret in range(6):scene.line(42,62+fret*16,132,62+fret*16,'#566a78',2 if fret==0 and position==1 else 1)
    for i in range(6):scene.line(42+i*18,62,42+i*18,158,'#566a78',1)
    for fret in range(7):scene.line(42,62+fret*16,132,62+fret*16,'#566a78',2 if fret==0 and position==1 else 1)
    scene.text(28,70,position,11,'#62757c')
    for string in range(6,0,-1):
        x=42+(6-string)*18;fret=chart['frets'].get(str(string),-1)
        if fret<=0:scene.text(x,51,'○' if fret==0 else '×',13,'#566a78')
        else:
            y=62+(fret-position+.5)*16;scene.dot(x,y,6,'#234945')
            finger=chart['fingers'].get(str(string),chart['fingers'].get(string,''))
            scene.text(x,y,finger,9,'white')
    # 和弦弹唱与伴奏编配：修改，扩展网格后参考说明下移，原位置保留。
    # scene.text(85,161,'夹'+str(chart['capo'])+'品 · 指型参考',11,'#62757c')
    scene.text(85,180,'夹'+str(chart['capo'])+'品 · 指型参考',11,'#62757c')
    return scene.svg()


# 和弦指型与X六线谱：新增离线黑点指型目录，展示与正文一致的实际按法。
def chord_chart_svg(chart):
    ns='{'+SVG_NS+'}';root=ET.Element(ns+'svg',{'width':'180','height':'186','viewBox':'0 0 180 186'})
    display={**chart,'display_id':'catalog-'+chart['id'],'draw_tick':chart['start_tick'],'display_end_tick':chart['end_tick']}
    root.append(draw_diagram(display,90))
    text=ET.SubElement(root,ns+'text',{'x':'90','y':'172','font-size':'11','text-anchor':'middle','fill':'#62757c'})
    text.text=f"实际 {chart['sounding_name']} · 夹{chart['capo']}品"
    return ET.tostring(root,encoding='unicode')


# 和弦弹唱与伴奏编配：新增谱面和弦使用正常文本字体，避免SMuFL私用升降号在系统字体显示错形。
def normalize_harmony_svg(svg,shared,mei=None):
    # 和弦弹唱与伴奏编配：修改，Verovio重建harm ID，改用其真实小节/拍位置绑定原和弦。
    # root=ET.fromstring(svg);names={h['id']:h['name'] for h in shared['harmony']};normalized=0
    root=ET.fromstring(svg);names={};normalized=0
    mei_ns='{http://www.music-encoding.org/ns/mei}';xml_id='{http://www.w3.org/XML/1998/namespace}id'
    if mei is not None:
        for measure in mei.iter(mei_ns+'measure'):
            for harmonic in measure.findall(mei_ns+'harm'):
                tick=(int(measure.get('n'))-1)*shared['statistics']['bar_ticks']+round((float(harmonic.get('tstamp'))-1)*PPQ)
                names[harmonic.get(xml_id)]=harmony_at(shared,tick)['name']
    for group in root.iter('{'+SVG_NS+'}g'):
        if 'harm' not in group.get('class','').split():continue
        # 和弦弹唱与伴奏编配：修改，原试图使用MusicXML和弦ID保留为注释。
        # identity=group.get('id','').split('_measure_')[0]
        identity=group.get('id','')
        if identity not in names:raise ValueError('和弦谱面缺少同源ID，不能替换未知文字。')
        text=group.find('.//{'+SVG_NS+'}text')
        if text is None:raise ValueError('和弦谱面未生成文字坐标。')
        for child in list(text):text.remove(child)
        # 和弦弹唱与伴奏编配：修改，正常中文字体用适合音乐SVG内部坐标的字号，原值保留。
        # text.text=names[identity];text.set('font-family','Microsoft YaHei, sans-serif');text.set('font-size','180px')
        text.text=names[identity];text.set('font-family','Microsoft YaHei, sans-serif');text.set('font-size','260px')
        normalized+=1
    return ET.tostring(root,encoding='unicode'),normalized


# 和弦弹唱与伴奏编配：新增节选边界仅用于预览的裁切，完整MusicXML及试听时值保持。
def trim_excerpt_edges(root,first,last,bar):
    measure0=(first-1)*bar;measure1=last*bar;pedal_down=False
    for measure in root.findall('part/measure'):
        number=int(measure.get('number'))
        for note in measure.findall('note'):
            identity=note.get('id','')
            if '_fragment_' not in identity:continue
            # 和弦弹唱与伴奏编配：新增跨节选边界的延音标记去除，避免渲染器寻找不存在的另一端。
            if number==first:
                cursor_tick=int(identity.rsplit('_fragment_',1)[1])
                if cursor_tick==measure0:
                    for mark in list(note.findall('tie')):
                        if mark.get('type')=='stop':note.remove(mark)
                    for mark in list(note.findall('notations/tied')):
                        if mark.get('type')=='stop':note.find('notations').remove(mark)
            if number==last:
                cursor_tick=int(identity.rsplit('_fragment_',1)[1]);length=int(note.findtext('duration'))
                if cursor_tick+length==measure1:
                    for mark in list(note.findall('tie')):
                        if mark.get('type')=='start':note.remove(mark)
                    for mark in list(note.findall('notations/tied')):
                        if mark.get('type')=='start':note.find('notations').remove(mark)
        # 和弦弹唱与伴奏编配：新增每小节踏板按时间排序，丢掉来自节选之前的孤立抬踏板。
        directions=[]
        for direction in list(measure.findall('direction')):
            pedal=direction.find('direction-type/pedal')
            if pedal is not None:
                directions.append((int(direction.findtext('offset','0')),0 if pedal.get('type')=='stop' else 1,direction,pedal))
                measure.remove(direction)
        accepted=[]
        for offset,priority,direction,pedal in sorted(directions,key=lambda x:(x[0],x[1])):
            if pedal.get('type')=='stop' and not pedal_down:continue
            pedal_down=pedal.get('type')=='start';accepted.append(direction)
        insert=1 if measure.find('attributes') is not None else 0
        for direction in accepted:measure.insert(insert,direction);insert+=1


# 和弦弹唱与伴奏编配：新增钢琴真实分页与逐四小节大谱表，程序往返与GUI往返分开。
def render_piano(root,output,shared,vocal):
    import verovio
    output=Path(output);pages=output/'staff_pages';pages.mkdir(parents=True,exist_ok=True)
    data=ET.tostring(root,encoding='unicode');toolkit=verovio.toolkit()
    if not toolkit.setOptions(RENDER_OPTIONS) or not toolkit.loadData(data):raise ValueError('钢琴整曲渲染导入失败：'+toolkit.getLog())
    all_ids=set();files=[]
    for number in range(1,toolkit.getPageCount()+1):
        # 和弦弹唱与伴奏编配：修改，原直接写SVG保留，和弦文字改正常字体显示。
        # svg=toolkit.renderToSVG(number);(pages/f'page_{number:03}.svg').write_text(svg,encoding='utf-8');files.append(str(pages/f'page_{number:03}.svg'))
        # 和弦弹唱与伴奏编配：修改，传入真实MEI位置映射，原调用保留。
        # svg,_=normalize_harmony_svg(toolkit.renderToSVG(number),shared)
        svg,_=normalize_harmony_svg(toolkit.renderToSVG(number),shared,ET.fromstring(toolkit.getMEI()))
        (pages/f'page_{number:03}.svg').write_text(svg,encoding='utf-8');files.append(str(pages/f'page_{number:03}.svg'))
        all_ids.update(n.get('id') for n in ET.fromstring(svg).iter() if n.get('id'))
    expected={n.get('id') for n in root.findall('part/measure/note') if n.find('pitch') is not None}
    if not expected.issubset(all_ids):raise ValueError('钢琴实际分页漏音符ID。')
    rows=[];row_dir=output/'rows';row_dir.mkdir(parents=True,exist_ok=True)
    # 强拍相位与伴奏同步纠错：修改，原从内部1每4节分行保留；弱起另列以使首句四小节同一行。
    # for first in range(1,vocal['statistics']['measure_count']+1,4):
    #     last=min(first+3,vocal['statistics']['measure_count']);subset=copy.deepcopy(root);part=subset.find('part')
    from beat_phase_alignment import score_row_ranges
    for first,last in score_row_ranges(vocal):
        subset=copy.deepcopy(root);part=subset.find('part')
        for measure in list(part):
            if not first<=int(measure.get('number'))<=last:part.remove(measure)
        first_measure=part.find('measure')
        old=first_measure.find('attributes')
        if old is not None:first_measure.remove(old)
        attrs_holder=ET.Element('temporary');xml_attributes(attrs_holder,SongClock(vocal).key((first-1)*vocal['statistics']['bar_ticks']),vocal['timing']['meter'],'piano',initial=True)
        first_measure.insert(0,attrs_holder[0])
        trim_excerpt_edges(subset,first,last,vocal['statistics']['bar_ticks'])
        row_options={**RENDER_OPTIONS,'pageWidth':2600,'pageHeight':1200,'scale':50,'breaks':'none','adjustPageHeight':True,
                     'header':'none','footer':'none','spacingSystem':3,'pageMarginTop':50,'pageMarginBottom':50}
        local=verovio.toolkit()
        if not local.setOptions(row_options) or not local.loadData(ET.tostring(subset,encoding='unicode')):
            raise ValueError('钢琴节选渲染失败：'+local.getLog())
        if local.getPageCount()!=1:raise ValueError('四小节钢琴参考行意外分页。')
        # 和弦弹唱与伴奏编配：修改，原直接渲染保留，节选与整曲采用同一正常和弦文字。
        # svg=local.renderToSVG(1);path=row_dir/f'measures_{first:03}_{last:03}.svg';path.write_text(svg,encoding='utf-8')
        # 和弦弹唱与伴奏编配：修改，节选使用它自己的MEI映射，原调用保留。
        # svg,_=normalize_harmony_svg(local.renderToSVG(1),shared)
        svg,_=normalize_harmony_svg(local.renderToSVG(1),shared,ET.fromstring(local.getMEI()))
        path=row_dir/f'measures_{first:03}_{last:03}.svg';path.write_text(svg,encoding='utf-8')
        vocal_svg=vocal_row(vocal,first,last).svg();vpath=row_dir/f'vocal_{first:03}_{last:03}.svg';vpath.write_text(vocal_svg,encoding='utf-8')
        rows.append({'first':first,'last':last,'staff':svg,'vocal':vocal_svg,'file':str(path)})
    return rows,{'name':'Verovio','version':toolkit.getVersion(),'page_count':len(files),'all_source_note_fragment_ids_visible':True,
                 'pages':files,'log':toolkit.getLog(),'external_editor_gui_roundtrip':'not_tested'}


# 和弦弹唱与伴奏编配：新增全离线谱面样式，阅读/试听/打印可直接使用。
STYLE='''
*{box-sizing:border-box}body{margin:0;background:#f4f2ed;color:#203345;font:15px/1.65 "Microsoft YaHei",sans-serif}
main{max-width:1460px;margin:auto;padding:28px}h1{font-size:30px;margin:0 0 8px}h2{font-size:20px}p{margin:8px 0}
a{color:#166b62}nav{display:flex;flex-wrap:wrap;gap:14px;padding:14px 0}button,select{font:inherit;border:1px solid #c5d2cf;background:white;border-radius:7px;padding:6px 13px;cursor:pointer}
button:hover{background:#e2f0eb}.toolbar{background:#fffefb;border:1px solid #dbe1dd;border-radius:12px;padding:18px;position:sticky;top:0;z-index:5;box-shadow:0 4px 16px #2033450d}
.players{display:flex;gap:25px;flex-wrap:wrap}.players label{display:block;font-size:13px;color:#64767b}audio{max-width:100%;height:36px}small,.muted{color:#6a7d82}.notice{color:#89591d;font-size:14px}
.score-row{background:white;margin:22px 0;padding:14px;border-radius:12px;border:1px solid #e0e3df;break-inside:avoid}.score-row header{display:flex;gap:12px;align-items:center;flex-wrap:wrap;color:#64767b;font-size:13px}.score-row svg{display:block;width:100%;height:auto}
.charts{display:grid;grid-template-columns:repeat(auto-fill,minmax(170px,1fr));gap:14px}.charts svg{width:170px;max-width:100%}.chart{background:white;border-radius:10px;padding:10px}
table{width:100%;border-collapse:collapse;background:white;font-size:14px}th,td{padding:10px;border-bottom:1px solid #dfe6e2;text-align:left;vertical-align:top}th{background:#e7efeb}.review-row:target{background:#fcf0d8}
.reference{display:flex;gap:16px;flex-wrap:wrap}.reference img{width:100%;max-width:600px}.metrics{display:flex;gap:16px;flex-wrap:wrap}.metric{background:white;padding:16px 22px;border:1px solid #dfe6e2;border-radius:12px}.metric b{display:block;font-size:24px}
@media print{@page{size:A4 portrait;margin:9mm}body{background:white}main{padding:0}nav,.toolbar,.score-row header button,.no-print{display:none}.score-row{border:0;padding:0;margin:5mm 0;break-inside:avoid}.score-row svg{max-height:120mm}.charts{grid-template-columns:repeat(4,1fr)}h1{font-size:22px}}
'''
# 结构稳定伴奏与人声合播：新增四小节可读尺寸、合播控制与横向打印。
STYLE+='''
.singing-player{flex:1 1 100%;border-top:1px solid #dbe1dd;margin-top:10px;padding-top:10px}.singing-actions,.singing-gains{display:flex;gap:15px;align-items:center;flex-wrap:wrap}.singing-player input[type=range]{width:240px;max-width:70vw;vertical-align:middle}#singing-seek{width:min(760px,75vw)}.singing-player p{font-size:12px;margin:4px 0}.singing-player label{font-size:13px}.singing-gains{margin-top:6px}
.guitar-score-row{overflow-x:auto}.guitar-score-row svg{min-width:calc(var(--score-native-width)*.64px)}
/* 结构稳定伴奏与人声合播：新增合播工具栏正常流布局，避免覆盖定位后的乐谱标题和人声。 */
.toolbar:has(.singing-player){position:static}
@media print{@page{size:A4 landscape;margin:8mm}.guitar-score-row{overflow:visible}.guitar-score-row svg{min-width:0!important;width:100%;max-height:100mm}.score-row{margin:4mm 0}}
'''
PLAYER_SCRIPT='''
document.querySelectorAll('button[data-player]').forEach(b=>b.addEventListener('click',()=>{
 const a=document.getElementById(b.dataset.player); document.querySelectorAll('audio').forEach(x=>{if(x!==a)x.pause()});
 const seek=()=>{a.currentTime=Math.max(0,Number(b.dataset.second));a.play().catch(()=>{})};
 if(a.readyState>=1)seek();else a.addEventListener('loadedmetadata',seek,{once:true});
}));
const s=document.getElementById('stem');if(s)s.addEventListener('change',()=>{const a=document.getElementById('original');a.pause();a.src=s.value;a.load()});
'''


# 和弦弹唱与伴奏编配：新增完整HTML容器，所有原文标题/路径先编码再进入页面。
def html_page(title,body,script=PLAYER_SCRIPT):
    return '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+html.escape(title)+'</title><style>'+STYLE+'</style></head><body><main>'+body+'</main><script>'+script+'</script></body></html>'


# 和弦弹唱与伴奏编配：新增原曲与编配的同段试听按钮，区分原音秒与谱面预留起始时间。
# 结构稳定伴奏与人声合播：修改，原代码注释保留。
# def play_buttons(vocal,first):
def play_buttons(vocal,first,singing=False):
    clock=SongClock(vocal);tick=(first-1)*clock.bar_ticks
    # 原曲拍轴与歌词拍位通用修复：修改，旧按钮偏移保留；定位采用真实共同音频起点。
    # original=max(0,clock.seconds(tick));preview=clock.seconds(tick)-clock.seconds(0)
    original=max(0,clock.seconds(tick));preview=clock.seconds(tick)-clock.audio_origin_seconds
    # 结构稳定伴奏与人声合播：修改，原代码注释保留。
    # return f'<button data-player="original" data-second="{original:.6f}">听原曲</button><button data-player="preview" data-second="{preview:.6f}">听编配</button>'
    combined=f'<button data-singing-second="{preview:.6f}">听人声＋伴奏</button>' if singing else ''
    return combined+f'<button data-player="original" data-second="{original:.6f}">听原曲</button><button data-player="preview" data-second="{preview:.6f}">听编配</button>'


# 和弦弹唱与伴奏编配：新增清楚的成谱入口，不在读谱流程散布模型细节。
def write_score_html(output,shared,vocal,arrangement,rows):
    output=Path(output);instrument=arrangement['instrument'];title=vocal['title']+' · '+('吉他弹唱伴奏' if instrument=='guitar' else '钢琴双手伴奏')
    mix=relative_url(shared['input_binding']['sources']['mix']['path'],output)
    key_text=' → '.join(s['key']['tonic']+'大调' for s in vocal['notation'].get('key_segments',[]) ) or vocal['notation']['key']['label']
    # 小节划分与拍速层级纠错：修改，原硬编码4/4与117兜底保留；谱头取真实拍号和时间映射。
    # body=f'<h1>{html.escape(title)}</h1><p>{html.escape(key_text)} · 4/4 · ♩ = {vocal["timing"].get("steady_tempo_bpm",117):g}</p>'
    clock=SongClock(vocal);meter='/'.join(str(n) for n in vocal['timing']['meter'])
    # 局部拍轴与原唱同步纠错：修改，保留固定速度文案；局部拍轴注明起始速度及随原曲变化。
    # body=f'<h1>{html.escape(title)}</h1><p>{html.escape(key_text)} · {meter} · ♩ = {clock.mapping.tempo_at(clock.origin):g}</p>'
    initial_bpm=clock.mapping.tempo_at(clock.origin)
    tempo_caption=f'起始 ♩ = {initial_bpm:.1f}（速度随原曲变化）' if vocal['timing'].get('local_beat_clock',{}).get('status')=='tracked' else f'♩ = {initial_bpm:g}'
    body=f'<h1>{html.escape(title)}</h1><p>{html.escape(key_text)} · {meter} · {tempo_caption}</p>'
    # 器乐背景休止与旋律突出：新增页头说明本谱黑点重音和复核背景休止，按原时值保持旋律连贯。
    if instrument=='guitar' and arrangement.get('instrumental_expression'):
        from guitar_instrumental_expression import expression_caption
        body+='<p>'+html.escape(expression_caption(arrangement))+'</p>'
    # 结构稳定伴奏与人声合播：修改，原代码注释保留。
    # if instrument=='guitar':body+=f'<p>标准调弦 E–A–D–G–B–E · 变调夹第 {arrangement["configuration"]["capo_fret"]} 品。和弦名为指型名，实际发声与钢琴版一致。</p>'
    if instrument=='guitar':
        # 局部拍轴与原唱同步纠错：修改，保留内部编号文案；独立弱起不计入正文换夹编号。
        # capo_text='；'.join('第'+str(s['start_measure'])+'小节起夹'+str(s['capo_fret'])+'品' for s in arrangement['configuration'].get('capo_segments',[])) or '变调夹第'+str(arrangement['configuration']['capo_fret'])+'品'
        from beat_phase_alignment import display_measure
        capo_text='；'.join(('弱起预备' if s['start_tick']==0 and vocal['timing'].get('initial_pickup_measure') else '第'+display_measure(vocal,s['start_measure'])+'小节')+'起夹'+str(s['capo_fret'])+'品' for s in arrangement['configuration'].get('capo_segments',[])) or '变调夹第'+str(arrangement['configuration']['capo_fret'])+'品'
        body+='<p>标准调弦 E–A–D–G–B–E · '+capo_text+'。和弦名为相对当前夹位的指型名，实际发声与钢琴版一致。每行'+str(arrangement['tab_display']['rows_measures'])+'小节。</p>'
    else:body+='<p>上行人声简谱供演唱参考，下方为左右手伴奏大谱表。指法为建议。</p>'
    body+='<p class="notice">自动编配初稿：和弦、织体及器乐旋律请结合原曲听审。</p>'
    # 渴首次吉他编配：新增有未决源拍轴时明确提示听审，编码合播通过不代表该音乐判断已确认。
    if shared.get('source_clock_review'):
        body+='<p class="notice">部分拍位尚待听审：本版保留校准前的人声拍轴，请结合原唱检查重拍及歌词位置。</p>'
    # 分解和弦优先：新增读谱所需的编配偏好说明，不显示声学实现细节。
    if arrangement['configuration'].get('texture_policy',{}).get('name')=='arpeggio_first':
        body+='<p>本版优先采用分解和弦；仅在原曲起音支持充分的地方保留柱式。器乐主线与主要低音优先保留。</p>'
    # 渴首次吉他编配：修改，谱页导航兼容单乐器与双乐器；原代码注释保留。
    # body+='<nav><a href="../index.html">两套谱入口</a><a href="../review.html">逐小节复核</a><a href="../project.json" download>可编辑工程</a><a href="score.musicxml" download>MusicXML</a><a href="score.mxl" download>MXL</a><a href="accompaniment.mid" download>MIDI</a><a href="preview.wav" download>试听音频</a>'
    # 渴首次吉他编配：新增按所选乐器执行，保留各乐器原验证。
    body+='<nav><a href="../index.html">乐谱入口</a><a href="../review.html">逐小节复核</a><a href="../project.json" download>可编辑工程</a><a href="score.musicxml" download>MusicXML</a><a href="score.mxl" download>MXL</a><a href="accompaniment.mid" download>MIDI</a><a href="preview.wav" download>试听音频</a>'
    # 和弦指型与X六线谱：修改，原参考页名称保留；目录与正文实际按法一致。
    # if instrument=='guitar':body+='<a href="chords.html">和弦指型参考</a>'
    if instrument=='guitar':body+='<a href="chords.html">和弦指型目录</a>'
    # 和弦指型与X六线谱：新增打印也保留的读谱约定，避免x被误读为闷音。
    # 空弦沿用指型X表示：修改，原空弦固定0说明保留；x包含左手无需改变的空弦。
    # if instrument=='guitar':body+='<p>指型图的黑点表示按弦，粗横线表示横按；第一行左侧标明起始品数。六线谱的 <b>x</b> 表示按当前指型拨响该弦，<b>0</b> 为空弦，其它数字为另行按弦的品数。所有品数以变调夹为 0 品。</p>'
    if instrument=='guitar':body+='<p>指型图的黑点表示按弦，粗横线表示横按；第一行左侧标起始品数。六线谱的 <b>x</b> 表示沿用当前左手指型拨弦，包含未按住的弦上弹空弦。只有需临时松开或增加按指时才写数字：<b>0</b> 表示松开当前按指弹空弦，其它数字为临时按到的品数。所有品数以变调夹为 0 品。</p><p>图中 ○ 为空弦，× 为通常不拨的弦；是否拨弦以六线谱为准。横按覆盖的弦也算已按，无黑点且无横按覆盖的弦上，x 即空弦。</p>'
    # 六线谱同拍节奏连线：新增读谱所需的按拍横线规则，与弦上的持续音细线区分。
    # 节奏符号说明与声部对齐：修改，原简略横线说明保留；新增符干/短钩/附点拍数和可展开图例。
    # if instrument=='guitar':body+='<p>六线谱下方按拍连接节奏：八分音符一条横线，十六分音符两条；混合时值只在相应音下加第二条线，单独短音用短横钩。附点写在符干旁，弦上的细横线表示持续发声。</p>'
    if instrument=='guitar':
        from guitar_rhythm_guide import rhythm_guide_svg,rhythm_guide_content
        guide=rhythm_guide_content()
        body+='<p>4/4拍中，单竖线通常为1拍，一条横线为半拍，两条为四分之一拍；右侧实心附点增加原时值的一半。短横钩朝左或朝右含义相同，扫弦方向另用↓/↑。<a href="rhythm_guide.html">查看详细节奏图例</a>。</p><p>人声简谱与六线谱按同一拍点对齐：同刻起音落在同一竖列，小号倚音保留主音左前方的记谱位置。</p>'
        body+='<details class="no-print"><summary>展开节奏符号与拍数图例</summary>'+guide+'</details>'
        (output/'rhythm_guide.svg').write_text(rhythm_guide_svg(),encoding='utf-8')
        (output/'rhythm_guide.html').write_text(html_page('六线谱节奏符号说明','<h1>六线谱节奏符号说明</h1><nav><a href="score.html">返回吉他谱</a><button onclick="window.print()">打印图例</button></nav>'+guide),encoding='utf-8')
    # 常用右手伴奏型：新增演奏说明，给读谱者讲清主型、性质音合拨和扫弦条件。
    if instrument=='guitar' and arrangement.get('right_hand_patterns'):
        body+='<p>演唱段优先采用稳定的常用分解型，保留休止及换和弦低音；少量合拨用于补足加音、挂留或其它和弦性质音。同刻两根弦用手指合拨，按谱中箭头才作扫弦。<a href="right_hand.html">查看常用分解与扫弦节奏参考</a>。</p>'
        from guitar_right_hand_patterns import library
        patterns=library()['patterns'];reference='<h1>常用右手伴奏节奏参考</h1><nav><a href="score.html">返回六线谱</a></nav><p>B为当前和弦或斜线低音所在弦，B2为手型内另一低音；1、2、3是弦号。+表示同时合拨，D下扫、U上扫，—本格不拨。4/4八分格数1 &amp; 2 &amp; 3 &amp; 4 &amp;；四分格每格一拍。</p><table><thead><tr><th>类型</th><th>拍号／每格</th><th>拨弦顺序</th></tr></thead><tbody>'
        for pattern in patterns:
            # 结构稳定伴奏与人声合播：修改，原代码注释保留。
            # reference+='<tr><td>'+html.escape(pattern['name'])+'</td><td>'+str(pattern['meter'][0])+'/'+str(pattern['meter'][1])+'／'+('四分' if pattern['step_ticks']==480 else '八分')+'</td><td>'+html.escape(' '.join(pattern['slots']).replace('-', '—'))+'</td></tr>'
            unit='四分' if pattern['step_ticks']==480 else '八分' if pattern['step_ticks']==240 else '十六分底格（混合）' if '-' in pattern['slots'] else '十六分'
            reference+='<tr><td>'+html.escape(pattern['name'])+'</td><td>'+str(pattern['meter'][0])+'/'+str(pattern['meter'][1])+'／'+unit+'</td><td>'+html.escape(' '.join(pattern['slots']).replace('-', '—'))+'</td></tr>'
        reference+='</tbody></table><p>低音弦随和弦变化，C/Am常用五弦、D常用四弦、G/Em常用六弦；斜线低音按指型与实际发声选择。高音弦可为和弦性质音作少量替换，具体以六线谱为准。3/4按三拍分组，6/8按两组各三个八分分组。主歌或副歌不自动决定扫弦；原伴奏、律动、歌声空间及力度共同决定。</p><p>这些是基本演奏类型的规范示例。当前谱保持分解优先，合拨与扫弦分别处理；六线谱中的x仍表示沿用左手指型，不表示闷音。</p>'
        (output/'right_hand.html').write_text(html_page('常用右手伴奏节奏参考',reference),encoding='utf-8')
    # 规整分解节奏与延音显示：新增直接说明本版的演奏规则，避免把延音长度当成右手附点节奏。
    if instrument=='guitar' and arrangement.get('regular_rhythm'):
        # 结构稳定伴奏与人声合播：修改，原代码注释保留。
        # body+='<p>普通演唱伴奏优先规整拍点的成组八分或四分分解，避免附点和孤立八分；特殊节奏须结合原曲确认。符干/横梁表示右手拨弦拍格，低音的较长延响看沿弦细线。<b>小节开头的括号品数表示上一小节的音继续响，无需重拨。</b>和弦图在实际拨弦或必须保持按指的位置出现，只有空弦延响时不重复整张图。</p>'
        types='成组四分、八分、十六分或八分/十六分混合' if arrangement['regular_rhythm'].get('version',1)>=2 else '成组八分或四分'
        body+='<p>普通演唱伴奏优先规整拍点的'+types+'分解，避免附点和孤立八分；特殊节奏须结合原曲确认。符干/横梁表示右手拨弦拍格，低音的较长延响看沿弦细线。<b>小节开头的括号品数表示上一小节的音继续响，无需重拨。</b>和弦图在实际拨弦或必须保持按指的位置出现，只有空弦延响时不重复整张图。</p>'
        if arrangement.get('structure_stability'):
            body+='<p>按乐句稳定主伴奏型，重复句尽量沿用。短促挂留/加音可用基本和弦加临时按指表达，重要和声变化仍按谱演奏。换夹标记从对应小节立即生效，后续品数以新夹位为0品。</p>'
    # 常用指型与器乐独奏：新增实际演奏规则说明，器乐纯数字区的0与带图区域需松手的0分开。
    if instrument=='guitar' and arrangement.get('notation_regions'):
        body+='<p>本版优先使用常用开放指型。前奏、间奏和尾奏以独奏六线谱为主；只有能依托常用指型、临时增减不超过两个按指操作时才附和弦。<b>没有和弦图的区间全部用实际品数，0表示空弦；有图的区间继续按上述x规则读谱。</b></p>'
    # 结构稳定伴奏与人声合播：修改，原代码注释保留。
    # body+='<button onclick="window.print()">打印谱子</button></nav><div class="toolbar"><div class="players"><div><label>编配试听（简化音色）</label><audio id="preview" controls preload="metadata" src="preview.wav"></audio></div><div><label>原曲</label><audio id="original" controls preload="metadata" src="'+mix+'"></audio></div></div></div>'
    singing=(output/'singing_preview.wav').exists()
    # 强拍相位与伴奏同步纠错：新增弱起说明，定位按钮继续使用同一真实时间轴。
    if vocal['timing'].get('initial_pickup_measure'):
        body+='<p>开头弱起预备单独列出，不计入正式小节号；正文每行四小节。首句位于第5–8小节，空歌词拍可继续延音。</p>'
    body+='<button onclick="window.print()">打印谱子</button></nav><div class="toolbar"><div class="players"><div><label>编配试听（简化音色）</label><audio id="preview" controls preload="metadata" src="preview.wav"></audio></div><div><label>原曲</label><audio id="original" controls preload="metadata" src="'+mix+'"></audio></div></div>'
    if singing:body+=singing_player_html()
    body+='</div>'
    for row in rows:
        # 结构稳定伴奏与人声合播：修改，原代码注释保留。
        # first,last=row['first'],row['last'];buttons=play_buttons(vocal,first)
        # body+=f'<section class="score-row" id="measures-{first}"><header><span>第 {first}–{last} 小节</span>{buttons}<a href="../review.html#measure-{first}">复核此段</a></header>'
        first,last=row['first'],row['last'];buttons=play_buttons(vocal,first,singing=singing)
        class_name='score-row guitar-score-row' if instrument=='guitar' else 'score-row'
        native_width=float(ET.fromstring(row['guitar']).get('width')) if instrument=='guitar' else 0
        # 强拍相位与伴奏同步纠错：修改，原内部编号标题保留；显示与定位时钟共享同一编号换算。
        # body+=f'<section class="{class_name}" style="--score-native-width:{native_width:g}" id="measures-{first}"><header><span>第 {first}–{last} 小节</span>{buttons}<a href="../review.html#measure-{first}">复核此段</a></header>'
        from beat_phase_alignment import display_measure
        row_label='弱起预备' if display_measure(vocal,first)=='弱起' else f'第 {display_measure(vocal,first)}–{display_measure(vocal,last)} 小节'
        body+=f'<section class="{class_name}" style="--score-native-width:{native_width:g}" id="measures-{first}"><header><span>{row_label}</span>{buttons}<a href="../review.html#measure-{first}">复核此段</a></header>'
        body+=row['guitar'] if instrument=='guitar' else row['vocal']+row['staff']
        body+='</section>'
    # 和弦弹唱与伴奏编配：修改，指法已贴近品号，原说明保留。
    # if instrument=='guitar':body+='<p class="muted no-print">绿色为器乐独奏旋律，棕色为主要低音。六线谱上方小数字为手位，下方数字为左手指法；短横线表示持续发声。指型图供参考，具体弦品、换把与释音按六线谱。</p>'
    # 和弦指型与X六线谱：修改，原逐音指号说明保留；指型改用黑点，换把处重标。
    # if instrument=='guitar':body+='<p class="muted no-print">绿色为器乐独奏旋律，棕色为主要低音。“位”表示手位，品号右上小数字为左手指法；短横线表示持续发声。指型图供参考，具体弦品、换把与释音按六线谱。</p>'
    # 常用指型与器乐独奏：修改，原每个和弦必须配图的说明保留；只在采用指型的区间重标。
    # if instrument=='guitar':body+='<p class="muted no-print">绿色为器乐独奏旋律，棕色为主要低音。“位”表示手位，短横线表示持续发声；每处和弦、行首和必要换把处均重标指型。MusicXML、MXL 与 MIDI 保留实际数字弦品和音高，x 是本页的读谱约定。</p>'
    if instrument=='guitar':body+='<p class="muted no-print">绿色为器乐独奏旋律，棕色为主要低音。“位”表示手位，短横线表示持续发声；采用和弦指型的区间在起始及行首重标，独奏数字区不沿用之前的图。MusicXML、MXL 与 MIDI 保留实际数字弦品和音高，x 是本页的读谱约定。</p>'
    (output/'score.html').write_text(html_page(title,body),encoding='utf-8')


# 和弦弹唱与伴奏编配：新增逐小节来源/候选复核，原混音和全部可获得分轨可播放对照。
def write_review(output,shared,vocal,arrangements):
    output=Path(output);clock=SongClock(vocal);sources=shared['input_binding']['sources']
    labels={'mix':'原曲','accompaniment':'完整伴奏','bass':'贝斯','drums':'鼓','other':'综合器乐','vocals':'人声',
            'six_guitar':'细分吉他（辅助）','six_piano':'细分钢琴（辅助）','six_other':'细分剩余器乐（辅助）'}
    options=''.join('<option value="'+relative_url(v['path'],output)+'">'+labels.get(name,name)+'</option>' for name,v in sources.items())
    mix=relative_url(sources['mix']['path'],output)
    # 渴首次吉他编配：修改，复核页不假定必须两套谱；原代码注释保留。
    # body='<h1>'+html.escape(vocal['title'])+' · 和声与伴奏复核</h1><nav><a href="index.html">两套谱入口</a><a href="shared_analysis.json">共享分析</a><a href="project.json" download>可编辑工程</a><a href="validation.json">验证记录</a></nav>'
    # 渴首次吉他编配：新增按所选乐器执行，保留各乐器原验证。
    body='<h1>'+html.escape(vocal['title'])+' · 和声与伴奏复核</h1><nav><a href="index.html">乐谱入口</a><a href="shared_analysis.json">共享分析</a><a href="project.json" download>可编辑工程</a><a href="validation.json">验证记录</a></nav>'
    # 强拍相位与伴奏同步纠错：修改，原认可谱文案保留；复核页明确人声量化已校正。
    # body+='<p>人声沿用已认可谱。和弦由录音推断；候选接近、原谱不同或多乐器难以分辨的地方，留给逐段听审。</p>'
    vocal_status='人声已按原音段和复核拍点重新量化。' if vocal.get('beat_phase_correction') else '人声沿用已认可谱。'
    body+='<p>'+vocal_status+'和弦由录音推断；候选接近、原谱不同或多乐器难以分辨的地方，留给逐段听审。</p>'
    # 器乐背景休止与旋律突出：新增复核页同步显示实际休止与旋律／填充力度规则。
    if arrangements['guitar'].get('instrumental_expression'):
        from guitar_instrumental_expression import expression_caption
        body+='<p>'+html.escape(expression_caption(arrangements['guitar']))+'</p>'
    # 渴首次吉他编配：新增复核页同步展示实际保留的拍轴不确定性，分轨冲突完整保存在共享分析。
    if shared.get('source_clock_review'):
        body+='<p class="notice">部分拍位尚待听审：本版保留校准前的人声拍轴，请结合原唱检查重拍及歌词位置。</p>'
    # 渴首次吉他编配：修改，复核页仅加载实际输出的音源；原代码注释保留。
    # body+='<div class="toolbar"><select id="stem">'+options+'</select><audio id="original" controls src="'+mix+'" preload="metadata"></audio><label>吉他编配 <audio id="preview" controls src="guitar/preview.wav" preload="metadata"></audio></label><label>钢琴编配 <audio id="piano-preview" controls src="piano/preview.wav" preload="metadata"></audio></label></div>'
    # 渴首次吉他编配：新增按所选乐器执行，保留各乐器原验证。
    body+='<div class="toolbar"><select id="stem">'+options+'</select><audio id="original" controls src="'+mix+'" preload="metadata"></audio><label>吉他编配 <audio id="preview" controls src="guitar/preview.wav" preload="metadata"></audio></label>'
    if 'piano' in arrangements:
        body+='<label>钢琴编配 <audio id="piano-preview" controls src="piano/preview.wav" preload="metadata"></audio></label>'
    body+='</div>'
    # 分解和弦优先：修改，明确第三列是原音轨候选，实际分解/柱式分别列在编配取舍中。
    # body+='<table><thead><tr><th>小节/原声</th><th>实际和弦与低音</th><th>伴奏与旋律</th><th>候选与编配取舍</th></tr></thead><tbody>'
    body+='<table><thead><tr><th>小节/原声</th><th>实际和弦与低音</th><th>原音轨候选与旋律</th><th>候选与编配取舍</th></tr></thead><tbody>'
    for texture in shared['measure_textures']:
        m=texture['measure'];start,end=texture['start_tick'],texture['end_tick'];chords=[h for h in shared['harmony'] if h['start_tick']<end and h['end_tick']>start]
        selected=' → '.join(h['name'] for h in chords);uncertain=any(h['requires_review'] for h in chords)
        # 器乐背景休止与旋律突出：新增无实际发声的复核小节明确显示休止，原和声候选仍保留在细节中。
        if arrangements['guitar'].get('instrumental_expression') and not any(n['start_tick']<end and n['end_tick']>start for n in arrangements['guitar']['notes']):
            selected='吉他休止'
        windows=[w for w in shared['harmony_windows'] if start<=w['start_tick']<end]
        candidates='<br>'.join(f"{max(0,w['start_seconds']):.2f}s："+' / '.join(html.escape(chord_name(c['root_pc'],c['quality'],None,w['key'])) for c in w['candidates'][:3]) for w in windows)
        melody=[x for x in shared['instrumental_melody'] if start<=x['start_tick']<end]
        changes=[]
        # 常用指型与器乐独奏：新增复核页的演奏展示取舍；第二列仍完整保留原有共享和声分析。
        notation=[r for r in arrangements['guitar'].get('notation_regions',[]) if r['start_tick']<end and r['end_tick']>start]
        if notation:changes.append('吉他谱：'+' / '.join(dict.fromkeys('独奏数字TAB' if r['mode']=='solo_tab' else '常用指型' if r.get('common_grip_id') else '实际按法' for r in notation)))
        for name,arr in arrangements.items():
            count=sum(start<=x.get('at_tick',next((n['start_tick'] for n in arr['notes'] if n['id']==x.get('note_id')), -1))<end for x in arr['adjustments'])
            # 分解和弦优先：修改，取舍现包含织体选择，原说明保留。
            # if count:changes.append(('吉他' if name=='guitar' else '钢琴')+f' {count} 项释音/换位/声部调整')
            if count:changes.append(('吉他' if name=='guitar' else '钢琴')+f' {count} 项编配调整')
            actual_label=arranged_texture_label(arr,start,end,texture['kind'])
            changes.append(('吉他' if name=='guitar' else '钢琴')+'实际：'+actual_label)
        # 原曲拍轴与歌词拍位通用修复：修改，旧逐小节试听偏移保留；正首拍前原声也在共同音频内。
        # original=max(0,texture['start_seconds']);preview=clock.seconds(start)-clock.seconds(0)
        original=max(0,texture['start_seconds']);preview=clock.seconds(start)-clock.audio_origin_seconds
        # 渴首次吉他编配：修改，逐小节试听按钮对应实际所选乐器；原代码注释保留。
        # controls=f'<button data-player="original" data-second="{original:.6f}">原声</button><button data-player="preview" data-second="{preview:.6f}">吉他</button><button data-player="piano-preview" data-second="{preview:.6f}">钢琴</button>'
        # 渴首次吉他编配：新增按所选乐器执行，保留各乐器原验证。
        controls=f'<button data-player="original" data-second="{original:.6f}">原声</button><button data-player="preview" data-second="{preview:.6f}">吉他</button>'
        if 'piano' in arrangements:controls+=f'<button data-player="piano-preview" data-second="{preview:.6f}">钢琴</button>'
        # 强拍相位与伴奏同步纠错：修改，原内部编号保留；可见小节号与谱面一致，定位ID和秒时间不变。
        # body+=f'<tr class="review-row" id="measure-{m}"><td><b>第{m}小节</b><br>{original:.2f}–{texture["end_seconds"]:.2f}s<br>{controls}</td><td>{html.escape(selected)}<br><small>{"候选接近，需听审" if uncertain else "自动候选，仍需听审"}</small></td><td>{SECTION_LABELS[texture["section"]]} · {KIND_LABELS[texture["kind"]]}<br>{len(texture["attacks"])}次攻击 / {len(melody)}个器乐主线候选<br><small>{html.escape(labels.get(texture["source"],texture["source"]))}</small></td><td>{html.escape("；".join(changes))}<details><summary>和弦候选</summary>{candidates}</details></td></tr>'
        from beat_phase_alignment import display_measure
        number=display_measure(vocal,m);measure_label=number if not number.isdigit() else '第'+number+'小节'
        body+=f'<tr class="review-row" id="measure-{m}"><td><b>{measure_label}</b><br>{original:.2f}–{texture["end_seconds"]:.2f}s<br>{controls}</td><td>{html.escape(selected)}<br><small>{"候选接近，需听审" if uncertain else "自动候选，仍需听审"}</small></td><td>{SECTION_LABELS[texture["section"]]} · {KIND_LABELS[texture["kind"]]}<br>{len(texture["attacks"])}次攻击 / {len(melody)}个器乐主线候选<br><small>{html.escape(labels.get(texture["source"],texture["source"]))}</small></td><td>{html.escape("；".join(changes))}<details><summary>和弦候选</summary>{candidates}</details></td></tr>'
    body+='</tbody></table><h2>上传的参考谱</h2><p>以下是对照资料；参考编配与原录音可能不同，变调夹指型需要换算为实际音高后比较。</p><div class="reference">'
    for reference in shared['input_binding']['references']:
        # 参考PDF通用显示兼容：修改旧一律作为图片的展示，原代码注释保留；PDF直接提供可查看链接。
        # url=relative_url(reference['path'],output);body+='<a href="'+url+'"><img loading="lazy" src="'+url+'" alt="上传的参考吉他谱"></a>'
        url=relative_url(reference['path'],output)
        if Path(reference['path']).suffix.lower()=='.pdf':body+='<a href="'+url+'">查看参考吉他谱PDF</a>'
        else:body+='<a href="'+url+'"><img loading="lazy" src="'+url+'" alt="上传的参考吉他谱"></a>'
    body+='</div>'
    (output/'review.html').write_text(html_page(vocal['title']+' · 伴奏复核',body),encoding='utf-8')


# 和弦弹唱与伴奏编配：新增TAB实际可见数字读回，按变调夹/弦号还原音高并检查时值。
# 和弦指型与X六线谱：修改，原数字回读保留，兼容历史版本复核。
# def validate_tab(rows,arrangement):
def _validate_numeric_tab(rows,arrangement):
    observed={};errors=[]
    for row in rows:
        root=ET.fromstring(row['guitar'])
        for node in root.iter('{'+SVG_NS+'}g'):
            if not node.get('data-string'):continue
            identity=node.get('id');text=node.find('{'+SVG_NS+'}text')
            if identity in observed:errors.append('duplicate_tab_note_id')
            string=int(node.get('data-string'));fret=int(text.text)
            observed[identity]=(int(node.get('data-start-tick')),int(node.get('data-end-tick')),# 结构稳定伴奏与人声合播：修改，原代码注释保留。
# TUNING[string]+arrangement['configuration']['capo_fret']+fret
TUNING[string]+capo_at(arrangement,int(node.get('data-start-tick')))+fret)
    expected={n['id']:(n['start_tick'],n['end_tick'],n['pitch_midi']) for n in arrangement['notes']}
    if observed!=expected:errors.append('visible_tab_sound_or_interval_mismatch')
    return {'valid':not errors,'errors':errors,'visible_attack_count':len(observed),'six_strings_only':True,
            'fret_labels_plus_tuning_and_capo_match_actual_sound':not errors}


# 和弦指型与X六线谱：新增从可见黑点/首行品数与六条弦线还原x音，逐弦逐品校验。
def validate_tab(rows,arrangement):
    ns='{'+SVG_NS+'}';roots=[ET.fromstring(row['guitar']) for row in rows]
    # 和弦指型与X六线谱：修改，原仅按图存在判断保留；新版图被全部移除也必须返回失败。
    # if not any(n.get('class')=='chord-diagram' for root in roots for n in root.iter(ns+'g')):
    if not arrangement.get('fingering_diagrams') and arrangement.get('tab_display',{}).get('mode')!='chord_grip_x' and not any(n.get('class')=='chord-diagram' for root in roots for n in root.iter(ns+'g')):
        return _validate_numeric_tab(rows,arrangement)
    # 空弦沿用指型X表示：修改，原统计保留；区分空弦x、真实空弦总数与需松手的0。
    # observed={};errors=[];counts={'x':0,'numeric':0,'open':0,'diagrams':0,'high':0}
    observed={};errors=[];counts={'x':0,'x_open':0,'numeric':0,'open':0,'zero':0,'diagrams':0,'high':0}
    unchanged_hand=arrangement.get('tab_display',{}).get('display_rule')=='unchanged_left_hand'
    plans={d['id']:d for d in arrangement.get('fingering_diagrams',[])}
    for root in roots:
        charts={}
        # 结构稳定伴奏与人声合播：新增从原指型计划重算可见合并区间，仍逐点核对真实黑点和横按。
        merged_plans={}
        if arrangement['configuration'].get('structure_policy') and root.get('data-first-measure'):
            first,last=int(root.get('data-first-measure')),int(root.get('data-last-measure'))
            bar=arrangement['configuration']['grip_policy']['bar_ticks']
            merged_plans={(d['id'],d['draw_tick']):d for d in visible_diagrams({'statistics':{'bar_ticks':bar}},arrangement,first,last)}
        for group in root.iter(ns+'g'):
            if group.get('class')!='chord-diagram':continue
            try:
                decoded=read_diagram(group);identity=group.get('id')
                if identity in charts:raise ValueError('重复指型标识。')
                if plans:
                    # 结构稳定伴奏与人声合播：修改，原单段区间保留；稳定同手型合并须对应重算结果。
                    # plan=plans[decoded['plan_id']]
                    plan=merged_plans.get((decoded['plan_id'],decoded['start_tick']),plans[decoded['plan_id']])
                    expected_frets={s:plan['frets'].get(str(s),-1) for s in range(1,7)}
                    # 空弦沿用指型X表示：修改，原仅比黑点/起始品保留；可见横按同样必须匹配。
                    # if decoded['frets']!=expected_frets or decoded['position']!=plan['position']:
                    if decoded['frets']!=expected_frets or decoded['position']!=plan['position'] or decoded['barre']!=plan.get('barre'):
                        raise ValueError('可见指型与实际按法不符。')
                    if not plan['start_tick']<=decoded['start_tick']<decoded['end_tick']<=plan['end_tick']:
                        raise ValueError('指型持续区间不符。')
                    if merged_plans and decoded['end_tick']!=plan['display_end_tick']:
                        raise ValueError('稳定指型可见区间与重算结果不符。')
                charts[identity]=decoded;counts['diagrams']+=1;counts['high']+=decoded['position']>1
            except (ValueError,KeyError,TypeError,StopIteration) as exc:
                errors.append('visible_chord_diagram_invalid:'+str(exc))
        string_y=sorted({float(n.get('y1')) for n in root.iter(ns+'line') if n.get('class')=='tab-string-line'})
        # 常用指型与器乐独奏：新增逐行核查应该出现的图，防止图和x一起被删后数字音仍蒙混通过。
        policy=arrangement['configuration'].get('grip_policy',{})
        if policy.get('name')=='common_open_and_instrumental_solo':
            try:
                first=int(root.get('data-first-measure'));last=int(root.get('data-last-measure'));bar=policy['bar_ticks']
                begin,finish=(first-1)*bar,last*bar
                points={d['start_tick'] for d in plans.values() if begin<=d['start_tick']<finish}
                points.update((m-1)*bar for m in range(first,last+1))
                # 规整分解节奏与延音显示：修改，原每个边界必有图保留；新版按有用途的实际起音/按指核查。
                # expected={(d['id'],tick) for tick in points for d in plans.values() if d['start_tick']<=tick<d['end_tick']}
                expected={(d['id'],d['draw_tick']) for d in visible_diagrams({'statistics':{'bar_ticks':bar}},arrangement,first,last)}
                actual={(d['plan_id'],d['start_tick']) for d in charts.values()}
                if actual!=expected:errors.append('required_visible_diagram_missing_or_extra')
            except (TypeError,ValueError,KeyError):errors.append('notation_row_range_invalid')
        if len(string_y)!=6:errors.append('tab_requires_six_visible_string_lines');continue
        for group in root.iter(ns+'g'):
            if not group.get('data-string'):continue
            try:
                identity=group.get('id');text=group.find(ns+'text');y=float(text.get('y'))
                string=min(range(1,7),key=lambda s:abs(string_y[s-1]-y))
                if abs(string_y[string-1]-y)>.02 or string!=int(group.get('data-string')):
                    raise ValueError('音符未画在对应弦线上。')
                if identity in observed:raise ValueError('重复音符标识。')
                begin,end=int(group.get('data-start-tick')),int(group.get('data-end-tick'))
                # 和弦指型与X六线谱：新增按可见图的时间区间独立确定当前按法，数字音也不能漏绑。
                current=[(identity,chart) for identity,chart in charts.items() if chart['start_tick']<=begin<chart['end_tick']]
                if len(current)>1:raise ValueError('当前时间出现重叠指型。')
                if current and group.get('data-diagram-id')!=current[0][0]:raise ValueError('音符未绑定当前可见指型。')
                chart=current[0][1] if current else None
                # 常用指型与器乐独奏：新增精确模式核对，无图区域必须用数字且不残留图绑定。
                region=guitar_region_at(arrangement,begin)
                if region:
                    mode='chord_grip' if chart else 'solo_tab'
                    if mode!=region['mode'] or group.get('data-notation-mode')!=mode:
                        raise ValueError('可见TAB模式与器乐/指型区间不符。')
                    if mode=='solo_tab' and group.get('data-diagram-id'):
                        raise ValueError('独奏区仍绑定了之前的指型。')
                glyph=text.text or ''
                if glyph=='x':
                    # 和弦指型与X六线谱：修改，原直接信任图标识保留，改由当前区间选图。
                    # chart=charts[group.get('data-diagram-id')]
                    if chart is None:raise ValueError('x缺少当前可见指型。')
                    if not chart['start_tick']<=begin<chart['end_tick']:raise ValueError('x超出当前指型区间。')
                    # 空弦沿用指型X表示：修改，旧版仍按正品位复核；新版由可见黑点和横按还原空弦或品位。
                    # fret=chart['frets'][string]
                    # if fret<=0:raise ValueError('x必须指向当前图中已按住的弦品。')
                    fret=left_hand_fret(chart,string) if unchanged_hand else chart['frets'][string]
                    if not unchanged_hand and fret<=0:raise ValueError('旧版x必须指向当前图中已按住的弦品。')
                    counts['x']+=1
                    if fret==0:counts['x_open']+=1
                else:
                    if not re.fullmatch(r'\d+',glyph):raise ValueError('六线谱必须为x或数字。')
                    # 空弦沿用指型X表示：修改，原按显示字形累计空弦保留；新增真实空弦与显示0分开统计。
                    # fret=int(glyph);counts['open' if fret==0 else 'numeric']+=1
                    fret=int(glyph);counts['zero' if fret==0 else 'numeric']+=1
                    # 和弦指型与X六线谱：修改，原数字音仅通过隐藏图标识取图保留。
                    # chart=charts.get(group.get('data-diagram-id'))
                    # 空弦沿用指型X表示：修改，原只检查正品位重复数字保留；新版空弦无需变指也必须显示x。
                    # if fret>0 and chart and chart['frets'][string]==fret:
                    #     raise ValueError('已按住的当前弦品应显示x。')
                    if chart and ((unchanged_hand and left_hand_fret(chart,string)==fret) or (not unchanged_hand and fret>0 and chart['frets'][string]==fret)):
                        raise ValueError('沿用当前左手指型的音应显示x。')
                if fret==0:counts['open']+=1
                # 结构稳定伴奏与人声合播：修改，按实际音符group起音查询夹位；原固定式及错误变量保留。
                # observed[identity]=(begin,end,TUNING[string]+arrangement['configuration']['capo_fret']+fret,string,fret)
                # observed[identity]=(begin,end,TUNING[string]+capo_at(arrangement,int(node.get('data-start-tick')))+fret,string,fret)
                observed[identity]=(begin,end,TUNING[string]+capo_at(arrangement,begin)+fret,string,fret)
            except (ValueError,KeyError,TypeError,AttributeError) as exc:
                errors.append('visible_tab_note_invalid:'+str(exc))
    expected={n['id']:(n['start_tick'],n['end_tick'],n['pitch_midi'],n['string'],n['fret']) for n in arrangement['notes']}
    if observed!=expected:errors.append('visible_tab_sound_string_fret_or_interval_mismatch')
    # 六线谱同拍节奏连线：新增由可见横线高度、端点及真实拍界独立核对节奏显示。
    rhythm=validate_rhythm(rows,arrangement)
    if rhythm and not rhythm['valid']:errors.extend('rhythm:'+e for e in rhythm['errors'])
    # 规整分解节奏与延音显示：新增可见跨小节延音必须完整且不伪造新的攻击。
    continuation_check=validate_continuations(rows,arrangement)
    if continuation_check and not continuation_check['valid']:errors.extend('continuation:'+e for e in continuation_check['errors'])
    return {'valid':not errors,'errors':errors,'visible_attack_count':len(observed),'six_strings_only':True,
            'fret_labels_plus_tuning_and_capo_match_actual_sound':not errors,
            'visible_geometry_and_exact_string_fret_checked':True,'x_count':counts['x'],
            'numeric_fret_count':counts['numeric'],'open_string_count':counts['open'],
            # 空弦沿用指型X表示：新增空弦x与需松手显示0的明细，保持旧统计字段。
            'open_string_x_count':counts['x_open'],'displayed_zero_count':counts['zero'],
            # 六线谱同拍节奏连线：修改，原结束行保留；新增节奏回读明细。
            # 'inline_diagram_count':counts['diagrams'],'high_position_diagram_count':counts['high']}
            # 规整分解节奏与延音显示：修改，原结束字段保留；增加延音回读结果。
            # 'inline_diagram_count':counts['diagrams'],'high_position_diagram_count':counts['high'],'rhythm':rhythm}
            'inline_diagram_count':counts['diagrams'],'high_position_diagram_count':counts['high'],'rhythm':rhythm,'continuations':continuation_check}


# 和弦弹唱与伴奏编配：新增独立输出总入口；XML/MIDI/TAB均真实回读后才能通过。
# 吉他器乐低把位与指型复用：修改，保留原入口签名；允许纯吉他升级原字节保留钢琴交付。
# def export_all(output,shared,vocal,arrangements):
# 重复乐句折叠与多遍挂词：修改导出签名，旧入口保留；阅读折叠独立于实际演奏验证。
# def export_all(output,shared,vocal,arrangements,preserve_piano_from=None):
# 旧工程功能自动升级与三曲器乐表现统一：修改导出签名，旧调用保留；支持原人声交付字节保护。
# def export_all(output,shared,vocal,arrangements,preserve_piano_from=None,fold_repeats=False):
def export_all(output,shared,vocal,arrangements,preserve_piano_from=None,fold_repeats=False,preserve_vocals_from=None):
    # 吉他编配规则与统一验收修复：新增旧参数式API无法携带原声验收和原工程绑定，遇到新修订必须走完整工程入口。
    if arrangements.get('guitar', {}).get('guitar_readability_revision'):
        raise ValueError('吉他修订数据须从完整project使用新版吉他修订入口导出；旧参数式导出会丢失原声验收。')
    # 原声覆盖与选音归属通用修复：新增公开导出也检查实际源覆盖，不能绕过CLI交付空白伴奏。
    from source_accompaniment_quality import validate_source_coverage
    source_check=validate_source_coverage(shared,vocal,arrangements)
    if not source_check['valid']:raise ValueError('导出原声覆盖缺失：'+str(source_check['errors'][:8]))
    # 相似乐句和弦框架复用：新增谱、指型、复核与试听共用实际视图，不覆盖原声学分析。
    storage_shared=shared;shared=arrangement_view(shared,vocal)
    # 器乐背景休止与旋律突出：新增公开导出也严格重放表现来源，避免绕过CLI直接伪造休止或重音。
    if arrangements['guitar'].get('instrumental_expression'):
        from guitar_instrumental_expression import validate_expression
        expression_check=validate_expression(shared,vocal,arrangements['guitar'],replay=True)
        if not expression_check['valid']:raise ValueError('器乐表现来源复演失败：'+str(expression_check['errors'][:6]))
    # 器乐低弦分解填充：新增公开导出入口完整来源重放，不能绕过CLI直接输出伪造填充音。
    if arrangements['guitar'].get('instrumental_flow'):
        from guitar_instrumental_flow import validate_flow
        flow_check=validate_flow(shared,vocal,arrangements['guitar'],replay=True)
        if not flow_check['valid']:raise ValueError('器乐低弦织体来源复演失败：'+str(flow_check['errors'][:6]))
    # 原曲器乐旋律骨干重提取：新增公开导出入口也复演源证据，不能绕过CLI校验直接交付伪造骨干。
    if arrangements['guitar'].get('instrumental_source_backbone'):
        from instrumental_source_melody import validate_source_backbone
        source_check=validate_source_backbone(shared,vocal,arrangements['guitar'],replay=True)
        if not source_check['valid']:raise ValueError('原曲器乐骨干来源复演失败：'+str(source_check['errors'][:6]))
    from accompaniment_arrange import validate_playability
    # 结构稳定伴奏与人声合播：修改，原代码注释保留。
    # output=Path(output);output.mkdir(parents=True,exist_ok=True);clock=SongClock(vocal)
    # validation=
    output=Path(output);output.mkdir(parents=True,exist_ok=True);clock=SongClock(vocal)
    singing=bool(arrangements['guitar']['configuration'].get('enable_vocal_playback'))
    voice,voice_meta=prepare_vocals(output,shared,vocal) if singing else (None,None)
    # 旧工程功能自动升级与三曲器乐表现统一：新增先验证重新计算的原唱PCM／时钟，再复用原WAV／OGG／脚本，避免无关重新编码。
    if singing and preserve_vocals_from is not None:
        from shutil import copytree
        accepted=score.read_json(Path(preserve_vocals_from)/'project.json')
        original_meta=score.read_json(Path(preserve_vocals_from)/'audio/vocal_alignment.json')
        if (accepted['accepted_vocal_project']!=vocal or original_meta!=voice_meta or
            score.sha256(output/'audio/vocals_aligned.wav')!=score.sha256(Path(preserve_vocals_from)/'audio/vocals_aligned.wav')):
            raise ValueError('保留原唱要求实际人声／拍轴与原交付PCM完全一致。')
        copytree(Path(preserve_vocals_from)/'audio',output/'audio',dirs_exist_ok=True)
    validation={'task':'和弦弹唱与伴奏编配','status':'checking','quality_status':'automatic_draft_requires_musical_review',
                'vocal_project_sha256':shared['input_binding']['vocal_project_sha256'],'instruments':{}}
    for instrument,arrangement in arrangements.items():
        folder=output/instrument;folder.mkdir(parents=True,exist_ok=True)
        # 吉他器乐低把位与指型复用：新增来源相同的钢琴复制与实际XML／MIDI回读，不重合成已认可钢琴。
        if instrument=='piano' and preserve_piano_from is not None:
            from shutil import copytree
            # 吉他器乐低把位与指型复用：修改，旧未导入名称保留；使用现有score模块的只读接口。
            # accepted=read_json(Path(preserve_piano_from)/'project.json')
            accepted=score.read_json(Path(preserve_piano_from)/'project.json')
            if accepted['accepted_vocal_project']!=vocal or accepted['arrangements']['piano']!=arrangement:
                raise ValueError('原字节保留钢琴要求人声及钢琴工程完全相同。')
            copytree(Path(preserve_piano_from)/'piano',folder,dirs_exist_ok=True)
            # 器乐合理分句与十二品硬限制：新增另存目录深度可不同；保留钢琴音乐／音频，只重定位HTML本地资源。
            from accompaniment_package_links import rebase_copied_html
            relocated_html = rebase_copied_html(preserve_piano_from, output,
                [p.relative_to(Path(preserve_piano_from)) for p in (Path(preserve_piano_from)/'piano').rglob('*.html')])
            parsed,xml_check=parse_musicxml_notes(ET.parse(folder/'score.musicxml').getroot())
            expected={n['id']:(n['start_tick'],n['end_tick'],n['pitch_midi']) for n in arrangement['notes']}
            actual={identity:(row['start_tick'],row['end_tick'],row['pitch_midi']) for identity,row in parsed.items()}
            midi_check=validate_midi(folder/'accompaniment.mid',arrangement,vocal)
            if actual!=expected or not xml_check['valid'] or not midi_check['valid']:
                raise ValueError('保留钢琴实际导出与认可工程不符。')
            # 吉他器乐低把位与指型复用：修改，旧未导入名称保留；沿用现有copy及score模块。
            # result=deepcopy(read_json(Path(preserve_piano_from)/'validation.json')['instruments']['piano'])
            result=copy.deepcopy(score.read_json(Path(preserve_piano_from)/'validation.json')['instruments']['piano'])
            # 器乐合理分句与十二品硬限制：修改，旧全字节声明保留；目录变化时HTML路径可改变，音乐／音频保持。
            # result['preserved_delivery']={'source':str(Path(preserve_piano_from).resolve()),'all_original_bytes_preserved':True}
            result['preserved_delivery']={'source':str(Path(preserve_piano_from).resolve()),
                'all_original_bytes_preserved':not relocated_html, 'music_and_audio_bytes_preserved':True,
                'relocated_html_files':relocated_html}
            validation['instruments'][instrument]=result
            continue
        # 常用指型与器乐独奏：修改，原只允许换弦说明保留；优先同音换弦，无解时最小释音并保存审计。
        # 常用指型与器乐独奏：新增在挑完整指型前先修正实际弦品的持续时序，不以移八度或截音代替。
        # 吉他器乐低把位与指型复用：修改，旧精确换弦入口保留；新联合规划不得被导出阶段再改成另一个按法。
        # if instrument=='guitar':refinger_exact_positions(shared,vocal,arrangement)
        if instrument=='guitar':
            if arrangement.get('instrumental_register'):
                from guitar_instrumental_register import validate_instrumental_register
                register_check=validate_instrumental_register(shared,vocal,arrangement)
                if not register_check['valid']:
                    raise ValueError('吉他器乐低把位来源／持续音校验失败：'+str(register_check['errors'][:6]))
            else:
                refinger_exact_positions(shared,vocal,arrangement)
        # 和弦指型与X六线谱：新增由实际音符重新派生显示；保持规范XML/MIDI的数字弦品。
        # 常用指型与器乐独奏：修改，原只核查静态覆盖保留；完整导出提供实际速度时间轴。
        # if instrument=='guitar':prepare_diagrams(shared,arrangement)
        if instrument=='guitar':prepare_diagrams(shared,arrangement,vocal)
        # 六线谱同拍节奏连线：新增派生的拍号与节奏显示配置，便于独立重导校验。
        if instrument=='guitar':prepare_rhythm(vocal,arrangement)
        # 节奏符号说明与声部对齐：新增导出层共同记谱拍点配置，试听和XML按原音乐导出。
        if instrument=='guitar':prepare_alignment(arrangement)
        root,mapping=build_musicxml(shared,vocal,arrangement);ET.indent(root,space='  ')
        data=ET.tostring(root,encoding='utf-8',xml_declaration=True);(folder/'score.musicxml').write_bytes(data);write_mxl(folder/'score.mxl',data)
        save_json(folder/'xml_note_sources.json',mapping)
        parsed,xml_check=parse_musicxml_notes(ET.parse(folder/'score.musicxml').getroot())
        expected={n['id']:(n['start_tick'],n['end_tick'],n['pitch_midi']) for n in arrangement['notes']}
        actual={identity:(row['start_tick'],row['end_tick'],row['pitch_midi']) for identity,row in parsed.items()}
        if actual!=expected:xml_check['errors'].append('musicxml_sound_or_interval_differs_from_project')
        if any(length!=clock.bar_ticks for length in xml_check['measure_lengths']):xml_check['errors'].append('musicxml_incomplete_measure')
        xml_check['valid']=not xml_check['errors']
        write_midi(folder/'accompaniment.mid',arrangement,vocal);midi_check=validate_midi(folder/'accompaniment.mid',arrangement,vocal)
        # 结构稳定伴奏与人声合播：修改，原代码注释保留。
        # audio=synthesize(folder/'preview.wav',arrangement,vocal);renderer=None;tab_check=None
        audio=synthesize(folder/'preview.wav',arrangement,vocal);renderer=None;tab_check=None
        singing_meta=write_singing_preview(folder,folder/'preview.wav',voice,voice_meta) if singing else None
        if instrument=='guitar':
            row_dir=folder/'rows';row_dir.mkdir(parents=True,exist_ok=True);rows=[]
            # 和弦指型与X六线谱：修改，原四小节行保留；两小节一行方便读黑点指型。
            # for first in range(1,vocal['statistics']['measure_count']+1,4):
            #     last=min(first+3,vocal['statistics']['measure_count']);svg=guitar_row(shared,vocal,arrangement,first,last)
            row_measures=arrangement['tab_display']['rows_measures']
            # 强拍相位与伴奏同步纠错：修改，原固定内部分组保留；开头弱起不挤入四小节正文。
            # for first in range(1,vocal['statistics']['measure_count']+1,row_measures):
            #     last=min(first+row_measures-1,vocal['statistics']['measure_count']);svg=guitar_row(shared,vocal,arrangement,first,last)
            from beat_phase_alignment import score_row_ranges
            for first,last in score_row_ranges(vocal,row_measures):
                svg=guitar_row(shared,vocal,arrangement,first,last)
                path=row_dir/f'measures_{first:03}_{last:03}.svg';path.write_text(svg,encoding='utf-8')
                rows.append({'first':first,'last':last,'guitar':svg,'file':str(path)})
            tab_check=validate_tab(rows,arrangement)
            # 节奏符号说明与声部对齐：新增回读整曲可见字形和实际TAB中心，而非只核隐藏布局数据。
            # 器乐背景休止与旋律突出：修改，旧对原背景候选的几何验收保留；核验实际公开参考视图与TAB同刻对齐。
            # alignment_check=validate_time_alignment(rows,arrangement,vocal,shared)
            from guitar_instrumental_expression import reference_vocal
            alignment_check=validate_time_alignment(rows,arrangement,reference_vocal(vocal,arrangement),shared)
            # 和弦指型与X六线谱：修改，原先独立参考按法目录保留；新版目录去重当前实际按法。
            # charts='<h1>'+html.escape(vocal['title'])+' · 和弦指型参考</h1><nav><a href="score.html">返回简谱/六线谱</a><button onclick="window.print()">打印指型</button></nav><p>图上方为指型名，下方为实际和弦名。变调夹固定，实际弹奏的弦品、换把与持续音按六线谱。</p><div class="charts">'
            # charts+=''.join('<div class="chart">'+chord_chart_svg(chart)+'</div>' for chart in arrangement['chord_charts'])+'</div>'
            charts='<h1>'+html.escape(vocal['title'])+' · 和弦指型目录</h1><nav><a href="score.html">返回简谱/六线谱</a><button onclick="window.print()">打印指型</button></nav><p>黑点与横按和正文一致，第一行标出起始品数；同名和弦可有不同实际按法。下方标实际和弦名。</p><div class="charts">'
            unique={}
            for chart in arrangement['fingering_diagrams']:
                # 结构稳定伴奏与人声合播：修改，原代码注释保留。
                # unique.setdefault((chart['shape_name'],tuple(sorted(chart['frets'].items()))),chart)
                unique.setdefault((chart['shape_name'],chart['capo'],tuple(sorted(chart['frets'].items()))),chart)
            charts+=''.join('<div class="chart">'+chord_chart_svg(chart)+'</div>' for chart in unique.values())+'</div>'
            (folder/'chords.html').write_text(html_page(vocal['title']+' · 和弦指型',charts),encoding='utf-8')
        else:
            rows,renderer=render_piano(root,folder,shared,vocal)
        write_score_html(folder,shared,vocal,arrangement,rows)
        playability=validate_playability(arrangement,clock)
        # 常用指型与器乐独奏：新增图式持握、增减按指、器乐匹配与时序验收，钢琴流程保持独立。
        grip_check=validate_grip_policy(shared,arrangement,vocal) if instrument=='guitar' else None
        # 常用右手伴奏型：新增最终实际音符的模板语义验收，换弦后也必须成立。
        from guitar_right_hand_patterns import validate_patterns
        pattern_check=validate_patterns(shared,arrangement) if instrument=='guitar' else None
        result={'xml':xml_check,'midi':midi_check,'playability':playability,'audio':audio,'renderer':renderer,'tab':tab_check,
                'editable_formats':['MusicXML','MXL','project.json'],'external_editor_gui_roundtrip':'not_tested'}
        validation['instruments'][instrument]=result
        # 结构稳定伴奏与人声合播：修改，原代码注释保留。
        # if grip_check:result['grip_policy']=grip_check
        if singing_meta:
            result['singing_audio']=singing_meta
            singing_check=validate_singing_preview(folder,shared,vocal);result['singing_validation']=singing_check
            if not singing_check['valid']:raise ValueError('原歌手合播校验不通过：'+str(singing_check['errors']))
        if instrument=='guitar' and arrangement['configuration'].get('capo_segments'):
            capo_check=validate_capo(arrangement,vocal,root);result['capo']=capo_check
            structure_check=validate_structure(shared,vocal,arrangement,rows);result['structure']=structure_check
            if not capo_check['valid'] or structure_check and not structure_check['valid']:
                raise ValueError('分段夹位/结构/四小节布局校验失败：'+str(capo_check['errors'])+str(structure_check['errors'] if structure_check else []))
        if grip_check:result['grip_policy']=grip_check
        if pattern_check:result['right_hand_patterns']=pattern_check
        # 规整分解节奏与延音显示：新增真实常规起音的成对拍格核查，不能只删除附点图形。
        regular_check=validate_regular_rhythm(shared,arrangement) if instrument=='guitar' else None
        if regular_check:
            result['regular_rhythm']=regular_check
            if not regular_check['valid']:raise ValueError('规整伴奏实际起音不通过：'+str(regular_check['errors'][:6]))
        # 节奏符号说明与声部对齐：新增吉他独立对齐结果，钢琴输出保持原流程。
        if instrument=='guitar':result['time_alignment']=alignment_check
        # 常用指型与器乐独奏：修改，原验收条件保留；指型策略同样必须通过才能交付。
        # if not all(x['valid'] for x in (xml_check,midi_check,playability)) or tab_check and not tab_check['valid']:
        # 常用右手伴奏型：修改，原验收条件保留；音序/低音/性质音与既有语义同样通过。
        # if not all(x['valid'] for x in (xml_check,midi_check,playability)) or tab_check and not tab_check['valid'] or grip_check and not grip_check['valid']:
        # 节奏符号说明与声部对齐：修改，原验收条件保留；可见对齐失败阻止交付。
        # if not all(x['valid'] for x in (xml_check,midi_check,playability)) or tab_check and not tab_check['valid'] or grip_check and not grip_check['valid'] or pattern_check and not pattern_check['valid']:
        if not all(x['valid'] for x in (xml_check,midi_check,playability)) or tab_check and not tab_check['valid'] or grip_check and not grip_check['valid'] or pattern_check and not pattern_check['valid'] or instrument=='guitar' and not alignment_check['valid']:
            save_json(output/'validation.json',validation);raise ValueError(instrument+'导出与演奏校验不通过。')
    # 相似乐句和弦框架复用：修改，原保存显示视图保留；原始分析与实际编配分别持久化。
    # save_json(output/'shared_analysis.json',shared)
    save_json(output/'shared_analysis.json',storage_shared)
    # 渴首次吉他编配：修改，可编辑工程明确记录实际交付范围；原代码注释保留。
    # project={'schema_version':1,'artifact_kind':'editable_guitar_and_piano_accompaniment','title':vocal['title'],
    # 渴首次吉他编配：新增按所选乐器执行，保留各乐器原验证。
    artifact_kind='editable_guitar_and_piano_accompaniment' if 'piano' in arrangements else 'editable_guitar_accompaniment'
    project={'schema_version':1,'artifact_kind':artifact_kind,'title':vocal['title'],
             # 相似乐句和弦框架复用：修改，原工程只存单一和声保留；统一视图只用于导出，工程保留审计。
             # 'accepted_vocal_project':vocal,'shared_analysis':shared,'arrangements':arrangements,
             'accepted_vocal_project':vocal,'shared_analysis':storage_shared,'arrangements':arrangements,
             'editing':'修改本工程notes的音高/弦品/起止tick或和声后，用--edited-project重新验证导出；不能覆盖原人声工程。'}
    save_json(output/'project.json',project);write_review(output,shared,vocal,arrangements)
    # 渴首次吉他编配：修改，总入口只展示实际生成的谱面；原代码注释保留。
    # summary='<h1>'+html.escape(vocal['title'])+' · 吉他与钢琴伴奏</h1><p>共用和声分析，分别为两种乐器编配。人声简谱沿用已认可成果。</p><p class="notice">自动编配初稿：完整曲长已覆盖，和声与原曲织体仍需逐段听审。</p><nav><a href="guitar/score.html">吉他简谱 / 六线谱</a><a href="piano/score.html">钢琴双手谱 + 简谱参考</a><a href="review.html">原曲与分轨复核</a><a href="project.json" download>可编辑工程</a><a href="validation.json">验证记录</a></nav><div class="metrics">'
    # 渴首次吉他编配：新增按所选乐器执行，保留各乐器原验证。
    instrument_title='吉他与钢琴伴奏' if 'piano' in arrangements else '吉他伴奏'
    instrument_info='共用和声分析，分别为两种乐器编配。' if 'piano' in arrangements else '依据人声旋律与同源多轨分析编配吉他伴奏。'
    piano_link='<a href="piano/score.html">钢琴双手谱 + 简谱参考</a>' if 'piano' in arrangements else ''
    summary='<h1>'+html.escape(vocal['title'])+' · '+instrument_title+'</h1><p>'+instrument_info+'人声简谱沿用已认可成果。</p><p class="notice">自动编配初稿：完整曲长已覆盖，和声与原曲织体仍需逐段听审。</p><nav><a href="guitar/score.html">吉他简谱 / 六线谱</a>'+piano_link+'<a href="review.html">原曲与分轨复核</a><a href="project.json" download>可编辑工程</a><a href="validation.json">验证记录</a></nav><div class="metrics">'
    # 器乐背景休止与旋律突出：新增总入口同样说明休止／重音，所有播放仍用更新后的实际MIDI与合播。
    if arrangements['guitar'].get('instrumental_expression'):
        from guitar_instrumental_expression import expression_caption
        summary=summary.replace('<nav>','<p>'+html.escape(expression_caption(arrangements['guitar']))+'</p><nav>',1)
    # 渴首次吉他编配：新增总入口展示音乐未决状态，详细分轨证据仍在复核工程中。
    if storage_shared.get('source_clock_review'):
        summary=summary.replace('<nav>', '<p class="notice">部分拍位尚待听审：本版保留校准前的人声拍轴，请结合原唱检查重拍及歌词位置。</p><nav>', 1)
    for name,arr in arrangements.items():summary+='<div class="metric"><b>'+str(len(arr['notes']))+'</b>'+('吉他' if name=='guitar' else '钢琴')+'实际音符</div>'
    # 结构稳定伴奏与人声合播：修改，原代码注释保留。
    # summary+='<div class="metric"><b>'+str(vocal['statistics']['measure_count'])+'</b>全曲小节</div></div><p>吉他固定变调夹第'+str(arrangements['guitar']['configuration']['capo_fret'])+'品，钢琴采用原声实际音高。前奏、间奏、尾奏含器乐旋律编配。可在两套谱内试听和打印。</p>'
    # 强拍相位与伴奏同步纠错：修改，原内部夹位编号保留；入口和谱面使用相同的正式小节编号。
    # capo_text='；'.join('第'+str(s['start_measure'])+'小节起夹'+str(s['capo_fret'])+'品' for s in arrangements['guitar']['configuration'].get('capo_segments',[])) or '夹'+str(arrangements['guitar']['configuration']['capo_fret'])+'品'
    from beat_phase_alignment import display_measure
    def capo_label(segment):
        # 强拍相位与伴奏同步纠错：新增独立弱起的夹位提示，不将其算作正式第一小节。
        number=display_measure(vocal,segment['start_measure'])
        return (('第'+number+'小节') if number.isdigit() else number)+'起夹'+str(segment['capo_fret'])+'品'
    capo_text='；'.join(capo_label(s) for s in arrangements['guitar']['configuration'].get('capo_segments',[])) or '夹'+str(arrangements['guitar']['configuration']['capo_fret'])+'品'
    # 渴首次吉他编配：修改，谱面说明与实际乐器数量一致；原代码注释保留。
    # summary+='<div class="metric"><b>'+str(vocal['statistics']['measure_count'])+'</b>全曲小节</div></div><p>吉他'+capo_text+'；钢琴采用原声实际音高。每行4小节；前奏、间奏、尾奏含器乐旋律编配。可在两套谱内试听和打印。</p>'
    # 渴首次吉他编配：新增按所选乐器执行，保留各乐器原验证。
    piano_caption='；钢琴采用原声实际音高。' if 'piano' in arrangements else '。'
    score_caption='两套谱' if 'piano' in arrangements else '谱面'
    summary+='<div class="metric"><b>'+str(vocal['statistics']['measure_count'])+'</b>全曲小节</div></div><p>吉他'+capo_text+piano_caption+'每行4小节；前奏、间奏、尾奏含器乐旋律编配。可在'+score_caption+'内试听和打印。</p>'
    # 渴首次吉他编配：修改，原唱合播说明适配单乐器；原代码注释保留。
    # if singing:summary+='<p>两套谱均可试听原歌手人声与本谱伴奏，独立调节两者音量；按小节定位同步播放。</p>'
    # 渴首次吉他编配：新增按所选乐器执行，保留各乐器原验证。
    if singing:summary+='<p>'+('两套谱均' if 'piano' in arrangements else '本谱')+'可试听原歌手人声与本谱伴奏，独立调节两者音量；按小节定位同步播放。</p>'
    # 渴首次吉他编配：修改，页面标题与输出范围一致；原代码注释保留。
    # (output/'index.html').write_text(html_page(vocal['title']+' · 两套伴奏谱',summary),encoding='utf-8')
    # 渴首次吉他编配：新增按所选乐器执行，保留各乐器原验证。
    (output/'index.html').write_text(html_page(vocal['title']+' · '+instrument_title,summary),encoding='utf-8')
    # 重复乐句折叠与多遍挂词：新增所有实际音乐验收通过后才折叠，不取代旧TAB／MIDI／来源校验。
    if fold_repeats:
        from guitar_repeat_score import write_repeat_score
        # 旧工程功能自动升级与三曲器乐表现统一：修改反复导出，旧调用保留；正式重新生成需同步刷新展开页的重音。
        # validation['guitar_repeat_layout']=write_repeat_score(output/'guitar',storage_shared,vocal,arrangements['guitar'])
        validation['guitar_repeat_layout']=write_repeat_score(output/'guitar',storage_shared,vocal,arrangements['guitar'],fresh_chronological=True)
        project['guitar_score_layout']={'mode':'repeat_folded','plan':'guitar/repeat_plan.json','music_unchanged':True}
        save_json(output/'project.json',project)
    # 吉他编配规则闭环修复：修改旧单凭结构／左手即通过的尾端，旧行保留；所有新实际交付须共用硬验收。
    # validation['status']='structural_and_playability_checks_passed';save_json(output/'validation.json',validation)
    from guitar_readability_acceptance import assess_guitar_readability, require_guitar_readability
    from guitar_repeat_plan import build_repeat_plan
    repeat_path=output/'guitar/repeat_plan.json'
    repeat_plan=score.read_json(repeat_path) if fold_repeats and repeat_path.is_file() else build_repeat_plan(storage_shared,vocal,arrangements['guitar'])
    if not fold_repeats:save_json(repeat_path,repeat_plan)
    readable=assess_guitar_readability(project,repeat_plan=repeat_plan,output_dir=output)
    if not fold_repeats and repeat_plan.get('folded_blocks'):
        readable['errors'].append('qualified_long_reuse_missing_from_actual_printed_score')
        readable.update(valid=False,status='failed')
    validation['guitar_readability_acceptance']=readable
    validation['status']='structural_and_playability_checks_passed' if readable['valid'] else 'needs_review'
    project['guitar_readability_acceptance']=readable
    if not readable['valid']:
        project['music_acceptance']={**project.get('music_acceptance',{}),'status':'needs_review',
                                     'reason':'guitar_readability_contract_failed','errors':readable['errors']}
    save_json(output/'guitar_readability_acceptance.json',readable)
    save_json(output/'project.json',project);save_json(output/'validation.json',validation)
    require_guitar_readability(project,readable)
    return validation
