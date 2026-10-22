"""原曲器乐旋律骨干重提取：分轨多音证据、连续主线及独立的吉他器乐修订。"""
from __future__ import annotations
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
import hashlib
import json
import sys
import numpy as np
from score_export import read_json,save_json,sha256
from accompaniment_analysis import SongClock

# 原曲器乐旋律骨干重提取：新增与歌名／参考谱无关的版本策略，先识别源音高，再考虑吉他八度。
ROOT=Path(__file__).resolve().parents[1]
POLICY={'version':1,'scope':['intro','interlude','outro'],'model':'spotify_basic_pitch_0.4.0_onnx',
        # 原曲器乐旋律骨干重提取：修改，旧三轨列表保留；其它乐器独立轨也参与声部证据。
        # 'sources':['six_piano','six_guitar','other'],'frame_threshold':.20,'spectral_floor':.035,
        'sources':['six_piano','six_guitar','six_other','other'],'frame_threshold':.20,'spectral_floor':.035,
        # 原曲器乐旋律骨干重提取：修改，试测过强的高音偏好会拖延真实下行；保留探查值。
        # 'upper_voice_bias':.12,'change_cost':.85,'interval_cost':.055,'tail_seconds':.42,
        # 原曲器乐旋律骨干重提取：修改，过弱的旋律音区偏好遗漏短促上行；配合本音起音约束取中间值。
        # 'upper_voice_bias':.065,'change_cost':.85,'interval_cost':.055,'tail_seconds':.42,
        'upper_voice_bias':.085,'change_cost':.85,'interval_cost':.055,'tail_seconds':.42,
        'minimum_grid_ticks':120,'minimum_contour_seconds':.13,'maximum_same_pitch_join_seconds':.12,
        'same_pitch_onset_threshold':.48,'source_voice_before_guitar_octave':True}
# 原曲器乐旋律骨干重提取：新增完整复演参数，阈值变化必须改变源计划策略指纹。
POLICY.update(original_support_threshold=.18,absolute_energy_fraction=.012,octave_harmonic_ratio=.35,
    continuation_register_span_semitones=24,independent_upper_onset_threshold=.72,
    maximum_short_inner_voice_seconds=.65,natural_register_leap_semitones=9,
    original_spectral_floor=.10,harmonic_parent_intervals=[12,19,24,28,31],
    source_contribution_floor=.04,independent_fundamental_ratio=.65,
    section_energy_fraction=.025,onset_lookback_seconds=.24,
    tempo_adaptive_short_notes=True,unsupported_audible_section='preserve_old_melody')

# 原声覆盖与选音归属通用修复：新增二至八次泛音的完整音程关系；旧v1政策和推理缓存保留。
QUALITY_POLICY = {**deepcopy(POLICY), 'version': 2,
                  'harmonic_parent_intervals': [12, 19, 24, 28, 31, 34, 36]}


def selection_policy(vocal):
    return QUALITY_POLICY if vocal.get('source_vocal_quality') else POLICY


# 原曲器乐旋律骨干重提取：新增随拍速的最短主线时值，快歌的规整十六分不能因固定130ms被删。
def contour_minimum(section):
    quarter=section.get('quarter_seconds',.6)
    return min(.13,max(.035,quarter*.22)) if quarter<.5 else .13
MODEL_REL='data/tools/basic_pitch_runtime/basic_pitch/saved_models/icassp_2022/nmp.onnx'


