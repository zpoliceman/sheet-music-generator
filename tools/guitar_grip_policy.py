"""常用指型与器乐独奏：常用完整指型优先、器乐匹配和左手连续覆盖。"""
# 常用指型与器乐独奏：新增演奏展示策略，保留共享和声及全部实际音符。
from __future__ import annotations
from collections import defaultdict
# 吉他器乐低把位与指型复用：新增保护已认可唱段图式的独立拷贝，不与来源快照共享可变对象。
from copy import deepcopy
from accompaniment_arrange import grip_info
from accompaniment_analysis import SongClock, chord_name, pc_name
from guitar_grip_library import common_grips, fret_map, load_library
# 结构稳定伴奏与人声合播：修改，原代码注释保留。
# from score_export import key_definition
from score_export import key_definition
# 结构稳定伴奏与人声合播：新增夹位与派生基本和弦查询。
from guitar_capo import capo_at,fret_at
from guitar_structure_patterns import display_chord,select_ornament_grip,ornament_aliases

POLICY = {'name':'common_open_and_instrumental_solo', 'version':1,
          'common_open_first':True, 'instrumental_sections':['intro','interlude','outro'],
          'minimum_match_ratio':0.65, 'minimum_melody_match_ratio':0.55,
          'maximum_temporary_finger_changes':2, 'solo_notes':'numeric_including_open_zero',
          'shared_harmony_preserved':True}


# 常用指型与器乐独奏：新增把横按视为一个按指单位，品位或覆盖范围改变计为松开/新增操作。
def finger_units(frets):
    info = grip_info(frets)
    if info is None:return None
    by_finger = defaultdict(list)
    for string,finger in info['fingers'].items():by_finger[finger].append((string,frets[string]))
    return {tuple(sorted(values)) for values in by_finger.values()}


# 常用指型与器乐独奏：新增实际黑点/横按覆盖基准；未画按点的弦保持未按，和匹配率分开。
def effective_frets(base, active):
    frets = dict(base);info = grip_info(base)
    if info and info['barre']:
        a,b,fret = info['barre']
        for string in range(a,b+1):frets[string] = max(frets.get(string,0),fret)
    frets.update({n['string']:n['fret'] for n in active})
    return frets


# 常用指型与器乐独奏：新增逐攻击检查完整基准按法和真实持续音，不把同音名当同弦同品。
def assess_grip(entry, notes, start, end):
    selected = [n for n in notes if n['start_tick']<end and n['end_tick']>start]
    base = fret_map(entry);units = finger_units(base)
    result = {'valid':False, 'note_count':len(selected), 'match_ratio':0., 'melody_match_ratio':0.,
              'max_temporary_finger_changes':0, 'reason':'no_notes'}
    if not selected or units is None:return result
    weights = {n['id']:min(end,n['end_tick'])-max(start,n['start_tick']) for n in selected}
    matches = {n['id']:base.get(n['string'])==n['fret'] for n in selected}
    total = sum(weights.values())
    result['match_ratio'] = sum(weights[n['id']] for n in selected if matches[n['id']])/total
    melody = [n for n in selected if n.get('role')=='instrumental_melody']
    melody_weight = sum(weights[n['id']] for n in melody)
    result['melody_match_ratio'] = (sum(weights[n['id']] for n in melody if matches[n['id']])/melody_weight
                                    if melody_weight else result['match_ratio'])
    changes = 0
    for tick in sorted({max(start,n['start_tick']) for n in selected}):
        active = [n for n in selected if n['start_tick']<=tick<n['end_tick']]
        effective = effective_frets(base,active);new_units = finger_units(effective)
        if new_units is None:
            result['reason']='complete_grip_and_sustains_not_coverable';return result
        # 常用指型与器乐独奏：新增移动一指按松开加按下两步计数，避免把整副手型替换算作一指。
        changes = max(changes,len(units-new_units)+len(new_units-units))
    result['max_temporary_finger_changes']=changes
    result['valid'] = (result['match_ratio']>=POLICY['minimum_match_ratio']
                       and result['melody_match_ratio']>=POLICY['minimum_melody_match_ratio']
                       and changes<=POLICY['maximum_temporary_finger_changes'])
    result['reason']='common_grip_matches' if result['valid'] else 'weak_match_or_too_many_finger_changes'
    return result


