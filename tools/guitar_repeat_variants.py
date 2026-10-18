"""相似长段复用与默认阅读修复：保留真实少量变奏的阅读复用，不修改演奏音乐。"""
# 相似长段复用与默认阅读修复：新增显示层策略；各遍不同小节必须实际画出，不能冒充逐音相同。
from copy import deepcopy
from collections import Counter
import xml.etree.ElementTree as ET
from accompaniment_analysis import SongClock
from guitar_capo import capo_at
from guitar_repeat_readability import candidates,musical_boundaries,POLICY
from phrase_harmony_plan import melody_signature,similarity

# 相似长段复用与默认阅读修复：修改句首／句末的明确变奏也可保留，不能用边缘一小节的差异否定完整长段。
# VARIANT_POLICY={'version':1,'maximum_variant_bars':2,'minimum_exact_bar_ratio':.8,
#     'maximum_span_bars':32,'first_and_last_bar_exact':True,'extra_reading_cost_per_variant_bar':1,
# 完整乐句与实际时长复用：修改旧小节计数策略；原代码注释保留。
# VARIANT_POLICY={'version':1,'maximum_variant_bars':2,'minimum_exact_bar_ratio':.8,
#     'maximum_span_bars':32,'first_and_last_bar_exact':False,'extra_reading_cost_per_variant_bar':1,
#     'scope':'regular_vocal_bars_only','music':'unchanged_complete_variant_tab_is_mandatory'}
VARIANT_POLICY={'version':2,'difference_basis':'actual_note_duration_and_contiguous_variants',
    'minimum_shared_note_duration_ratio':.8,'scope':'regular_vocal_bars_only',
    'music':'unchanged_complete_variant_tab_is_mandatory'}
NS='{http://www.w3.org/2000/svg}'


def variant_pairs(group):
    # 相似长段复用与默认阅读修复：新增实际替代来源映射，与主回跳路线分开，不增加小节跳转。
    return {(v['canonical_measure'],v['source_measure']) for v in group.get('variant_bars',[])}


def _regular_bars(project,timeline):
    # 相似长段复用与默认阅读修复：新增按真实起音／时值／弦序确认普通唱段，器乐和持续跨界不得近似折叠。
    guitar=project['arrangements']['guitar'];result={}
    selected=set(guitar.get('section_patterns',{}).get('arranged_measures',[]))
    clock=SongClock(project['accepted_vocal_project'])
    for measure in timeline:
        number=measure['number'];a,b=measure['start_tick'],measure['end_tick']
        if number not in selected or b-a!=1920 or measure['meter']!=[4,4] or measure.get('pickup'):continue
        notes=sorted((n for n in guitar['notes'] if n['start_tick']<b and n['end_tick']>a),key=lambda n:n['start_tick'])
        if len(notes) not in (4,8):continue
        step=1920//len(notes);tokens=[]
        for index,note in enumerate(notes):
            if (note.get('section')!='vocal' or note.get('role') not in ('bass','harmony') or note.get('source_melody_id')
                    or note['start_tick']!=a+index*step or note['end_tick']!=a+(index+1)*step):break
            if note.get('role')=='bass' and note['string'] in (4,5,6):tokens.append('B')
            elif note.get('role')=='harmony' and note['string'] in (1,2,3):tokens.append(str(note['string']))
            else:break
        else:
            if ''.join(tokens) not in ('B321','B321B321','B3231323'):continue
            key_points={a}|{s['start_tick'] for s in project['accepted_vocal_project']['notation'].get('key_segments',[]) if a<s['start_tick']<b}
            capo_points={a}|{s['start_tick'] for s in guitar['configuration'].get('capo_segments',[]) if a<s['start_tick']<b}
            result[number]=(step,''.join(tokens),[(t-a,clock.key(t)) for t in sorted(key_points)],
                            [(t-a,capo_at(guitar,t)) for t in sorted(capo_points)])
    return result


