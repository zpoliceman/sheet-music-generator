"""连续转调识别与不确定调性保护：唱句及持续音高证据先分调，再对可靠段应用调式约束。"""
# 连续转调识别与不确定调性保护：新增通用局部规则，不读取歌曲名、参考谱或固定字序答案。
from collections import defaultdict
import copy

PARAMETERS={'minimum_phrase_units':6,'maximum_block_units':8,'minimum_change_units':12,'minimum_supporting_blocks':2,'minimum_correlation':.50,'minimum_margin':.03,'minimum_candidate_scale_fit':.86,'minimum_scale_gain':.16,'melody_minimum_scale_gain':.08,'minimum_new_pitch_classes':2,'uncertain_scale_gain':.10,'uncertain_current_fit':.82,'minimum_aggregate_scale_fit':.78}
MAJOR=frozenset((0,2,4,5,7,9,11))

# 连续转调识别与不确定调性保护：新增时长/支持加权音阶解释率，保留连续音高之外的原始音段不变。
def scale_fit(notes,key):
    weights=[(n['end_seconds']-n['start_seconds'])*max(.05,n.get('confidence') or .3) for n in notes]
    total=sum(weights)
    return sum(w for w,n in zip(weights,notes) if (n['pitch_midi']-key['tonic_pc'])%12 in MAJOR)/total if total else 0.

# 连续转调识别与不确定调性保护：新增按歌词行及最长八个真实声单位划局部块，无需长停唱。
def blocks_for(owned,characters):
    lines={c['index']:c.get('line_index',0) for c in characters};groups=[];current=[];indices=set();last_line=None
    for note in owned:
        line=lines.get(note['lyric_index'],last_line)
        if current and (line!=last_line or (note['lyric_index'] not in indices and len(indices)>=PARAMETERS['maximum_block_units'])):
            groups.append(current);current=[];indices=set()
        current.append(note);indices.add(note['lyric_index']);last_line=line
    if current:groups.append(current)
    combined=[];pending=[]
    for group in groups:
        pending+=group
        if len({n['lyric_index'] for n in pending})>=PARAMETERS['minimum_phrase_units']:
            combined.append(pending);pending=[]
    if pending:combined.append(pending)
    return combined

# 连续转调识别与不确定调性保护：新增不依赖歌词文本的重复旋律证据，八度变化的调距为零。
def melody_shift(previous,following,delta):
    def pitches(group):
        totals=defaultdict(lambda:defaultdict(float))
        for n in group:totals[n['lyric_index']][n['pitch_midi']]+=max(.05,n.get('confidence') or .3)*(n['end_seconds']-n['start_seconds'])
        return [max(totals[i],key=totals[i].get) for i in sorted(totals)]
    old=[pitches(g) for g in previous];pairs=[]
    for group in following:
        new=pitches(group);options=[]
        if len(new)<6:continue
        for before in old:
            if len(before)!=len(new) or len(set(p%12 for p in before))<3:continue
            shifts=[((b-a+6)%12)-6 for a,b in zip(before,new)]
            support=sum(d==delta for d in shifts)/len(shifts)
            if support>=.75:options.append((support,len(shifts)))
        if options:pairs.append(max(options))
    units=sum(n for _,n in pairs)
    return {'accepted':bool(delta) and len(pairs)>=2 and units>=12,'paired_blocks':len(pairs),'paired_units':units,'support':sum(s*n for s,n in pairs)/units if units else 0.,'semitones':delta,'confidence_is_accuracy':False}

# 连续转调识别与不确定调性保护：新增疑难段合并，候选仅作复核证据，不作为已确认转调。
def merge_regions(regions):
    out=[]
    for region in sorted(regions,key=lambda r:r['start_seconds']):
        if out and region['reason']==out[-1]['reason'] and region['first_character_index']<=out[-1]['last_character_index']+1:
            out[-1]['end_seconds']=max(out[-1]['end_seconds'],region['end_seconds']);out[-1]['last_character_index']=max(out[-1]['last_character_index'],region['last_character_index'])
        else:out.append(copy.deepcopy(region))
    for i,r in enumerate(out):r['id']='tonality-uncertain-'+str(i+1)
    return out

