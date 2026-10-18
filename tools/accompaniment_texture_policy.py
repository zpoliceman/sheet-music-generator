"""分解和弦优先：保留原织体观察，以多轨起音证据决定柱式例外。"""
# 分解和弦优先：新增独立偏好层，不改已有和弦识别、人声或源音轨。
from __future__ import annotations
import copy
from pathlib import Path
import numpy as np
from accompaniment_analysis import extract_features

POLICY = {'name':'arpeggio_first','version':1,'block_exception':'repeated_chord_onsets_cross_checked_in_audio',
          'minimum_distinct_chord_pitch_classes':3,'minimum_relative_attack_weight':.58,
          'cross_source_tolerance_seconds':.07,'minimum_confirmed_attacks':2,
          # 分解和弦优先：新增排除CQT尾部振铃的弱攻击，分母只计有效主要起音。
          'minimum_attack_strength_fraction':.35,
          'minimum_confirmed_attack_fraction':.65,'arranged_subdivision_ticks':240,
          'quality_status':'conservative_uncalibrated_requires_listening'}


# 分解和弦优先：新增去除八度重复、低权重倍频与仅持续未重起的多音计数。
def onset_pitch_classes(attack,chord):
    result=set()
    for pitch in attack['pitches']:
        sustain=float(pitch.get('sustain_weight',0))
        onset=(float(pitch.get('weight',0))-.08*sustain)/.7
        if (48<=pitch['pitch_midi']<=84 and pitch.get('relative_weight',0)>=.58
                and (not sustain or onset>=.06*sustain)):
            pc=pitch['pitch_midi']%12
            if pc in chord['pitch_classes']:result.add(pc)
    return result


# 分解和弦优先：新增逐攻击交叉核查，源相关性不声称统计独立或音乐准确率。
def block_support(texture,harmony,features):
    name=texture['source'];attacks=texture['attacks'];matches=[]
    start,end=texture['start_seconds'],texture['end_seconds']
    energies={key:float(f.rms[f.window(start,end)].mean()) for key,f in features.items()}
    baseline=energies.get('accompaniment',energies.get('other',0))
    source_active=energies.get(name,0)>=max(.001,.08*baseline)
    # 分解和弦优先：新增合成真柱式实测修正，尾部微弱振铃不能当成原曲主要攻击。
    strength=max((a['strength'] for a in attacks),default=0)
    evaluated=[a for a in attacks if a['strength']>=.35*strength]
    if texture['kind'] in ('block','strum') and source_active:
        # 分解和弦优先：修改，原全候选循环保留，柱式匹配只核查有效主要起音。
        # for attack in attacks:
        for attack in evaluated:
            chord=next((c for c in harmony if c['start_tick']<=attack['tick']<c['end_tick']),None)
            if chord is None or chord['name']=='N.C.':continue
            pcs=onset_pitch_classes(attack,chord)
            if len(pcs)<3:continue
            supporters=[]
            for other in ('accompaniment','other','six_other','six_piano','six_guitar'):
                if other==name or other not in features or energies[other]<max(.001,.08*baseline):continue
                candidates=[a for a in features[other].attacks if abs(a['seconds']-attack['seconds'])<=.07]
                if any(len(pcs&onset_pitch_classes(a,chord))>=3 for a in candidates):supporters.append(other)
            if supporters:
                matches.append({'tick':attack['tick'],'seconds':attack['seconds'],
                                'pitch_classes':sorted(pcs),'cross_support_sources':supporters})
    # 分解和弦优先：修改，原分母保留；真实合成C和弦的3次攻击伴3次弱尾部振铃不能误拒绝。
    # ratio=len(matches)/max(1,len(attacks))
    ratio=len(matches)/max(1,len(evaluated))
    allowed=len(matches)>=2 and ratio>=.65
    return {'allow_block':allowed,'confirmed_attack_count':len(matches),'attack_count':len(attacks),
            'evaluated_attack_count':len(evaluated),
            'confirmed_fraction':ratio,'source_has_effective_energy':source_active,'matches':matches,
            'reason':'repeated_cross_supported_chord_attacks' if allowed else 'insufficient_chord_onset_evidence',
            'evidence_status':'heuristic_cross_support_not_human_verified'}


# 分解和弦优先：新增复用声学缓存补充证据，原分类及所有源候选原样保留。
def add_block_support(shared,vocal,cache_dir):
    features={}
    for name in ('accompaniment','other','six_other','six_piano','six_guitar'):
        source=shared['input_binding']['sources'].get(name)
        if source:features[name]=extract_features(source,Path(cache_dir),name)
    for texture in shared['measure_textures']:
        texture['block_support']=block_support(texture,shared['harmony'],features)
    shared['arrangement_policy']=copy.deepcopy(POLICY)
    return shared


# 分解和弦优先：新增逐攻击例外门槛，稀疏攻击或无证据旧缓存一律不能强制柱式。
def performance_kind(texture,tick):
    observed=texture['kind']
    if observed not in ('block','strum'):return observed,'follow_observed_attacks'
    evidence=texture.get('block_support',{})
    matched=any(row['tick']==tick for row in evidence.get('matches',[]))
    if evidence.get('allow_block',False) and matched:
        return observed,'retained_cross_supported_simultaneous_chord'
    return 'arpeggio','prefer_arpeggio_without_strong_block_evidence'


# 分解和弦优先：新增实际谱面织体标签，避免显示已被编配改写的原观察分类。
def arranged_texture_label(arrangement,start,end,fallback):
    kinds={e['kind'] for e in arrangement['attack_events'] if start<=e['start_tick']<end}
    labels={'arpeggio':'分解','block':'柱式','strum':'扫弦','sustain':'延音','silence':'休止'}
    return '/'.join(labels[k] for k in ('arpeggio','block','strum','sustain','silence') if k in kinds) or labels[fallback]


# 分解和弦优先：新增攻击来源标记，编配细分与原曲检测攻击明确区分。
def attack_provenance(group):
    return {key:group.get(key) for key in ('observed_kind','arrangement_reason','onset_origin','texture_measure',
                                         'arpeggio_step','arpeggio_pitch_class')}
