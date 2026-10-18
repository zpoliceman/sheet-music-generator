"""首拍与首尾局部补证：稳态内容、无拍引子和实测结尾的独立证据。"""
# 首拍与首尾局部补证：新增原声路线；既有模型／门槛／人工认可不在此修改。
from workspace_location import local_path
from copy import deepcopy
import numpy as np
import soundfile as sf
from source_meter_sequence import VECTOR_KEYS,cosine_distance
from source_edge_pulses import POLICY as EDGE_POLICY,original_transients,validate_fixed_grid
from first_generation_tail import inspect_decay
from score_export import read_json

POLICY={'version':1,'window_seconds':32.,'minimum_window_bars':3,
        'minimum_positive_windows':3,'minimum_positive_fraction':.65,'minimum_temporal_thirds':2,
        'minimum_content_margin':.03,'minimum_global_content_margin':.04,'minimum_relative_rms':.08,
        'steady_sample_ranges':[[.10,.20,.30],[.15,.30,.45,.60,.75,.85]],
        'minimum_silent_calibration_seconds':1.,'maximum_mix_calibration_dbfs':-100.,
        'maximum_residual_dbfs':-60.,'maximum_residual_above_calibration_db':6.,
        'minimum_prefix_entry_contrast_db':12.,'minimum_entry_above_residual_db':20.,
        'prefix_context_beats':8,'minimum_prefix_quarter_coverage':.90,
        'maximum_context_beats':32,'context_extension_beats':4,
        'old_model_thresholds_changed':False,'pitch_chord_or_lyric_decoder_called':False}


def content_grouping(candidate,tracks,duration):
    # 首拍与首尾局部补证：新增两种稳态采样均须通过的内容证据；混音和相关吉他分轨合并成一组，不多票表决。
    beats=candidate['clock']['beats'];at=np.asarray([b['seconds'] for b in beats]);labels=np.asarray([b['beat'] for b in beats])
    period=float(np.median(np.diff(at)));ranges=[]
    for offsets in POLICY['steady_sample_ranges']:
        details=[]
        for start in np.arange(0,duration,POLICY['window_seconds']):
            use=(at>=start)&(at<start+POLICY['window_seconds'])
            if any(np.count_nonzero(use&(labels==i))<POLICY['minimum_window_bars'] for i in range(1,5)):
                continue
            roles={}
            for role in ('accompaniment','six_guitar','bass'):
                tr=tracks.get(role)
                if tr is None or not all(k in tr for k in VECTOR_KEYS[:12]):continue
                local=(tr['times']>=start)&(tr['times']<start+POLICY['window_seconds'])
                relative=float(np.median(tr['rms'][local])/max(1e-9,np.percentile(tr['rms'],90))) if np.any(local) else 0.
                if relative<POLICY['minimum_relative_rms']:continue
                vectors=np.stack([np.mean([np.interp(at+o*period,tr['times'],tr[k]) for o in offsets],axis=0) for k in VECTOR_KEYS[:12]],axis=-1)
                delta=np.r_[0.,cosine_distance(vectors[1:],vectors[:-1])]
                values=[float(np.mean(delta[use&(labels==i)])) for i in range(1,5)]
                roles[role]={'relative_rms':relative,'changes_by_beat':values,
                             'first_minus_best_other':values[0]-max(values[1:]),'first_minus_third':values[0]-values[2]}
            harmonic=[r for role,r in roles.items() if role!='bass']
            if not harmonic or 'bass' not in roles:continue
            h=float(np.median([r['first_minus_best_other'] for r in harmonic]));b=roles['bass']['first_minus_best_other']
            counter=(float(np.median([r['first_minus_third'] for r in harmonic]))<-POLICY['minimum_content_margin']
                     and roles['bass']['first_minus_third']<-POLICY['minimum_content_margin'])
            details.append({'start_seconds':float(start),'end_seconds':min(float(start+POLICY['window_seconds']),duration),
                'roles':roles,'harmonic_margin':h,'bass_margin':b,'joint_margin':min(h,b),
                'positive':min(h,b)>=POLICY['minimum_content_margin'],'opposite_source_consensus':counter})
        positive=[r for r in details if r['positive']]
        thirds={min(2,int(r['start_seconds']/max(1e-9,duration)*3)) for r in positive}
        fraction=len(positive)/max(1,len(details));margin=float(np.mean([r['joint_margin'] for r in details])) if details else 0.
        passed=(len(positive)>=POLICY['minimum_positive_windows'] and fraction>=POLICY['minimum_positive_fraction']
                and len(thirds)>=POLICY['minimum_temporal_thirds'] and margin>=POLICY['minimum_global_content_margin']
                and not any(r['opposite_source_consensus'] for r in details))
        ranges.append({'offsets':offsets,'windows':details,'positive_windows':len(positive),'qualified_windows':len(details),
                       'positive_fraction':fraction,'global_margin':margin,'temporal_thirds':sorted(thirds),'supported':passed})
    # 首拍与首尾局部补证：新增只补充模型无法区分首／三拍的缺证，明确反证、两拍过渡缺证和其它问题不可清除。
    eligible=all(r['kind']=='insufficient_independent_grouping_support' for r in candidate['grouping']['issues'])
    good=eligible and not candidate['counterfactual_issues'] and all(r['supported'] for r in ranges)
    return {'status':'supported' if good else 'needs_review','ranges':ranges,'eligible_parent_issues':eligible,
            'source_pulse_seconds_and_groups_changed':False,'unit_choice_not_inferred':True,
            'issues':[] if good else ['independent_content_phase_not_established']}


