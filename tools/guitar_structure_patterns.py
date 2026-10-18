"""结构稳定伴奏与人声合播：原曲节奏证据、歌词乐句和重复段的稳定编配。"""
# 结构稳定伴奏与人声合播：新增吉他派生层，原和声、人声与钢琴字典保持只读。
from collections import defaultdict
from copy import deepcopy
from pathlib import Path
import json
import statistics
import numpy as np
from accompaniment_analysis import SongClock, extract_features, chord_name
from guitar_pattern_grid import pattern_schedule

POLICY = {'name':'source_and_phrase_stable', 'version':1, 'regular_version':2,
          'preferred_steps':[120,240,480], 'repeat_local_variation_margin':.65,
          'main_pattern_change_cost':.65, 'maximum_ornament_ticks':480,
          'source_evidence_is_accuracy':False, 'old_arrangement_not_a_rhythm_vote':True}


# 结构稳定伴奏与人声合播：新增完整缓存复用，防止14个攻击上限阻止十六分评估。
def collect_rhythm_evidence(shared, vocal, cache_dir):
    root = Path(__file__).resolve().parents[1]; clock = SongClock(vocal)
    bar = shared['statistics']['bar_ticks']; result = []; sources = []
    for name in ('accompaniment','six_guitar','six_piano','other','six_other','bass','mix'):
        source = shared['input_binding']['sources'].get(name)
        if not source: continue
        token = 'v1_'+source['sha256'][:16]+'_22050_512_24_96.json'
        cached = sorted((root/'test_outputs/accompaniment_runs').glob('*/features/'+token))
        folder = cached[0].parent if cached else Path(cache_dir)
        feature = extract_features(source, folder, name)
        # 原声覆盖与选音归属通用修复：新增模板选型也复查弱起音，避免共享分析已补回而后级仍读旧攻击造成空小节。
        from source_accompaniment_quality import enabled, refine_attacks
        if enabled(shared) and name not in ('mix', 'bass'):
            refine_attacks(feature)
        offset = float(source.get('offset_seconds',0)); strength_scale = float(np.percentile([a['strength'] for a in feature.attacks],85)) if feature.attacks else 1.
        floor = max(1e-6,float(np.percentile(feature.rms,90))*.035)
        by_measure = defaultdict(list)
        for attack in feature.attacks:
            seconds = float(attack['seconds'])+offset; tick = clock.tick(seconds)
            if not 0<=tick<clock.total_ticks: continue
            by_measure[int(tick//bar)+1].append({'tick':tick,'seconds':seconds,
                'strength':min(2.,float(attack['strength'])/max(1e-9,strength_scale)),
                'pitches':[{'pitch_midi':int(p['pitch_midi']),'weight':float(p['relative_weight'])} for p in attack['pitches']]})
        source_rows = []
        for m in range(1,shared['statistics']['measure_count']+1):
            a,b = clock.seconds((m-1)*bar)-offset, clock.seconds(m*bar)-offset
            rms = float(feature.rms[feature.window(a,b)].mean())
            source_rows.append({'measure':m,'source':name,'rms':rms,'active':rms>=floor,
                                'attacks':by_measure[m]})
        result.extend(source_rows)
        sources.append({'source':name,'sha256':source['sha256'],'cache':str(folder/token),
                        'complete_attack_count':len(feature.attacks),'offset_seconds':offset})
    return {'source_time':'original_song_seconds','sources':sources,'measures':result,
            'no_fourteen_attack_cap':True,'correlated_stems_not_independent_votes':True}


