"""器乐填充密度随主体伴奏：从真实正文右手攻击推断稳定填充密度，不使用歌曲名称。"""
from copy import deepcopy
from collections import Counter
from guitar_instrumental_register import fingerprint

# 器乐填充密度随主体伴奏：新增只分析伴奏攻击格，不把音符持续或同刻和弦音数当密度。
POLICY={'version':1,'minimum_coverage_pulses':8,'minimum_attack_groups':6,
    'maximum_fill_subdivision_ticks':120,'density_tolerance_ratio':.025,
    'mixed_eighth_sixteenth_base':'eighth','simultaneous_notes_count_as_one':True,
    'adjacent_stable_vocal_section_first':True,'one_density_per_instrumental_section':True,
    'fallback':'historical_meter_eighth_grid','song_name_or_lyric_answers_used':False}


# 器乐填充密度随主体伴奏：新增拍号适配，复拍的自然细分保持八分单位，可支持整个复拍的慢织体。
def density_units(meter):
    numerator,denominator=meter;unit=480*4//denominator
    compound=denominator==8 and numerator>=6 and numerator%3==0
    pulse=unit*3 if compound else unit
    steps=sorted({120,unit,pulse}) if compound else sorted({120,max(120,pulse//2),pulse})
    return pulse,steps,unit if compound else max(120,pulse//2)


# 器乐填充密度随主体伴奏：新增按覆盖时长加权的基本攻击格；混合型的短细节不把全段填充推到最快格。
def summarize(attacks,meter):
    pulse,steps,fallback=density_units(meter)
    coverage=sum(e['duration_ticks'] for e in attacks);count=len(attacks)
    mean=coverage/count if count else None
    available=[step for step in steps if mean is not None and step>=mean*(1-POLICY['density_tolerance_ratio'])]
    step=min(available) if available else (max(steps) if mean is not None else fallback)
    reliable=count>=POLICY['minimum_attack_groups'] and coverage>=pulse*POLICY['minimum_coverage_pulses']
    return {'step_ticks':step if reliable else fallback,'reliable':reliable,'attack_groups':count,
        'covered_ticks':coverage,'mean_attack_slot_ticks':round(mean,6) if mean is not None else None,
        'duration_histogram':{str(k):v for k,v in sorted(Counter(e['duration_ticks'] for e in attacks).items())},
        'decision':'observed_stable_vocal_density' if reliable else 'insufficient_ordinary_evidence_keep_meter_fallback'}


# 器乐填充密度随主体伴奏：新增正文实际攻击证据，低弦填充、器乐短句和多弦合拨不会污染主体密度。
def ordinary_attacks(shared,vocal,guitar):
    sections=[s for s in shared['sections'] if s['kind']=='vocal']
    notes=[n for n in guitar['notes'] if any(s['start_tick']<=n['start_tick']<s['end_tick'] for s in sections)
        and n['role']!='instrumental_melody' and not n.get('instrumental_flow_fill')]
    ticks={n['start_tick'] for n in notes};by_tick={}
    for event in guitar['attack_events']:
        tick=event['start_tick'];duration=event.get('right_hand_duration_ticks')
        if tick not in ticks or event.get('right_hand_duration_source')!='regular_pattern_slot' or not isinstance(duration,int) or duration<120:continue
        value={'tick':tick,'duration_ticks':duration,'pattern_id':event.get('right_hand_pattern_id'),
            'source':'actual_regular_right_hand_slot'}
        # 器乐填充密度随主体伴奏：新增同刻多事件仅记一次，以最短真实攻击格为准。
        if tick not in by_tick or duration<by_tick[tick]['duration_ticks']:by_tick[tick]=value
    if not by_tick:
        # 器乐填充密度随主体伴奏：新增无模板历史工程用同一小节内起音间距后备，跨休止长间距不冒充慢伴奏。
        bar=vocal['statistics']['bar_ticks'];pulse,_,_=density_units(vocal['timing']['meter'])
        for section in sections:
            ordered=sorted(t for t in ticks if section['start_tick']<=t<section['end_tick'])
            for a,b in zip(ordered,ordered[1:]):
                if a//bar==b//bar and 120<=b-a<=pulse:
                    by_tick[a]={'tick':a,'duration_ticks':b-a,'pattern_id':None,'source':'observed_same_bar_attack_spacing'}
    return sorted(by_tick.values(),key=lambda e:e['tick'])


# 器乐填充密度随主体伴奏：新增相邻稳定唱段密度选择，器乐一段只选择一次，不随每个音／和弦切换。
def build_density_plan(shared,vocal,guitar):
    meter=vocal['timing']['meter'];attacks=ordinary_attacks(shared,vocal,guitar);global_density=summarize(attacks,meter)
    profiles=[]
    for i,section in enumerate(shared['sections']):
        if section['kind']!='vocal':continue
        group=[e for e in attacks if section['start_tick']<=e['tick']<section['end_tick']]
        profiles.append({'id':f'vocal_density_{i}','start_tick':section['start_tick'],'end_tick':section['end_tick'],**summarize(group,meter)})
    stable=[p for p in profiles if p['reliable']];instrumentals=[]
    for i,section in enumerate(shared['sections']):
        if section['kind'] not in ('intro','interlude','outro'):continue
        previous=[p for p in stable if p['end_tick']<=section['start_tick']]
        following=[p for p in stable if p['start_tick']>=section['end_tick']]
        chosen=(previous[-1] if previous else None) if section['kind']=='outro' else (following[0] if following else previous[-1] if previous else None)
        density=chosen or global_density
        instrumentals.append({'section_index':i,'kind':section['kind'],'start_tick':section['start_tick'],'end_tick':section['end_tick'],
            'step_ticks':density['step_ticks'],'source_profile_id':chosen['id'] if chosen else 'whole_song',
            'decision':'adjacent_stable_vocal_section' if chosen else global_density['decision']})
    return {'version':1,'policy':deepcopy(POLICY),'meter':list(meter),'ordinary_attacks':attacks,
        'ordinary_evidence_sha256':fingerprint(attacks),'global_density':global_density,'vocal_profiles':profiles,
        'instrumental_profiles':instrumentals}


def section_step(density_plan,section,fallback):
    return next((p['step_ticks'] for p in density_plan['instrumental_profiles'] if p['start_tick']==section['start_tick'] and p['end_tick']==section['end_tick']),fallback)