def envelope(source,start,end,hop=.1):
    # 首拍与首尾局部补证：新增直接读取原音绝对能量；不用相对归一后的分轨噪声冒充演奏。
    with sf.SoundFile(local_path(source['path'])) as stream:
        rate=stream.samplerate;stream.seek(max(0,round(start*rate)))
        origin=stream.tell()/rate;audio=stream.read(max(0,round(end*rate)-stream.tell()),dtype='float64',always_2d=True)
    size=max(1,round(hop*rate));count=len(audio)//size
    rms=np.sqrt(np.mean(audio[:count*size].reshape(count,size,-1)**2,axis=(1,2))) if count else np.array([])
    return origin+(np.arange(count)+.5)*size/rate,20*np.log10(np.maximum(1e-9,rms))


def residual_calibration(binding):
    # 首拍与首尾局部补证：新增必须由原混音整秒静音给出的分离器残差标尺；原曲没有静音时保留未决。
    end=float(binding['duration_seconds']);start=max(0.,end-POLICY['minimum_silent_calibration_seconds'])
    _,db=envelope(binding['sources']['mix'],start,end)
    supported=bool(len(db)>=9 and float(np.max(db))<=POLICY['maximum_mix_calibration_dbfs'])
    levels={}
    if supported:
        for role in ('accompaniment','bass','six_guitar','six_piano'):
            if role not in binding['sources']:continue
            _,local=envelope(binding['sources'][role],start,end)
            levels[role]=float(np.percentile(local,90))
    return {'status':'supported' if supported else 'needs_review','start_seconds':start,'end_seconds':end,
            'maximum_original_mix_dbfs':float(np.max(db)) if len(db) else None,'residual_levels_dbfs':levels}


def inspect_prefix(binding,candidate,dependencies,calibration):
    # 首拍与首尾局部补证：新增无拍背景与第一个稳定演奏入口的夹证，不向背景反向补造节拍。
    issues=[];details={};beats=candidate['clock']['beats'];end=float(binding['duration_seconds'])
    row=next((r for r in dependencies if r['role']=='six_guitar'),None)
    if row is None or calibration['status']!='supported':
        return {'status':'needs_review','issues':['prefix_source_or_noise_calibration_missing']}
    attacks=read_json(row['metadata_path'])['attacks'];noise=calibration['residual_levels_dbfs']['six_guitar']
    first=None
    for attack in attacks:
        second=float(attack['seconds'])
        if second>beats[0]['seconds']+4:break
        _,level=envelope(binding['sources']['six_guitar'],max(0.,second),min(end,second+.2))
        if len(level) and float(np.max(level))>=max(POLICY['maximum_residual_dbfs'],noise+POLICY['minimum_entry_above_residual_db']):
            first=second;break
    if first is None:return {'status':'needs_review','issues':['no_bound_first_instrument_entry']}
    index=min(range(len(beats)),key=lambda i:abs(beats[i]['seconds']-first));entry=beats[index]['seconds']
    if beats[index]['beat']!=1 or abs(entry-first)>EDGE_POLICY['maximum_alignment_seconds']:
        issues.append('first_entry_not_supported_first_beat')
    if index>POLICY['prefix_context_beats']:issues.append('prefix_has_unexamined_model_pulses')
    prefix_end=max(0.,first-.1)
    _,guitar=envelope(binding['sources']['six_guitar'],0,prefix_end)
    _,mix=envelope(binding['sources']['mix'],0,prefix_end)
    stop=beats[min(len(beats)-1,index+POLICY['prefix_context_beats'])]['seconds']
    _,body=envelope(binding['sources']['mix'],entry,stop)
    contrast=float(np.median(body)-np.max(mix)) if len(body) and len(mix) else 0.
    if (not len(guitar) or float(np.max(guitar))>POLICY['maximum_residual_dbfs']
            or float(np.max(guitar))-noise>POLICY['maximum_residual_above_calibration_db']):
        issues.append('prefix_contains_actual_instrument_energy')
    if contrast<POLICY['minimum_prefix_entry_contrast_db']:issues.append('prefix_not_separated_from_stable_entry')
    early=[a['seconds'] for a in attacks if a['seconds']<first-.08]
    if early:issues.append('prefix_contains_cached_attacks')
    context=beats[index:index+POLICY['prefix_context_beats']]
    hits=[min((abs(a['seconds']-b['seconds']) for a in attacks),default=1e9)<=EDGE_POLICY['maximum_alignment_seconds'] for b in context]
    # 首拍与首尾局部补证：修改后续实拍用原混音实际瞬态核对；缓存漏起音不降低覆盖门槛，仍另存缓存覆盖率。
    # coverage=float(np.mean(hits)) if hits else 0.
    # if len(hits)<POLICY['prefix_context_beats'] or coverage<POLICY['minimum_prefix_quarter_coverage']:
    #     issues.append('first_entry_has_no_stable_following_pulse_context')
    original_events=original_transients(binding['sources']['mix'],max(0.,first-.1),stop)
    original_hits=[min((abs(e['seconds']-b['seconds']) for e in original_events),default=1e9)<=EDGE_POLICY['maximum_alignment_seconds'] for b in context]
    coverage=float(np.mean(original_hits)) if original_hits else 0.
    if len(original_hits)<POLICY['prefix_context_beats'] or coverage<POLICY['minimum_prefix_quarter_coverage']:
        issues.append('first_entry_has_no_stable_following_pulse_context')
    original_match=min((abs(e['seconds']-first) for e in original_events),default=1e9)
    if original_match>EDGE_POLICY['maximum_alignment_seconds']:issues.append('first_entry_not_in_original_mix')
    vocal=read_json(binding['vocal_project'])
    if any(n['start_seconds']<entry-.04 for n in vocal['quantized_notes']):issues.append('prefix_contains_existing_vocal_note')
    details.update(first_cached_attack_seconds=first,entry_seconds=entry,trimmed_model_prefix_beats=index,
        prefix_instrument_peak_dbfs=float(np.max(guitar)) if len(guitar) else None,calibrated_residual_dbfs=noise,
        entry_contrast_db=contrast,following_quarter_coverage=coverage,cached_quarter_coverage=float(np.mean(hits)) if hits else 0.,
        first_original_attack_error_seconds=original_match)
    return {'status':'supported' if not issues else 'needs_review','issues':issues,'kind':'unmetered_source_prefix',
            'start_seconds':0.,'end_seconds':entry,'details':details,'source_audio_origin_and_full_length_retained':True,
            'background_not_transcribed_as_rhythmic_guitar':True}