# 连续转调识别与不确定调性保护：新增基准证据不足、小调诊断及原音保护区域。
def uncertain_region(group,reason,evidence,key=None):
    return {'start_seconds':group[0]['start_seconds'],'end_seconds':group[-1]['end_seconds'],'first_character_index':min(n['lyric_index'] for n in group),'last_character_index':max(n['lyric_index'] for n in group),'reason':reason,'candidate_key':evidence['selected'],'previous_key':key['label'] if key else None,'preserve_acoustic_pitch':True,'candidate_evidence':evidence}

# 连续转调识别与不确定调性保护：新增邻近音段变化点优化；共有音的边界歧义保存在证据中。
def refine_boundary(groups,index,old_key,new_key):
    before=groups[max(0,index-1)] if index else []
    after=[n for g in groups[index:index+2] for n in g]
    notes=before+after;preferred=len(before);scores=[]
    for split in range(len(before)+len(groups[index])+1):
        if split==len(notes):continue
        cost=0.
        for j,n in enumerate(notes):
            key=old_key if j<split else new_key
            if (n['pitch_midi']-key['tonic_pc'])%12 not in MAJOR:cost+=(n['end_seconds']-n['start_seconds'])*max(.05,n.get('confidence') or .3)
        scores.append((cost,abs(split-preferred),split))
    best=min(scores);minimum=best[0];ties=[s for c,_,s in scores if abs(c-minimum)<1e-8]
    return notes[best[2]],{'method':'weighted_scale_change_point','tied_boundary_indices':[notes[s]['lyric_index'] for s in ties],'preferred_block_first_character':groups[index][0]['lyric_index'],'boundary_requires_review':len(ties)>1}