# 常用指型与器乐独奏：新增先过滤不可覆盖候选，再按基础开放指型、常用变体和匹配度排序。
def select_common(chord,notes,start,end,capo):
    found = []
    for entry in common_grips(chord['root_pc'],chord['quality'],chord['bass_pc'],capo):
        check = assess_grip(entry,notes,start,end)
        if check['valid']:
            found.append(((entry['priority'],-check['melody_match_ratio'],-check['match_ratio'],
                           check['max_temporary_finger_changes'],entry['max_fret']),entry,check))
    return min(found,key=lambda x:x[0])[1:] if found else None


# 常用指型与器乐独奏：新增常用候选的完整黑点图，和弦性质/转位及变调夹换算保持准确。
def common_chart(chord,entry,check,capo):
    frets = fret_map(entry);info = grip_info(frets);positive = [f for f in frets.values() if f>0]
    first = min(positive,default=1)
    if max(positive,default=0)<=4:first=1
    from accompaniment_arrange import capo_shape_key
    key = capo_shape_key(chord['key'],capo)
    return {'frets':{str(s):f for s,f in frets.items()}, 'position':first,
            'shape_name':chord_name(chord['root_pc']-capo,chord['quality'],chord['bass_pc']-capo,key),
            'sounding_name':chord['name'], 'capo':capo, 'barre':info['barre'], 'finger_count':info['finger_count'],
            'simplified':False, 'source':'sourced_common_grip', 'common_grip_id':entry['id'],
            'common_grip_tier':entry['tier'], 'compatibility':check}


