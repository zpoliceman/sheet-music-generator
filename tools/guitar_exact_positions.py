# 常用指型与器乐独奏：修改，原仅同音换弦且不缩短原音的声明保留；固定极端音域无解时允许最小释音。
# """常用指型与器乐独奏：保持音高/时值的同音换弦，修正真实持续音下的换把。"""
# 常用指型与器乐独奏：新增精确音高的弦品调整，不移八度、不新增攻击、不缩短原音。
"""常用指型与器乐独奏：优先同音换弦，必要时最小释音，保持音高与起音。"""
# 常用指型与器乐独奏：修改，原无界组合枚举保留；限制局部搜索，避免密集声部造成组合爆炸。
# from itertools import product
# 常用指型与器乐独奏：修改，原只含组合积保留；同步结束的旋律/低音需要联合释放才可能换把。
# from itertools import product,islice
from itertools import product,islice,combinations
from accompaniment_arrange import TUNING,grip_info
from guitar_grip_policy import grip_position_path
# 结构稳定伴奏与人声合播：修改，原代码注释保留。
# from guitar_grip_library import common_grips,fret_map
from guitar_grip_library import common_grips,fret_map
# 结构稳定伴奏与人声合播：新增每音夹位查询。
from guitar_capo import capo_at


# 常用指型与器乐独奏：新增同音候选与原按法优先，所有品数相对变调夹计算。
def exact_locations(note,capo):
    found=[(s,note['pitch_midi']-TUNING[s]-capo) for s in range(6,0,-1)
           if 0<=note['pitch_midi']-TUNING[s]-capo<=20]
    return sorted(found,key=lambda sf:(sf!=(note['string'],note['fret']),abs(sf[1]-note['fret']),-sf[0]))


# 常用指型与器乐独奏：新增禁止同弦实际持续区间重叠，不能为了换把把之前的音悄悄截断。
def strings_do_not_overlap(notes):
    for string in range(1,7):
        selected=sorted((n for n in notes if n['string']==string),key=lambda n:n['start_tick'])
        if any(a['end_tick']>b['start_tick'] for a,b in zip(selected,selected[1:])):return False
    return True


