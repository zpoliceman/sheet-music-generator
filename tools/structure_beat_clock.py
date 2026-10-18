"""通用段落强拍与乐句节奏修复：音乐结构约束过门拍数，保留全部原录音秒时间。"""
from copy import deepcopy
from pathlib import Path
import math
import numpy as np

from local_beat_clock import POLICY as LOCAL_POLICY, collect_candidates, derive_local_vocal
from melodic_structure import POLICY as FORM_POLICY, infer_form

VERSION=1
POLICY={'version':VERSION,'form_policy':FORM_POLICY,'bridge_beam_per_count':6,
        'bridge_period_range':[.65,1.6],'bridge_smooth_sigma':.2,
        'bridge_attack_reward':.8,'bridge_missing_penalty':.35,
        'supplemental_tracks':{'six_guitar':.30,'drums':.35},
        'maximum_gap_mean_ratio':1.6,'minimum_gap_mean_ratio':.65,
        'retain_original_seconds':True,'retain_unresolved_special_gap':True}


# 通用段落强拍与乐句节奏修复：新增完整吉他和鼓的攻击辅助，相关分轨同族只取最大贡献。
def structural_candidates(binding,cache):
    from accompaniment_analysis import extract_features
    observations=[]
    for row in collect_candidates(binding,cache):observations.extend(row['observations'])
    for name,weight in POLICY['supplemental_tracks'].items():
        source=binding['sources'].get(name)
        if not source:continue
        feature=extract_features(source,cache,name)
        scale=max(1e-9,float(np.percentile([a['strength'] for a in feature.attacks],85))) if feature.attacks else 1.
        for attack in feature.attacks:
            strength=weight*min(1.5,float(attack['strength'])/scale)
            if strength>.03:observations.append({'seconds':float(attack['seconds'])+float(source.get('offset_seconds',0)),
                                               'strength':strength,'track':name})
    from local_beat_clock import fuse_candidates
    rows=fuse_candidates(observations)
    family=lambda n:'bass' if n=='bass' else 'drums' if n=='drums' else 'harmonic_mix'
    for row in rows:
        groups={}
        for obs in row['observations']:
            f=family(obs['track']);groups[f]=max(groups.get(f,0.),obs['strength'])
        row['strength']=sum(groups.values())
        row['independent_families']=sorted(groups)
    return rows


# 通用段落强拍与乐句节奏修复：新增固定端点/总拍数的二阶路径；每种累计拍数独立保留候选。
def bridge_clock(nodes,start_seconds,end_seconds,count,period):
    if count<1:return None
    mean=(end_seconds-start_seconds)/count
    if not .65*period<=mean<=1.6*period:return None
    candidates=[dict(n) for n in nodes if start_seconds+.35*mean<n['seconds']<end_seconds-.35*mean]
    candidates.extend({'seconds':start_seconds+(end_seconds-start_seconds)*i/(count*4),'strength':0.,'tracks':[]}
                      for i in range(2,count*4-1))
    rows=[{'seconds':start_seconds,'strength':0.,'tracks':[]}]+sorted(candidates,key=lambda n:n['seconds'])
    rows.append({'seconds':end_seconds,'strength':0.,'tracks':[]})
    states=[{} for _ in rows];states[0][(0,round(period/.04))]=(0.,period,0,())
    for index,node in enumerate(rows[1:],1):
        current={}
        for j in range(index-1,-1,-1):
            distance=node['seconds']-rows[j]['seconds']
            if distance>4*period*1.6:break
            for cost,previous,used,path in states[j].values():
                for step in range(1,min(4,count-used)+1):
                    local=distance/step
                    if not .65*period<=local<=1.6*period:continue
                    if index==len(rows)-1 and used+step!=count:continue
                    remain=count-used-step;remaining_seconds=end_seconds-node['seconds']
                    if index<len(rows)-1 and (remain<1 or not .65*period*remain<=remaining_seconds<=1.6*period*remain):continue
                    value=cost+.45*(math.log(local/previous)/.2)**2/max(1.,math.sqrt(step))
                    value+=.18*step*(math.log(local/mean)/.22)**2+.35*(step-1)-.8*node['strength']
                    key=(used+step,round(local/.04))
                    if key not in current or value<current[key][0]:current[key]=(value,local,used+step,path+((index,step),))
        # 通用段落强拍与乐句节奏修复：新增按累计拍数分束，不能由强攻击把另一种过门拍数提前全淘汰。
        grouped={}
        for key,state in current.items():grouped.setdefault(key[0],[]).append((key,state))
        states[index]={key:state for values in grouped.values() for key,state in sorted(values,key=lambda p:p[1][0])[:6]}
    if not states[-1]:return None
    best=min(states[-1].values(),key=lambda s:s[0])
    beats=[{'seconds':start_seconds,'step':0,'kind':'protected_boundary','tracks':[],'strength':0.}]
    previous=start_seconds;used=0
    for index,step in best[3]:
        node=rows[index]
        for k in range(1,step+1):
            observed=k==step and bool(node['tracks'])
            beats.append({'seconds':previous+(node['seconds']-previous)*k/step,'step':used+k,
                          'kind':'observed_attack' if observed else 'interpolated_structure_beat',
                          'tracks':node['tracks'] if observed else [],'strength':node['strength'] if observed else 0.})
        previous=node['seconds'];used+=step
    return {'cost':best[0],'beats':beats,'count':count,'mean_period_seconds':mean}