# 结构稳定伴奏与人声合播：新增真实歌词句与主音轮廓，跨半音重复按音程比较。
def lyric_lines(vocal):
    chars = defaultdict(list); notes = defaultdict(list)
    for c in vocal.get('lyrics',{}).get('characters',[]): chars[c['line_index']].append(c)
    for n in vocal.get('quantized_notes',[]):
        if n.get('line_index') is not None and n.get('lyric_index') is not None and n.get('role')=='main' and not n.get('grace'):
            notes[n['line_index']].append(n)
    result = []
    for index, values in sorted(chars.items()):
        by_unit = defaultdict(list)
        for n in notes[index]: by_unit[n['lyric_index']].append(n)
        main = [max(ns,key=lambda n:(bool(n.get('anchor')),n['end_tick']-n['start_tick'])) for _,ns in sorted(by_unit.items())]
        if not main: continue
        pitches=[n['pitch_midi'] for n in main]
        result.append({'line_index':index,'text':''.join(c['text'] for c in values),
                       'start_tick':min(n['start_tick'] for n in main),'end_tick':max(n['end_tick'] for n in main),
                       'intervals':[b-a for a,b in zip(pitches,pitches[1:])],
                       'relative_onsets':[n['start_tick']-main[0]['start_tick'] for n in main],
                       'unit_count':len(main)})
    return result


# 结构稳定伴奏与人声合播：新增歌词活动对应的乐句，不再每到四小节机械换组。
def structure_phrases(shared, vocal, measures):
    lines=lyric_lines(vocal); bar=shared['statistics']['bar_ticks']; phrases=[]
    for measure in measures:
        start,end=(measure-1)*bar,measure*bar
        matching=[line for line in lines if line['start_tick']<end and line['end_tick']>start]
        line=max(matching,key=lambda r:min(end,r['end_tick'])-max(start,r['start_tick'])) if matching else None
        identity=line['line_index'] if line else None
        section=next((i for i,s in enumerate(shared['sections']) if s['kind']=='vocal' and s['start_tick']<end and s['end_tick']>start),None)
        if phrases and phrases[-1]['line_index']==identity and phrases[-1]['section_index']==section and phrases[-1]['measures'][-1]+1==measure:
            phrases[-1]['measures'].append(measure)
        else: phrases.append({'measures':[measure],'line_index':identity,'section_index':section,
                              'text':line['text'] if line else '', 'repeat_group':None})
    groups=[]
    for phrase in phrases:
        line=next((r for r in lines if r['line_index']==phrase['line_index']),None)
        if line is None: continue
        for group in groups:
            base=group['line']; a,b=base['intervals'],line['intervals']
            support=sum(abs(x-y)<=1 for x,y in zip(a,b))/max(1,max(len(a),len(b)))
            if base['text']==line['text'] and abs(base['unit_count']-line['unit_count'])<=1 and support>=.72:
                phrase['repeat_group']=group['id']; phrase['repeat_melody_support']=support; break
        else:
            identity='repeat_'+str(len(groups)+1)
            groups.append({'id':identity,'line':line});phrase['repeat_group']=identity;phrase['repeat_melody_support']=1.
    counts=defaultdict(int)
    # 通用段落强拍与乐句节奏修复：新增人声、和声与右手共享的音乐复用关系，不再只靠同词重复。
    matches=shared.get('melodic_motif_matches',[])
    if matches:
        parent={line['line_index']:line['line_index'] for line in lines}
        def find(i):
            while parent[i]!=i:i=parent[i]
            return i
        for match in matches:
            a,b=match['reference_line'],match['target_line']
            if a in parent and b in parent:
                a,b=find(a),find(b);parent[max(a,b)]=min(a,b)
        for phrase in phrases:
            if phrase['line_index'] in parent:
                phrase['repeat_group']='musical_repeat_'+str(find(phrase['line_index']))
                phrase['repeat_source']='shared_source_melody_alignment'
    for p in phrases:
        if p['repeat_group']: counts[p['repeat_group']]+=1
    for p in phrases:
        if p['repeat_group'] and counts[p['repeat_group']]<2:p['repeat_group']=None
    return phrases, lines