# 常用指型与器乐独奏：新增修正仅发生在严格时序失败的攻击，常用指型匹配作为同等可行方案的优先。
def refinger_exact_positions(shared,vocal,arrangement):
    notes=arrangement['notes'];capo=arrangement['configuration']['capo_fret']
    before={n['id']:(n['string'],n['fret']) for n in notes}
    # 常用指型与器乐独奏：新增原始结束时间记录，默认保持；真正无解时逐项记录最小释音。
    before_end={n['id']:n['end_tick'] for n in notes}
    sound=[(n['id'],n['pitch_midi'],n['start_tick'],n['end_tick'],n['velocity']) for n in notes]
    probe={**arrangement,'fingering_diagrams':[]};check=grip_position_path(probe,vocal);repairs=0
    while not check['valid']:
        # 常用指型与器乐独奏：修改，原只调整失败攻击保留；固定最高音有时需要提前两三次攻击准备手位。
        # tick=check['tick'];group=[n for n in notes if n['start_tick']==tick]
        # if not group:raise ValueError('持续音换把失败不在可修正攻击处：'+str(check))
        tick=check['tick'];onsets=sorted({n['start_tick'] for n in notes if n['start_tick']<=tick})
        if not any(n['start_tick']==tick for n in notes):raise ValueError('持续音换把失败不在可修正攻击处：'+str(check))
        # 结构稳定伴奏与人声合播：修改，原代码注释保留。
        # chord=next((h for h in shared['harmony'] if h['start_tick']<=tick<h['end_tick']),None)
        capo=capo_at(arrangement,tick)
        chord=next((h for h in shared['harmony'] if h['start_tick']<=tick<h['end_tick']),None)
        common=[fret_map(e) for e in common_grips(chord['root_pc'],chord['quality'],chord['bass_pc'],capo)] if chord and chord['name']!='N.C.' else []
        # 常用指型与器乐独奏：修改，原单攻击穷举保留；仅单攻击无解时扩大到最近四次攻击，完整时间轴仍须前进。
        # original=[(n['string'],n['fret']) for n in group];best=None
        # for locations in product(*(exact_locations(n,capo) for n in group)):
        #     if list(locations)==original or len({s for s,f in locations})!=len(locations):continue
        #     for note,(string,fret) in zip(group,locations):note['string'],note['fret']=string,fret
        #     if not strings_do_not_overlap(notes):continue
        #     trial=grip_position_path(probe,vocal)
        #     progress=shared['statistics']['total_ticks']+1 if trial['valid'] else trial['tick']
        #     if progress<=tick:continue
        #     matched=max((sum(base.get(s)==f for s,f in locations) for base in common),default=0)
        #     changes=sum(a!=b for a,b in zip(locations,original))
        #     rank=(-progress,changes,-matched,sum(abs(a[1]-b[1]) for a,b in zip(locations,original)))
        #     if best is None or rank<best[0]:best=(rank,locations,trial)
        # for note,(string,fret) in zip(group,original):note['string'],note['fret']=string,fret
        best=None
        for lookback in range(1,min(4,len(onsets))+1):
            scope=set(onsets[-lookback:]);group=[n for n in notes if n['start_tick'] in scope]
            original=[(n['string'],n['fret']) for n in group]
            # 常用指型与器乐独奏：修改，原全枚举保留；最多检查8192种最近四次攻击的组合。
            # for locations in product(*(exact_locations(n,capo) for n in group)):
            # 结构稳定伴奏与人声合播：修改，原代码注释保留。
            # for locations in islice(product(*(exact_locations(n,capo) for n in group)),8192):
            for locations in islice(product(*(exact_locations(n,capo_at(arrangement,n['start_tick'])) for n in group)),8192):
                if list(locations)==original:continue
                for note,(string,fret) in zip(group,locations):note['string'],note['fret']=string,fret
                if not strings_do_not_overlap(notes):continue
                trial=grip_position_path(probe,vocal)
                progress=shared['statistics']['total_ticks']+1 if trial['valid'] else trial['tick']
                if progress<=tick:continue
                matched=max((sum(base.get(s)==f for s,f in locations) for base in common),default=0)
                changes=sum(a!=b for a,b in zip(locations,original))
                rank=(-progress,changes,-matched,sum(abs(a[1]-b[1]) for a,b in zip(locations,original)))
                if best is None or rank<best[0]:best=(rank,locations,trial)
            for note,(string,fret) in zip(group,original):note['string'],note['fret']=string,fret
            if best is not None:break
        # 常用指型与器乐独奏：修改，原无同音解就停止的过程保留；仅在此时以60tick网格寻找最小释音。
        # if best is None:raise ValueError('保持音高/时值的同音换弦未找到持续音时序可行方案：'+str(check))
        # for note,(string,fret) in zip(group,best[1]):note['string'],note['fret']=string,fret
        # check=best[2];repairs+=1
        # 结构稳定伴奏与人声合播：修改，原代码注释保留。
        # if best is None:
            # endings=
        if best is None:
            # 结构稳定伴奏与人声合播：新增严格保护模式，不以释音代替器乐音乐保持。
            if arrangement['configuration'].get('structure_policy'):
                raise ValueError('新版受保护音乐的同音换弦仍不可行：'+str(check))
            endings=[n for n in notes if n['start_tick']<tick and n['end_tick']==tick]
            release=None
            for trim in range(60,max((n['end_tick']-n['start_tick'] for n in endings),default=0)//2+1,60):
                # 常用指型与器乐独奏：修改，原仅限制本次缩短保留；多次修复仍不能累计超过原持续的一半。
                # candidates=[n for n in endings if trim<=(before_end[n['id']]-n['start_tick'])//2 and n['end_tick']-trim-n['start_tick']>=60]
                candidates=[n for n in endings if before_end[n['id']]-(tick-trim)<=(before_end[n['id']]-n['start_tick'])//2
                            and tick-trim-n['start_tick']>=60]
                # 常用指型与器乐独奏：修改，原仅释放单音保留；按最少音数尝试联合结束，仍使用最小60tick网格。
                # for note in candidates:
                #     old_end=note['end_tick'];note['end_tick']=old_end-trim
                #     trial=grip_position_path(probe,vocal);note['end_tick']=old_end
                #     progress=shared['statistics']['total_ticks']+1 if trial['valid'] else trial['tick']
                #     if progress>tick:release=(note,old_end-trim,trial);break
                # 常用指型与器乐独奏：修改，原只枚举释放组合保留；联合同音换弦，避免可以延续的旋律被多余截短。
                # for size in range(1,len(candidates)+1):
                #     for released in combinations(candidates,size):
                #         for note in released:note['end_tick']=tick-trim
                #         trial=grip_position_path(probe,vocal)
                #         for note in released:note['end_tick']=tick
                #         progress=shared['statistics']['total_ticks']+1 if trial['valid'] else trial['tick']
                #         if progress>tick:release=(released,tick-trim,trial);break
                #     if release:break
                original_endings=[(n['string'],n['fret']) for n in endings]
                for size in range(1,len(candidates)+1):
                    choices=[]
                    for released in combinations(candidates,size):
                        for note in released:note['end_tick']=tick-trim
                        # 结构稳定伴奏与人声合播：修改，原代码注释保留。
                        # for locations in islice(product(*(exact_locations(n,capo) for n in endings)),8192):
                        for locations in islice(product(*(exact_locations(n,capo_at(arrangement,n['start_tick'])) for n in endings)),8192):
                            for note,(string,fret) in zip(endings,locations):note['string'],note['fret']=string,fret
                            if not strings_do_not_overlap(notes):continue
                            trial=grip_position_path(probe,vocal)
                            progress=shared['statistics']['total_ticks']+1 if trial['valid'] else trial['tick']
                            if progress<=tick:continue
                            changes=sum(a!=b for a,b in zip(locations,original_endings))
                            rank=(sum(n['role']=='instrumental_melody' for n in released),changes,
                                  sum(abs(a[1]-b[1]) for a,b in zip(locations,original_endings)),-progress)
                            choices.append((rank,(released,tick-trim,trial,locations)))
                        for note,(string,fret) in zip(endings,original_endings):note['string'],note['fret']=string,fret
                        for note in released:note['end_tick']=tick
                    if choices:release=min(choices,key=lambda x:x[0])[1];break
                if release:break
            if release is None:raise ValueError('同音换弦和最小释音仍未找到持续时序可行方案：'+str(check))
            # 常用指型与器乐独奏：修改，原单音提交保留；联合释放逐项提交并记录原结束时间。
            # release[0]['end_tick']=release[1];check=release[2]
            for note in release[0]:note['end_tick']=release[1]
            # 常用指型与器乐独奏：新增提交联合选出的同音位置，其余音的原结束时间保持。
            for note,(string,fret) in zip(endings,release[3]):note['string'],note['fret']=string,fret
            check=release[2]
        else:
            for note,(string,fret) in zip(group,best[1]):note['string'],note['fret']=string,fret
            check=best[2]
        repairs+=1
        if repairs>len(notes):raise ValueError('同音换弦超过单调推进上限。')
    changes=[{'note_id':n['id'],'from_string_fret':list(before[n['id']]),'to_string_fret':[n['string'],n['fret']]}
             for n in notes if before[n['id']]!=(n['string'],n['fret'])]
    # 常用指型与器乐独奏：修改，原全参数一致检查保留；音高/攻击/力度必须相等，结束时间单独审计。
    # if sound!=[(n['id'],n['pitch_midi'],n['start_tick'],n['end_tick'],n['velocity']) for n in notes]:
    #     raise ValueError('同音换弦意外改变了音乐发声。')
    if [(i,p,a,vel) for i,p,a,b,vel in sound]!=[(n['id'],n['pitch_midi'],n['start_tick'],n['velocity']) for n in notes]:
        raise ValueError('持续音修正意外改变了音高、攻击或力度。')
    releases=[{'note_id':n['id'],'from_end_tick':before_end[n['id']],'to_end_tick':n['end_tick']}
              for n in notes if before_end[n['id']]!=n['end_tick']]
    # 常用指型与器乐独奏：修改，原仅换弦更新保留；必要释音后同样重算手位与指法。
    # if changes:
    # 结构稳定伴奏与人声合播：修改，原条件注释保留。
    # if changes or releases:
    if changes or releases or arrangement['configuration'].get('capo_segments'):
        arrangement['hand_positions']=check['positions']
        positions={p['tick']:p['position'] for p in check['positions']}
        for tick in sorted({n['start_tick'] for n in notes}):
            active=[n for n in notes if n['start_tick']<=tick<n['end_tick']]
            info=grip_info({n['string']:n['fret'] for n in active})
            for note in active:
                if note['start_tick']==tick:
                    note['hand_position']=positions[tick];note['finger']=info['fingers'].get(note['string'],0)
        # 常用指型与器乐独奏：修改，原换弦说明保留；联合释音时结束时间由独立审计准确说明。
        # arrangement['adjustments'].extend({'type':'same_pitch_refingering_for_sustain_transition',**item,
        #                                    'reason':'持续音结束前不能提前换把；音高与完整时值保留'} for item in changes)
        arrangement['adjustments'].extend({'type':'same_pitch_refingering_for_sustain_transition',**item,
                                           'reason':'持续音结束前不能提前换把；音高与起音保留，结束时间由释音审计单列'} for item in changes)
        # 常用指型与器乐独奏：新增独立记录必要释音，不得声称试听或时值与旧版完全一致。
        arrangement['adjustments'].extend({'type':'minimal_release_for_sustain_transition',**item,
                                           'reason':'同音换弦无解，保留音高与起音，以最小释音留出24品/秒换把时间'} for item in releases)
    # 常用指型与器乐独奏：修改，原所有结束时间保留的结论存注释；按真实变更输出。
    # result={'valid':True,'changed_note_count':len(changes),'changes':changes,
    #         'all_pitches_attacks_releases_and_velocities_preserved':True,
    result={'valid':True,'changed_note_count':len(changes),'changes':changes,
            'release_change_count':len(releases),'releases':releases,
            'all_pitches_attacks_and_velocities_preserved':True,
            'all_releases_preserved':not releases,
            'maximum_actual_note_position_rate':check['max_frets_per_second']}
    arrangement['exact_pitch_refingering']=result
    return result