# 常用指型与器乐独奏：新增共同时轴分区，器乐/人声边界即使在小节中间也不跨过去沿用图式。
# 结构稳定伴奏与人声合播：修改，原代码注释保留。
# def notation_spans(shared,notes):
def notation_spans(shared,notes,arrangement=None):
    total = shared['statistics']['total_ticks'];bar = shared['statistics']['bar_ticks']
    # 结构稳定伴奏与人声合播：修改，原代码注释保留。
    # points = {0,total}
    # for h in shared['harmony']:
    points = {0,total}
    if arrangement is not None:points.update(s['start_tick'] for s in arrangement['configuration'].get('capo_segments',[]))
    for h in shared['harmony']:points.update((h['start_tick'],h['end_tick']))
    for section in shared.get('sections',[]):points.update((section['start_tick'],section['end_tick']))
    points = sorted(p for p in points if 0<=p<=total)
    for start,end in zip(points,points[1:]):
        chord = next((h for h in shared['harmony'] if h['start_tick']<=start<h['end_tick']),None)
        section = next((s['kind'] for s in shared.get('sections',[]) if s['start_tick']<=start<s['end_tick']),None)
        if section is None:
            textures=shared.get('measure_textures',[])
            section=textures[min(start//bar,len(textures)-1)]['section'] if textures else 'vocal'
        yield start,end,chord,section


# 常用指型与器乐独奏：新增完整图式持握后的手位连续路径，实际品数/持续音仍不改写。
def grip_position_path(arrangement,vocal):
    notes=arrangement['notes'];plan=arrangement['fingering_diagrams'];clock=SongClock(vocal)
    # 常用指型与器乐独奏：修改，原只检查攻击边界保留；持续音结束也约束何时才能开始换把。
    # ticks=sorted({n['start_tick'] for n in notes});costs={};traces=[];previous_tick=None;previous_chart=None
    ticks=sorted({t for n in notes for t in (n['start_tick'],n['end_tick'])} |
                 {t for d in plan for t in (d['start_tick'],d['end_tick'])})
    # 常用指型与器乐独奏：修改，原仅追踪紧邻事件的图式保留；跨无图边界仍定位最近实际持握的图。
    # costs={};traces=[];previous_tick=None;previous_chart=None;previous_allowed=None
    costs={};traces=[];previous_tick=None;previous_chart=None;previous_allowed=None;last_held_chart=None
    for tick in ticks:
        active=[n for n in notes if n['start_tick']<=tick<n['end_tick']]
        chart=next((d for d in plan if d['start_tick']<=tick<d['end_tick']),None)
        # 常用指型与器乐独奏：修改，原在无声间隙也强行持握保留；休止时允许准备下一次按法。
        # base={int(s):f for s,f in chart['frets'].items()} if chart else {}
        base={int(s):f for s,f in chart['frets'].items()} if chart and active else {}
        # 结构稳定伴奏与人声合播：修改，原代码注释保留。
        # effective=effective_frets(base,active);info=grip_info(effective)
        effective=effective_frets(base,[{**n,'fret':fret_at(n,arrangement,tick)} for n in active]);info=grip_info(effective)
        if info is None:return {'valid':False,'reason':'full_grip_not_coverable','tick':tick,'chart_id':chart['id'] if chart else None}
        positive=[f for f in effective.values() if f>0]
        allowed=range(max(1,max(positive,default=1)-5),min(positive,default=20)+1)
        old=next((p['position'] for p in reversed(arrangement.get('hand_positions',[])) if p['tick']<=tick),1)
        current={};trace={}
        for position in allowed:
            if previous_tick is None:current[position]=abs(position-old)*.01;trace[position]=None;continue
            seconds=max(.001,clock.seconds(tick)-clock.seconds(previous_tick))
            # 常用指型与器乐独奏：修改，原只要求端点速度保留；运动途中不能越过仍在发声的旧手位范围。
            # choices=[(cost+.1*abs(position-before)+.01*abs(position-old),before) for before,cost in costs.items()
            #          if abs(position-before)/seconds<=24+1e-8]
            choices=[(cost+.1*abs(position-before)+.01*abs(position-old),before) for before,cost in costs.items()
                     # 结构稳定伴奏与人声合播：修改，原代码注释保留。
                     # if position in previous_allowed and abs(position-before)/seconds<=24+1e-8]
                     if position+capo_at(arrangement,tick)-capo_at(arrangement,previous_tick) in previous_allowed and
                     abs(position+capo_at(arrangement,tick)-before-capo_at(arrangement,previous_tick))/seconds<=24+1e-8]
            if choices:current[position],trace[position]=min(choices)
        if not current:
            candidates=[d for d in (chart,previous_chart) if d and d.get('common_grip_id')]
            # 常用指型与器乐独奏：修改，原跨图式结束边界返回None保留；定位最近持握图以便安全撤回。
            # return {'valid':False,'reason':'complete_grip_position_rate','tick':tick,
            #         'chart_id':candidates[0]['id'] if candidates else (chart['id'] if chart else None)}
            responsible=candidates[0] if candidates else (chart or previous_chart or last_held_chart)
            return {'valid':False,'reason':'complete_grip_position_rate','tick':tick,
                    'chart_id':responsible['id'] if responsible else None}
        # 常用指型与器乐独奏：修改，原路径状态保留；记录上一持续区间的可覆盖手位。
        # traces.append((tick,trace));costs=current;previous_tick=tick;previous_chart=chart
        traces.append((tick,trace));costs=current;previous_tick=tick;previous_chart=chart;previous_allowed=allowed
        # 常用指型与器乐独奏：新增只记录实际发声时的持握，休止区的空图不作为换把原因。
        if chart and active:last_held_chart=chart
    if not ticks:return {'valid':True,'positions':[],'max_frets_per_second':0.}
    winner=min(costs,key=costs.get);path=[]
    for tick,trace in reversed(traces):path.append({'tick':tick,'position':winner});winner=trace[winner]
    path.reverse()
    # 结构稳定伴奏与人声合播：修改，原代码注释保留。
    # rate=max((abs(b['position']-a['position'])/(clock.seconds(b['tick'])-clock.seconds(a['tick']))
    rate=max((abs(b['position']+capo_at(arrangement,b['tick'])-a['position']-capo_at(arrangement,a['tick']))/(clock.seconds(b['tick'])-clock.seconds(a['tick']))
              for a,b in zip(path,path[1:])),default=0.)
    return {'valid':True,'positions':path,'max_frets_per_second':rate}


# 常用指型与器乐独奏：新增普通伴奏的实际按法后备，保留旧搜索仅用于无法采用常用完整指型时。
def actual_charts(chord,notes,start,end,capo,path):
    from guitar_chord_diagrams import choose_diagram, fits
    future=[n for n in notes if start<=n['start_tick']<end];current=None;charts=[]
    for tick in sorted({start,*[n['start_tick'] for n in future]}):
        active=[n for n in notes if n['start_tick']<=tick<n['end_tick']];probe=tick
        if not active and tick==start and future:
            probe=min(n['start_tick'] for n in future);active=[n for n in notes if n['start_tick']<=probe<n['end_tick']]
        position=max(1,next((p['position'] for p in reversed(path) if p['tick']<=probe),
                            min((n['fret'] for n in active if n['fret']>0),default=1)))
        if current is None or not fits(current['frets'],active,position):
            chart=choose_diagram(chord,active,[n for n in future if n['start_tick']>=probe],capo,position)
            if current:current['end_tick']=tick
            chart.update({'start_tick':tick,'end_tick':end,'chord_id':chord['id'],
                          'reason':'no_compatible_common_grip' if tick==start else 'actual_position_change'})
            charts.append(chart);current=chart
    return charts


# 常用指型与器乐独奏：新增统一策略入口，无合适常用指型的器乐段不生成勉强凑出的和弦。
def prepare_common_diagrams(shared,arrangement,vocal=None):
    # 结构稳定伴奏与人声合播：修改，原代码注释保留。
    # notes=arrangement['notes'];capo=arrangement['configuration']['capo_fret'];plan=[];regions=[]
    # for start,end,chord,section in notation_spans(shared,notes):
    notes=arrangement['notes'];plan=[];regions=[]
    for start,end,chord,section in notation_spans(shared,notes,arrangement):
        capo=capo_at(arrangement,start)
        region={'id':f'notation_region_{len(regions)+1:04}','start_tick':start,'end_tick':end,
                'section':section,'mode':'solo_tab','reason':'no_notes_or_no_harmony',
                'chord_id':chord['id'] if chord else None}
        selected=[n for n in notes if n['start_tick']<end and n['end_tick']>start]
        # 吉他器乐低把位与指型复用：新增唱段原图式优先保留；新器乐图只在授权段内重建。
        register=arrangement.get('instrumental_register')
        if register and register.get('source_notation_regions') and section not in POLICY['instrumental_sections']:
            old_region=next((r for r in register['source_notation_regions'] if r['start_tick']==start and r['end_tick']==end),None)
            if old_region:
                region=deepcopy(old_region)
                plan.extend(deepcopy(d) for d in register['source_fingering_diagrams'] if start<=d['start_tick']<end)
                regions.append(region)
                continue
        # 器乐主旋律简化与规整节奏：新增单线编配显示；单个旋律音不再触发整副和弦指型，普通演唱沿原规则。
        if section in POLICY['instrumental_sections'] and any(n.get('backbone_id') for n in selected) and \
                arrangement['configuration'].get('instrumental_policy',{}).get('mode')=='monophonic_backbone_without_inner_chord_fills':
            region['reason']='simplified_monophonic_backbone_without_forced_chord'
            regions.append(region)
            continue
        if chord and chord['name']!='N.C.' and selected:
            # 结构稳定伴奏与人声合播：修改，原代码注释保留。
            # chosen=select_common(chord,notes,start,end,capo)
            # if chosen:
                # entry,check=chosen;chart=common_chart(chord,entry,check,capo)
            shown=display_chord(shared,arrangement,chord) if section=='vocal' else chord
            ornament=shown['quality']!=chord['quality']
            chosen=select_ornament_grip(shown,notes,start,end,capo) if ornament else select_common(chord,notes,start,end,capo)
            if chosen:
                entry,check=chosen;chart=common_chart(shown,entry,check,capo)
                if ornament:chart.update({'ornament_source_quality':chord['quality'],'base_harmony_id':arrangement['ornament_display']['aliases'][chord['id']]['base_harmony_id'],'sounding_name':chord['name']})
                chart.update({'start_tick':start,'end_tick':end,'chord_id':chord['id'],'reason':'common_open_first'})
                plan.append(chart);region.update(mode='chord_grip',reason='common_grip_matches',common_grip_id=entry['id'])
            elif section in POLICY['instrumental_sections']:
                region['reason']='instrumental_no_compatible_common_grip'
            else:
                plan.extend(actual_charts(chord,notes,start,end,capo,arrangement.get('hand_positions',[])))
                region.update(mode='chord_grip',reason='vocal_actual_grip_fallback')
        regions.append(region)
    # 吉他器乐低把位与指型复用：修改，旧全曲重编号保留；新器乐图采用独立前缀，唱段原图ID保持。
    # for index,chart in enumerate(plan,1):chart['id']=f'grip_{index:04}'
    for index,chart in enumerate(plan,1):
        if arrangement.get('instrumental_register'):
            if not chart.get('id'):chart['id']=f'register_grip_{index:04}'
        else:chart['id']=f'grip_{index:04}'
    arrangement['fingering_diagrams']=plan
    # 常用指型与器乐独奏：新增换把速度不通过时自动撤销该常用图，器乐转数字，演唱回实际按法。
    if vocal is not None:
        # 常用指型与器乐独奏：修改，原按图数限制迭代保留；每区最多经历常用、实际后备、纯数字三种状态。
        # for _ in range(len(plan)+1):
        for _ in range(2*len(regions)+1):
            check=grip_position_path(arrangement,vocal)
            if check['valid']:break
            # 常用指型与器乐独奏：修改，原只能撤回常用图保留；实际后备也须满足持续音的换把时序。
            # bad=next((d for d in plan if d['id']==check.get('chart_id') and d.get('common_grip_id')),None)
            bad=next((d for d in plan if d['id']==check.get('chart_id')),None)
            if bad is None:raise ValueError('图式持握时序无法满足：'+str(check))
            # 常用指型与器乐独奏：修改，原只找完全等长区间保留；实际后备图允许在区间中途换位。
            # region=next(r for r in regions if r['start_tick']==bad['start_tick'] and r['end_tick']==bad['end_tick'])
            region=next(r for r in regions if r['start_tick']<=bad['start_tick']<r['end_tick'])
            # 常用指型与器乐独奏：新增不可持续持握的后备段退为明确数字，不以虚假的左手图继续解释x。
            if not bad.get('common_grip_id'):
                plan[:]=[d for d in plan if not region['start_tick']<=d['start_tick']<region['end_tick']]
                region.update(mode='solo_tab',reason='actual_grip_rejected_transition');region.pop('common_grip_id',None)
                continue
            plan.remove(bad);region.pop('common_grip_id',None);region['reason']='common_grip_rejected_transition'
            if region['section'] in POLICY['instrumental_sections']:region['mode']='solo_tab'
            else:
                chord=next(h for h in shared['harmony'] if h['id']==region['chord_id'])
                # 结构稳定伴奏与人声合播：修改，原代码注释保留。
                # extra=actual_charts(chord,notes,region['start_tick'],region['end_tick'],capo,arrangement.get('hand_positions',[]))
                extra=actual_charts(chord,notes,region['start_tick'],region['end_tick'],capo_at(arrangement,region['start_tick']),arrangement.get('hand_positions',[]))
                for index,chart in enumerate(extra,1):chart['id']=bad['id']+f'_fallback_{index}'
                plan.extend(extra);plan.sort(key=lambda d:d['start_tick'])
        if not check['valid']:raise ValueError('常用图式退回后仍无法满足时序。')
        arrangement['grip_hand_positions']=check['positions']
        arrangement['grip_position_rate']=check['max_frets_per_second']
    arrangement['notation_regions']=regions
    # 常用指型与器乐独奏：修改，原只保存库数量保留；加入实际拍界供可见图独立核对。
    # arrangement['configuration']['grip_policy']={**POLICY,'library_count':len(load_library()['entries'])}
    arrangement['configuration']['grip_policy']={**POLICY,'library_count':len(load_library()['entries']),
                                               'bar_ticks':shared['statistics']['bar_ticks']}
    # 常用指型与器乐独奏：新增与完整持握一致的导出指法，保存在派生层，不改原音符列表。
    fingerings={}
    for tick in sorted({n['start_tick'] for n in notes}):
        active=[n for n in notes if n['start_tick']<=tick<n['end_tick']]
        chart=next((d for d in plan if d['start_tick']<=tick<d['end_tick']),None)
        base={int(s):f for s,f in chart['frets'].items()} if chart else {}
        info=grip_info(effective_frets(base,active))
        if info:
            for note in active:
                if note['start_tick']==tick:fingerings[note['id']]=info['fingers'].get(note['string'],0)
    arrangement['grip_fingerings']=fingerings
    # 吉他器乐低把位与指型复用：新增真实连续实体手指的导出，器乐与已认可唱段分别沿用其实际按指。
    register=arrangement.get('instrumental_register')
    if register:
        editable=set(register['editable_note_ids'])
        fingerings.update({i:f for i,f in register.get('source_grip_fingerings',{}).items() if i not in editable})
        fingerings.update({n['id']:n['finger'] for n in notes if n['id'] in editable})
    # 器乐低弦分解填充：新增沿用联合持续手指选择的填充按指，不能在绘图时另换仍需保持的手指。
    if arrangement.get('instrumental_flow'):
        fingerings.update({n['id']:n['finger'] for n in notes if n.get('instrumental_flow_fill')})
    return plan


# 常用指型与器乐独奏：新增交付核验，独立复算常用图式及器乐区间，拒绝把纯数字段误当和弦段。
def validate_grip_policy(shared,arrangement,vocal):
    if arrangement['configuration'].get('grip_policy',{}).get('name')!=POLICY['name']:return None
    errors=[];entries={e['id']:e for e in load_library()['entries']};regions=arrangement['notation_regions']
    plan=arrangement['fingering_diagrams'];notes=arrangement['notes']
    for a,b in zip(regions,regions[1:]):
        if a['end_tick']!=b['start_tick']:errors.append('notation_regions_gap_or_overlap')
    if not regions or regions[0]['start_tick']!=0 or regions[-1]['end_tick']!=shared['statistics']['total_ticks']:
        errors.append('notation_regions_do_not_cover_song')
    for chart in plan:
        region=next((r for r in regions if r['start_tick']<=chart['start_tick']<r['end_tick']),None)
        if not region or region['mode']!='chord_grip' or chart['end_tick']>region['end_tick']:
            errors.append('diagram_in_solo_or_crossing_region');continue
        if chart.get('common_grip_id'):
            entry=entries.get(chart['common_grip_id'])
            if entry is None or {int(s):f for s,f in chart['frets'].items()}!=fret_map(entry):
                errors.append('common_grip_geometry_differs_from_library');continue
            # 结构稳定伴奏与人声合播：修改，原代码注释保留。
            # chord=next(h for h in shared['harmony'] if h['id']==chart['chord_id']);capo=chart['capo']
            chord=next(h for h in shared['harmony'] if h['id']==chart['chord_id']);capo=chart['capo']
            if chart.get('ornament_source_quality'):
                actual_alias=ornament_aliases(shared).get(chord['id'])
                if not actual_alias or actual_alias['base_harmony_id']!=chart.get('base_harmony_id'):errors.append('unsupported_basic_chord_ornament')
                chord=display_chord(shared,arrangement,chord)
            if capo!=capo_at(arrangement,chart['start_tick']):errors.append('diagram_wrong_capo_segment')
            if (entry['root_pc']+capo)%12!=chord['root_pc'] or entry['quality']!=chord['quality'] or (entry['bass_pc']+capo)%12!=chord['bass_pc']:
                errors.append('common_grip_chord_or_bass_semantics_mismatch')
            # 结构稳定伴奏与人声合播：修改，原代码注释保留。
            # if not assess_grip(entry,notes,chart['start_tick'],chart['end_tick'])['valid']:
                # errors.append('common_grip_match_or_finger_changes_failed')
            check=assess_grip(entry,notes,chart['start_tick'],chart['end_tick'])
            valid=check['valid']
            if chart.get('ornament_source_quality'):
                valid=check['note_count']>0 and check['reason']!='complete_grip_and_sustains_not_coverable' and check['max_temporary_finger_changes']<=2
            if not valid:errors.append('common_grip_match_or_finger_changes_failed')
        elif region['section'] in POLICY['instrumental_sections']:errors.append('instrumental_noncommon_forced_grip')
    for region in regions:
        if region['mode']=='chord_grip' and not any(d['start_tick']==region['start_tick'] for d in plan):
            errors.append('chord_region_missing_diagram')
    position=grip_position_path(arrangement,vocal)
    if not position['valid']:errors.append('complete_grip_hand_position_failed:'+position['reason'])
    return {'valid':not errors,'errors':errors,'common_grip_count':sum(bool(d.get('common_grip_id')) for d in plan),
            'actual_grip_fallback_count':sum(not d.get('common_grip_id') for d in plan),
            'instrumental_solo_region_count':sum(r['mode']=='solo_tab' and r['section'] in POLICY['instrumental_sections'] for r in regions),
            'maximum_position_rate':position.get('max_frets_per_second'),'library_count':len(entries)}