# 结构稳定伴奏与人声合播：新增相关分轨能量门槛与分组权重；混音只作低权重辅助。
def weighted_sources(rows):
    active=[r for r in rows if r['active'] and r['attacks']]
    result=[]; instruments=[r for r in active if r['source'] in ('six_guitar','six_piano','other','six_other')]
    total=sum(r['rms'] for r in instruments)
    for row in active:
        name=row['source']
        if name=='accompaniment':weight=.42
        elif name=='mix':weight=.08
        elif name=='bass':weight=.10
        else:weight=.40*row['rms']/max(1e-9,total)
        result.append((row,weight))
    amount=sum(w for r,w in result)
    return [(r,w/max(1e-9,amount)) for r,w in result]


# 结构稳定伴奏与人声合播：新增漏起音、额外攻击、时间残差、重音和音序分项评分。
# 结构稳定伴奏与人声合播：修改，首次评分函数完整注释保留。
# def score_pattern(shared, guitar, measures, pattern):
#     evidence=guitar['source_rhythm_evidence'];bar=shared['statistics']['bar_ticks']; schedule=pattern_schedule(pattern)
#     totals=defaultdict(float); used=0; source_details=[]
#     for measure in measures:
#         start=(measure-1)*bar; rows=[r for r in evidence['measures'] if r['measure']==measure]
#         weights=weighted_sources(rows)
#         if not weights: continue
#         predicted=np.array([start+r['offset'] for r in schedule],dtype=float)
#         for row,weight in weights:
#             attacks=row['attacks'];observed=np.array([a['tick'] for a in attacks]);strength=np.array([a['strength'] for a in attacks])
#             # 结构稳定伴奏与人声合播：新增检测峰的微小延迟补偿，限半个十六分而非任意对齐模板。
#             residual=observed-np.round(observed/120)*120
#             bias=float(np.clip(np.median(residual),-40,40)); observed=observed-bias
#             distances=np.abs(observed[:,None]-predicted[None,:]); nearest=distances.min(axis=1)
#             mass=max(1e-9,float(strength.sum()))
#             missing=float(np.sum(strength*np.clip((nearest-55)/120,0,1))/mass)
#             time_error=float(np.sum(strength*np.minimum(1,nearest/120))/mass)
#             extra=float(np.mean(distances.min(axis=0)>70))
#             density=abs(len(observed)-len(predicted))/max(len(observed),len(predicted),1)
#             hit=distances<=70; accents=np.max(np.where(hit,strength[:,None],0),axis=0)
#             expected=np.array([1. if r['slot'] in pattern['accent_slots'] else .65 for r in schedule])
#             accent_error=float(np.mean(np.abs(accents/max(.01,float(accents.max()))-expected)))
#             pieces={'missing':missing,'timing':time_error,'extra':extra,'density':density,'accent':accent_error}
#             for key,value in pieces.items():totals[key]+=weight*value
#             source_details.append({'measure':measure,'source':row['source'],'weight':weight,
#                 'observed_attacks':len(observed),'predicted_attacks':len(predicted),'detector_bias_ticks':bias,**pieces})
#         used+=1
#     average={k:v/max(1,used) for k,v in totals.items()}
#     score=2.6*average.get('missing',0)+.9*average.get('timing',0)+1.1*average.get('extra',1)+.7*average.get('density',0)+.45*average.get('accent',0)
#     if not used: score=2. if pattern['step_ticks']<240 else .4
#     return {'pattern_id':pattern['id'],'phase_tick':0,'score':score,'components':average,
#             'source_details':source_details,'observed_measures':used}
# 结构稳定伴奏与人声合播：新增来源自身的脉冲间隔/相位估计，不随候选密度改变。
def source_pulse(attacks):
    ticks=np.array([a['tick'] for a in attacks]);strength=np.array([a['strength'] for a in attacks])
    intervals=np.diff(ticks)
    typical=float(np.median(intervals)) if len(intervals) else 480.
    step=120 if typical<180 else 240 if typical<360 else 480
    vector=np.sum(strength*np.exp(2j*np.pi*ticks/step))/max(1e-9,float(strength.sum()))
    concentration=abs(vector)
    phase=float(np.angle(vector)*step/(2*np.pi)) if concentration>=.6 else 0.
    return step,phase,float(concentration)


