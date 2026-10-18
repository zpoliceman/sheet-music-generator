"""通用段落强拍与乐句节奏修复：音乐短句、跨词音组及相似旋律共用的节奏求解。"""
from collections import defaultdict
from copy import deepcopy
from functools import lru_cache
import math
from itertools import product

from phrase_rhythm import (PPQ, start_candidates, end_candidates, onset_cost,
                           has_sounding_gap, release_cost)
from phrase_rhythm_local import (word_models,choose_phrases,slot_cost as binary_slot_cost,
                                 musical_onset_cost,solve_words as solve_legacy_words)
from rhythm_notation import MeterTree
from melodic_structure import infer_form

VERSION = 1
POLICY = {'version':VERSION, 'entry_window_quarters':.5, 'maximum_latency_quarters':.4,
          'entry_weight':.24, 'onset_weight':.65, 'duration_weight':.85,
          # 通用段落强拍与乐句节奏修复：修改，原权重保留；组内规整先验与演唱观测分开评分。
          # 'motif_weight':.65, 'short_group_weight':1.35, 'tuplet_complexity':.7,
          # 通用段落强拍与乐句节奏修复：修改，保留初次软先验；高支持的音乐骨架胜过单字界偏差。
          # 'motif_weight':.8, 'short_group_weight':1.35, 'tuplet_complexity':.15,
          'motif_weight':2., 'short_group_weight':1.35, 'tuplet_complexity':.15,
          'tuplet_fit_gain_weight':3., 'ordinary_phrase_fallback':'source_bound_legacy_path',
          'regular_group_reward':1.25, 'local_latency_blend':.7,
          # 通用段落强拍与乐句节奏修复：修改，原筛选保留；低增益连音仍竞争，由整句代价决定。
          # 'minimum_tuplet_fit_gain':.16, 'rapid_maximum_step_quarters':.5,
          'minimum_tuplet_fit_gain':.10, 'rapid_maximum_step_quarters':.5,
          'rapid_maximum_short_span':.55, 'rapid_first_to_fourth_span': [.55,1.08],
          'tuplet_first_to_third_span': [.53,.84], 'tuplet_step_ratio_limit':1.85,
          'small_cost_margin':.08, 'text_used_for_matching':False}


# 通用段落强拍与乐句节奏修复：新增短音乐窗；歌词换行仅作候选窗，短孤立窗与连读窗仍联合选边界。
def music_phrases(words):
    output=[]
    for word in words:
        if not output:
            output.append([word]);continue
        last=output[-1][-1]
        changed=word['char'].get('line_index')!=last['char'].get('line_index')
        gap=word['voiced_start']-last['voiced_end']
        if gap>=.65 or word['orphan']!=last['orphan'] or changed:
            output.append([word])
        else:output[-1].append(word)
    return output


# 通用段落强拍与乐句节奏修复：新增跨字的规整短音组，字内有转音不取消整组候选。
def short_groups(words, beat,allow_eighth=False):
    if abs(beat-1.)>1e-8:
        return []
    output=[]
    for i in range(len(words)-3):
        ws=words[i:i+4]
        # 通用段落强拍与乐句节奏修复：新增组首的音乐边界；不从连续短音串中任意挑中间四个字。
        if i and words[i-1]['observed_span']<.6 and ws[0]['voiced_start']-words[i-1]['voiced_end']<.4:continue
        steps=[b['start']-a['start'] for a,b in zip(ws,ws[1:])]
        span=ws[-1]['start']-ws[0]['start']
        if (all(not w['orphan'] for w in ws) and all(w['observed_span']<=.55 for w in ws[:3])
                and min(steps)>.09 and max(steps)<=.5 and .55<=span<=1.08
                and ws[-1]['observed_span']>=.5):
            output.append({'first':i,'count':4,'step':PPQ//4,'kind':'four_sixteenths',
                           'observed_span':span,'head':round(ws[0]['start']/beat)*round(beat*PPQ)})
    # 通用段落强拍与乐句节奏修复：新增规整八分候选，覆盖连续中等时长字音，真实短长混合仍竞争。
    for i in range(0,len(words)-3,4) if allow_eighth else ():
        ws=words[i:i+4];steps=[b['start']-a['start'] for a,b in zip(ws,ws[1:])]
        if (all(not w['orphan'] for w in ws) and min(steps)>=.30 and max(steps)<=.75
                and 1.40<=sum(steps)<=1.70 and all(.30<=w['observed_span']<=.85 for w in ws[:3])
                and not any(g['first']<i+4 and g['first']+4>i for g in output)):
            output.append({'first':i,'count':4,'step':PPQ//2,'kind':'four_eighths',
                           'observed_span':sum(steps),'head':round(ws[0]['start']*2)*240})
    return output