def inspect_tail(binding,candidate,start,dependencies,calibration):
    # 首拍与首尾局部补证：新增按起音数量延长上下文，数量／匹配门槛沿用旧值；不按匹配结果反复挑选窗口。
    end=float(binding['duration_seconds']);beats=candidate['clock']['beats'];period=float(np.median(np.diff([b['seconds'] for b in beats])))
    maximum=max(0.,start-POLICY['maximum_context_beats']*period)
    events=original_transients(binding['sources']['mix'],maximum,end)
    length=EDGE_POLICY['context_beats'];context=max(0.,start-length*period)
    while len([e for e in events if e['seconds']>=context])<EDGE_POLICY['minimum_attack_count'] and length<POLICY['maximum_context_beats']:
        length+=POLICY['context_extension_beats'];context=max(0.,start-length*period)
    rhythm=validate_fixed_grid(beats,events,context,end);issues=list(rhythm['issues'])
    local=[e for e in events if e['seconds']>=start]
    residuals=[];retained=list(dependencies);tail=None
    if not local:issues.append('no_observed_terminal_music')
    else:
        tail_start=local[-1]['seconds']+EDGE_POLICY['ringout_after_attack_seconds']
        # 首拍与首尾局部补证：新增仅排除原混音静音标定过、整尾段低于既有可听下限、没有缓存起音的分离残差。
        if calibration['status']=='supported':
            for row in dependencies:
                role=row['role'];_,db=envelope(binding['sources'][role],tail_start,end)
                level=calibration['residual_levels_dbfs'].get(role)
                attacks=[a['seconds'] for a in read_json(row['metadata_path'])['attacks'] if a['seconds']>=tail_start]
                maximum_db=float(np.max(db)) if len(db) else 0.
                # 首拍与首尾局部补证：修改残差资格须同时验证全曲缓存的常态绝对能量；活跃真乐器仍完整参加旧三轨尾响检验。
                # if (level is not None and not attacks and maximum_db<=POLICY['maximum_residual_dbfs']
                with np.load(local_path(row['path']),allow_pickle=False) as data:
                    source_level=float(20*np.log10(max(1e-9,np.percentile(data['rms'],90))))
                if (level is not None and source_level<=POLICY['maximum_residual_dbfs'] and not attacks and maximum_db<=POLICY['maximum_residual_dbfs']
                        and maximum_db<=level+POLICY['maximum_residual_above_calibration_db']):
                    residuals.append({'role':role,'maximum_tail_dbfs':maximum_db,'calibration_dbfs':level,
                                      'no_cached_attacks':True,'kind':'calibrated_inaudible_separation_residue'})
            retained=[r for r in dependencies if r['role'] not in {r['role'] for r in residuals}]
        tail=inspect_decay(binding,tail_start,end,retained)
        if tail['status']!='supported':issues+=tail['issues']
    return {'status':'supported' if not issues else 'needs_review','issues':issues,'start_seconds':start,'end_seconds':end,
            'context_start_seconds':context,'context_beats':length,'rhythm':rhythm,'terminal_decay':tail,
            'calibrated_residual_tracks':residuals,'original_activity_and_tail_checked_separately':True,
            'new_pulses_or_groups_invented':False}