# 结构稳定伴奏与人声合播：新增一对一起音匹配与额外次数惩罚，不能用多填音掩盖相位。
def score_pattern(shared, guitar, measures, pattern):
    from scipy.optimize import linear_sum_assignment
    from guitar_right_hand_patterns import shape_for
    from accompaniment_arrange import TUNING
    from guitar_capo import capo_at
    evidence=guitar['source_rhythm_evidence'];bar=shared['statistics']['bar_ticks'];schedule=pattern_schedule(pattern)
    totals=defaultdict(float);used=0;source_details=[]
    shapes={}
    for measure in measures:
        start=(measure-1)*bar;rows=[r for r in evidence['measures'] if r['measure']==measure]
        weights=weighted_sources(rows)
        if not weights:continue
        predicted=np.array([start+r['offset'] for r in schedule],dtype=float)
        for row,weight in weights:
            attacks=row['attacks'];raw=np.array([a['tick'] for a in attacks]);strength=np.array([a['strength'] for a in attacks])
            pulse,phase,concentration=source_pulse(attacks);observed=raw-phase
            distances=np.abs(observed[:,None]-predicted[None,:])
            oi,pi=linear_sum_assignment(distances)
            good=distances[oi,pi]<=65;matched_observed=set(oi[good]);matched_predicted=set(pi[good])
            mass=max(1e-9,float(strength.sum()))
            missing=float(sum(strength[i] for i in range(len(observed)) if i not in matched_observed)/mass)
            time_error=float(sum(strength[i]*min(1.,distances[i,j]/120) for i,j in zip(oi,pi))/mass)
            extra=(len(predicted)-len(matched_predicted))/len(predicted)
            density=abs(len(observed)-len(predicted))
            accents=np.zeros(len(predicted));contour=[]
            for i,j in zip(oi[good],pi[good]):
                accents[j]=strength[i]
                # 结构稳定伴奏与人声合播：音序读取原轨音高，不使用上一版编配的音高轮廓。
                tick=float(raw[i]);chord=next((h for h in shared['harmony'] if h['start_tick']<=tick<h['end_tick']),None)
                if not chord or chord['name']=='N.C.':continue
                capo=capo_at(guitar,tick);key=(chord['id'],capo)
                if key not in shapes:shapes[key]=shape_for(chord,capo)
                shape,mapped=shapes[key];token=schedule[j]['token'].split('+')[-1]
                string=mapped[token];target=TUNING[string]+capo+shape['frets'][str(string)]
                tones=[q for q in attacks[i]['pitches'] if (q['pitch_midi']<60 if token.startswith('B') else 48<=q['pitch_midi']<=84)]
                if tones:
                    peak=max(tones,key=lambda q:q['weight'])['pitch_midi']
                    contour.append(min(abs(target-peak),12)/12)
            expected=np.array([1. if r['slot'] in pattern['accent_slots'] else .65 for r in schedule])
            accent_error=float(np.mean(np.abs(accents/max(.01,float(accents.max()))-expected)))
            pieces={'missing':missing,'timing':time_error,'extra':extra,'density_count_error':density,
                    'accent':accent_error,'original_pitch_contour':float(np.mean(contour)) if contour else 0.}
            for key,value in pieces.items():totals[key]+=weight*value
            source_details.append({'measure':measure,'source':row['source'],'weight':weight,
                'observed_attacks':len(observed),'predicted_attacks':len(predicted),
                'source_pulse_ticks':pulse,'source_phase_ticks':phase,'phase_concentration':concentration,
                'matched_attack_pairs':len(matched_predicted),**pieces})
        used+=1
    average={k:v/max(1,used) for k,v in totals.items()}
    score=2.0*average.get('missing',0)+.65*average.get('timing',0)+1.0*average.get('extra',1)+.24*average.get('density_count_error',0)+.35*average.get('accent',0)+.30*average.get('original_pitch_contour',0)
    if not used:score=2. if pattern['step_ticks']<240 else .4
    return {'pattern_id':pattern['id'],'phase_tick':0,'score':score,'components':average,
            'source_details':source_details,'observed_measures':used}