# 通用段落强拍与乐句节奏修复：新增多乐句共同校验的段落首拍，再在真实空档比较累计拍数。
def infer_structural_clock(vocal,binding,cache):
    from score_export import TempoMap
    from rhythm_notation import MeterTree
    timing=vocal['timing'];mapping=TempoMap(timing['knots'])
    tree=MeterTree.from_meter(timing['meter'],timing.get('beat_groups'))
    beat=tree.groups[0]*tree.unit_ticks/480;period=60/timing['steady_tempo_bpm']*beat
    form=infer_form(vocal['quantized_notes'],vocal['lyrics']['characters'],mapping,timing,tree.bar_ticks/480)
    knots=deepcopy(timing['knots']);transitions=[];applied_delta=0.;nodes=None
    for previous,section in zip(form['sections'],form['sections'][1:]):
        target=section['phase_delta_quarters'];change=target-applied_delta
        # 通用段落强拍与乐句节奏修复：修改，原半拍门限保留；短局部改唱不触发全段拍数改变。
        # if abs(change)<.5:continue
        if abs(change)<FORM_POLICY['minimum_phase_change_quarters']:continue
        # 通用段落强拍与乐句节奏修复：新增不等大拍的保守回退；不能把半大拍相位四舍五入成整数拍路径。
        if abs(change/beat-round(change/beat))>1e-8:
            transitions.append({'section':section['section'],'phase_change_quarters':change,
                                'status':'unresolved_nonintegral_big_beat_phase_keep_original',
                                'alternatives':['special_meter_or_partial_measure','different_phrase_pickup','free_extension'],
                                'source_seconds_unchanged':True})
            continue
        # 通用段落强拍与乐句节奏修复：新增只在没有歌词/发声音段的过门内调整拍数，先后唱段均保留秒锚点。
        left=math.ceil(mapping.seconds_to_quarters(previous['end_seconds'])/beat)*beat
        right=math.floor(mapping.seconds_to_quarters(section['start_seconds'])/beat)*beat
        a,b=mapping.quarters_to_seconds(left),mapping.quarters_to_seconds(right)
        old_count=round((right-left)/beat);new_count=round((right-left-change)/beat)
        if nodes is None:nodes=structural_candidates(binding,cache)
        alternatives=[bridge_clock(nodes,a,b,c,period) for c in sorted({old_count,new_count,max(1,new_count-1),new_count+1})]
        selected=next((p for p in alternatives if p and p['count']==new_count),None)
        entry={'section':section['section'],'source_start_seconds':a,'source_end_seconds':b,
               'original_count':old_count,'proposed_count':new_count,'phase_change_quarters':change,
               'structural_support':section['phase_support'],'witness_count':section['witness_count'],
               'alternatives':[{'count':p['count'],'cost':p['cost'],'mean_period_seconds':p['mean_period_seconds']} for p in alternatives if p],
               'status':'structure_supported_retracked_gap' if selected else 'unresolved_special_gap_keep_original'}
        if selected:
            old_left=left-applied_delta
            bridge=[{'seconds':p['seconds'],'quarter':old_left+p['step']*beat} for p in selected['beats']]
            knots=[k for k in knots if k['seconds']<a]+bridge+[dict(k,quarter=k['quarter']-change) for k in knots if k['seconds']>b]
            entry['beats']=deepcopy(selected['beats']);applied_delta=target
        transitions.append(entry)
    if any(a['seconds']>=b['seconds'] or a['quarter']>=b['quarter'] for a,b in zip(knots,knots[1:])):
        raise ValueError('段落拍轴不单调，拒绝改变音轨或强拼小节。')
    audit={'version':VERSION,'policy':deepcopy(POLICY),'form':{k:deepcopy(v) for k,v in form.items() if k not in ('units','lines')},
           'transitions':transitions,'original_audio_seconds_unchanged':True,'human_answers_used':False,
           'status':'structure_reconciled' if any(t['status']=='structure_supported_retracked_gap' for t in transitions) else 'retained_clock',
           'confidence_kind':'evidence_not_calibrated_accuracy'}
    return knots,audit