# 完整乐句与实际时长复用：修改旧小节计数策略；原代码注释保留。
# def propose_with_variants(shared,vocal,signatures,project,timeline):
#     # 相似长段复用与默认阅读修复：新增先保留精确候选，再允许完整长段最多两小节明确变奏；不缩小8小节门槛。
#     proposed=candidates(shared,vocal,signatures);regular=_regular_bars(project,timeline)
#     if not regular:return proposed
#     starts,ends=musical_boundaries(shared,vocal);count=len(signatures);minimum=POLICY['minimum_reused_bars']
#     melody_cache={};bar_melodies={}
#     def melody(first,size):
#         # 相似长段复用与默认阅读修复：新增按小节缓存只读旋律证据，避免逐候选重复扫描整曲。
#         key=(first,size)
#         if key not in melody_cache:
#             for number in range(first,first+size):
#                 if number not in bar_melodies:bar_melodies[number]=melody_signature(shared,vocal,(number-1)*1920,number*1920)
#             melody_cache[key]={field:[value for number in range(first,first+size) for value in bar_melodies[number][field]]
#                                for field in ('pitch','activity','onset')}
#         return melody_cache[key]
#     for first in sorted(starts):
#         for second in sorted(s for s in starts if s>=first+minimum):
#             # 相似长段复用与默认阅读修复：修改句首真实差异由实际变奏图承担，仍按全段旋律／精确小节比例判断。
#             # if signatures[first-1]!=signatures[second-1]:continue
#             if VARIANT_POLICY['first_and_last_bar_exact'] and signatures[first-1]!=signatures[second-1]:continue
#             variants=[];maximum=min(VARIANT_POLICY['maximum_span_bars'],second-first,count-second+1)
#             for offset in range(maximum):
#                 a,b=first+offset,second+offset
#                 if a not in regular or b not in regular or regular[a]!=regular[b]:break
#                 if signatures[a-1]!=signatures[b-1]:variants.append(offset)
#                 if len(variants)>VARIANT_POLICY['maximum_variant_bars']:break
#                 size=offset+1
#                 # 相似长段复用与默认阅读修复：修改句末差异也须实际列出，不用旧末小节相同限制掩盖可共用主体。
#                 # if (size<minimum or not variants or a not in ends or b not in ends or offset in variants
#                 if (size<minimum or not variants or a not in ends or b not in ends
#                         or (VARIANT_POLICY['first_and_last_bar_exact'] and offset in variants)
#                         or (size-len(variants))/size<VARIANT_POLICY['minimum_exact_bar_ratio']):continue
#                 evidence=similarity(melody(first,size),melody(second,size))
#                 if not evidence['accepted']:continue
#                 gap=second-first-size;tail_ends=sorted(e for e in ends if e>=second+size)
#                 tail_end=tail_ends[0] if tail_ends else count
#                 method='repeat' if not gap else 'volta' if gap<=size and second+size<=count else 'ds'
#                 proposed.append({'first':first,'second':second,'length':size,'method':method,'last':second+size-1,
#                     'second_ending_last':tail_end if method=='volta' else None,
#                     'reading_gain':size-POLICY['reading_cost'][method]-len(variants)*VARIANT_POLICY['extra_reading_cost_per_variant_bar'],
#                     'variant_bars':[{'canonical_measure':first+i,'source_measure':second+i,'pass':2} for i in variants],
#                     'melody_evidence':evidence})
#     return proposed
def propose_with_variants(shared, vocal, signatures, project, timeline):
    # 完整乐句与实际时长复用：新增实际音乐和完整变奏共同评估；差异比例及代价不再按整小节投票。
    from guitar_phrase_repeat import propose
    return propose(shared, vocal, signatures, project['arrangements']['guitar'],
                   project=project, timeline=timeline, allow_variants=True)


def printed_music_sources(plan):
    # 相似长段复用与默认阅读修复：新增独立按印刷反复展开后选择实际印刷音乐来源；局部变奏不改变路线或总时长。
    from guitar_repeat_readability import expand_printed_bars
    result=[]
    for number in expand_printed_bars(plan):
        source=number
        for group in plan['repeat_groups']:
            if group['second_first']<=number<=group['second_last']:
                canonical=group['canonical_first']+number-group['second_first']
                source=number if (canonical,number) in variant_pairs(group) else canonical
                break
        result.append({'performed_measure':number,'printed_source_measure':source})
    return result


def block_variants(plan,block):
    # 相似长段复用与默认阅读修复：新增只列本行所在长段的实际变奏，避免续行重复画或错误挂到别段。
    return [deepcopy(v) for group in plan['repeat_groups'] if group['id']==block.get('repeat_group')
            for v in group.get('variant_bars',[]) if block['canonical_first']<=v['canonical_measure']<=block['canonical_last']]


def variant_caption(variant,pickup):
    # 相似长段复用与默认阅读修复：新增短明确奏法，替代本小节而非另加一小节。
    return f"第{variant['pass']}遍：第{variant['source_measure']-pickup}小节，替换上方第{variant['canonical_measure']-pickup}小节"