# 连续转调识别与不确定调性保护：新增持续局部候选、旋律辅助证据和保护，兼容旧长间奏统计基准。
def infer_sections(pieces,characters,infer_key,key_definition,repeated_phrase_shift):
    owned=sorted((copy.deepcopy(n) for n in pieces if n.get('lyric_index') is not None),key=lambda n:(n['start_seconds'],n['end_seconds']))
    if not owned:raise ValueError('没有可确认的人声声段来推断调性。')
    aggregate=infer_key(owned);gapped=[[]]
    for n in owned:
        if gapped[-1] and n['start_seconds']-gapped[-1][-1]['end_seconds']>=8.:gapped.append([])
        gapped[-1].append(n)
    first=infer_key(gapped[0]);native=copy.deepcopy(aggregate)
    if len({n['lyric_index'] for n in gapped[0]})>=24 and first['margin']>=.03 and first['candidates'][0]['correlation']>=.45:
        native=copy.deepcopy(first)
    groups=blocks_for(owned,characters)
    prefix=[]
    for group in groups:
        prefix+=group
        if len({n['lyric_index'] for n in prefix})>=24:break
    early=infer_key(prefix);early_key=key_definition(early['selected']);initial=key_definition(native['selected'])
    # 连续转调识别与不确定调性保护：新增首段证据范围，后续转调不能反向降低可靠起始段。
    baseline_notes=gapped[0]
    if early['candidates'][0]['correlation']>=.60 and early['margin']>=.03 and not early.get('unsupported_minor_may_fit_better') and scale_fit(prefix,early_key)>=.88 and scale_fit(prefix,early_key)-scale_fit(prefix,initial)>=.16:
        # 连续转调识别与不确定调性保护：修改首段证据范围，原赋值保留。
        # native=copy.deepcopy(early);initial=early_key
        native=copy.deepcopy(early);initial=early_key;baseline_notes=prefix
    native['aggregate_vocal_evidence']=aggregate;native['scope']='first_reliable_vocal_section';native['excluded_unassigned_note_count']=len(pieces)-len(owned)
    # 连续转调识别与不确定调性保护：修改不确定基准的证据范围，原代码保留。
    # regions=[];base_fit=scale_fit(gapped[0],initial)
    regions=[];base_fit=scale_fit(baseline_notes,initial)
    if native.get('unsupported_minor_may_fit_better'):
        regions.append(uncertain_region(owned,'unsupported_minor_may_fit_better',native,initial))
    elif native['candidates'][0]['correlation']<.50 or base_fit<.78 or (native['margin']<.025 and base_fit<.90) or len({n['pitch_midi']%12 for n in owned})<3:
        regions.append(uncertain_region(owned,'weak_baseline_tonality',native,initial))
    sections=[{'start_seconds':owned[0]['start_seconds'],'key':initial,'source_key':initial,'first_character_index':owned[0]['lyric_index'],'evidence':{'candidate':copy.deepcopy(native),'accepted_change':False}}]
    current=initial;audits=[]
    for index,group in enumerate(groups):
        window=[];following=[]
        for nxt in groups[index:index+3]:
            following.append(nxt);window+=nxt
            if len({n['lyric_index'] for n in window})>=12:break
        found=infer_key(window);candidate=key_definition(found['selected']);delta=((candidate['tonic_pc']-current['tonic_pc']+6)%12)-6
        candidate_fit=scale_fit(window,candidate);current_fit=scale_fit(window,current);gain=candidate_fit-current_fit
        prior=[n for g in groups[:index] for n in g]
        text_support=repeated_phrase_shift(prior,window,characters,delta) if delta else {'accepted':False}
        melody_support=melody_shift(groups[:index],following,delta) if delta else {'accepted':False}
        repeated=text_support['accepted'] or melody_support['accepted']
        distinct={n['pitch_midi']%12 for n in window if (n['pitch_midi']-current['tonic_pc'])%12 not in MAJOR and (n['pitch_midi']-candidate['tonic_pc'])%12 in MAJOR}
        supporting=sum(len({n['lyric_index'] for n in g})>=4 and scale_fit(g,candidate)>=.86 and scale_fit(g,candidate)-scale_fit(g,current)>=.08 for g in following)
        local=infer_key(group);local_fit=scale_fit(group,current);local_gain=scale_fit(group,candidate)-local_fit
        record={'first_seconds':group[0]['start_seconds'],'last_seconds':window[-1]['end_seconds'],'character_count':len({n['lyric_index'] for n in window}),'candidate':found,'accepted_change':False,'previous_key':current['label'],'candidate_scale_fit':candidate_fit,'previous_scale_fit':current_fit,'scale_fit_gain':gain,'supporting_blocks':supporting,'novel_pitch_classes':sorted(distinct),'repeat_evidence':text_support,'melody_repeat_evidence':melody_support}
        enough=len({n['lyric_index'] for n in window})>=12 and supporting>=2
        reliable=found['candidates'][0]['correlation']>=.50 and found['margin']>=.03 and not found.get('unsupported_minor_may_fit_better') and candidate_fit>=.86
        change=bool(delta) and enough and reliable and local_gain>=.08 and (gain>=.16 and len(distinct)>=2 or repeated and gain>=.08)
        if change:
            boundary,boundary_audit=refine_boundary(groups,index,current,candidate)
            if boundary['lyric_index']>sections[-1]['first_character_index']:
                record['accepted_change']=True;record['boundary']=boundary_audit
                sections.append({'start_seconds':boundary['start_seconds'],'key':candidate,'source_key':candidate,'first_character_index':boundary['lyric_index'],'evidence':record})
                current=candidate
                regions=[r for r in regions if not (r['reason']=='possible_unconfirmed_modulation' and r['candidate_key']==candidate['label'] and r['first_character_index']>=boundary['lyric_index'])]
        # 连续转调识别与不确定调性保护：短桥段只用本段候选保护，避免后续原调唱句稀释掉升调证据。
        # elif bool(delta) and local_gain>=.10 and local_fit<.82:
        #     regions.append(uncertain_region(group,'possible_unconfirmed_modulation',found,current))
        elif local['selected']!=current['label'] and local_fit<.82 and scale_fit(group,key_definition(local['selected']))-local_fit>=.10 and len({n['pitch_midi']%12 for n in group if (n['pitch_midi']-current['tonic_pc'])%12 not in MAJOR})>=2:
            regions.append(uncertain_region(group,'possible_unconfirmed_modulation',local,current))
        elif local.get('unsupported_minor_may_fit_better') and local_fit<.78:
            regions.append(uncertain_region(group,'local_minor_or_modal_ambiguity',local,current))
        audits.append(record)
    native['section_candidates']=audits;native['modulation_not_modeled']=False;native['modulation_detection']='local_blocks_scale_gain_and_melody_persistence';native['local_tonality_parameters']=PARAMETERS;native['uncertain_regions']=merge_regions(regions)
    return native,sections if len(sections)>1 else []
