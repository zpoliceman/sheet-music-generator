"""两曲来源补证与首次生成：以原鼓强攻击的角色分布补充拍单位证据。"""
# 两曲来源补证与首次生成：新增独立原声方法，不修改旧选择器、旧分差或已冻结决定。
import math
import numpy as np
import soundfile as sf
from scipy.signal import find_peaks, resample_poly, stft

POLICY = {'version': 1, 'sample_rate': 22050, 'fft_size': 2048, 'hop_samples': 220,
          'bands_hz': [[35,150],[150,500],[500,4000]], 'quantile_normalization': 90,
          'peak_prominence': .3, 'minimum_peak_distance_seconds': .12,
          'window_seconds': 32., 'minimum_events_before_selection': 12,
          'minimum_selected_events': 8, 'strong_event_percentile': 60.,
          'minimum_normalized_event_strength': .5, 'maximum_alignment_seconds': .08,
          'minimum_role_margin': .25, 'minimum_window_fraction': .65,
          'minimum_supported_windows': 3, 'minimum_temporal_thirds': 2,
          'minimum_candidate_margin': .20,
          'scope': 'positive_conventional_backbeat_evidence_not_universal_music_rule',
          'human_answers_or_score_timing_used': False, 'normal_publication_allowed': False}


def extract_drum_bands(source):
    # 两曲来源补证与首次生成：新增原鼓频带瞬态；不识别音高／和弦，不把多个分轨算成独立投票。
    audio,rate=sf.read(source['path'],dtype='float32',always_2d=True)
    target=POLICY['sample_rate'];common=math.gcd(rate,target)
    mono=resample_poly(audio.mean(axis=1),target//common,rate//common)
    n=POLICY['fft_size'];hop=POLICY['hop_samples']
    f,t,z=stft(mono,fs=target,nperseg=n,noverlap=n-hop,boundary='zeros')
    magnitude=np.abs(z)
    flux=np.maximum(0,np.diff(magnitude,axis=1,prepend=magnitude[:,:1]))
    result={'times':t+float(source.get('offset_seconds',0))}
    for name,(a,b) in zip(('kick','lowmid','snare'),POLICY['bands_hz']):
        v=flux[(f>=a)&(f<b)].sum(axis=0)
        result[name]=v/max(1e-9,float(np.percentile(v,POLICY['quantile_normalization'])))
    return result


def strong_noise_attacks(bands):
    # 两曲来源补证与首次生成：新增中低与中高共同的噪声攻击，扣除底鼓宽带瞬态；弱填充保留原数据但不代表主要反拍。
    values=np.maximum(0,np.minimum(bands['lowmid'],bands['snare'])-bands['kick'])
    dt=float(np.median(np.diff(bands['times'])))
    peaks,_=find_peaks(values,prominence=POLICY['peak_prominence'],
                       distance=max(1,round(POLICY['minimum_peak_distance_seconds']/dt)))
    return bands['times'][peaks],values[peaks]


def candidate_roles(bands,beats,duration):
    # 两曲来源补证与首次生成：新增四种交替位置同台比较，半拍上的主噪声攻击不能因和声模板高分被忽略。
    seconds=np.asarray([r['seconds'] for r in beats],float)
    labels=np.asarray([r['beat']-1 for r in beats],int)
    half=np.arange(0,len(seconds)-1,.5)
    grid=np.interp(half,np.arange(len(seconds)),seconds)
    classes=(labels[np.floor(half).astype(int)]*2+np.rint((half%1)*2).astype(int))%4
    at,strength=strong_noise_attacks(bands)
    rows=[]
    for start in np.arange(0,duration,POLICY['window_seconds']):
        use=(at>=start)&(at<min(duration,start+POLICY['window_seconds']))
        t,w=at[use],strength[use]
        if len(t)<POLICY['minimum_events_before_selection']:
            continue
        threshold=max(POLICY['minimum_normalized_event_strength'],float(np.percentile(w,POLICY['strong_event_percentile'])))
        take=w>=threshold;t,w=t[take],w[take]
        if len(t)<POLICY['minimum_selected_events']:
            continue
        index=np.argmin(np.abs(t[:,None]-grid[None,:]),axis=1)
        aligned=np.abs(t-grid[index])<=POLICY['maximum_alignment_seconds']
        masses=np.asarray([w[aligned&(classes[index]==k)].sum()/max(1e-9,w.sum()) for k in range(4)])
        # 两曲来源补证与首次生成：新增标准反拍是2／4拍对应的半拍类2，其余三类和未对齐事件仍完整列出。
        margin=float(masses[2]-max(masses[[0,1,3]]))
        rows.append({'start_seconds':float(start),'end_seconds':min(duration,float(start+POLICY['window_seconds'])),
                     'selected_event_count':len(t),'event_seconds':t.tolist(),'event_strengths':w.tolist(),
                     'position_masses':masses.tolist(),'unaligned_mass':float(1-masses.sum()),'role_margin':margin,
                     'supported':margin>=POLICY['minimum_role_margin']})
    good=[r for r in rows if r['supported']]
    thirds=sorted({min(2,int((r['start_seconds']+r['end_seconds'])/2/duration*3)) for r in good})
    fraction=len(good)/max(1,len(rows))
    qualified=(len(good)>=POLICY['minimum_supported_windows'] and fraction>=POLICY['minimum_window_fraction']
               and len(thirds)>=POLICY['minimum_temporal_thirds'])
    return {'status':'supported' if qualified else 'insufficient_or_nonconventional', 'windows':rows,
            'supported_window_count':len(good),'supported_window_fraction':fraction,'temporal_thirds':thirds,
            'score':float(np.mean([r['role_margin'] for r in rows])) if rows else 0.,
            'not_a_universal_veto_for_half_time_or_syncopation':True}


def compare_drum_roles(candidates,bands,duration):
    # 两曲来源补证与首次生成：新增只用合格原模型候选竞争；无明确单一鼓角色结果时不选择，不把非标准鼓型判为错误。
    rows=[]
    for row in candidates:
        result=candidate_roles(bands,row['clock']['beats'],duration)
        rows.append({'candidate_index':row['candidate_index'],'bpm':row['bpm'],
                     'original_source_qualified':row['qualification']['eligible'],**result})
    ranked=sorted((r for r in rows if r['original_source_qualified']),key=lambda r:-r['score'])
    supported=[r for r in ranked if r['status']=='supported']
    margin=(ranked[0]['score']-ranked[1]['score']) if len(ranked)>=2 else 0.
    chosen=(ranked[0]['candidate_index'] if len(supported)==1 and supported[0] is ranked[0]
            and margin>=POLICY['minimum_candidate_margin'] else None)
    return {'version':1,'policy':POLICY.copy(),'candidates':rows,'margin':margin,
            'status':'selected' if chosen is not None else 'needs_review','selected_candidate_index':chosen,
            'scope':'notation_unit_support_only_first_beat_and_coverage_still_required'}