def append_variant_tabs(outer,wrapper,project,plan,block,render_row,timeline):
    # 相似长段复用与默认阅读修复：新增直接从真实来源渲染变奏指型／TAB，原多遍人声仍只在共用行完整显示。
    variants=block_variants(plan,block)
    if not variants:return []
    width=float(outer.get('width'));cursor=float(outer.get('height'));pickup=int(timeline[0].get('pickup',False))
    # 完整乐句与实际时长复用：新增同一遍的变奏共用纵向带，横向仍逐小节对齐，避免逐个下堆造成空白。
    band_origins={value:cursor+index*365 for index,value in enumerate(sorted({v['pass'] for v in variants}))}
    for variant in variants:
        # 完整乐句与实际时长复用：新增从所属遍次取得纵向位置，完整音符及替换说明不变。
        cursor=band_origins[variant['pass']]
        measure=timeline[variant['source_measure']-1]
        # 相似长段复用与默认阅读修复：修改变奏与上方两遍人声使用同一联合时间列，并放在对应小节正下方。
        # alternate=ET.fromstring(render_row(project,[measure],True))
        canonical=timeline[variant['canonical_measure']-1]
        column=next(n for n in wrapper.iter(NS+'svg') if n.get('data-vocal-pass')=='1'
                    and n.get('data-shared-measure')==str(variant['canonical_measure']))
        alternate=ET.fromstring(render_row(project,[measure],True,vocal_measures=[[canonical],[measure]]))
        if abs(float(alternate.get('width'))-float(column.get('width'))-30)>.05:
            raise ValueError('变奏与共用人声的联合小节宽度不一致，拒绝错列输出')
        column_x=float(column.get('x'))-15
        for child in list(alternate):
            if child.get('data-vocal-pass') is not None or (child.tag==NS+'text' and child.get('y')!='19'):
                alternate.remove(child)
            elif child.get('data-shared-tab'):
                child.set('transform','translate(0,-180)')
        alternate.set('height','320');alternate.set('viewBox',f"0 0 {float(alternate.get('width')):g} 320")
        # 相似长段复用与默认阅读修复：修改变奏横坐标继承真实共用时间列，不放到整行最左而错挂相邻歌词。
        # alternate.set('x','0');alternate.set('y',str(cursor+32));alternate.set('style','max-width:none')
        alternate.set('x',str(column_x));alternate.set('y',str(cursor+32));alternate.set('style','max-width:none')
        alternate.set('data-repeat-variant-pass',str(variant['pass']))
        alternate.set('data-variant-canonical-measure',str(variant['canonical_measure']))
        alternate.set('data-variant-source-measure',str(variant['source_measure']))
        # 相似长段复用与默认阅读修复：修改替换说明也贴合该小节的实际列。
        # caption=ET.SubElement(wrapper,NS+'text',{'x':'15','y':str(cursor+22),'font-size':'14','fill':'#854d24',
        caption=ET.SubElement(wrapper,NS+'text',{'x':str(column_x+15),'y':str(cursor+22),'font-size':'14','fill':'#854d24',
            'data-variant-caption-source':str(variant['source_measure'])})
        # 完整乐句与实际时长复用：修改按遍次增加行高，旧逐变奏加高保留为注释。
        # caption.text=variant_caption(variant,pickup);wrapper.append(alternate);cursor+=365
        caption.text=variant_caption(variant,pickup);wrapper.append(alternate)
        for node in wrapper.findall(NS+'g/'+NS+'text'):
            if node.get('y')=='19' and node.text==str(variant['canonical_measure']-pickup):
                node.text+=' · 1.（2.见下方变奏）'
    # 完整乐句与实际时长复用：新增容纳所有变奏带的最终边界，不裁剪较早遍次。
    cursor=max(band_origins.values())+365
    outer.set('height',str(cursor));outer.set('viewBox',f'0 0 {width:g} {cursor:g}')
    wrapper.set('height',str(cursor))
    return variants


