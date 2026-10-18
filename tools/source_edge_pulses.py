"""两曲来源补证与首次生成：用原曲末段实际瞬态验证已有拍序的延续。"""
# 两曲来源补证与首次生成：新增只验证不挪动拍点的尾部覆盖；原曲仍演奏时不能冒充余音。
from workspace_location import local_path
from copy import deepcopy
import numpy as np
import soundfile as sf
from scipy.signal import find_peaks
from first_generation_tail import inspect_decay

POLICY={'version':1,'context_beats':12,'envelope_seconds':.03,'hop_seconds':.01,
        'prior_seconds':.08,'minimum_attack_growth_db':3.,'minimum_prominence_db':1.,
        'minimum_attack_spacing_seconds':.10,'audible_floor_dbfs':-60.,
        'maximum_alignment_seconds':.08,'minimum_alignment_fraction':.90,
        'minimum_attack_count':12,'minimum_covered_quarters':8,
        'minimum_observed_span_beats':8,'ringout_after_attack_seconds':.10,
        'supported_parent_groups_required':True,'quarter_or_eighth_grid_only':True,
        'source_pulse_seconds_changed':False,'new_first_beat_claimed':False}


def original_transients(source,start,end):
    # 两曲来源补证与首次生成：新增立体声能量瞬态，不依赖漏检尾部的节拍模型或分轨攻击。
    with sf.SoundFile(local_path(source['path'])) as stream:
        rate=stream.samplerate;stream.seek(max(0,round((start-.1)*rate)));origin=stream.tell()/rate
        audio=stream.read(round((end-origin)*rate),dtype='float64',always_2d=True)
    hop=round(POLICY['hop_seconds']*rate);size=round(POLICY['envelope_seconds']*rate)
    positions=np.arange(0,max(0,len(audio)-size+1),hop)
    energy=np.asarray([np.sqrt(np.mean(audio[i:i+size]**2)) for i in positions])
    at=origin+(positions+size/2)/rate;db=20*np.log10(np.maximum(1e-9,energy))
    prior=max(1,round(POLICY['prior_seconds']/POLICY['hop_seconds']))
    growth=np.asarray([db[i]-20*np.log10(max(1e-9,float(np.mean(energy[max(0,i-prior):i])))) if i else 0. for i in range(len(energy))])
    peaks,_=find_peaks(growth,height=POLICY['minimum_attack_growth_db'],prominence=POLICY['minimum_prominence_db'],
                       distance=max(1,round(POLICY['minimum_attack_spacing_seconds']/POLICY['hop_seconds'])))
    peaks=peaks[(at[peaks]>=start)&(db[peaks]>=POLICY['audible_floor_dbfs'])]
    return [{'seconds':float(at[i]),'rms_dbfs':float(db[i]),'growth_db':float(growth[i])} for i in peaks]


def validate_fixed_grid(beats,events,start,end):
    # 两曲来源补证与首次生成：新增原四分／八分格的实际匹配；不通过分组翻转、移拍或倍速强行贴合。
    seconds=np.asarray([r['seconds'] for r in beats]);period=float(np.median(np.diff(seconds)))
    grid=np.arange(0,len(seconds)-1,.5);points=np.interp(grid,np.arange(len(seconds)),seconds)
    at=np.asarray([e['seconds'] for e in events if start<=e['seconds']<=end])
    if not len(at):
        return {'status':'needs_review','issues':['no_original_attacks'],'events':[]}
    nearest=np.argmin(np.abs(at[:,None]-points[None,:]),axis=1)
    errors=np.abs(at-points[nearest]);aligned=errors<=POLICY['maximum_alignment_seconds']
    fraction=float(np.mean(aligned));covered=len(set(np.floor(grid[nearest[aligned]]).astype(int)))
    span=float((at[-1]-at[0])/period)
    issues=[]
    if len(at)<POLICY['minimum_attack_count'] or covered<POLICY['minimum_covered_quarters'] or span<POLICY['minimum_observed_span_beats']:
        issues.append('insufficient_original_pulse_context')
    if fraction<POLICY['minimum_alignment_fraction']:
        issues.append('original_attacks_disagree_with_fixed_pulses')
    return {'status':'supported' if not issues else 'needs_review','issues':issues,
            'event_count':len(at),'aligned_fraction':fraction,'covered_quarters':covered,'observed_span_beats':span,
            'maximum_error_seconds':float(np.max(errors)),'median_error_seconds':float(np.median(errors)),
            'events':[{**event,'nearest_grid_seconds':float(points[i]),'error_seconds':float(error)}
                      for event,i,error in zip([e for e in events if start<=e['seconds']<=end],nearest,errors)],
            'group_labels_inherited_not_newly_inferred':True,'pulse_seconds_preserved':True}


def inspect_terminal_continuation(binding,candidate,start,dependencies):
    # 两曲来源补证与首次生成：新增只用于已有主体单位／首拍得到正证据的结尾；仍在拨弦的部分以真实起音覆盖，末次起音之后才单独验余音。
    end=float(binding['duration_seconds']);beats=candidate['clock']['beats']
    period=float(np.median(np.diff([b['seconds'] for b in beats])))
    context=max(0.,start-POLICY['context_beats']*period)
    events=original_transients(binding['sources']['mix'],context,end)
    rhythm=validate_fixed_grid(beats,events,context,end)
    issues=[]
    if candidate['grouping']['status']!='supported' or candidate['counterfactual_issues']:
        issues.append('parent_first_beat_not_supported')
    if rhythm['status']!='supported':
        issues+=rhythm['issues']
    tail=None
    local=[e for e in events if e['seconds']>=start]
    if not local:
        issues.append('no_observed_terminal_music')
    else:
        tail_start=local[-1]['seconds']+POLICY['ringout_after_attack_seconds']
        if tail_start>=end:
            issues.append('no_bound_terminal_fade')
        else:
            tail=inspect_decay(binding,tail_start,end,dependencies)
            if tail['status']!='supported':
                issues+=tail['issues']
    return {'status':'supported' if not issues else 'needs_review','issues':issues,'policy':deepcopy(POLICY),
            'start_seconds':float(start),'end_seconds':end,'context_start_seconds':context,
            'rhythm':rhythm,'terminal_decay':tail,'first_beat_from_approved_body_continuity_only':True,
            'source_audio_and_existing_pulse_seconds_retained':True}