# 通用段落强拍与乐句节奏修复：新增三等分声学候选；三个十六分及不均匀短音不会自动标三连音。
def tuplet_candidates(words, beat):
    if abs(beat-1.)>1e-8:
        return []
    output=[]
    for i in range(len(words)-2):
        ws=words[i:i+3]
        a,b=[y['start']-x['start'] for x,y in zip(ws,ws[1:])]
        if (any(w['orphan'] for w in ws) or min(a,b)<=0 or not .53<=a+b<=.84
                or max(a,b)/min(a,b)>1.85 or any(w['observed_span']>.58 for w in ws[:2])
                or ws[-1]['observed_span']<.5 or abs(ws[0]['start']-round(ws[0]['start']))>.35):
            continue
        # 通用段落强拍与乐句节奏修复：修改，原间隔独立误差保留；比较去整体演唱延迟的整组误差。
        # triple=sum((x-1/3)**2 for x in (a,b))
        # binary=min(sum((x-y)**2 for x,y in zip((a,b),candidate))
        #            for candidate in ((.25,.25),(.25,.5),(.5,.25),(.5,.5)))
        # gain=(binary-triple)/(.25**2)
        def fit(candidate):
            errors=[x-y for x,y in zip((0.,a,a+b),candidate)]
            center=sum(errors)/3
            return sum((e-center)**2 for e in errors)
        triple=fit((0.,1/3,2/3))
        binary=min(fit(candidate) for candidate in ((0.,.25,.5),(0.,.25,.75),(0.,.5,.75),(0.,.5,1.)))
        gain=(binary-triple)/(.125**2)
        if gain>=POLICY['minimum_tuplet_fit_gain']:
            output.append({'first':i,'count':3,'step':PPQ//3,'kind':'three_eighths_in_two',
                           'fit_gain':gain,'observed_span':a+b,
                           'head':round(ws[0]['start'])*PPQ})
    return output


# 通用段落强拍与乐句节奏修复：新增分组感知的原音段分配；细网格只在确定的三连音窗口启用。
@lru_cache(maxsize=50000)
def allocate(raw, begin, end, tuple_windows=()):
    if end<=begin:return math.inf,()
    raw_total=sum(raw)
    def valid(t):
        active=next(((a,b) for a,b in tuple_windows if a<=t<b),None)
        return (t-active[0])%40==0 if active else t%60==0
    boundaries=tuple(t for t in range(begin,end+1,20) if valid(t))
    if not valid(begin) or not valid(end):return math.inf,()
    states={begin:(0.,())}
    for index,observed in enumerate(raw):
        following={}
        for start,(cost,lengths) in states.items():
            for finish in boundaries:
                if finish<=start or end-finish<(len(raw)-index-1)*40:continue
                length=finish-start
                value=cost+5*(length/(end-begin)-observed/raw_total)**2
                # 通用段落强拍与乐句节奏修复：新增真实转音可用三十二分，不再因一字两音扩大整个歌词音值。
                if length<120:value+=.10
                if finish not in following or value<following[finish][0]:
                    following[finish]=(value,lengths+(length,))
        states=following
    return states.get(end,(math.inf,()))