# 通用段落强拍与乐句节奏修复：新增严格源绑定派生；先重建历史策略，再重建新版结构与节奏。
def derive_structural_vocal(original,binding,correction):
    from score_export import TempoMap,attach_lyrics,tempo_events
    from phrase_rhythm import quantize_phrase
    from phrase_rhythm_structure import POLICY as RHYTHM_POLICY
    if (correction.get('version')!=VERSION or correction.get('policy')!=POLICY or correction.get('rhythm_policy')!=RHYTHM_POLICY
            or correction.get('source_vocal_project_sha256')!=binding['vocal_project_sha256']):
        raise ValueError('音乐结构派生策略或源指纹不一致。')
    base=derive_local_vocal(original,binding,correction['base_local_correction']) if correction.get('base_local_correction') else deepcopy(original)
    knots,audit=infer_structural_clock(base,binding,Path(correction['feature_cache']))
    if audit!=correction.get('clock_evidence'):raise ValueError('音乐结构拍轴证据无法从源重建。')
    vocal=deepcopy(base);timing=vocal['timing'];mapping=TempoMap(knots)
    timing.update(knots=knots,score_start_seconds=mapping.quarters_to_seconds(timing['score_start_quarter']),
                  structural_rhythm={'version':VERSION,'policy':deepcopy(RHYTHM_POLICY)},musical_structure=deepcopy(audit))
    events,notes,stats=quantize_phrase(base['quantized_notes'],vocal['lyrics']['characters'],mapping,timing,vocal['audio_analysis']['duration_seconds'])
    vocal.update(events=events,quantized_notes=notes,statistics=stats,lyric_mapping=attach_lyrics(events,vocal['lyrics']['characters']),
                 structural_clock_correction=deepcopy(correction))
    vocal['tempo_events']=tempo_events(mapping,timing,stats['total_ticks'])
    vocal['decoder']['phrase_rhythm']=deepcopy(stats['phrase_rhythm'])
    vocal['decoder']['musical_structure']={'version':VERSION,'original_source_fields_preserved':True}
    for i,section in enumerate(vocal['notation'].get('key_segments',[])):
        first=next(n for n in notes if n.get('lyric_index')==section['first_character_index'])
        section['performance_start_tick']=first['start_tick']
        section['start_tick']=math.ceil(first['start_tick']/stats['bar_ticks'])*stats['bar_ticks'] if i else 0
        section['start_measure']=section['start_tick']//stats['bar_ticks']+1
        section['pickup_before_signature']=bool(i and first['start_tick']<section['start_tick'])
    return vocal


