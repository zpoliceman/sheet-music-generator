"""第四首《日落大道》男声跨歌曲验证：新增人声调性与重复唱句转调证据，不读取参考谱。"""
from collections import defaultdict
from difflib import SequenceMatcher
import copy
MIN_GAP_SECONDS=8.
MIN_SECTION_CHARACTERS=24
MIN_PAIRED_CHARACTERS=12
MIN_TRANSPOSE_SUPPORT=.75
# 第四首《日落大道》男声跨歌曲验证：新增逐字主导实际音高，仅给调性证据，不改旋律或字音归属。
def character_pitches(pieces):
    weights=defaultdict(lambda:defaultdict(float))
    for n in pieces:
        if n.get('lyric_index') is not None:
            weights[n['lyric_index']][n['pitch_midi']]+=(n['end_seconds']-n['start_seconds'])*max(.05,n.get('confidence') or .3)
    return {i:max(values,key=values.get) for i,values in weights.items()}

# 第四首《日落大道》男声跨歌曲验证：新增按相同唱句配对，至少两句/十二字共同支持同向移调才接受。
def repeated_phrase_shift(previous,current,characters,delta):
    lines=defaultdict(list)
    for c in characters:lines[c['line_index']].append(c)
    prev_pitch=character_pitches(previous);new_pitch=character_pitches(current)
    old_lines=[cs for cs in lines.values() if sum(c['index'] in prev_pitch for c in cs)>=6]
    new_lines=[cs for cs in lines.values() if sum(c['index'] in new_pitch for c in cs)>=6]
    pairs=[]
    for new in new_lines:
        # 中文版本冻结与英文融合验证：注释保留被替换的原实现。
        # text=''.join(c['text'] for c in new);options=[]
        # 中文版本冻结与英文融合验证：新增中英文兼容实现。
        from lyrics_tokens import lyric_match_key
        text=[lyric_match_key(c['text']) for c in new];options=[]
        for old in old_lines:
            # 中文版本冻结与英文融合验证：注释保留被替换的原实现。
            # matcher=SequenceMatcher(None,''.join(c['text'] for c in old),text,autojunk=False)
            # 中文版本冻结与英文融合验证：新增中英文兼容实现。
            matcher=SequenceMatcher(None,[lyric_match_key(c['text']) for c in old],text,autojunk=False)
            matched=[(old[b.a+i]['index'],new[b.b+i]['index']) for b in matcher.get_matching_blocks() for i in range(b.size)
                     if old[b.a+i]['index'] in prev_pitch and new[b.b+i]['index'] in new_pitch]
            if len(matched)<6 or len(matched)/len(new)<.70:continue
            shifts=[((new_pitch[b]-prev_pitch[a]+6)%12)-6 for a,b in matched]
            support=sum(d==delta for d in shifts)/len(shifts)
            options.append((len(matched)/len(new),support,matched,shifts,old[0]['line_index']))
        if options:
            coverage,support,matched,shifts,line=max(options,key=lambda x:(x[0],x[1]))
            pairs.append({'previous_line_index':line,'current_line_index':new[0]['line_index'],
                          'paired_characters':len(matched),'support':support,'semitone_differences':shifts})
    count=sum(p['paired_characters'] for p in pairs)
    support=sum(p['paired_characters']*p['support'] for p in pairs)/count if count else 0.
    return {'accepted':len(pairs)>=2 and count>=MIN_PAIRED_CHARACTERS and support>=MIN_TRANSPOSE_SUPPORT,
            'semitones':delta,'phrase_pairs':pairs,'paired_characters':count,'support':support,'accuracy_probability':False}

# 第四首《日落大道》男声跨歌曲验证：新增只用真正挂词声段取主调；长停顿分段候选需文本及音高共同支持。
# 连续转调识别与不确定调性保护：替换旧长停顿必要条件，原函数完整注释保留。
# def infer_sections(pieces,characters,infer_key,key_definition):
#     owned=[copy.deepcopy(n) for n in pieces if n.get('lyric_index') is not None]
#     if not owned:raise ValueError('没有可确认的人声声段来推断调性。')
#     native=infer_key(owned);native['scope']='lyric_owned_vocal_notes';native['excluded_unassigned_note_count']=len(pieces)-len(owned)
#     groups=[[]]
#     for n in owned:
#         if groups[-1] and n['start_seconds']-groups[-1][-1]['end_seconds']>=MIN_GAP_SECONDS:groups.append([])
#         groups[-1].append(n)
#     # 第四首《日落大道》男声跨歌曲验证：修改起始调取可靠首个人声段；整曲混合转调分布不能反向改写开始的调。
#     # sections=[];audit=[];prior=[];initial_key=key_definition(native['selected']);previous_key=initial_key
#     first=infer_key(groups[0]);first_count=len({n['lyric_index'] for n in groups[0]})
#     if first_count>=MIN_SECTION_CHARACTERS and first['margin']>=.03 and first['candidates'][0]['correlation']>=.45:
#         aggregate=copy.deepcopy(native);native=first;native['aggregate_vocal_evidence']=aggregate
#         native['scope']='first_reliable_vocal_section';native['excluded_unassigned_note_count']=len(pieces)-len(owned)
#     sections=[];audit=[];prior=[];initial_key=key_definition(native['selected']);previous_key=initial_key
#     for index,group in enumerate(groups):
#         evidence=infer_key(group);candidate=key_definition(evidence['selected'])
#         record={'first_seconds':group[0]['start_seconds'],'last_seconds':group[-1]['end_seconds'],
#                 'character_count':len({n['lyric_index'] for n in group}),'candidate':evidence,'accepted_change':False}
#         selected=previous_key
#         if index and record['character_count']>=MIN_SECTION_CHARACTERS and candidate['mode']==previous_key['mode'] and candidate['label']!=previous_key['label']:
#             delta=((candidate['tonic_pc']-previous_key['tonic_pc']+6)%12)-6
#             support=repeated_phrase_shift(prior,group,characters,delta);record['repeat_evidence']=support
#             if delta and evidence['margin']>=.03 and evidence['candidates'][0]['correlation']>=.45 and support['accepted']:
#                 selected=candidate;record['accepted_change']=True
#         if not sections or selected['label']!=previous_key['label']:
#             sections.append({'start_seconds':group[0]['start_seconds'],'key':selected,'source_key':selected,
#                              'first_character_index':min(n['lyric_index'] for n in group),'evidence':record})
#         previous_key=selected;audit.append(record);prior.extend(group)
#     native['section_candidates']=audit;native['modulation_not_modeled']=False
#     native['modulation_detection']='long_vocal_gap_and_repeated_phrase_transposition'
#     return native,sections if len(sections)>1 else []

# 连续转调识别与不确定调性保护：新增局部分段入口，旧重复歌词验证作为辅助证据保留。
def infer_sections(pieces,characters,infer_key,key_definition):
    from local_tonality import infer_sections as infer_local_sections
    return infer_local_sections(pieces,characters,infer_key,key_definition,repeated_phrase_shift)