def validate_variant_tabs(project,plan,rows):
    # 相似长段复用与默认阅读修复：新增印刷变奏映射和可见替换说明核验，删图／改来源／只留标签均不能通过。
    # 相似长段复用与默认阅读修复：删除未使用的提示缓存，实际可见文案仍逐项核验。
    # expected=[];actual=[];captions=[];errors=[]
    expected=[];actual=[];errors=[]
    pickup=int(plan['actual_measure_timeline'][0].get('pickup',False))
    for block in plan['blocks']:
        for variant in block_variants(plan,block):
            expected.append((block['id'],str(variant['canonical_measure']),str(variant['source_measure']),str(variant['pass'])))
    for row in rows:
        root=ET.fromstring(row['guitar'])
        for block in root.iter(NS+'g'):
            if block.get('class')!='repeat-block':continue
            # 完整乐句与实际时长复用：新增实际图形带的交叠／裁切核对，不能只凭来源标签声称布局正确。
            variant_bounds=[];band_positions={}
            for node in block.iter(NS+'svg'):
                if node.get('data-repeat-variant-pass') is None:continue
                value=(block.get('data-block-id'),node.get('data-variant-canonical-measure'),
                       node.get('data-variant-source-measure'),node.get('data-repeat-variant-pass'))
                actual.append(value)
                try:
                    variant={'canonical_measure':int(value[1]),'source_measure':int(value[2]),'pass':int(value[3])}
                    caption=next((c for c in block.findall(NS+'text') if c.get('data-variant-caption-source')==value[2]),None)
                    if caption is None or caption.text!=variant_caption(variant,pickup):errors.append('variant_visible_replacement_caption_missing_or_changed')
                    ids=[n.get('data-note-id') for n in node.iter() if n.get('data-string')]
                    # 扫弦箭头与实际弦组记谱修正：新增变奏实际跨弦箭头的独立解码，保留原逐弦音头核对。
                    from guitar_strum_notation import read_visible_strums
                    swept,arrow_errors=read_visible_strums(node,project['arrangements']['guitar'])
                    ids.extend(note[0] for note in swept);errors.extend(arrow_errors)
                    m=plan['actual_measure_timeline'][int(value[2])-1]
                    wanted=[n['id'] for n in project['arrangements']['guitar']['notes'] if m['start_tick']<=n['start_tick']<m['end_tick']]
                    if Counter(ids)!=Counter(wanted):errors.append('variant_actual_tab_notes_missing_or_extra')
                    # 相似长段复用与默认阅读修复：新增从真实可见音符x坐标核对各拍对齐，不能只靠来源标签声称同列。
                    canonical=plan['actual_measure_timeline'][variant['canonical_measure']-1]
                    column=next((c for c in block.iter(NS+'svg') if c.get('data-vocal-pass')=='1'
                                 and c.get('data-shared-measure')==value[1]),None)
                    if column is None or abs(float(node.get('x'))-float(column.get('x'))+15)>.05:
                        errors.append('variant_not_below_its_shared_measure')
                    # 完整乐句与实际时长复用：新增边距内实际区域及说明位置校验，同遍的多个小节须在同一带。
                    x,y,w,h=(float(node.get(k)) for k in ('x','y','width','height'))
                    variant_bounds.append((x+15,y,x+w-15,y+h))
                    if y<32 or y+h>float(root.get('height'))+.05:
                        errors.append('variant_clipped_or_invalid_band')
                    if value[3] in band_positions and abs(band_positions[value[3]]-y)>.05:
                        errors.append('same_pass_variants_not_in_same_band')
                    band_positions[value[3]]=y
                    if caption is not None and (abs(float(caption.get('x'))-x-15)>.05 or abs(float(caption.get('y'))-y+10)>.05):
                        errors.append('variant_caption_detached_from_tab')
                    main_positions={int(n.get('data-start-tick'))-canonical['start_tick']:float(n.find(NS+'text').get('x'))
                        for n in block.iter() if n.get('data-string') and canonical['start_tick']<=int(n.get('data-start-tick'))<canonical['end_tick']}
                    alt_positions={int(n.get('data-start-tick'))-m['start_tick']:float(node.get('x'))+float(n.find(NS+'text').get('x'))
                        for n in node.iter() if n.get('data-string')}
                    # 扫弦箭头与实际弦组记谱修正：新增用真实箭头杆横坐标参与变奏同拍对齐，不能靠动作标签声称同列。
                    for group in block.iter(NS+'g'):
                        if group.get('data-action-kind')=='strum' and canonical['start_tick']<=int(group.get('data-action-tick'))<canonical['end_tick']:
                            main_positions[int(group.get('data-action-tick'))-canonical['start_tick']]=float(group.find(NS+"line[@class='strum-shaft']").get('x1'))
                    for group in node.iter(NS+'g'):
                        if group.get('data-action-kind')=='strum':
                            alt_positions[int(group.get('data-action-tick'))-m['start_tick']]=float(node.get('x'))+float(group.find(NS+"line[@class='strum-shaft']").get('x1'))
                    if set(main_positions)!=set(alt_positions) or any(abs(main_positions[t]-alt_positions[t])>.05 for t in main_positions):
                        errors.append('variant_actual_attacks_not_aligned_with_shared_time_columns')
                except (ValueError,TypeError,IndexError):errors.append('variant_source_reference_invalid')
            # 完整乐句与实际时长复用：新增成对核对内侧绘图区，SVG两侧15像素留白不算音符重叠。
            for index,left in enumerate(variant_bounds):
                for right in variant_bounds[index+1:]:
                    if min(left[2],right[2])-max(left[0],right[0])>.05 and min(left[3],right[3])-max(left[1],right[1])>.05:
                        errors.append('variant_tab_regions_overlap')
    if Counter(actual)!=Counter(expected):errors.append('variant_printed_mapping_missing_or_extra')
    return {'valid':not errors,'errors':errors,'explicit_variant_bars':len(expected),'actual_variant_bars':len(actual)}