# 通用段落强拍与乐句节奏修复：新增整组位置先验及逐字软观测；释放延迟不反向挪整块歌词。
def phrase_options(words, maximum, beat, bar_ticks, reference=None,baseline=None,allow_eighth=False):
    observed=words[0]['start']
    entries=[k/4 for k in range(max(0,math.floor((observed-.5)*4)),math.ceil((observed+.5)*4)+1)
             if abs(k/4-observed)<=POLICY['entry_window_quarters']]
    regular=short_groups(words,beat,allow_eighth)
    # 通用段落强拍与乐句节奏修复：新增改唱差异保护；局部短音组有自己的证据，不继承旧句的长短比例。
    variant_units={g['first']+k for g in regular for k in range(g['count'])}
    tuplets=[g for g in tuplet_candidates(words,beat) if not any(r['first']<=g['first'] and g['first']+3<=r['first']+4 for r in regular)]
    # 通用段落强拍与乐句节奏修复：新增二等分与三等分整句路径竞争，不能在已量化谱面上补数字3。
    # 通用段落强拍与乐句节奏修复：修改，保留只比较连音的原式；规整十六分与弱起混合型也独立竞争。
    # variants=[None]+tuplets
    profiles=[]
    for group in regular:
        head=group['head']
        # 通用段落强拍与乐句节奏修复：修改，保留十六分试验；八分组使用自己的有效步长。
        # profiles.append([None,dict(group,targets=[head+k*120 for k in range(4)]),
        #                  dict(group,kind='sixteenth_eighth_sixteenth_pickup',targets=[head-120,head,head+240,head+360])])
        values=[None,dict(group,targets=[head+k*group['step'] for k in range(4)])]
        if group['step']==120:values.append(dict(group,kind='sixteenth_eighth_sixteenth_pickup',targets=[head-120,head,head+240,head+360]))
        profiles.append(values)
    variants=[(tuplet,choices) for tuplet in [None]+tuplets for choices in product(*profiles)] if profiles else [(t,()) for t in [None]+tuplets]
    options=[]
    for tuplet,choices in variants:
        fixed={}
        selected_groups=[g for g in choices if g is not None and not (tuplet and g['first']<tuplet['first']+3 and g['first']+4>tuplet['first'])]
        for group in selected_groups:
            for k in range(group['count']):fixed[group['first']+k]=(group['targets'][k],'regular')
        if tuplet:
            for k in range(3):fixed[tuplet['first']+k]=(tuplet['head']+k*160,'tuplet')
        windows=((tuplet['head'],tuplet['head']+PPQ),) if tuplet else ()
        for entry in entries:
            first=round(entry*PPQ)
            latency=max(-.4,min(.4,observed-entry))
            # 通用段落强拍与乐句节奏修复：新增逐字局部残差；不把首字的迟入量固定施加到后半句。
            local_latencies=[latency if i==0 else .3*latency+.7*(w['start']-round(w['start']*4)/4)
                             for i,w in enumerate(words)]
            def score_onset(index,tick):
                word=words[index]
                # 通用段落强拍与乐句节奏修复：修改，旧固定入口补偿注释保留；普通词仍沿用原拍层级。
                # value=POLICY['onset_weight']*onset_cost(word,tick,latency)
                value=musical_onset_cost(word,tick,local_latencies[index],bar_ticks)
                if index in fixed:
                    target,kind=fixed[index]
                    value+=POLICY['short_group_weight']*((tick-target)/120)**2
                if reference and word['char'].get('index') in reference and index not in variant_units:
                    value+=POLICY['motif_weight']*((tick-first-reference[word['char']['index']])/120)**2
                # 通用段落强拍与乐句节奏修复：新增普通字的旧路径软先验，组内变化不波及无新证据的位置。
                elif baseline and index not in fixed and not tuplet:
                    value+=.75*((tick-baseline[index])/120)**2
                return value
            def candidates(index):
                values=set(start_candidates(words[index],local_latencies[index]))
                if index in fixed:values.add(fixed[index][0])
                # 通用段落强拍与乐句节奏修复：新增音乐参照的候选，不让窄声学窗把正确的延音出口先删除。
                if reference and words[index]['char'].get('index') in reference:
                    target=first+round(reference[words[index]['char']['index']])
                    if abs(target/PPQ-words[index]['start'])<=.85:values.add(target)
                if baseline and abs(baseline[index]/PPQ-words[index]['start'])<=.5:values.add(baseline[index])
                if index in fixed:
                    return (fixed[index][0],)
                return sorted(values)
            if tuplet and tuplet['first']==0 and first!=tuplet['head']:continue
            if 0 in fixed and first!=fixed[0][0]:continue
            states={first:(POLICY['entry_weight']*((entry-observed)/.25)**2+score_onset(0,first),())}
            def slot(index,begin,end):
                word=words[index]
                if not windows and index not in fixed:
                    return binary_slot_cost(word,begin,end,local_latencies[index])
                alloc,lengths=allocate(tuple(round(x,6) for x in word['durations']),begin,end,windows)
                if not lengths:return math.inf,()
                return alloc+POLICY['duration_weight']*math.log((end-begin)/PPQ/word['observed_span'])**2,lengths
            for index,word in enumerate(words[:-1]):
                nxt=words[index+1];following={};gap=has_sounding_gap(word,nxt)
                for begin,(cost,path) in states.items():
                    for nb in candidates(index+1):
                        if nb<=begin or nb>=maximum:continue
                        endings=set(end_candidates(word,local_latencies[index],nb)) if gap else {nb}
                        if gap and nxt['voiced_start']-word['voiced_end']<.4:endings.add(nb)
                        for end in endings:
                            alloc,lengths=slot(index,begin,end)
                            if not lengths:continue
                            value=cost+alloc
                            value+=score_onset(index+1,nb)
                            if end<nb:
                                value+=release_cost(word,end,local_latencies[index],round(beat*PPQ))
                                value+=.18*((nb-end)/PPQ-max(0,nxt['voiced_start']-word['voiced_end']))**2/.25**2
                            if nb not in following or value<following[nb][0]:
                                following[nb]=(value,path+((begin,end,lengths),))
                states=following
            last=words[-1]
            final={}
            for begin,(cost,path) in states.items():
                for end in end_candidates(last,local_latencies[-1],maximum):
                    alloc,lengths=slot(len(words)-1,begin,end)
                    if not lengths:continue
                    value=cost+alloc
                    value+=release_cost(last,end,local_latencies[-1],round(beat*PPQ))
                    # 通用段落强拍与乐句节奏修复：修改，原单倍增益保留；按整组三个观测的改善计分。
                    # if tuplet:value+=POLICY['tuplet_complexity']-tuplet['fit_gain']
                    if tuplet:value+=POLICY['tuplet_complexity']-POLICY['tuplet_fit_gain_weight']*tuplet['fit_gain']
                    value-=POLICY['regular_group_reward']*len(selected_groups)
                    if math.isfinite(value) and (end not in final or value<final[end]['cost']):
                        final[end]={'cost':value,'path':path+((begin,end,lengths),),'entry':entry,
                                    'latency':latency,'local_latencies':local_latencies,'regular_groups':selected_groups,'tuplet':tuplet}
            options.extend(final.values())
    if not options:raise ValueError('音乐结构节奏候选为空，拒绝挤压或丢弃源音段。')
    return options