# 结构稳定伴奏与人声合播：新增重复句复用与整段路径；明显原曲节奏变化可成为变体。
def structured_phrase_plan(shared, guitar, measures):
    from guitar_right_hand_patterns import library
    vocal=guitar['_structure_vocal'];phrases,lines=structure_phrases(shared,vocal,measures)
    # 结构稳定伴奏与人声合播：修改，按库的family字段筛选，原筛选表达式注释保留。
    # patterns=[p for p in library()['patterns'] if (p['default_candidate'] or p.get('structured_candidate')) and p['meter']==shared['timing']['meter'] and p['kind']=='arpeggio']
    patterns=[p for p in library()['patterns'] if (p['default_candidate'] or p.get('structured_candidate'))
              and p['meter']==shared['timing']['meter'] and p['family']=='arpeggio']
    details=[[score_pattern(shared,guitar,p['measures'],pattern) for pattern in patterns] for p in phrases]
    allowed=[set(range(len(patterns))) for p in phrases]; repeats=defaultdict(list)
    for i,p in enumerate(phrases):
        if p['repeat_group']:repeats[p['repeat_group']].append(i)
    for identity,indices in repeats.items():
        best=min(range(len(patterns)),key=lambda j:sum(details[i][j]['score'] for i in indices))
        for i in indices:
            loss=details[i][best]['score']-min(r['score'] for r in details[i])
            if loss<=POLICY['repeat_local_variation_margin']:
                allowed[i]={best};phrases[i]['repeat_action']='reuse_main_pattern'
            else:phrases[i]['repeat_action']='original_rhythm_variant';phrases[i]['repeat_local_loss']=loss
    costs=[];traces=[]
    for i,rows in enumerate(details):
        current={};trace={}
        for j in allowed[i]:
            if not i:current[j]=rows[j]['score'];trace[j]=None;continue
            contiguous=phrases[i-1]['measures'][-1]+1==phrases[i]['measures'][0]
            options=[(old+(.65 if contiguous and previous!=j else 0),previous) for previous,old in costs[-1].items()]
            value,previous=min(options);current[j]=value+rows[j]['score'];trace[j]=previous
        costs.append(current);traces.append(trace)
    if not phrases:return []
    selected=[];winner=min(costs[-1],key=costs[-1].get)
    for trace in reversed(traces):selected.append(winner);winner=trace[winner]
    selected.reverse()
    plans=[{**p,**details[i][j],'all_candidates':details[i]} for i,(p,j) in enumerate(zip(phrases,selected))]
    guitar['structure_stability']={'version':1,'lyric_lines':lines,'phrases':deepcopy(plans),
        'repeat_groups':dict(repeats),'source_only_pattern_selection':True,
        'old_arrangement_density_used':False,'left_hand':'consistent_common_grip_with_required_ornaments'}
    return plans