# 通用段落强拍与乐句节奏修复：新增显式升级；共享和声与两套乐器都从同一新版人声/拍轴重算。
def correct_structural_project(shared,vocal,arrangements,cache_dir):
    from score_export import read_json
    from phrase_rhythm_structure import POLICY as RHYTHM_POLICY
    from accompaniment_analysis import analyze
    # 渴首次吉他编配：修改，重建阶段继承绑定的乐器范围；原代码注释保留。
    # from accompaniment_arrange import arrange_guitar,arrange_piano
    # 渴首次吉他编配：新增按所选乐器执行，保留各乐器原验证。
    from accompaniment_arrange import arrange_requested
    from accompaniment_texture_policy import add_block_support
    from beat_phase_alignment import seed_existing_music,align_piano_bass
    from local_beat_clock import reusable_guitar_configuration
    from shutil import copy2
    if vocal.get('structural_clock_correction'):return shared,vocal,arrangements
    root=Path(__file__).resolve().parents[1];cache=Path(cache_dir).resolve()
    if not cache.is_relative_to(root/'test_outputs/accompaniment_runs'):raise ValueError('新版缓存必须位于项目分析目录。')
    cache.mkdir(parents=True,exist_ok=True);binding=shared['input_binding']
    for source in binding['sources'].values():
        token='v1_'+source['sha256'][:16]+'_22050_512_24_96'
        old=sorted((root/'test_outputs/accompaniment_runs').glob('*/features/'+token+'.json'))
        if old:
            for suffix in ('.json','.npz'):
                src=old[0].with_suffix(suffix);dst=cache/(token+suffix)
                if src.is_file() and not dst.exists():copy2(src,dst)
    _,audit=infer_structural_clock(vocal,binding,cache)
    correction={'version':VERSION,'policy':deepcopy(POLICY),'rhythm_policy':deepcopy(RHYTHM_POLICY),
                'source_vocal_project_sha256':binding['vocal_project_sha256'],
                'base_local_correction':deepcopy(vocal.get('local_clock_correction')),
                'feature_cache':str(cache),'clock_evidence':audit}
    updated=derive_structural_vocal(read_json(binding['vocal_project']),binding,correction)
    fresh_shared=add_block_support(analyze(binding,updated,cache),updated,cache)
    fresh_shared['arrangement_policy']=deepcopy(shared.get('arrangement_policy',{}))
    fresh_shared['musical_structure']=deepcopy(audit)
    fresh_shared['melodic_motif_matches']=deepcopy(updated['statistics']['phrase_rhythm']['observed_repeat_groups'])
    # 渴首次吉他编配：修改，避免未请求乐器阻塞所选乐器；原代码注释保留。
    # fresh={'guitar':arrange_guitar(fresh_shared,updated,arrangements['guitar']['configuration']['capo_fret']),
    #        'piano':arrange_piano(fresh_shared,updated)}
    # 渴首次吉他编配：新增按所选乐器执行，保留各乐器原验证。
    fresh = arrange_requested(fresh_shared,updated,arrangements['guitar']['configuration']['capo_fret'])
    fresh=seed_existing_music(shared,vocal,arrangements,fresh_shared,updated,fresh,source_time_sections=True)
    fresh['guitar']['configuration'].update(reusable_guitar_configuration(arrangements['guitar']['configuration']))
    fresh['guitar']['configuration']['beat_synchronous_patterns']=True
    # 渴首次吉他编配：修改，仅对已选择钢琴校准钢琴低音；原代码注释保留。
    # align_piano_bass(fresh_shared,updated,fresh['piano'])
    # 渴首次吉他编配：新增按所选乐器执行，保留各乐器原验证。
    if 'piano' in fresh:
        align_piano_bass(fresh_shared,updated,fresh['piano'])
    return fresh_shared,updated,fresh