# 通用段落强拍与乐句节奏修复：新增改唱的时长差异；少一个转音且明显更短时，不继承旧字的全部预算。
def adapted_reference(reference_words,target_words,reference_path,pairs,variant_units=()):
    origin=reference_path[0][0];shift=0;result={};variations=[]
    for (_,a),(_,b) in sorted(pairs,key=lambda p:p[1][1]):
        left,right=reference_words[a],target_words[b]
        result[right['char']['index']]=reference_path[a][0]-origin-shift
        span=reference_path[a][1]-reference_path[a][0]
        if (b not in variant_units and len(right['notes'])<len(left['notes']) and 120<span<=480
                and right['observed_span']/left['observed_span']<.8):
            shorter=min((120,240,360,480),key=lambda n:abs(n/PPQ-right['observed_span']))
            if shorter<span and abs(shorter/PPQ-right['observed_span'])+.10<abs(span/PPQ-right['observed_span']):
                shift+=span-shorter
                variations.append({'character_index':right['char']['index'],'reference_ticks':span,
                                   'variant_ticks':shorter,'evidence':'fewer_pitch_pieces_and_shorter_source_span'})
    return result,variations


# 通用段落强拍与乐句节奏修复：新增整曲接口，复用音乐对齐关系，挂词与源音段身份完全独立。
def solve_words(pieces, characters, mapping, timing, duration):
    output=deepcopy(pieces)
    words=word_models(output,characters,mapping,timing)
    tree=MeterTree.from_meter(timing['meter'],timing.get('beat_groups'))
    beat=tree.groups[0]*tree.unit_ticks/PPQ
    if not words:return output,{'version':VERSION,'policy':deepcopy(POLICY),'phrases':[],'tuplet_groups':[]}
    phrases=music_phrases(words)
    form=infer_form(output,characters,mapping,timing,tree.bar_ticks/PPQ)
    audio_end=math.ceil((mapping.seconds_to_quarters(duration)-timing['score_start_quarter'])*PPQ)
    maxima=[math.ceil((phrases[i+1][0]['start']+.5)*PPQ) if i+1<len(phrases) else audio_end for i in range(len(phrases))]
    # 通用段落强拍与乐句节奏修复：新增保守回退；没有新增独立结构证据的短句保留通用旧策略结果。
    legacy_notes,legacy_audit=solve_legacy_words(pieces,characters,mapping,timing,duration)
    legacy_by_id={n['id']:n for n in legacy_notes}
    baselines=[[legacy_by_id[w['notes'][0]['id']]['start_tick'] for w in p] for p in phrases]
    repeated_lines={m[k] for m in form['matches'] for k in ('reference_line','target_line')}
    eighth_enabled=[p[0]['char'].get('line_index') in repeated_lines for p in phrases]
    # 渴首次吉他编配：修改，旧先枚举全部结构候选再覆盖普通句，会因无新增结构证据的句尾音素滞后而提前失败。
    # options=[phrase_options(p,m,beat,tree.bar_ticks,baseline=b,allow_eighth=e)
    #          for p,m,b,e in zip(phrases,maxima,baselines,eighth_enabled)]
    # 渴首次吉他编配：新增延迟枚举；普通句直接保留已通过整曲非重叠约束的旧联合路径，不丢音或移动源秒。
    options=[]
    for i,phrase in enumerate(phrases):
        # 渴首次吉他编配：修改，有独立短音组／连音证据的乐句才竞争结构候选，原跳过覆盖条件保留。
        # if short_groups(phrase,beat,eighth_enabled[i]) or tuplet_candidates(phrase,beat):continue
        if short_groups(phrase,beat,eighth_enabled[i]) or tuplet_candidates(phrase,beat):
            options.append(phrase_options(phrase,maxima[i],beat,tree.bar_ticks,baseline=baselines[i],allow_eighth=eighth_enabled[i]))
            continue
        path=[]
        for word in phrase:
            ns=[legacy_by_id[n['id']] for n in word['notes']]
            path.append((ns[0]['start_tick'],ns[-1]['end_tick'],tuple(n['end_tick']-n['start_tick'] for n in ns)))
        latencies=[legacy_by_id[w['notes'][0]['id']]['rhythm_decision']['performance_latency_quarters'] for w in phrase]
        # 渴首次吉他编配：修改，旧覆盖不存在的候选列表改为顺序加入，原字段及既有工程输出不变。
        # options[i]=[{'cost':0.,'path':tuple(path),'entry':path[0][0]/PPQ,'latency':latencies[0],
        #              'local_latencies':latencies,'regular_groups':[],'tuplet':None,'baseline_retained':True}]
        options.append([{'cost':0.,'path':tuple(path),'entry':path[0][0]/PPQ,'latency':latencies[0],
                        'local_latencies':latencies,'regular_groups':[],'tuplet':None,'baseline_retained':True}])
    selected=choose_phrases(phrases,options)
    by_index={w['char'].get('index'):(i,k) for i,p in enumerate(phrases) for k,w in enumerate(p) if not w['orphan']}
    references={};reference_links={};reused=[];variations=[]
    for match in form['matches']:
        # 通用段落强拍与乐句节奏修复：新增仅同一首拍相位支持的音乐复用，不把真实改唱硬复制。
        # 通用段落强拍与乐句节奏修复：修改，原窄门限保留；局部拖腔可偏半拍，不等同整段首拍改变。
        # if match['phase_vote']['support']<.7 or min(match['phase_vote']['phase'],tree.bar_ticks/PPQ-match['phase_vote']['phase'])>.35:continue
        if match['phase_vote']['support']<.7 or min(match['phase_vote']['phase'],tree.bar_ticks/PPQ-match['phase_vote']['phase'])>.75:continue
        pairs=[(by_index[a],by_index[b]) for a,b in zip(match['reference_indices'],match['target_indices']) if a in by_index and b in by_index]
        if not pairs:continue
        target_ids={i for _,(i,k) in pairs}
        ref_ids={i for (i,k),_ in pairs}
        if len(target_ids)!=1 or len(ref_ids)!=1:continue
        ri=next(iter(ref_ids));ti=next(iter(target_ids))
        if ri>=ti:continue
        origin=selected[ri]['path'][0][0]
        references[ti]={phrases[ti][b]['char']['index']:selected[ri]['path'][a][0]-origin for (_,a),(_,b) in pairs}
        reference_links[ti]=(ri,pairs)
        reused.append({k:deepcopy(v) for k,v in match.items() if k!='phase_vote'})
    if references:
        # 通用段落强拍与乐句节奏修复：新增沿音乐顺序重解相似乐句，下游参照使用已选择的较早骨架。
        # 通用段落强拍与乐句节奏修复：修改，原同时更新保留；重复的重复必须引用已经修好的参照。
        # for i,ref in references.items():options[i]=phrase_options(phrases[i],maxima[i],beat,tree.bar_ticks,ref)
        # selected=choose_phrases(phrases,options)
        for i,(ri,pairs) in sorted(reference_links.items()):
            origin=selected[ri]['path'][0][0]
            # 通用段落强拍与乐句节奏修复：修改，原刚性相对时值保留；用源改唱差异调整共同骨架。
            # ref={phrases[i][b]['char']['index']:selected[ri]['path'][a][0]-origin for (_,a),(_,b) in pairs}
            covered={g['first']+k for g in short_groups(phrases[i],beat,eighth_enabled[i]) for k in range(g['count'])}
            ref,changes=adapted_reference(phrases[ri],phrases[i],selected[ri]['path'],pairs,covered)
            variations.extend(dict(c,phrase=i,reference_phrase=ri) for c in changes)
            references[i]=ref
            options[i]=phrase_options(phrases[i],maxima[i],beat,tree.bar_ticks,ref,baselines[i],eighth_enabled[i])
            selected=choose_phrases(phrases,options)
    decisions=[];groups=[]
    for i,(phrase,option) in enumerate(zip(phrases,selected)):
        for word,word_latency,(begin,end,lengths) in zip(phrase,option['local_latencies'],option['path']):
            at=begin
            for note,length in zip(word['notes'],lengths):
                note.pop('notation_onset_prior',None)
                note.update(start_tick=at,end_tick=at+length,collapsed_to_grace=False,
                            rhythm_decision={'version':VERSION,'strategy':'musical_structure','phrase':i,
                                             'performance_latency_quarters':word_latency,'source_boundary_unchanged':True})
                at+=length
        if option['tuplet']:
            group=option['tuplet'];a=group['head']
            groups.append({'id':'tuplet_'+str(len(groups)+1),'start_tick':a,'end_tick':a+PPQ,
                           'actual_notes':3,'normal_notes':2,'normal_type':'eighth',
                           'character_indices':[w['char']['index'] for w in phrase[group['first']:group['first']+3]],
                           'acoustic_fit_gain':group['fit_gain']})
        costs=sorted({round(p['cost'],8) for p in options[i] if p['path']!=option['path']})
        margin=min((abs(c-option['cost']) for c in costs),default=None)
        decisions.append({'phrase':i,'first_character_index':phrase[0]['char'].get('index'),
                          'last_character_index':phrase[-1]['char'].get('index'),
                          'entry_tick':option['path'][0][0],'end_tick':option['path'][-1][1],
                          'latency_quarters':option['latency'],'candidate_cost':option['cost'],
                          'candidate_margin':margin,'needs_review':margin is not None and margin<POLICY['small_cost_margin'],
                          'baseline_retained_without_new_structure_evidence':option.get('baseline_retained',False),
                          'regular_groups':option['regular_groups'],'observed_repeat_soft_reference':i in references,
                          'words':[{'character_index':w['char'].get('index'),'begin_tick':p[0],'end_tick':p[1]} for w,p in zip(phrase,option['path'])]})
    by_id={n['id']:n for n in output}
    for note in output:
        if note.get('grace'):
            anchor=by_id[note['anchor_id']]
            note.update(start_tick=anchor['start_tick'],end_tick=anchor['start_tick'],collapsed_to_grace=False)
    main=sorted((n for n in output if not n.get('grace')),key=lambda n:n['start_tick'])
    if any(a['end_tick']>b['start_tick'] for a,b in zip(main,main[1:])):raise ValueError('音乐短句联合节奏出现重叠。')
    return output,{'version':VERSION,'strategy':'musical_structure','policy':deepcopy(POLICY),'phrases':decisions,
                   'observed_repeat_groups':reused,'source_supported_variations':variations,
                   'tuplet_groups':groups,'source_piece_count':len(output),
                   'preserved_pitch_ids_and_source_seconds':True,'human_beat_answers_used_by_solver':False}