# 结构稳定伴奏与人声合播：新增短装饰的邻接和声核查，七音功能与转位不强行简化。
def ornament_aliases(shared):
    aliases={};harmony=shared['harmony']
    for i,chord in enumerate(harmony):
        if chord['quality'] not in ('sus2','sus4','add9','madd9') or chord['end_tick']-chord['start_tick']>480 or chord['bass_pc']!=chord['root_pc']:continue
        adjacent=[]
        for j in (i-1,i+1):
            if not 0<=j<len(harmony):continue
            other=harmony[j]
            if other['root_pc']==chord['root_pc'] and other['bass_pc']==chord['bass_pc'] and other['quality'] in ('','m') and other['end_tick']-other['start_tick']>=480:
                adjacent.append(other)
        if not adjacent or len({h['quality'] for h in adjacent})!=1:continue
        base=adjacent[0]
        if chord['quality']=='madd9' and base['quality']!='m':continue
        if chord['quality']=='add9' and base['quality']!='':continue
        aliases[chord['id']]={'base_harmony_id':base['id'],'base_quality':base['quality'],
                              'source_harmony_id':chord['id'],'temporary_finger_limit':2,
                              'source_quality_preserved_in_sound':True}
    return aliases


# 结构稳定伴奏与人声合播：新增独立显示和弦查询，实际和声/音符仍用原性质。
def display_chord(shared,guitar,chord):
    alias=guitar.get('ornament_display',{}).get('aliases',{}).get(chord['id'])
    if not alias:return chord
    base=next(h for h in shared['harmony'] if h['id']==alias['base_harmony_id'])
    return {**chord,'quality':base['quality'],'pitch_classes':base['pitch_classes'],
            'name':chord_name(chord['root_pc'],base['quality'],chord['bass_pc'],chord['key'])}


# 结构稳定伴奏与人声合播：新增已明确允许的短装饰按指核查，覆盖约束仍不可放宽。
def select_ornament_grip(chord,notes,start,end,capo):
    from guitar_grip_library import common_grips
    from guitar_grip_policy import assess_grip
    found=[]
    for entry in common_grips(chord['root_pc'],chord['quality'],chord['bass_pc'],capo):
        check=assess_grip(entry,notes,start,end)
        if check['note_count'] and check['reason']!='complete_grip_and_sustains_not_coverable' and check['max_temporary_finger_changes']<=2:
            check={**check,'valid':True,'reason':'short_supported_ornament_on_base_grip'}
            found.append(((entry['priority'],check['max_temporary_finger_changes'],-check['match_ratio']),entry,check))
    return min(found,key=lambda r:r[0])[1:] if found else None


# 结构稳定伴奏与人声合播：新增旧工程显式升级入口，新工程默认接入；编辑重导幂等。
def apply_structured_patterns(shared,vocal,guitar,cache_dir):
    if guitar.get('structure_stability',{}).get('version')==1:return guitar
    from guitar_regular_rhythm import apply_regular_patterns
    # 结构稳定伴奏与人声合播：新增拍号边界，当前结构规整候选仅支持4/4，其它拍号不强套。
    if shared['timing']['meter'] != [4,4]:
        guitar['configuration'].pop('structure_policy',None)
        guitar['configuration']['rows_measures']=4
        guitar['structure_fallback']={'reason':'structured_regular_grid_requires_4_4','meter':shared['timing']['meter']}
        return apply_regular_patterns(shared,vocal,guitar)
    guitar['source_rhythm_evidence']=collect_rhythm_evidence(shared,vocal,cache_dir)
    guitar['configuration']['structure_policy']=deepcopy(POLICY)
    guitar['configuration']['rows_measures']=4
    guitar['ornament_display']={'version':1,'aliases':ornament_aliases(shared)}
    guitar['_structure_vocal']=vocal
    guitar.pop('regular_rhythm',None);guitar['configuration'].pop('right_hand_policy',None)
    # 结构稳定伴奏与人声合播：新增版本2规整策略，旧显式规整入口仍保留版本1语义。
    policy={'name':'structured_regular_arpeggio_first','version':2,'phase_tick':0,
            'preferred_steps':[120,240,480],'rest_unit_ticks':480,'rhythm_source':'right_hand_slots',
            'sounding_duration':'independent_per_string','protected_feature_and_instrumental_notes':True}
    apply_regular_patterns(shared,vocal,guitar,policy=policy)
    guitar.pop('_structure_vocal',None)
    return guitar