# 原曲器乐旋律骨干重提取：新增规范指纹，只读证据与派生乐谱分别绑定。
def fingerprint(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()


# 原曲器乐旋律骨干重提取：新增公开推理接口的隔离运行时，不修改系统包或既有虚拟环境。
@lru_cache(maxsize=1)
def runtime():
    folder=ROOT/'data/tools/basic_pitch_runtime'
    if not (ROOT/MODEL_REL).is_file():
        raise ValueError('器乐多音运行时未准备；请按data/tools/basic_pitch_runtime_setup.txt安装项目隔离依赖。')
    if str(folder) not in sys.path:sys.path.insert(0,str(folder))
    import onnxruntime as ort
    from basic_pitch.inference import Model
    options=ort.SessionOptions();options.intra_op_num_threads=2;options.inter_op_num_threads=1
    model=Model.__new__(Model);model.model_type=Model.MODEL_TYPES.ONNX
    model.model=ort.InferenceSession(str(ROOT/MODEL_REL),options,providers=['CPUExecutionProvider'])
    return model


# 原曲器乐旋律骨干重提取：新增基频邻域幅度；高音与低八度同起且仅为弱倍频时降权，独立高音保留。
def spectral_bins(audio,sr,times):
    import librosa
    spectrum=abs(librosa.stft(audio,n_fft=8192,hop_length=1024))
    frequencies=librosa.fft_frequencies(sr=sr,n_fft=8192)
    indices=np.clip(np.rint(times*sr/1024).astype(int),0,spectrum.shape[1]-1)
    values=[]
    for p in range(21,109):
        hz=float(librosa.midi_to_hz(p));mask=(frequencies>=hz*2**(-.38/12))&(frequencies<=hz*2**(.38/12))
        if not mask.any():mask[np.argmin(abs(frequencies-hz))]=True
        values.append(spectrum[mask][:,indices].max(axis=0))
    return np.asarray(values,dtype=np.float32).T


# 原曲器乐旋律骨干重提取：新增内容寻址、源秒偏移和模型指纹缓存；旧攻击候选不是新检测输入。
def track_evidence(name,source,cache_dir):
    import librosa
    from basic_pitch.inference import run_inference
    from basic_pitch.note_creation import model_frames_to_time
    # 原曲器乐旋律骨干重提取：修改，声部筛选策略与昂贵推理缓存分离；更新旋律判断不需要重复推理。
    # policy={'algorithm':POLICY,'source_sha256':source['sha256'],'offset_seconds':source.get('offset_seconds',0.),
    policy={'inference_version':1,'frame_aggregation':4,'source_sha256':source['sha256'],'offset_seconds':source.get('offset_seconds',0.),
            'model_sha256':sha256(ROOT/MODEL_REL)}
    folder=Path(cache_dir);folder.mkdir(parents=True,exist_ok=True)
    path=folder/('polyphonic_'+fingerprint(policy)[:24]+'.npz');meta=path.with_suffix('.json')
    # 尾段原声局部补证：新增初提取与后续器乐规划共用内容寻址缓存，不能因一级目录不同再次整轨推理。
    if not path.exists():
        initial=folder/'instrumental_source'/path.name
        if initial.is_file() and initial.with_suffix('.json').is_file():
            path=initial;meta=initial.with_suffix('.json')
    if not path.exists():
        if sha256(source['path'])!=source['sha256']:raise ValueError('器乐来源音轨已改变。')
        print('检测器乐多音源：'+name,flush=True)
        raw=run_inference(Path(source['path']),runtime())
        times=model_frames_to_time(len(raw['note']));audio,sr=librosa.load(source['path'],sr=22050,mono=True)
        # 原曲器乐旋律骨干重提取：新增四帧聚合，不把跨窗时间直接当作固定86帧／秒。
        index=np.arange(0,len(times),4);local_times=times[index]
        notes=np.asarray([raw['note'][i:i+4].max(axis=0) for i in index],dtype=np.float32)
        onsets=np.asarray([raw['onset'][i:i+4].max(axis=0) for i in index],dtype=np.float32)
        spectral=spectral_bins(audio,sr,np.maximum(0,local_times))
        np.savez_compressed(path,times=local_times+float(source.get('offset_seconds',0.)),
                            note=notes,onset=onsets,spectral=spectral)
        save_json(meta,{'source_name':name,'binding':policy,'npz_sha256':sha256(path)})
    info=read_json(meta)
    if info['binding']!=policy or info['npz_sha256']!=sha256(path):raise ValueError('器乐多音证据缓存指纹不符。')
    with np.load(path) as data:arrays={k:data[k].copy() for k in data.files}
    if any(arrays[k].shape!=(len(arrays['times']),88) for k in ('note','onset','spectral')):
        raise ValueError('器乐多音证据形状不正确。')
    return {**arrays,'source':name,'binding':policy,'path':str(path.resolve()),'sha256':info['npz_sha256']}


# 原曲器乐旋律骨干重提取：新增持续音证据融合，关联分轨取最大支持而不计为独立投票。
# 原声覆盖与选音归属通用修复：修改，原入口保留默认政策，新的源质量生成显式选择v2。
# def combine_tracks(tracks,times):
def combine_tracks(tracks,times,policy=None):
    policy = POLICY if policy is None else policy
    evidence=[];onsets=[];sounding=[]
    # 原曲器乐旋律骨干重提取：新增原伴奏交叉门限，分离伪影不能凭分轨上的高置信度独自变成旋律。
    original=next((t for t in tracks if t['source']=='other'),tracks[0])
    original_idx=np.clip(np.searchsorted(original['times'],times),0,len(original['times'])-1)
    # 原曲器乐旋律骨干重提取：修改，常量进入版本策略，便于复演和跨曲审计。
    # original_support=original['note'][original_idx]>=.18
    original_support=original['note'][original_idx]>=POLICY['original_support_threshold']
    # 原曲器乐旋律骨干重提取：新增源偏移范围门限，未来第一帧或文件末帧不能夹取到范围外。
    original_support&=((times>=original['times'][0])&(times<=original['times'][-1]+.04644))[:,None]
    # 原曲器乐旋律骨干重提取：新增绝对能量底线，尾部底噪归一化之后不能被放大成一串新旋律。
    # absolute_floor=float(np.percentile(original['spectral'].max(axis=1),90))*.012
    absolute_floor=float(np.percentile(original['spectral'].max(axis=1),90))*POLICY['absolute_energy_fraction']
    # 原曲器乐旋律骨干重提取：新增段内能量底线，演唱结束的微弱泄漏不强行填成尾奏新主线。
    absolute_floor=max(absolute_floor,float(np.percentile(original['spectral'][original_idx].max(axis=1),95))*POLICY['section_energy_fraction'])
    audible=original['spectral'][original_idx].max(axis=1)>=absolute_floor
    original_support&=audible[:,None]
    # 原曲器乐旋律骨干重提取：新增所有分轨都必须有原伴奏本频幅度；近静音轨模型不能独自赢得声部。
    original_spectrum=original['spectral'][original_idx]
    original_relative=original_spectrum/np.maximum(1e-8,original_spectrum.max(axis=1,keepdims=True))
    original_support&=original_relative>=POLICY['original_spectral_floor']
    for track in tracks:
        idx=np.clip(np.searchsorted(track['times'],times),0,len(track['times'])-1)
        note=track['note'][idx].copy();onset=track['onset'][idx].copy();spectrum=track['spectral'][idx]
        relative=spectrum/np.maximum(1e-8,spectrum.max(axis=1,keepdims=True))
        # 原曲器乐旋律骨干重提取：修改，保留原单轨门限；新增混合伴奏支持。
        # valid=(note>=POLICY['frame_threshold'])&(relative>=POLICY['spectral_floor'])
        valid=(note>=POLICY['frame_threshold'])&(relative>=POLICY['spectral_floor'])&original_support
        valid&=((times>=track['times'][0])&(times<=track['times'][-1]+.04644))[:,None]
        contribution=np.clip(spectrum/np.maximum(1e-8,original_spectrum),0.,1.)
        if track is not original:
            valid&=contribution>=POLICY['source_contribution_floor']
        # 原曲器乐旋律骨干重提取：新增声学幅度参与支持度，未标定的模型概率不等于原曲声部响度。
        note*=np.sqrt(original_relative)*np.sqrt(contribution)
        # 原曲器乐旋律骨干重提取：新增倍频判断依赖实际上下音幅度，替代旧固定82音以上一律降八度。
        ratio=spectrum[:,12:]/np.maximum(1e-8,spectrum[:,:-12])
        harmonic=(note[:,:-12]>=.35)&(ratio<.35)&(onset[:,12:]<=onset[:,:-12]+.08)
        note[:,12:]*=np.where(harmonic,.16,1.)
        # 原曲器乐旋律骨干重提取：新增二／三／四等阶泛音关系，修复弦乐或吉他高次泛音被误当骨干。
        # 原声覆盖与选音归属通用修复：修改，依照来源政策筛七／八次泛音，不按曲名或吉他品位删音。
        # for interval in POLICY['harmonic_parent_intervals']:
        for interval in policy['harmonic_parent_intervals']:
            parent=original_spectrum[:,:-interval];child=original_spectrum[:,interval:]
            strong_parent=(parent>=original_spectrum.max(axis=1,keepdims=True)*.12)
            weak_child=child<POLICY['independent_fundamental_ratio']*parent
            simultaneous=onset[:,interval:]<=onset[:,:-interval]+.15
            # 原曲器乐旋律骨干重提取：新增声学起音核验，低音模型漏检起音时高次泛音仍可识别。
            delayed=np.concatenate((parent[:1].repeat(min(3,len(parent)),axis=0),parent[:-3]),axis=0)[:len(parent)]
            parent_rising=parent>np.maximum(1e-8,delayed)*1.25
            # suppress=strong_parent&weak_child&simultaneous
            suppress=strong_parent&weak_child&(simultaneous|parent_rising)
            note[:,interval:]*=np.where(suppress,.15,1.)
        note*=valid;onset*=valid
        sounding.append(note.copy())
        # 原曲器乐旋律骨干重提取：新增短衰减尾声，只续接原音，不以伴奏的其它起音重新触发。
        delta=float(np.median(np.diff(times))) if len(times)>1 else .04644
        for i in range(1,len(times)):
            carry=note[i-1]*np.exp(-delta/.20)
            note[i]=np.maximum(note[i],np.minimum(carry,.20))
        evidence.append(note);onsets.append(onset)
    values=np.stack(evidence);attacks=np.stack(onsets);active=np.stack(sounding)
    winner=values.argmax(axis=0)
    # 原曲器乐旋律骨干重提取：修改，分离轨的伪攻击不算原曲重弹；起音以未细分的原伴奏为准。
    # return values.max(axis=0),attacks.max(axis=0),active.max(axis=0),winner
    original_onset=original['onset'][original_idx]*original_support
    return values.max(axis=0),original_onset,active.max(axis=0),winner


# 原曲器乐旋律骨干重提取：新增整段动态规划，内声部起音不再直接转成旋律；音域随证据决定。
def continuous_voice(evidence,times,onsets=None,quarter_seconds=.6):
    pitches=np.arange(21,109);dt=float(np.median(np.diff(times))) if len(times)>1 else .04644
    active=np.where(evidence>=.20,pitches[None,:],np.nan)
    tops=np.nanmax(np.where(np.isnan(active),-1,active),axis=1)
    anchor=float(np.median(tops[tops>=21])) if (tops>=21).any() else 60.
    # 原曲器乐旋律骨干重提取：新增随真实音区估计的声部底线；上声部结束后不接管两八度以下的独立低音。
    # evidence=evidence.copy();evidence[:,pitches<anchor-24]=0.
    evidence=evidence.copy();evidence[:,pitches<anchor-POLICY['continuation_register_span_semitones']]=0.
    # 原曲器乐旋律骨干重提取：修改，单看持续概率会跳回已弹过的残响；起音提高本音瞬时支持。
    # score=np.log(.035+evidence)+np.clip((pitches-anchor)*POLICY['upper_voice_bias'],-4.,1.44)
    fresh=onsets*.35 if onsets is not None else 0.
    score=np.log(.035+evidence+fresh)+np.clip((pitches-anchor)*POLICY['upper_voice_bias'],-4.,1.44)
    # 原曲器乐旋律骨干重提取：新增无本音支持时必须允许休止；高音先验不能把静音变成高音。
    score[evidence<.035]=-8.
    # 原曲器乐旋律骨干重提取：修改，快拍时按实际十六分尺度累计持续支持，不能沿用慢歌固定130ms。
    # score=np.column_stack((score,np.full(len(times),-2.35)))*(dt/.14)
    reference=.14 if quarter_seconds>=.5 else max(.04,quarter_seconds*.28)
    score=np.column_stack((score,np.full(len(times),-2.35)))*(dt/reference)
    states=np.append(pitches,0);distance=abs(states[:,None]-states[None,:])
    transition=POLICY['change_cost']+POLICY['interval_cost']*distance
    transition[-1,:]=.50;transition[:,-1]=.50;np.fill_diagonal(transition,0.)
    costs=-score[0];traces=[]
    for i,row in enumerate(score[1:],1):
        # 原曲器乐旋律骨干重提取：新增真实本音起音可降低换音惩罚，避免短而清楚的主旋律被持续伴奏吞没。
        discounts=np.append(np.clip(onsets[i]-.25,0,.65)*.85,0.) if onsets is not None else np.zeros(89)
        changes=np.maximum(0,transition-discounts[None,:])
        if onsets is not None:
            recent=np.max(onsets[max(0,i-1):i+1],axis=0)
            changes[:,:88]+=np.where(recent[None,:]>=.38,0.,3.0)
            np.fill_diagonal(changes,0.)
        # 原曲器乐旋律骨干重提取：修改，本音没有新起音时提高进入成本，继续原音不受影响。
        # choices=costs[:,None]+np.maximum(0,transition-discounts[None,:]);trace=choices.argmin(axis=0)
        choices=costs[:,None]+changes;trace=choices.argmin(axis=0)
        costs=choices[trace,np.arange(89)]-row;traces.append(trace)
    current=int(costs.argmin());path=[current]
    for trace in reversed(traces):current=int(trace[current]);path.append(current)
    return states[np.asarray(path[::-1])]


# 原曲器乐旋律骨干重提取：新增只保留可听见的主线变化和有独立起音的同音重弹，弱短碎片留在证据中。
def voice_events(times,path,evidence,onsets,active,winner,tracks,section):
    boundaries=[0]+[i for i in range(1,len(path)) if path[i]!=path[i-1]]+[len(path)]
    result=[];dt=float(np.median(np.diff(times))) if len(times)>1 else .04644
    # 原曲器乐旋律骨干重提取：新增快歌的真实短主线和同音重弹阈值，慢歌原策略保持。
    minimum=contour_minimum(section);reattack_gap=.18 if section.get('quarter_seconds',.6)>=.5 else minimum
    for a,b in zip(boundaries,boundaries[1:]):
        pitch=int(path[a]);start=float(times[a]);end=min(section['end_seconds'],float(times[b-1]+dt))
        # if pitch==0 or end-start<POLICY['minimum_contour_seconds']:continue
        if pitch==0 or end-start<minimum:continue
        column=pitch-21
        # 原曲器乐旋律骨干重提取：新增丢弃路径预备状态，静音中没有本音实证便不能提前发声。
        audible=np.flatnonzero(active[a:b,column]>=.24)
        if not len(audible):continue
        start=max(start,float(times[a+audible[0]]))
        # 原曲器乐旋律骨干重提取：新增回溯本音真实起音，路径稍晚进入时也不将强拍平移。
        # 原曲器乐旋律骨干重提取：修改，滤除泛音后的路径可能稍晚确认；从邻近原伴奏本音起音找回攻击。
        # candidates=np.flatnonzero((times>=start-.12)&(times<start+.055)&(active[:,column]>=.20))
        candidates=np.flatnonzero((times>=start-POLICY['onset_lookback_seconds'])&(times<start+.055)&(onsets[:,column]>=.38))
        if not len(candidates):candidates=np.flatnonzero((times>=start-.12)&(times<start+.055)&(active[:,column]>=.20))
        # 原曲器乐旋律骨干重提取：修改，首个弱帧提前于真实起音，改取邻近的本音起音峰值。
        # if len(candidates):start=max(section['start_seconds'],float(times[candidates[0]]))
        if len(candidates):
            strongest=candidates[int(np.argmax(onsets[candidates,column]))]
            start=max(section['start_seconds'],float(times[strongest]))
        peaks=[]
        original=next((t for t in tracks if t['source']=='other'),tracks[0])
        original_index=np.clip(np.searchsorted(original['times'],times),0,len(original['times'])-1)
        envelope=original['spectral'][original_index,column]
        for i in range(a+2,b-1):
            # 原曲器乐旋律骨干重提取：修改，单有模型起音不足；同音重弹还需本音声学包络重新上升。
            # if onsets[i,column]>=POLICY['same_pitch_onset_threshold'] and onsets[i,column]>=onsets[i-1,column] and onsets[i,column]>onsets[i+1,column]:
            rising=envelope[i]>1.18*max(1e-8,float(np.max(envelope[max(0,i-4):max(1,i-1)])))
            if rising and onsets[i,column]>=POLICY['same_pitch_onset_threshold'] and onsets[i,column]>=onsets[i-1,column] and onsets[i,column]>onsets[i+1,column]:
                # 原曲器乐旋律骨干重提取：修改，旧固定180ms重弹间隔保留供历史对照。
                # if not peaks or times[i]-times[peaks[-1]]>=.18:peaks.append(i)
                if not peaks or times[i]-times[peaks[-1]]>=reattack_gap:peaks.append(i)
        # if end-start<POLICY['minimum_contour_seconds']:continue
        # cuts=[start]+[float(times[i]) for i in peaks if times[i]>start+.18 and end-times[i]>=.13]+[end]
        if end-start<minimum:continue
        cuts=[start]+[float(times[i]) for i in peaks if times[i]>start+reattack_gap and end-times[i]>=minimum]+[end]
        for left,right in zip(cuts,cuts[1:]):
            sl=(times>=left)&(times<right);where=np.flatnonzero(sl)
            if not len(where) or active[sl,column].max()<.24:continue
            best=where[int(np.argmax(active[sl,column]))];source=tracks[int(winner[best,column])]['source']
            result.append({'source_start_seconds':round(left,6),'source_end_seconds':round(right,6),
                'pitch_midi':pitch,'source':source,'section':section['kind'],'section_id':section['id'],
                'activation':round(float(active[sl,column].max()),5),
                'onset_activation':round(float(onsets[sl,column].max()),5),'role':'instrumental_melody'})
    return result


# 原曲器乐旋律骨干重提取：新增强起音上行锚点恢复和短内声部剔除，补足持续概率对短音的偏差。
def structural_anchors(rows,times,path,active,onsets,tracks,section):
    result=deepcopy(rows);original=next((t for t in tracks if t['source']=='other'),tracks[0])
    # 原曲器乐旋律骨干重提取：新增快拍短上行的相同时值门限。
    minimum=contour_minimum(section)
    index=np.clip(np.searchsorted(original['times'],times),0,len(original['times'])-1)
    spectrum=original['spectral'][index]
    for i in range(1,len(times)-1):
        current=int(path[i])
        if not current:continue
        candidates=[]
        for pitch in range(current+3,min(108,current+12)+1):
            col=pitch-21
            if active[i,col]<.35 or onsets[i,col]<.72 or onsets[i,col]<onsets[i-1,col] or onsets[i,col]<=onsets[i+1,col]:continue
            if spectrum[i,col]<.16*max(1e-8,float(spectrum[i].max())):continue
            if col>=12 and active[i,col-12]>.35 and spectrum[i,col]<.60*spectrum[i,col-12]:continue
            candidates.append((pitch,float(onsets[i,col])))
        if not candidates:continue
        pitch,strength=max(candidates,key=lambda p:(p[0],p[1]));start=float(times[i])
        old=next((r for r in result if r['source_start_seconds']<=start<r['source_end_seconds']),None)
        # 原曲器乐旋律骨干重提取：修改，旧固定短音门限保留；使用当前拍速允许的最短骨干音。
        # if not old or old['pitch_midi']>=pitch or start-old['source_start_seconds']<.13 or old['source_end_seconds']-start<.13:continue
        if not old or old['pitch_midi']>=pitch or start-old['source_start_seconds']<minimum or old['source_end_seconds']-start<minimum:continue
        end=old['source_end_seconds'];old['source_end_seconds']=round(start,6)
        result.append({'source_start_seconds':round(start,6),'source_end_seconds':end,'pitch_midi':pitch,
            'source':original['source'],'section':section['kind'],'section_id':section['id'],
            'activation':round(float(active[i,pitch-21]),5),'onset_activation':round(strength,5),
            'role':'instrumental_melody','structural_reason':'independent_strong_upper_onset'})
        result.sort(key=lambda n:n['source_start_seconds'])
    # 原曲器乐旋律骨干重提取：新增只删短暂下沉又立刻返回上声部的填充，不删真正持续的低音旋律。
    removed=[]
    for i,row in enumerate(result):
        if not 0<i<len(result)-1:continue
        before,after=result[i-1],result[i+1]
        if (row['source_end_seconds']-row['source_start_seconds']<.65 and
            min(before['pitch_midi'],after['pitch_midi'])-row['pitch_midi']>=7 and
            after['source_start_seconds']-before['source_end_seconds']<.80):
            before['source_end_seconds']=after['source_start_seconds'];removed.append(row)
    return [r for r in result if r not in removed]


# 原曲器乐旋律骨干重提取：新增全曲源骨干；声部检测从音频开始，不沿用旧候选的音域或音符个数。
def build_source_plan(shared,vocal,cache_dir):
    # 原声覆盖与选音归属通用修复：新增政策分派；v1旧工程复演仍产生完全相同计划。
    policy = selection_policy(vocal)
    runtime();binding=shared['input_binding']['sources'];tracks=[]
    for name in POLICY['sources']:
        if name in binding:tracks.append(track_evidence(name,binding[name],cache_dir))
    if not tracks:raise ValueError('缺少器乐分析音轨。')
    clock=SongClock(vocal);events=[];sections=[]
    for index,old_section in enumerate(shared['sections']):
        if old_section['kind'] not in POLICY['scope']:continue
        section={**old_section,'id':f'instrumental_section_{index+1:03}'}
        # 原曲器乐旋律骨干重提取：新增认可拍轴的局部拍长，仅用于短音识别，不重定拍或改原唱。
        section['quarter_seconds']=clock.seconds(section['start_tick']+480)-clock.seconds(section['start_tick'])
        times=np.arange(max(0,section['start_seconds']),section['end_seconds'],4*256/22050)
        if not len(times):continue
        # 原声覆盖与选音归属通用修复：修改，来源骨干在吉他降八度之前去除高次倍频误选。
        # evidence,onset,active,winner=combine_tracks(tracks,times)
        evidence,onset,active,winner=combine_tracks(tracks,times,policy)
        # 原曲器乐旋律骨干重提取：修改，旧纯持续概率路径保留；真实起音参与连续主线重解。
        # path=continuous_voice(evidence,times)
        # 原曲器乐旋律骨干重提取：修改，旧慢歌统一尺度保留；快歌使用认可拍长。
        # path=continuous_voice(evidence,times,onset)
        path=continuous_voice(evidence,times,onset,section['quarter_seconds'])
        found=voice_events(times,path,evidence,onset,active,winner,tracks,section)
        found=structural_anchors(found,times,path,active,onset,tracks,section)
        # 原曲器乐旋律骨干重提取：新增跨音符一致的十六分格量化，边界裁剪只作用器乐。
        aligned=[]
        for row in found:
            # 原曲器乐旋律骨干重提取：修改，混合段界可能在15tick处；采用段内首个十六分格，不输出不可记谱的碎时值。
            # tick=max(section['start_tick'],clock.quantize(row['source_start_seconds'],120))
            tick=max((section['start_tick']+119)//120*120,clock.quantize(row['source_start_seconds'],120))
            if tick>=section['end_tick']:continue
            if aligned and tick<=aligned[-1]['start_tick']:
                if row['activation']<=aligned[-1]['activation']:continue
                aligned.pop()
            aligned.append({**row,'start_tick':tick})
        # 原曲器乐旋律骨干重提取：新增真实段界内的十六分格，末音不被裁成小于十六分的碎值。
        aligned=[r for r in aligned if r['start_tick']+120<=section['end_tick']//120*120]
        for i,row in enumerate(aligned):
            end=clock.quantize(row['source_end_seconds'],120)
            # 原曲器乐旋律骨干重提取：修改，保留旧任意tick边界裁剪，改为段界内的规整格。
            # limit=aligned[i+1]['start_tick'] if i+1<len(aligned) else section['end_tick']
            limit=aligned[i+1]['start_tick'] if i+1<len(aligned) else section['end_tick']//120*120
            row['end_tick']=min(limit,max(row['start_tick']+120,end));row['duration_ticks']=row['end_tick']-row['start_tick']
            row['id']=f'source_backbone_{len(events)+1:05}';events.append(row)
        # 原曲器乐旋律骨干重提取：新增证据不足的可见退化状态，有声音却解不出主线时保留旧旋律。
        original=next((t for t in tracks if t['source']=='other'),tracks[0])
        idx=np.clip(np.searchsorted(original['times'],times),0,len(original['times'])-1)
        audible_peak=float(original['spectral'][idx].max())
        quiet_floor=float(np.percentile(original['spectral'].max(axis=1),95))*.005
        decision='reextract_supported_backbone' if aligned else ('remove_old_melody_in_verified_quiet' if audible_peak<=quiet_floor else 'preserve_old_melody_due_to_insufficient_evidence')
        # sections.append({**section,'detected_notes':len(aligned)})
        sections.append({**section,'detected_notes':len(aligned),'decision':decision})
    # 原声覆盖与选音归属通用修复：修改，记录真实使用的选音政策，便于原缓存确定重放。
    # payload={'version':1,'policy':deepcopy(POLICY),'sections':sections,'notes':events,
    payload={'version':1,'policy':deepcopy(policy),'sections':sections,'notes':events,
        'model_path':str((ROOT/MODEL_REL).resolve()),'model_sha256':sha256(ROOT/MODEL_REL),
        'source_clock_sha256':fingerprint(vocal),'sources':[{'name':t['source'],'binding':t['binding'],
        'evidence_path':t['path'],'evidence_sha256':t['sha256']} for t in tracks]}
    # 尾段原声局部补证：新增来源核验后的局部假起音过滤，既有音符的完整尾音不裁短；旧计划无此层完全保持。
    if vocal.get('first_source_meter_correction'):
        from first_generation_tail import verified_tail_observation,constrain_terminal_events
        observation=verified_tail_observation(vocal,shared['input_binding'])
        if observation is not None:
            payload['notes'],payload['terminal_decay_constraint']=constrain_terminal_events(payload['notes'],observation)
            for section in payload['sections']:
                section['detected_notes']=sum(note['section_id']==section['id'] for note in payload['notes'])
    path=Path(cache_dir)/('source_backbone_'+fingerprint(payload)[:24]+'.json')
    if not path.exists():save_json(path,payload)
    return payload,path


# 原曲器乐旋律骨干重提取：新增窄范围修订，仅替换真实器乐范围的旧主线；低音、和声及唱段账本不删。
# 保音持续按弦与整句八度衔接：修改新来源与历史初始化分开；新版交付原音高请求，最终整句／全声部只统一规划一次。
# def revised_guitar(shared,vocal,original,plan):
def revised_guitar(shared,vocal,original,plan,register_input_version=1):
    if register_input_version not in (1, 2):
        raise ValueError('未知器乐原音高请求版本。')
    from accompaniment_arrange import TUNING,harmony_at
    from guitar_capo import capo_at
    from guitar_instrumental_register import editable_notes,DERIVED_FIELDS,melodic_phrases,register_shared_view
    # 原曲器乐旋律骨干重提取：新增统一实际和声视图，生成前与导出后不能给同一主线挂不同和弦ID。
    shared=register_shared_view(shared,vocal)
    result=deepcopy(original);editable=editable_notes(shared,original)
    # 保音持续按弦与整句八度衔接：新增原音高请求身份；历史种子不增加字段，已认可旧派生按旧账本验证。
    if register_input_version == 2:
        result['configuration']['source_register_input_version'] = 2
    # 原曲器乐旋律骨干重提取：修改，旧全部替换规则保留；缺证据段不强删原旋律。
    # superseded={n['id'] for n in original['notes'] if n['id'] in editable and n['role']=='instrumental_melody'}
    replace_sections=[s for s in plan['sections'] if s.get('decision')!='preserve_old_melody_due_to_insufficient_evidence']
    superseded={n['id'] for n in original['notes'] if n['id'] in editable and n['role']=='instrumental_melody' and
                any(s['start_tick']<=n['start_tick']<s['end_tick'] for s in replace_sections)}
    notes=[deepcopy(n) for n in original['notes'] if n['id'] not in superseded]
    for note in notes:
        if note['id'] in editable:
            for field in DERIVED_FIELDS:note.pop(field,None)
    # 原曲器乐旋律骨干重提取：修改，整段器乐可跨多个八度，按真实动机初始化才能兼顾高音与低音。
    # for section in plan['sections']:
    #     rows=[r for r in plan['notes'] if r['section_id']==section['id']]
    virtual=[{'id':'guitar_'+r['id'],'pitch_midi':r['pitch_midi'],'start_tick':r['start_tick'],'end_tick':r['end_tick'],
        'source_backbone_pitch_midi':r['pitch_midi'],'source_backbone_section_id':r['section_id'],
        'role':'instrumental_melody','chord_id':harmony_at(shared,r['start_tick'])['id']} for r in plan['notes']]
    phrases=melodic_phrases(shared,virtual,{n['id'] for n in virtual})
    for phrase in phrases:
        rows=[r for r in plan['notes'] if 'guitar_'+r['id'] in phrase['note_ids']]
        # 原曲器乐旋律骨干重提取：修改，旧整段筛选改由上面的自然动机筛选。
        # rows=[r for r in plan['notes'] if r['section_id']==section['id']]
        if not rows:continue
        # 原曲器乐旋律骨干重提取：新增整段初始八度统一，不在此阶段逐音折回导致旋律折断。
        shift=0
        # 保音持续按弦与整句八度衔接：修改20品初始化仅供真实历史重放；新来源不先降一遍再让后续重复降位。
        # while max(r['pitch_midi'] for r in rows)+shift>min(TUNING[1]+capo_at(original,r['start_tick'])+20 for r in rows):shift-=12
        if register_input_version == 1:
            while max(r['pitch_midi'] for r in rows)+shift>min(TUNING[1]+capo_at(original,r['start_tick'])+20 for r in rows):shift-=12
        for row in rows:
            pitch=row['pitch_midi']+shift;capo=capo_at(original,row['start_tick'])
            # 保音持续按弦与整句八度衔接：修改新种子只表示未配音来源，不能导出；历史20品候选代码仅留原分支。
            # positions=[(s,pitch-base-capo) for s,base in TUNING.items() if 0<=pitch-base-capo<=20]
            # if not positions:raise ValueError('源旋律整段八度无法进入吉他音域，需保留证据而不乱改音名。')
            # string,fret=min(positions,key=lambda sf:(sf[1],sf[0]));chord=harmony_at(shared,row['start_tick'])
            if register_input_version == 1:
                positions=[(s,pitch-base-capo) for s,base in TUNING.items() if 0<=pitch-base-capo<=20]
                if not positions:raise ValueError('源旋律整段八度无法进入吉他音域，需保留证据而不乱改音名。')
                string,fret=min(positions,key=lambda sf:(sf[1],sf[0]))
            else:
                string, fret = 1, pitch - TUNING[1] - capo
            chord=harmony_at(shared,row['start_tick'])
            notes.append({'id':'guitar_'+row['id'],'pitch_midi':pitch,'string':string,'fret':fret,
                'finger':int(fret>0),'hand_position':max(1,fret),'start_tick':row['start_tick'],'end_tick':row['end_tick'],
                'velocity':92,'role':'instrumental_melody','source_melody_id':row['id'],'source':row['source'],
                'source_attack_seconds':row['source_start_seconds'],'source_release_seconds':row['source_end_seconds'],
                'source_backbone_pitch_midi':row['pitch_midi'],'source_backbone_initial_octave_shift':shift,
                'source_backbone_section_id':row['section_id'],'section':row['section'],'chord_id':chord['id'],
                'observed_kind':'melody','arrangement_reason':'source_polyphonic_continuous_backbone',
                'onset_origin':'source_pitch_specific_onset','right_hand_duration_ticks':row['duration_ticks'],
                'right_hand_duration_source':'instrumental_source_backbone_grid'})
    result['notes']=sorted(notes,key=lambda n:(n['start_tick'],n['id']))
    events=[deepcopy(e) for e in original['attack_events'] if not any(s['start_tick']<=e['start_tick']<s['end_tick'] for s in plan['sections'])]
    instrumental=[n for n in result['notes'] if any(s['start_tick']<=n['start_tick']<s['end_tick'] for s in plan['sections'])]
    for tick in sorted({n['start_tick'] for n in instrumental}):
        group=[n for n in instrumental if n['start_tick']==tick];duration=min(n['end_tick']-tick for n in group)
        # 原曲器乐旋律骨干重提取：新增规整拍内拨弦显示；真实持续音仍按end_tick发声，不凭附点添攻击。
        horizon=min(duration,480-tick%480)
        duration=max((d for d in (120,240,480) if d<=horizon),default=120)
        events.append({'start_tick':tick,'kind':'melody','chord_id':group[0]['chord_id'],'source':group[0]['source'],
            'onset_origin':'source_backbone_with_preserved_bass_harmony','note_ids':[n['id'] for n in group],
            'stroke':None,'right_hand_duration_ticks':duration,'right_hand_duration_source':'instrumental_source_backbone_grid'})
    result['attack_events']=sorted(events,key=lambda e:e['start_tick'])
    result.pop('instrumental_register',None);result['configuration'].pop('instrumental_register_policy',None)
    # 原曲器乐旋律骨干重提取：新增旧指型缓存只交给后续联合规划继承，正常段图、按指保持原编号。
    for field in ('tab_display','rhythm_display','time_alignment_display'):result.pop(field,None)
    result['adjustments'].append({'type':'source_instrumental_melody_revision','superseded_melody_ids':sorted(superseded),
                                  'new_melody_ids':['guitar_'+r['id'] for r in plan['notes']]})
    return result,sorted(superseded)


# 原曲器乐旋律骨干重提取：新增真实旧工程和源证据绑定，允许明确更正旋律，不篡改过去的保护账本。
# 保音持续按弦与整句八度衔接：修改新请求默认原音高版本；历史重放由账本显式选择原初始化。
# def reextract_guitar(shared,vocal,guitar,upstream,cache_dir):
def reextract_guitar(shared,vocal,guitar,upstream,cache_dir,register_input_version=2):
    plan,path=build_source_plan(shared,vocal,cache_dir)
    # 保音持续按弦与整句八度衔接：修改配音前不再按20品折叠，原调用保留。
    # result,superseded=revised_guitar(shared,vocal,guitar,plan)
    result,superseded=revised_guitar(shared,vocal,guitar,plan,register_input_version=register_input_version)
    # 原声覆盖与选音归属通用修复：修改，绑定新计划政策，历史账本不升级不改写。
    # result['instrumental_source_backbone']={'version':1,'policy':deepcopy(POLICY),
    result['instrumental_source_backbone']={'version':1,'policy':deepcopy(plan['policy']),
        'upstream_project':str(Path(upstream).resolve()),'upstream_sha256':sha256(upstream),
        'source_plan_path':str(path.resolve()),'source_plan_sha256':sha256(path),
        'source_notes_sha256':fingerprint(guitar['notes']),'seed_notes':deepcopy(result['notes']),
        'seed_notes_sha256':fingerprint(result['notes']),'superseded_note_ids':superseded,
        'model_sha256':plan['model_sha256'],'new_note_count':len(plan['notes']),
        'shared_sha256':fingerprint(shared),'vocal_sha256':fingerprint(vocal)}
    # 保音持续按弦与整句八度衔接：新增来源请求版本及未配音种子说明，最终导出仍须实际十二品／持续按弦通过。
    if register_input_version != 1:
        result['instrumental_source_backbone']['register_input_version'] = register_input_version
        result['instrumental_source_backbone']['seed_is_unvoiced_source_request'] = True
    return result


# 原曲器乐旋律骨干重提取：新增只读上游缓存；保护音投影不逐音重复读取几十MB的历史工程。
@lru_cache(maxsize=8)
def upstream_project(path,digest,mtime,size):
    value=read_json(path)
    if sha256(path)!=digest:raise ValueError('源旋律修订的认可上游工程改变。')
    return value


# 原曲器乐旋律骨干重提取：新增绑定来源查询，既有音区派生链在新骨干修订中继续有效。
def source_parent(guitar):
    info=guitar.get('instrumental_source_backbone')
    if not info:return None
    path=Path(info['upstream_project']);stat=path.stat()
    return upstream_project(str(path),info['upstream_sha256'],stat.st_mtime_ns,stat.st_size)


# 原曲器乐旋律骨干重提取：新增完整来源复演；仅元数据写“已修复”或删掉旧保护音不会通过。
def validate_source_backbone(shared,vocal,guitar,replay=False):
    # 原声覆盖与选音归属通用修复：新增先核验认可段落的确定合并，再按原来源完整验证基础骨干。
    if guitar.get('approved_section_preservation'):
        from approved_music_sections import validate_chain
        return validate_chain(shared,vocal,guitar,replay,validate_source_backbone)
    # 器乐背景休止与旋律突出：新增原曲骨干证据仍在真实上游复演；休止、重音及音量不冒充源旋律变化。
    if guitar.get('instrumental_expression'):
        from guitar_instrumental_expression import validate_expression_chain
        return validate_expression_chain(shared,vocal,guitar,replay,validate_source_backbone)
    # 器乐低弦分解填充：新增原骨干在真实绑定输入验证；最终新增ID和响尾由独立织体层完整重放。
    if guitar.get('instrumental_flow'):
        from guitar_instrumental_flow import flow_parent,validate_flow
        try:
            parent=flow_parent(guitar)['arrangements']['guitar']
            upstream=validate_source_backbone(shared,vocal,parent,replay=replay)
            current=validate_flow(shared,vocal,guitar,replay=replay)
            errors=(upstream or {}).get('errors',[])+current['errors']
            return {**(upstream or {}),'valid':not errors,'errors':errors,'flow':current}
        except (OSError,KeyError,ValueError) as exc:
            return {'valid':False,'errors':['instrumental_flow_backbone_binding_invalid:'+str(exc)]}
    info=guitar.get('instrumental_source_backbone')
    if not info:return None
    from guitar_instrumental_register import editable_notes,ALLOWED_FIELDS,DERIVED_FIELDS,register_shared_view
    errors=[]
    try:
        # 原声覆盖与选音归属通用修复：修改，核对由源人声政策决定的版本，不接受任意降低门限的账本。
        # if info.get('version')!=1 or info.get('policy')!=POLICY:errors.append('unknown_source_backbone_policy')
        policy = selection_policy(vocal)
        if info.get('version')!=1 or info.get('policy')!=policy:errors.append('unknown_source_backbone_policy')
        parent=source_parent(guitar);original=parent['arrangements']['guitar'];plan_path=Path(info['source_plan_path'])
        if not plan_path.is_file() or sha256(plan_path)!=info.get('source_plan_sha256'):errors.append('source_backbone_plan_changed')
        plan=read_json(plan_path)
        # 原曲器乐旋律骨干重提取：新增不能为空的真实源轨集合，重复或缺少原伴奏不能充当旋律证据。
        expected_sources=[n for n in POLICY['sources'] if n in shared['input_binding']['sources']]
        if [s['name'] for s in plan['sources']]!=expected_sources or not expected_sources:
            errors.append('source_backbone_audio_evidence_missing_or_duplicate')
        # 原声覆盖与选音归属通用修复：修改，新旧声部选择政策分别严格核对。
        # if plan['policy']!=POLICY or fingerprint(vocal)!=info['vocal_sha256'] or fingerprint(vocal)!=fingerprint(parent['accepted_vocal_project']):errors.append('source_backbone_vocal_or_policy_changed')
        if plan['policy']!=policy or fingerprint(vocal)!=info['vocal_sha256'] or fingerprint(vocal)!=fingerprint(parent['accepted_vocal_project']):errors.append('source_backbone_vocal_or_policy_changed')
        if fingerprint(register_shared_view(shared,vocal))!=fingerprint(register_shared_view(parent['shared_analysis'],vocal)):
            errors.append('source_backbone_harmony_or_clock_changed')
        # 原曲器乐旋律骨干重提取：修改，除计划内自洽还绑定真正的固定模型；任意文件不能冒充模型。
        # if sha256(plan['model_path'])!=plan['model_sha256'] or plan['model_sha256']!=info['model_sha256']:errors.append('source_backbone_model_changed')
        if (Path(plan['model_path']).resolve()!=(ROOT/MODEL_REL).resolve() or sha256(plan['model_path'])!=plan['model_sha256']
            or plan['model_sha256']!=info['model_sha256']):errors.append('source_backbone_model_changed')
        if fingerprint(original['notes'])!=info['source_notes_sha256']:errors.append('source_backbone_original_notes_changed')
        for source in plan['sources']:
            binding=shared['input_binding']['sources'][source['name']]
            if source['binding']['source_sha256']!=binding['sha256'] or sha256(binding['path'])!=binding['sha256']:
                errors.append('source_backbone_audio_changed:'+source['name'])
            if sha256(source['evidence_path'])!=source['evidence_sha256']:errors.append('source_backbone_evidence_changed:'+source['name'])
        # 保音持续按弦与整句八度衔接：修改新旧来源按真实版本重放；缺字段的已认可工程保持旧初始化。
        # seed,superseded=revised_guitar(shared,vocal,original,plan)
        seed,superseded=revised_guitar(shared,vocal,original,plan,register_input_version=info.get('register_input_version',1))
        if info['superseded_note_ids']!=superseded or fingerprint(seed['notes'])!=info['seed_notes_sha256'] or seed['notes']!=info['seed_notes']:
            errors.append('source_backbone_seed_or_scope_changed')
        expected={n['id']:n for n in seed['notes']};actual={n['id']:n for n in guitar['notes']};editable=editable_notes(shared,seed)
        if set(expected)!=set(actual):errors.append('source_backbone_actual_note_set_changed')
        for identity,note in expected.items():
            current=actual.get(identity)
            if current is None:continue
            exempt=set(ALLOWED_FIELDS+DERIVED_FIELDS) if identity in editable else set()
            if any(current.get(k)!=note.get(k) for k in note if k not in exempt):errors.append('source_backbone_protected_music_changed:'+identity)
            # 原曲器乐旋律骨干重提取：新增实际音名保护，允许的八度／按指派生不能改写骨干的音级。
            if current['pitch_midi']%12!=note['pitch_midi']%12:errors.append('source_backbone_pitch_class_changed:'+identity)
        if replay and not errors:
            rebuilt,_=build_source_plan(shared,vocal,plan_path.parent)
            if fingerprint(rebuilt)!=fingerprint(plan):errors.append('source_backbone_evidence_replay_differs')
    except (OSError,KeyError,ValueError) as exc:errors.append('source_backbone_binding_invalid:'+str(exc))
    return {'valid':not errors,'errors':errors,'replayed':bool(replay),'new_melody_notes':info.get('new_note_count'),
            'superseded_melody_notes':len(info.get('superseded_note_ids',[]))}


# 原曲器乐旋律骨干重提取：新增只承认已核验的旧主线替换；旧低音／和声永远不能混入此集合。
def superseded_ids(guitar,check):
    info=guitar.get('instrumental_source_backbone')
    return set(info['superseded_note_ids']) if info and check and check['valid'] else set()
