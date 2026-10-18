"""和弦弹唱与伴奏编配：共享和声的吉他与钢琴独立配音及演奏约束。"""
# 和弦弹唱与伴奏编配：新增编配层，声学候选不变，所有省略/移八度/释音另存。
from __future__ import annotations
from functools import lru_cache
from itertools import product
import math
import statistics
# 和弦弹唱与伴奏编配：修改，增加通用指型调号换算，原导入保留。
# from accompaniment_analysis import CHORD_TYPES, SongClock, chord_name, section_at
from accompaniment_analysis import CHORD_TYPES, SongClock, chord_name, section_at, pc_name
from score_export import PPQ
# 分解和弦优先：新增独立偏好及攻击来源，原观察不被编配标签覆盖。
from accompaniment_texture_policy import POLICY,performance_kind,attack_provenance
# 常用指型与器乐独奏：新增共用离线常用候选，进入初始编配搜索而非仅替换图片。
from guitar_grip_library import common_grips, fret_map

TUNING = {6:40,5:45,4:50,3:55,2:59,1:64}
ROLE_PRIORITY = {'instrumental_melody':0,'bass':1,'countermelody':2,'harmony':3}


# 新曲慢拍生成与转调标签同步：新增通用夹位指型调号换算；音符拼写G#不等于可用的大调调号，缺失时选等音调。
def capo_shape_key(sounding_key, capo):
    from score_export import key_definition, MAJOR_FIFTHS, PITCH_CLASS
    target = (sounding_key['tonic_pc'] - capo) % 12
    tonic = pc_name(target, sounding_key)
    if tonic not in MAJOR_FIFTHS:
        tonic = next(name for name in MAJOR_FIFTHS
                     if (PITCH_CLASS[name[0]] + name.count('#') - name.count('b')) % 12 == target)
    return key_definition(tonic + ':major')


# 和弦弹唱与伴奏编配：新增实际吉他握法检查，空弦不计跨度，横按不穿过必须开放的弦。
def grip_info(frets, max_span=5):
    positive = [(string,fret) for string,fret in frets.items() if fret>0]
    if not positive:
        return {'position':0,'span':0,'fingers':{},'barre':None,'finger_count':0}
    low,high = min(f for _,f in positive),max(f for _,f in positive)
    if high-low>max_span:
        return None
    best = None
    same = sorted(s for s,f in positive if f==low)
    options = [None]
    for left in same:
        for right in same:
            if right>left and not any(frets.get(s)==0 for s in range(left,right+1)):
                options.append((left,right,low))
    for barre in options:
        covered = [s for s,f in positive if barre and barre[0]<=s<=barre[1] and f==barre[2]]
        remaining = sorted((s,f) for s,f in positive if s not in covered)
        count=len(remaining)+bool(covered)
        if count>4:
            continue
        fingers={s:1 for s in covered}; number=2 if covered else 1
        for string,fret in sorted(remaining,key=lambda x:(x[1],-x[0])):
            fingers[string]=number; number+=1
        current={'position':low,'span':high-low,'fingers':fingers,'barre':list(barre) if covered else None,'finger_count':count}
        if best is None or (count, bool(current['barre'])) < (best['finger_count'],bool(best['barre'])):
            best=current
    return best


# 和弦弹唱与伴奏编配：新增自动搜索和弦指型，根音/性质音/扩展保留，五度允许省略。
@lru_cache(maxsize=2048)
def shape_candidates(root, quality, bass, capo, max_fret=20):
    intervals=CHORD_TYPES[quality]
    chord_pcs={(root+i)%12 for i in intervals}
    essential={(root+i)%12 for i in intervals if i!=7}
    required=essential|{bass}; available=chord_pcs|{bass}
    candidates={}
    for position in range(1,max_fret+1):
        options=[]
        for string in range(6,0,-1):
            frets=[-1]
            if (TUNING[string]+capo)%12 in available:
                frets.append(0)
            frets.extend(f for f in range(position,min(position+5,max_fret)+1) if (TUNING[string]+capo+f)%12 in available)
            options.append(frets)
        for values in product(*options):
            voiced={s:f for s,f in zip(range(6,0,-1),values) if f>=0}
            if len(voiced)<max(3,len(required)):
                continue
            pitches={s:TUNING[s]+capo+f for s,f in voiced.items()}
            pcs={p%12 for p in pitches.values()}
            if not required.issubset(pcs) or min(pitches.values())%12!=bass:
                continue
            grip=grip_info(voiced)
            if grip is None:
                continue
            value=(.06*sum(voiced.values())+.16*grip['position']+.16*grip['span']+
                   .14*bool(grip['barre'])+.14*(6-len(voiced))-.14*sum(f==0 for f in voiced.values()))
            item={'frets':{str(s):f for s,f in voiced.items()},'pitches':{str(s):p for s,p in pitches.items()},
                  **grip,'cost':value,'root_pc':root,'quality':quality,'bass_pc':bass,
                  'omitted_pitch_classes':sorted(chord_pcs-pcs)}
            candidates[values]=item
    # 常用指型与器乐独奏：新增在裁剪18个候选之前注入完整常用指型，开放基础优先且保留真实性质音。
    for entry in common_grips(root,quality,bass,capo):
        voiced=fret_map(entry)
        if max(voiced.values(),default=0)>max_fret:continue
        grip=grip_info(voiced)
        if grip is None:continue
        pitches={s:TUNING[s]+capo+f for s,f in voiced.items()};pcs={p%12 for p in pitches.values()}
        if not required.issubset(pcs) or not pcs.issubset(available) or min(pitches.values())%12!=bass:continue
        value=(.06*sum(voiced.values())+.16*grip['position']+.16*grip['span']+
               .14*bool(grip['barre'])+.14*(6-len(voiced))-.14*sum(f==0 for f in voiced.values())
               -6+.35*entry['priority'])
        values=tuple(voiced.get(s,-1) for s in range(6,0,-1))
        candidates[values]={'frets':{str(s):f for s,f in voiced.items()},'pitches':{str(s):p for s,p in pitches.items()},
                            **grip,'cost':value,'root_pc':root,'quality':quality,'bass_pc':bass,
                            'omitted_pitch_classes':sorted(chord_pcs-pcs),'common_grip_id':entry['id'],
                            'common_grip_tier':entry['tier']}
    # 常用指型与器乐独奏：原候选排序继续用于动态换把路径，新库不绕过演奏约束。
    ranked=sorted(candidates.values(),key=lambda x:x['cost'])
    diverse,positions=[],set()
    for item in ranked:
        key=(item['position'],tuple(sorted(item['pitches'].values())))
        if key not in positions:
            diverse.append(item); positions.add(key)
        if len(diverse)>=18:
            break
    if not diverse:
        raise ValueError(f'找不到保留性质音的吉他握法：root={root},quality={quality},bass={bass},capo={capo}')
    return tuple(diverse)


# 和弦弹唱与伴奏编配：新增全曲换把路径，选调/变调夹改变指型但不改变发声。
def choose_shapes(harmony, capo):
    rows=[c for c in harmony if c['name']!='N.C.']
    candidates=[shape_candidates(c['root_pc'],c['quality'],c['bass_pc'],capo) for c in rows]
    costs,traces=[],[]
    for index,items in enumerate(candidates):
        if not index:
            costs.append([x['cost'] for x in items]);traces.append([-1]*len(items));continue
        previous=candidates[index-1]; values,trace=[],[]
        gap=max(.12, rows[index]['start_seconds']-rows[index-1]['start_seconds'])
        for item in items:
            options=[]
            for i,old in enumerate(previous):
                distance=abs(item['position']-old['position'])
                move=.17*distance + .03*sum(abs(int(item['frets'].get(str(s),0))-int(old['frets'].get(str(s),0))) for s in TUNING)
                move+=max(0,distance/gap-12)*.03
                options.append(costs[-1][i]+move)
            winner=min(range(len(options)),key=options.__getitem__)
            values.append(options[winner]+item['cost']);trace.append(winner)
        costs.append(values);traces.append(trace)
    if not rows:
        return {},0
    winner=min(range(len(costs[-1])),key=costs[-1].__getitem__); total=costs[-1][winner]
    chosen=[winner]
    for trace in traces[:0:-1]:
        chosen.append(trace[chosen[-1]])
    chosen.reverse()
    return {row['id']:dict(items[i]) for row,items,i in zip(rows,candidates,chosen)},total


def harmony_at(shared,tick):
    return next((h for h in shared['harmony'] if h['start_tick']<=tick<h['end_tick']),shared['harmony'][-1])


# 和弦弹唱与伴奏编配：新增原音攻击音高的有限八度还原，分析候选仍原样保留。
def sounding_target(pitches, low=48, high=84):
    candidate=max(pitches,key=lambda p:p['relative_weight'])
    pitch=int(candidate['pitch_midi'])
    while pitch>high: pitch-=12
    while pitch<low: pitch+=12
    return pitch


# 和弦弹唱与伴奏编配：新增共同节奏计划，继承实际攻击并优先保留器乐特色旋律。
def performance_groups(shared):
    groups={}
    bar=shared['statistics']['bar_ticks']
    for texture in shared['measure_textures']:
        if texture['kind']=='silence':
            continue
        attacks=texture['attacks']
        # 原声覆盖与选音归属通用修复：修改，无起音的真实持续音须保留；旧无覆盖证据的工程仍走原跳过路径。
        # if not attacks and texture['kind']=='sustain':
        #     continue
        if not attacks and texture['kind']=='sustain':
            observation = texture.get('sustained_observation')
            if observation is None:
                continue
            attacks = [observation]
        for attack in attacks:
            tick=attack['tick']; chord=harmony_at(shared,tick)
            if chord['name']=='N.C.':
                continue
            # 分解和弦优先：修改，柱式须逐攻击通过原曲交叉支持，原分类赋值保留。
            # groups[tick]={'tick':tick,'kind':texture['kind'],'section':texture['section'],
            kind,reason=performance_kind(texture,tick)
            groups[tick]={'tick':tick,'kind':kind,'observed_kind':texture['kind'],'arrangement_reason':reason,
                          # 原声覆盖与选音归属通用修复：修改，记录延续证据与独立拨弦的区别。
                          # 'onset_origin':'observed','texture_measure':texture['measure'],'section':texture['section'],
                          'onset_origin':attack.get('origin','observed'),'texture_measure':texture['measure'],'section':texture['section'],
                          'chord_id':chord['id'],'source':attack['source'],
                          'source_seconds':attack['seconds'],'source_pitches':attack['pitches'],
                          'target_midi':sounding_target(attack['pitches']),
                          'strength':attack['strength'],'bass_anchor':False,'melody':None}
        # 和弦弹唱与伴奏编配：新增每半小节主要低音锚点，放在已有攻击上，不添加虚构音序。
        for half in (texture['start_tick'],texture['start_tick']+bar//2):
            candidates=[t for t in groups if half<=t<half+bar//2]
            if candidates:
                groups[min(candidates)]['bass_anchor']=True
    for melody in shared['instrumental_melody']:
        tick=melody['start_tick']; chord=harmony_at(shared,tick)
        if chord['name']=='N.C.':
            continue
        if tick not in groups:
            texture=shared['measure_textures'][min(len(shared['measure_textures'])-1,tick//bar)]
            # 分解和弦优先：修改，器乐主线攻击也遵循柱式证据门槛，原行保留。
            # groups[tick]={'tick':tick,'kind':texture['kind'],'section':melody['section'],'chord_id':chord['id'],
            kind,reason=performance_kind(texture,tick)
            groups[tick]={'tick':tick,'kind':kind,'observed_kind':texture['kind'],'arrangement_reason':reason,
                          'onset_origin':'instrumental_melody_candidate','texture_measure':texture['measure'],
                          'section':melody['section'],'chord_id':chord['id'],
                          'source':melody['source'],'source_seconds':melody['start_seconds'],
                          'source_pitches':[{'pitch_midi':melody['pitch_midi'],'relative_weight':melody['support']}],
                          'target_midi':melody['pitch_midi'],'strength':melody['support'],
                          'bass_anchor':False,'melody':None}
        groups[tick]['melody']=melody
    # 尾段原声局部补证：修改首次来源尾响不生成新拨弦／琴键；先筛起音再计算末音完整延续，不能删掉攻击后反而裁短此前长音。
    # rows=sorted(groups.values(),key=lambda x:x['tick'])
    terminal=shared.get('terminal_decay_constraint',{}).get('observation')
    if terminal:
        from score_export import TempoMap
        mapping=TempoMap(shared['timing']['knots']);origin=shared['timing']['score_start_quarter']
        groups={tick:row for tick,row in groups.items() if mapping.quarters_to_seconds(origin+tick/PPQ)<terminal['start_seconds']-1e-6}
    rows=sorted(groups.values(),key=lambda x:x['tick'])
    for index,row in enumerate(rows):
        next_tick=rows[index+1]['tick'] if index+1<len(rows) else shared['statistics']['total_ticks']
        row['duration_ticks']=max(120,min(960,next_tick-row['tick']))
    # 分解和弦优先：修改，原直接返回保留；把未证实柱式拆成性质音/五度/加音/根音的顺序。
    # return rows
    planned=[];steps={}
    for row in rows:
        chord=harmony_at(shared,row['tick'])
        converted=row['arrangement_reason']=='prefer_arpeggio_without_strong_block_evidence'
        copies=[dict(row)]
        horizon=min(row['duration_ticks'],chord['end_tick']-row['tick'],bar-row['tick']%bar)
        # 分解和弦优先：新增仅在改写的伴奏攻击间填入八分音；不覆盖器乐主线或越过和声/小节。
        if converted and row['melody'] is None and horizon>=480:
            for offset in range(240,horizon,240):
                copies.append({**row,'tick':row['tick']+offset,'bass_anchor':False,
                               'onset_origin':'arranged_subdivision','melody':None})
            for index,item in enumerate(copies):
                item['duration_ticks']=min(240,horizon-index*240)
        for item in copies:
            if converted and item['melody'] is None:
                intervals=CHORD_TYPES[chord['quality']]
                sequence=[(chord['root_pc']+i)%12 for i in intervals[1:]]+[chord['root_pc']]
                step=steps.get(chord['id'],0);pc=sequence[step%len(sequence)];steps[chord['id']]=step+1
                item['arpeggio_step']=step;item['arpeggio_pitch_class']=pc
                choices=[p for p in range(48,85) if p%12==pc]
                item['target_midi']=min(choices,key=lambda p:abs(p-row['target_midi']))
            planned.append(item)
    # 尾段原声局部补证：修改人工分解填充同样不得伸入尾响，新起音与此前持续音分别处理。
    # return sorted(planned,key=lambda x:x['tick'])
    if terminal:
        planned=[row for row in planned if mapping.quarters_to_seconds(origin+row['tick']/PPQ)<terminal['start_seconds']-1e-6]
    return sorted(planned,key=lambda x:x['tick'])


# 和弦弹唱与伴奏编配：新增独奏段动态弦品求解，声部超额按已确认优先级省略。
def solve_guitar_group(requests, capo, previous_position=1):
    working=sorted(requests,key=lambda x:ROLE_PRIORITY[x['role']])
    omitted=[]
    while working:
        options=[]
        for row in working:
            choices=[]
            for shift in (0,-12,12):
                pitch=row['pitch_midi']+shift
                for string in range(1,7):
                    fret=pitch-TUNING[string]-capo
                    if 0<=fret<=20:
                        value=abs((fret if fret else previous_position)-previous_position)*.15+abs(shift)*.7
                        choices.append((value,string,fret,pitch,shift))
            choices.sort()
            options.append(choices[:8])
        best=None
        for choices in product(*options):
            if len({v[1] for v in choices})!=len(choices):
                continue
            frets={v[1]:v[2] for v in choices}; grip=grip_info(frets)
            if grip is None:
                continue
            assigned=[{**r,'string':c[1],'fret':c[2],'pitch_midi':c[3],
                       'finger':grip['fingers'].get(c[1],0),'octave_adjustment':c[4]} for r,c in zip(working,choices)]
            lead=[r['pitch_midi'] for r in assigned if r['role']=='instrumental_melody']
            bass=[r['pitch_midi'] for r in assigned if r['role']=='bass']
            if lead and lead[0] != max(r['pitch_midi'] for r in assigned):
                continue
            if bass and bass[0] != min(r['pitch_midi'] for r in assigned):
                continue
            value=sum(c[0] for c in choices)+.1*grip['span']+.07*grip['position']
            if best is None or value<best[0]:
                best=(value,assigned,grip)
        if best:
            return best[1],omitted,best[2]
        omitted.append(working.pop())
    raise ValueError('器乐旋律没有可行吉他位置。')


# 和弦弹唱与伴奏编配：新增同弦占用/持续音与换把处理，每次提前释音保存理由。
def resolve_guitar_sustain(notes, clock, adjustments):
    ordered=sorted(notes,key=lambda x:(x['start_tick'],ROLE_PRIORITY[x['role']]))
    groups={}
    for note in ordered: groups.setdefault(note['start_tick'],[]).append(note)
    active=[]
    for tick,current in groups.items():
        active=[n for n in active if n['end_tick']>tick]
        strings={n['string'] for n in current}
        for old in active[:]:
            if old['string'] in strings:
                old['end_tick']=tick;active.remove(old)
                adjustments.append({'type':'release_previous_same_string','note_id':old['id'],'at_tick':tick})
        while active and grip_info({n['string']:n['fret'] for n in active+current}) is None:
            old=max(active,key=lambda n:(ROLE_PRIORITY[n['role']],-n['start_tick']))
            old['end_tick']=tick;active.remove(old)
            adjustments.append({'type':'release_for_left_hand_reposition','note_id':old['id'],'at_tick':tick})
        if grip_info({n['string']:n['fret'] for n in current}) is None:
            raise ValueError('吉他同一攻击组无法用一只手按住。')
        active+=current
    return [n for n in ordered if n['end_tick']>n['start_tick']]


# 和弦弹唱与伴奏编配：新增全曲攻击手位动态规划，跨度正确之外硬约束换把时间。
def optimize_guitar_positions(notes, capo, clock, adjustments, max_rate=24):
    grouped={}
    for note in notes:grouped.setdefault(note['start_tick'],[]).append(note)
    groups=sorted(grouped.items());states=[]
    for tick,values in groups:
        essential=[];occupied_pcs=set()
        for note in sorted(values,key=lambda n:ROLE_PRIORITY[n['role']]):
            pc=note['pitch_midi']%12
            if note['role']=='harmony' and pc in occupied_pcs:
                adjustments.append({'type':'omit_doubled_inner_voice_for_position_path','note_id':note['id'],'at_tick':tick})
                continue
            occupied_pcs.add(pc);essential.append(note)
        choices=[]
        for note in essential:
            options=[]
            shifts=(0,) if note['role']=='instrumental_melody' else (0,-12,12)
            for shift in shifts:
                pitch=note['pitch_midi']+shift
                for string in range(1,7):
                    fret=pitch-TUNING[string]-capo
                    if 0<=fret<=20:
                        options.append((string,fret,pitch,shift))
            choices.append(options)
        possible={}
        for values0 in product(*choices):
            if len({v[0] for v in values0})!=len(values0):continue
            grip=grip_info({v[0]:v[1] for v in values0})
            if not grip:continue
            assigned=[{**n,'string':v[0],'fret':v[1],'pitch_midi':v[2],
                       'finger':grip['fingers'].get(v[0],0),'path_octave_adjustment':v[3]} for n,v in zip(essential,values0)]
            lead=[n['pitch_midi'] for n in assigned if n['role']=='instrumental_melody']
            bass=[n['pitch_midi'] for n in assigned if n['role']=='bass']
            if lead and lead[0]!=max(n['pitch_midi'] for n in assigned):continue
            if bass and bass[0]!=min(n['pitch_midi'] for n in assigned):continue
            positive=[v[1] for v in values0 if v[1]>0]
            allowed=range(max(1,max(positive)-5),min(positive)+1) if positive else range(1,21)
            cost=.45*sum(abs(v[3])/12 for v in values0)+.006*sum(v[1] for v in values0)+.025*grip['finger_count']+.035*bool(grip['barre'])
            for position in allowed:
                row={'position':position,'notes':assigned,'cost':cost+.003*position}
                if position not in possible or row['cost']<possible[position]['cost']:
                    possible[position]=row
        if not possible:
            raise ValueError(f'保留器乐主线后没有吉他手位：tick={tick}')
        states.append(sorted(possible.values(),key=lambda n:n['position']))
    costs,traces=[],[]
    for index,items in enumerate(states):
        if not index:
            costs.append([x['cost'] for x in items]);traces.append([-1]*len(items));continue
        seconds=clock.seconds(groups[index][0])-clock.seconds(groups[index-1][0])
        maximum=max(1,math.floor(max_rate*seconds+1e-6))
        values,trace=[],[]
        for item in items:
            options=[costs[-1][i]+.12*abs(item['position']-old['position']) if
                     abs(item['position']-old['position'])<=maximum else math.inf for i,old in enumerate(states[index-1])]
            winner=min(range(len(options)),key=options.__getitem__)
            values.append(options[winner]+item['cost']);trace.append(winner)
        if not any(math.isfinite(v) for v in values):
            raise ValueError(f'吉他换把超过{max_rate}品/秒：tick={groups[index][0]}，需人工简化器乐候选。')
        costs.append(values);traces.append(trace)
    if not states:return [],[]
    winner=min(range(len(costs[-1])),key=costs[-1].__getitem__);chosen=[winner]
    for trace in traces[:0:-1]:chosen.append(trace[chosen[-1]])
    chosen.reverse();result=[];positions=[];active=[]
    for (tick,_),items,index in zip(groups,states,chosen):
        state=items[index];position=state['position']
        active=[n for n in active if n['end_tick']>tick]
        for old in active[:]:
            if old['fret'] and not position<=old['fret']<=position+5:
                old['end_tick']=tick;active.remove(old)
                adjustments.append({'type':'release_sustain_for_timed_position_path','note_id':old['id'],'at_tick':tick})
        current=[dict(n) for n in state['notes']]
        for note in current:
            note['hand_position']=position
            if note['path_octave_adjustment']:
                adjustments.append({'type':'octave_redistribution_for_timed_guitar_position','note_id':note['id'],
                                    'semitones':note['path_octave_adjustment'],'at_tick':tick})
        result+=current;active+=current;positions.append({'tick':tick,'position':position})
    return resolve_guitar_sustain(result,clock,adjustments),positions


# 和弦弹唱与伴奏编配：新增吉他实际伴奏与器乐段；输出只含六线谱和人声简谱。
def arrange_guitar(shared, vocal, capo=None):
    clock=SongClock(vocal)
    if capo is None:
        alternatives=[]
        for candidate in range(5):
            try:
                shapes,cost=choose_shapes(shared['harmony'],candidate)
                alternatives.append((cost+.15*candidate,candidate,shapes))
            except ValueError:
                continue
        if not alternatives:
            raise ValueError('标准调弦无法完成当前和声，需人工修改编配。')
        _,capo,shapes=min(alternatives,key=lambda x:x[0])
    else:
        shapes,_=choose_shapes(shared['harmony'],capo)
    notes,adjustments,charts,events=[],[],{},[]
    previous_position=1
    for group in performance_groups(shared):
        chord=harmony_at(shared,group['tick']); shape=shapes[chord['id']]
        # 分解和弦优先：新增保存织体取舍，细分攻击留在音符来源，不重复记为原曲证据。
        if group['arrangement_reason']=='prefer_arpeggio_without_strong_block_evidence' and group['onset_origin']=='observed':
            adjustments.append({'type':'prefer_arpeggio_over_unconfirmed_block','at_tick':group['tick'],
                                'observed_kind':group['observed_kind'],'texture_measure':group['texture_measure']})
        tick=group['tick']; duration=group['duration_ticks']
        shape_notes=[{'pitch_midi':pitch,'string':int(string),'fret':shape['frets'][string],
                      'finger':shape['fingers'].get(int(string),0),'role':'harmony','octave_adjustment':0}
                     for string,pitch in shape['pitches'].items()]
        bass=min(shape_notes,key=lambda x:x['pitch_midi'])
        selected=[]
        if group['kind'] in ('block','strum'):
            selected=[dict(n) for n in shape_notes]
        elif group['kind']=='arpeggio':
            target=group['target_midi']
            upper=[n for n in shape_notes if n['string']<=4]
            # 分解和弦优先：新增让改写后的分解保留选定性质音，不能只取最接近却遗漏三度/加音的上弦。
            if group.get('arpeggio_pitch_class') is not None:
                upper=[n for n in shape_notes if n['pitch_midi']%12==group['arpeggio_pitch_class']] or upper
            selected=[dict(min(upper or shape_notes,key=lambda x:abs(x['pitch_midi']-target)))]
        if group['bass_anchor']:
            selected=[n for n in selected if n['string']!=bass['string']]
            selected.append({**bass,'role':'bass'})
        if group['melody']:
            melody=group['melody']
            requests=[{'pitch_midi':melody['pitch_midi'],'role':'instrumental_melody',
                       'source_melody_id':melody['id']}]
            if group['bass_anchor']:
                requests.append({'pitch_midi':bass['pitch_midi'],'role':'bass'})
            if group['kind'] in ('block','strum'):
                inner=[n for n in shape_notes if n['pitch_midi']!=bass['pitch_midi'] and n['pitch_midi']%12!=melody['pitch_midi']%12]
                requests.extend({'pitch_midi':n['pitch_midi'],'role':'harmony'} for n in inner[:2])
            selected,omitted,grip=solve_guitar_group(requests,capo,previous_position)
            for row in omitted:
                adjustments.append({'type':'omit_secondary_voice_for_guitar_grip','at_tick':tick,**row})
            previous_position=grip['position'] or previous_position
        elif selected:
            grip=grip_info({n['string']:n['fret'] for n in selected})
            previous_position=grip['position'] or previous_position
        chart_id='shape_'+str(len(charts)+1)
        signature=tuple(shape['frets'].get(str(s),-1) for s in range(6,0,-1))
        if signature not in charts:
            # 和弦弹唱与伴奏编配：新增指型和实际和弦双标签，capo转换是减去夹品。
            shape_key=clock.key(tick)
            # 和弦弹唱与伴奏编配：修改，原夹一品/降调专用显示改为任意调通用换算。
            # if shape_key['fifths']<0 and capo==1:
            #     from score_export import key_definition
            #     shape_key=key_definition('C:major')
            from score_export import key_definition
            # 新曲慢拍生成与转调标签同步：修改仅指型调号标签的等音拼写，原式保留；实际音高、夹位和和弦不改。
            # shape_key=key_definition(pc_name(shape_key['tonic_pc']-capo,shape_key)+':major')
            shape_key=capo_shape_key(shape_key,capo)
            charts[signature]={'id':chart_id,'sounding_name':chord['name'],
                               'shape_name':chord_name(chord['root_pc']-capo,chord['quality'],chord['bass_pc']-capo,shape_key),
                               'capo':capo,**shape}
        chart=charts[signature]
        for value in selected:
            role=value['role']; hold=duration
            if role=='bass': hold=max(duration,480)
            if role=='instrumental_melody': hold=group['melody']['duration_ticks']
            end=min(shared['statistics']['total_ticks'],tick+hold,chord['end_tick'] if role!='instrumental_melody' else tick+hold)
            row={**value,'id':f'guitar_note_{len(notes)+1:05}','start_tick':tick,'end_tick':max(tick+120,end),
                 'velocity':92 if role=='instrumental_melody' else 78 if role=='bass' else 64,
                 'chord_id':chord['id'],'source_attack_seconds':group['source_seconds'],
                 # 分解和弦优先：修改，来源扩展包含原观察与编配细分，原尾字段保留。
                 # 'source':group['source'],'section':group['section']}
                 'source':group['source'],'section':group['section'],**attack_provenance(group)}
            notes.append(row)
            if value.get('octave_adjustment'):
                adjustments.append({'type':'octave_reduction_for_guitar','note_id':row['id'],
                                    'semitones':value['octave_adjustment'],'reason':'instrument_range_or_single_hand_grip'})
        events.append({'start_tick':tick,'kind':group['kind'],'chord_id':chord['id'],'chart_id':chart['id'],
                       'shape_name':chart['shape_name'],'sounding_name':chord['name'],'source':group['source'],
                       'stroke':('down' if (tick//120)%4<2 else 'up') if group['kind']=='strum' else None,
                       # 分解和弦优先：修改，攻击事件同样保存偏好决策，原结尾保留。
                       # 'stroke_status':'arrangement_choice_original_direction_unresolved' if group['kind']=='strum' else None})
                       'stroke_status':'arrangement_choice_original_direction_unresolved' if group['kind']=='strum' else None,
                       **attack_provenance(group)})
    notes=resolve_guitar_sustain(notes,clock,adjustments)
    # 和弦弹唱与伴奏编配：新增攻击间的硬时序规划，原声部取舍记录仍保留。
    notes,hand_positions=optimize_guitar_positions(notes,capo,clock,adjustments)
    return {'instrument':'guitar','format':'jianpu_and_six_string_tab_only',
            'configuration':{'standard_tuning_midi':TUNING,'capo_fret':capo,'maximum_fretted_span':5,
                             # 分解和弦优先：新增持久偏好，后续歌曲沿用，实际柱式例外可查共享证据。
                             'texture_policy':dict(POLICY),
                             'maximum_fret':20,'maximum_left_hand_fingers':4,
                             'maximum_position_change_frets_per_second':24,
                             'performer':'experienced_single_player','fixed_capo_entire_song':True},
            'notes':notes,'attack_events':events,'chord_charts':list(charts.values()),'adjustments':adjustments,
            'hand_positions':hand_positions,
            'pedal':[], 'quality_status':'automatic_arrangement_draft_requires_listening',
            'fingering_status':'suggested_from_grip_search_not_human_certified'}


# 和弦弹唱与伴奏编配：新增钢琴单手紧凑配音；八度为12半音，性质音与旋律优先。
def compact_voicing(pcs, anchor=72, melody=None, span=12):
    # 和弦弹唱与伴奏编配：修改，均值锚点为小数，离散键盘搜索必须转为整数，原式保留。
    # pcs=sorted(set(pcs)); target=melody if melody is not None else anchor
    pcs=sorted(set(pcs)); target=int(round(melody if melody is not None else anchor))
    choices=[]
    for pc in pcs:
        pitches=[p for p in range(max(48,target-18),min(88,target+8)+1) if p%12==pc and (melody is None or p<=melody)]
        choices.append(pitches)
    best=None
    for values in product(*choices):
        rows=sorted(set(values)|({melody} if melody is not None else set()))
        if len(rows)>5 or max(rows)-min(rows)>span:
            continue
        cost=sum(abs(p-anchor) for p in rows)*.05 + (max(rows)-min(rows))*.04
        if melody is not None: cost+=.02*(melody-min(rows))
        if best is None or cost<best[0]:best=(cost,rows)
    if best:
        return best[1]
    raise ValueError('单手八度内无法保留当前声部，需分配另一只手。')


# 和弦弹唱与伴奏编配：新增键盘同时按音、同音重起与持续音释指，踏板继续由独立事件表达。
def resolve_piano_sustain(notes, adjustments):
    groups={}
    for n in sorted(notes,key=lambda x:(x['start_tick'],x['hand'])):
        groups.setdefault(n['start_tick'],[]).append(n)
    active=[]
    for tick,current in groups.items():
        active=[n for n in active if n['end_tick']>tick]
        for hand in ('left','right'):
            new=[n for n in current if n['hand']==hand]
            old=[n for n in active if n['hand']==hand]
            pitches={n['pitch_midi'] for n in new}
            for n in old[:]:
                if n['pitch_midi'] in pitches:
                    n['end_tick']=tick;active.remove(n);old.remove(n)
            combined=old+new
            while old and (max(n['pitch_midi'] for n in combined)-min(n['pitch_midi'] for n in combined)>12 or
                           len({n['pitch_midi'] for n in combined})>5):
                release=max(old,key=lambda x:(ROLE_PRIORITY[x['role']],-x['start_tick']))
                release['end_tick']=tick;active.remove(release);old.remove(release)
                adjustments.append({'type':'release_key_for_hand_reposition_use_pedal_if_marked',
                                    'note_id':release['id'],'hand':hand,'at_tick':tick})
                combined=old+new
            if new and (max(n['pitch_midi'] for n in new)-min(n['pitch_midi'] for n in new)>12 or len(pitches)>5):
                raise ValueError('钢琴当前攻击组超出八度或五个手指。')
        active+=current
    return [n for n in notes if n['end_tick']>n['start_tick']]


# 和弦弹唱与伴奏编配：新增钢琴两手真实攻击间的位置时序，分解换位也受速度约束。
def piano_hand_positions(notes,clock,max_rate=96):
    paths={}
    for hand in ('left','right'):
        values=[n for n in notes if n['hand']==hand];ticks=sorted({n['start_tick'] for n in values})
        states=[];costs=[];traces=[]
        for index,tick in enumerate(ticks):
            active=[n['pitch_midi'] for n in values if n['start_tick']<=tick<n['end_tick']]
            options=list(range(max(21,max(active)-12),min(96,min(active))+1))
            if not options:raise ValueError('钢琴持续按键没有单手八度手位。')
            states.append(options)
            if not index:costs.append([.001*position for position in options]);traces.append([-1]*len(options));continue
            seconds=clock.seconds(tick)-clock.seconds(ticks[index-1]);maximum=math.floor(max_rate*seconds+1e-6)
            row,trace=[],[]
            for position in options:
                candidates=[costs[-1][i]+.06*abs(position-old) if abs(position-old)<=maximum else math.inf for i,old in enumerate(states[index-1])]
                best=min(range(len(candidates)),key=candidates.__getitem__);row.append(candidates[best]);trace.append(best)
            if not any(math.isfinite(c) for c in row):raise ValueError(f'钢琴{hand}换位超速，tick={tick}。')
            costs.append(row);traces.append(trace)
        if not ticks:paths[hand]=[];continue
        best=min(range(len(costs[-1])),key=costs[-1].__getitem__);selected=[best]
        for trace in traces[:0:-1]:selected.append(trace[selected[-1]])
        selected.reverse();paths[hand]=[{'tick':tick,'position':states[i][choice]} for i,(tick,choice) in enumerate(zip(ticks,selected))]
    return paths


# 极美通用双乐器制谱：新增失败时的通用左手内声八度搜索，同时保护持续音与相邻攻击换位。
# 极美通用双乐器制谱：修改，原仅左手签名保留；两手内声分别规划，固定低音和器乐旋律均不改。
# def plan_piano_left_inner_register(notes, clock, max_rate=96):
# 乐句钢琴持续配音通用修复：修改签名，原入口保留；器乐保护音可以明确锁定，旧调用行为不变。
# def plan_piano_inner_register(notes, clock, hand, max_rate=96):
# 乐句钢琴持续配音通用修复：修改扩展可选新低音范围，原签名保留；默认与原低音仍固定。
# def plan_piano_inner_register(notes, clock, hand, max_rate=96, locked_ids=()):
def plan_piano_inner_register(notes, clock, hand, max_rate=96, locked_ids=(), generated_bass_ids=()):
    from copy import deepcopy
    # 极美通用双乐器制谱：修改，原左手过滤保留；当前手独立搜索，另一只手完整保持。
    # values = sorted((n for n in notes if n['hand'] == 'left'), key=lambda n: (n['start_tick'], n['id']))
    values = sorted((n for n in notes if n['hand'] == hand), key=lambda n: (n['start_tick'], n['id']))
    lower, upper = (21, 59) if hand == 'left' else (48, 108)
    # 乐句钢琴持续配音通用修复：新增保护ID集合，不改已经固定的器乐旋律／和声及音长。
    locked_ids = set(locked_ids)
    # 乐句钢琴持续配音通用修复：新增仅针对本次新编低音的同音级八度候选，器乐原低音不动。
    generated_bass_ids = set(generated_bass_ids)
    ticks = sorted({n['start_tick'] for n in values})
    by_id = {n['id']: n for n in values}
    layers = []
    previous = {((), None): (0., None, ())}
    for index, tick in enumerate(ticks):
        new = [n for n in values if n['start_tick'] == tick]
        # 极美通用双乐器制谱：修改，原单八度候选保留；允许同音级多八度，持续低音冲突时仍不可删音。
        # choices = [([n['pitch_midi']] if n['role'] != 'harmony' else
        #             [p for p in (n['pitch_midi'], n['pitch_midi'] - 12, n['pitch_midi'] + 12)
        #              if 21 <= p < 60]) for n in new]
        # 极美通用双乐器制谱：修改，原左手候选保留；右手内声也可选择邻近八度，原旋律不降。
        # choices = [([n['pitch_midi']] if n['role'] != 'harmony' else
        #             [n['pitch_midi']] + [p for p in range(21, 60)
        #              if p % 12 == n['pitch_midi'] % 12 and p != n['pitch_midi']]) for n in new]
        # 乐句钢琴持续配音通用修复：修改可移八度的范围，原式保留；固定器乐内声也必须保持。
        # choices = [([n['pitch_midi']] if n['role'] != 'harmony' else
        # 乐句钢琴持续配音通用修复：修改只允许和弦内声的条件，原式保留；新编低音可在当前手音域内选八度。
        # choices = [([n['pitch_midi']] if n['role'] != 'harmony' or n['id'] in locked_ids else
        choices = [([n['pitch_midi']] if n['id'] in locked_ids or not (n['role'] == 'harmony' or
                    n['role'] == 'bass' and n['id'] in generated_bass_ids) else
                    [n['pitch_midi']] + [p for p in range(lower, upper + 1)
                     if p % 12 == n['pitch_midi'] % 12 and p != n['pitch_midi']]) for n in new]
        maximum = (math.floor(max_rate * (clock.seconds(tick) - clock.seconds(ticks[index - 1])) + 1e-6)
                   if index else None)
        current = {}
        for previous_key, (previous_cost, _, _) in previous.items():
            held, old_position = previous_key
            active = tuple((identity, pitch) for identity, pitch in held if by_id[identity]['end_tick'] > tick)
            for pitches in product(*choices):
                assignments = tuple((n['id'], p) for n, p in zip(new, pitches))
                combined = tuple(sorted(active + assignments))
                sounding = [p for _, p in combined]
                if len(set(sounding)) != len(sounding) or len(sounding) > 5 or max(sounding) - min(sounding) > 12:
                    continue
                positions = range(max(21, max(sounding) - 12), min(96, min(sounding)) + 1)
                register_cost = sum(abs(p - n['pitch_midi']) / 12 for n, p in zip(new, pitches))
                for position in positions:
                    if old_position is not None and abs(position - old_position) > maximum:
                        continue
                    cost = previous_cost + register_cost + (.06 * abs(position - old_position)
                           if old_position is not None else .001 * position)
                    key = (combined, position)
                    if key not in current or cost < current[key][0]:
                        current[key] = (cost, previous_key, assignments)
        if not current:
            # 极美通用双乐器制谱：修改，原错误文案保留；无解时明确当前手，继续严格停止。
            # raise ValueError(f'钢琴左手内声八度规划无合法路径，tick={tick}；低音、持续音和换位门限保持。')
            raise ValueError(f'钢琴{hand}内声八度规划无合法路径，tick={tick}；低音、旋律、持续音和换位门限保持。')
        layers.append(current)
        previous = current
    adjusted = deepcopy(notes)
    changes = []
    if not layers:
        return adjusted, changes
    selected = {}
    key = min(layers[-1], key=lambda k: layers[-1][k][0])
    for layer in reversed(layers):
        _, predecessor, assignments = layer[key]
        selected.update(assignments)
        key = predecessor
    for note in adjusted:
        pitch = selected.get(note['id'], note['pitch_midi'])
        if pitch != note['pitch_midi']:
            # 极美通用双乐器制谱：修改，原仅左手记录保留；两手八度变化均逐音留账。
            # changes.append({'type': 'compact_piano_left_inner_voice_for_harmonic_transition',
            # 乐句钢琴持续配音通用修复：修改变化类别，原行保留；新低音八度和内声调整分别留账。
            # changes.append({'type': 'compact_piano_inner_voice_for_harmonic_transition', 'hand': hand,
            changes.append({'type': 'compact_piano_generated_bass_for_phrase_transition' if note['role'] == 'bass' else 'compact_piano_inner_voice_for_harmonic_transition', 'hand': hand,
                            'note_id': note['id'], 'at_tick': note['start_tick'],
                            'old_pitch_midi': note['pitch_midi'], 'pitch_midi': pitch,
                            'octave_shift': pitch - note['pitch_midi']})
            note['pitch_midi'] = pitch
    return adjusted, changes


# 极美通用双乐器制谱：新增左手专用兼容入口，复用同一约束搜索。
def plan_piano_left_inner_register(notes, clock, max_rate=96):
    return plan_piano_inner_register(notes, clock, 'left', max_rate)


# 和弦弹唱与伴奏编配：新增两手各自的原声配音，演唱段不完整复制人声主旋律。
def arrange_piano(shared, vocal):
    notes,adjustments,events=[],[],[]
    anchor=70
    for group in performance_groups(shared):
        chord=harmony_at(shared,group['tick']); tick=group['tick']; duration=group['duration_ticks']
        # 分解和弦优先：新增钢琴与吉他共享织体偏好，但各自独立配音。
        if group['arrangement_reason']=='prefer_arpeggio_without_strong_block_evidence' and group['onset_origin']=='observed':
            adjustments.append({'type':'prefer_arpeggio_over_unconfirmed_block','at_tick':tick,
                                'observed_kind':group['observed_kind'],'texture_measure':group['texture_measure']})
        bass=36+chord['bass_pc']
        if bass<32:bass+=12
        melody=group['melody']['pitch_midi'] if group['melody'] else None
        shape_pcs=[pc for pc in chord['pitch_classes'] if pc!=(chord['root_pc']+7)%12 or len(chord['pitch_classes'])<=3]
        selected=[]
        if group['kind'] in ('block','strum'):
            voiced=compact_voicing(shape_pcs,anchor,melody)
            selected=[{'pitch_midi':p,'hand':'right','role':'instrumental_melody' if p==melody else 'harmony'} for p in voiced]
            anchor=statistics.mean(voiced)
        elif melody is not None:
            selected=[{'pitch_midi':melody,'hand':'right','role':'instrumental_melody'}]
            anchor=melody
        else:
            target=group['target_midi']
            options=[p for p in range(52,85) if p%12 in chord['pitch_classes']]
            # 分解和弦优先：新增严格按已规划的和弦音依次弹出，保留三度/七音/挂留等性质。
            if group.get('arpeggio_pitch_class') is not None:
                options=[p for p in options if p%12==group['arpeggio_pitch_class']]
            pitch=min(options,key=lambda p:abs(p-target)+.015*abs(p-anchor))
            # 渴首次吉他编配：修改，旧按中央C分手却不参照低音音区，会令左手在低音与高内声间快速往返。
            # selected=[{'pitch_midi':pitch,'hand':'left' if pitch<60 else 'right','role':'harmony'}]
            # 渴首次吉他编配：新增通用左手内声八度安排，只调整和弦内声部，保留真实低音、旋律和起音。
            if pitch < 60 and pitch > bass + 12:
                previous_pitch = pitch
                while pitch > bass + 12:
                    pitch -= 12
                adjustments.append({'type':'compact_piano_left_inner_voice_register','at_tick':tick,
                                    'old_pitch_midi':previous_pitch,'pitch_midi':pitch,
                                    'octave_shift':pitch-previous_pitch,'bass_pitch_midi':bass})
            selected=[{'pitch_midi':pitch,'hand':'left' if pitch<60 else 'right','role':'harmony'}]
            if pitch>=60:anchor=pitch
        if group['bass_anchor'] or group['kind'] in ('block','strum'):
            selected.append({'pitch_midi':bass,'hand':'left','role':'bass'})
        # 和弦弹唱与伴奏编配：新增宽幅低部交给右手或移八度，不能用踏板掩盖键盘按音跨度。
        left=[n for n in selected if n['hand']=='left']
        if left and max(n['pitch_midi'] for n in left)-min(n['pitch_midi'] for n in left)>12:
            for n in left:
                if n['role']!='bass':
                    n['hand']='right'
                    adjustments.append({'type':'redistribute_inner_voice_to_right_hand','at_tick':tick,'pitch_midi':n['pitch_midi']})
        by_hand={hand:sorted((n for n in selected if n['hand']==hand),key=lambda n:n['pitch_midi']) for hand in ('left','right')}
        for hand,values in by_hand.items():
            finger_sets={1:[3],2:[1,5],3:[1,3,5],4:[1,2,3,5],5:[1,2,3,4,5]}
            fingering=finger_sets[len(values)] if values else []
            if hand=='left':fingering=list(reversed(fingering))
            for value,finger in zip(values,fingering):
                hold=duration
                if value['role']=='bass':hold=max(duration,480)
                if value['role']=='instrumental_melody':hold=group['melody']['duration_ticks']
                end=min(shared['statistics']['total_ticks'],tick+hold,
                        chord['end_tick'] if value['role']!='instrumental_melody' else tick+hold)
                notes.append({**value,'id':f'piano_note_{len(notes)+1:05}','start_tick':tick,'end_tick':max(tick+120,end),
                              'finger':finger,'velocity':96 if value['role']=='instrumental_melody' else 77 if value['role']=='bass' else 65,
                              'chord_id':chord['id'],'source':group['source'],'source_attack_seconds':group['source_seconds'],
                              'source_melody_id':group['melody']['id'] if value['role']=='instrumental_melody' else None,
                              # 分解和弦优先：修改，原section结尾保留，新增攻击选择来源。
                              # 'section':group['section']})
                              'section':group['section'],**attack_provenance(group)})
        # 分解和弦优先：修改，原事件保留，增加观察/偏好/原曲与细分来源。
        # events.append({'start_tick':tick,'kind':group['kind'],'chord_id':chord['id'],'source':group['source']})
        events.append({'start_tick':tick,'kind':group['kind'],'chord_id':chord['id'],'source':group['source'],
                       **attack_provenance(group)})
    notes=resolve_piano_sustain(notes,adjustments)
    # 极美通用双乐器制谱：修改，原只接受逐和弦内声的入口保留；仅左手换位失败时联合搜索八度。
    # hand_positions=piano_hand_positions(notes,SongClock(vocal))
    try:
        hand_positions=piano_hand_positions(notes,SongClock(vocal))
    except ValueError as error:
        # 极美通用双乐器制谱：修改，原只处理左手失败保留；两手失败同样联合考虑相邻配音。
        # if not str(error).startswith('钢琴left换位超速，'):
        if not str(error).startswith(('钢琴left换位超速，', '钢琴right换位超速，')):
            raise
        # 极美通用双乐器制谱：修改，原仅左手调用保留；逐手完整持续音搜索后再用原检验器复核。
        # notes, register_changes = plan_piano_left_inner_register(notes, SongClock(vocal))
        # adjustments.extend(register_changes)
        for hand in ('left', 'right'):
            notes, register_changes = plan_piano_inner_register(notes, SongClock(vocal), hand)
            adjustments.extend(register_changes)
        hand_positions = piano_hand_positions(notes, SongClock(vocal))
    pedal=[]
    for chord in shared['harmony']:
        if chord['name']=='N.C.':continue
        if any(chord['start_tick']<=n['start_tick']<chord['end_tick'] for n in notes):
            pedal.extend([{'tick':chord['start_tick'],'value':127,'chord_id':chord['id']},
                          {'tick':chord['end_tick'],'value':0,'chord_id':chord['id']}])
    return {'instrument':'piano','format':'vocal_jianpu_reference_and_two_hand_grand_staff',
            'configuration':{'maximum_simultaneous_semitones_per_hand':12,'maximum_keys_per_hand':5,
                             # 分解和弦优先：新增钢琴持久偏好，不改变双手范围与实际发声。
                             'texture_policy':dict(POLICY),
                             'note_range':[21,108],'performer':'experienced_single_player',
                             'pedal_policy':'release_at_each_harmonic_change','sequential_arpeggios_may_reposition':True,
                             'maximum_hand_position_semitones_per_second':96},
            'notes':notes,'attack_events':events,'pedal':pedal,'adjustments':adjustments,'hand_positions':hand_positions,
            'quality_status':'automatic_arrangement_draft_requires_listening',
            'fingering_status':'suggested_per_attack_group_not_human_certified'}


# 和弦弹唱与伴奏编配：新增全曲独立演奏校验，涵盖持续音，而不只检查每次新攻击。
# 结构稳定伴奏与人声合播：新增动态夹位发声与物理手位核查。
def validate_playability(arrangement, clock):
    from guitar_capo import capo_at, fret_at
    errors=[];notes=arrangement['notes']; checkpoints=sorted({x[t] for x in notes for t in ('start_tick','end_tick')})
    # 和弦弹唱与伴奏编配：修改，补充钢琴时序指标，旧初始化保留。
    # ids=set();max_span=0;max_count=0;max_movement=0.;previous_position=None;previous_tick=None
    ids=set();max_span=0;max_count=0;max_movement=0.;piano_movement=0.;previous_position=None;previous_tick=None
    for note in notes:
        if note['id'] in ids:errors.append('duplicate_note_id:'+note['id'])
        ids.add(note['id'])
        if note['end_tick']<=note['start_tick']:errors.append('nonpositive_duration:'+note['id'])
        if note['start_tick']<0 or note['end_tick']>clock.total_ticks:errors.append('outside_score:'+note['id'])
        if arrangement['instrument']=='guitar':
            config=arrangement['configuration'];string=note['string'];fret=note['fret']
            # 结构稳定伴奏与人声合播：修改，原代码注释保留。
            # if TUNING[string]+config['capo_fret']+fret!=note['pitch_midi']:errors.append('tab_sound_mismatch:'+note['id'])
            if TUNING[string]+capo_at(arrangement,note['start_tick'])+fret!=note['pitch_midi']:errors.append('tab_sound_mismatch:'+note['id'])
            if not 0<=fret<=config['maximum_fret']:errors.append('fret_out_of_range:'+note['id'])
        elif not 21<=note['pitch_midi']<=108:errors.append('keyboard_out_of_range:'+note['id'])
    for tick in checkpoints:
        active=[n for n in notes if n['start_tick']<=tick<n['end_tick']]
        if not active:continue
        if arrangement['instrument']=='guitar':
            if len({n['string'] for n in active})!=len(active):errors.append('same_string_overlap:'+str(tick))
            # 结构稳定伴奏与人声合播：修改，原代码注释保留。
            # info=grip_info({n['string']:n['fret'] for n in active})
            info=grip_info({n['string']:fret_at(n,arrangement,tick) for n in active})
            if info is None:errors.append('guitar_hand_span_or_fingers:'+str(tick));continue
            max_span=max(max_span,info['span']);max_count=max(max_count,info['finger_count'])
            # 和弦弹唱与伴奏编配：修改，最低在按品变化不等于手实际移动，原估算保留。
            # if info['position'] and previous_position is not None and tick!=previous_tick:
            #     seconds=clock.seconds(tick)-clock.seconds(previous_tick)
            #     rate=abs(info['position']-previous_position)/max(.01,seconds)
            #     max_movement=max(max_movement,rate)
            # if info['position']:
            #     previous_position,previous_tick=info['position'],tick
            active_position=next((p['position'] for p in reversed(arrangement.get('hand_positions',[])) if p['tick']<=tick),None)
            # 结构稳定伴奏与人声合播：修改，原代码注释保留。
            # if active_position is not None and any(n['fret'] and not active_position<=n['fret']<=active_position+5 for n in active):
            if active_position is not None and any(fret_at(n,arrangement,tick)>0 and not active_position<=fret_at(n,arrangement,tick)<=active_position+5 for n in active):
                errors.append('sustained_note_outside_planned_hand_position:'+str(tick))
        else:
            for hand in ('left','right'):
                held=[n for n in active if n['hand']==hand]
                if not held:continue
                span=max(n['pitch_midi'] for n in held)-min(n['pitch_midi'] for n in held)
                count=len({n['pitch_midi'] for n in held})
                max_span=max(max_span,span);max_count=max(max_count,count)
                if span>12 or count>5:errors.append('piano_hand_span_or_fingers:'+hand+':'+str(tick))
                if len(held)!=count:errors.append('same_key_rearticulation_overlap:'+hand+':'+str(tick))
                position=next((x['position'] for x in reversed(arrangement.get('hand_positions',{}).get(hand,[])) if x['tick']<=tick),None)
                if position is not None and any(not position<=n['pitch_midi']<=position+12 for n in held):
                    errors.append('piano_sustain_outside_planned_hand_position:'+hand+':'+str(tick))
    review=[]
    # 和弦弹唱与伴奏编配：修改，旧只标待复核，改为对规划手位进行真实时间检查。
    # if arrangement['instrument']=='guitar' and max_movement>24:
    #     review.append('rapid_position_changes_require_player_review')
    if arrangement['instrument']=='guitar':
        positions=arrangement.get('hand_positions',[])
        for left,right in zip(positions,positions[1:]):
            seconds=clock.seconds(right['tick'])-clock.seconds(left['tick'])
            # 结构稳定伴奏与人声合播：修改，原代码注释保留。
            # rate=abs(right['position']-left['position'])/max(.01,seconds)
            # max_movement
            rate=abs(right['position']+capo_at(arrangement,right['tick'])-left['position']-capo_at(arrangement,left['tick']))/max(.01,seconds)
            max_movement=max(max_movement,rate)
            if rate>arrangement['configuration'].get('maximum_position_change_frets_per_second',24)+1e-6:
                errors.append('guitar_position_change_too_fast:'+str(right['tick']))
    else:
        for hand,path in arrangement.get('hand_positions',{}).items():
            for left,right in zip(path,path[1:]):
                seconds=clock.seconds(right['tick'])-clock.seconds(left['tick']);rate=abs(right['position']-left['position'])/max(.01,seconds)
                piano_movement=max(piano_movement,rate)
                if rate>arrangement.get('configuration',{}).get('maximum_hand_position_semitones_per_second',96)+1e-6:
                    errors.append('piano_position_change_too_fast:'+hand+':'+str(right['tick']))
    return {'valid':not errors,'errors':errors,'review_flags':review,'sounding_note_count':len(notes),
            'maximum_simultaneous_span':max_span,'maximum_fingers_or_keys':max_count,
            'maximum_guitar_position_movement_frets_per_second':max_movement,
            'maximum_piano_hand_position_semitones_per_second':piano_movement,
            'checks':['absolute_sound_pitch','held_notes','same_string_or_key_collision','single_hand_span','finger_count','score_boundaries'],
            'manual_fingering_and_musical_quality':'not_certified_requires_listening_and_player_review'}


# 渴首次吉他编配：新增可持久化乐器范围，历史未指定时继续默认吉他和钢琴。
def requested_instruments(shared):
    selected = shared['input_binding'].get('requested_instruments', ['guitar', 'piano'])
    if selected not in (['guitar'], ['guitar', 'piano']):
        raise ValueError('乐器选择必须为仅吉他或吉他与钢琴，不能默默忽略未知乐器。')
    return tuple(selected)


# 渴首次吉他编配：新增所有重建阶段共用的选择器，仍调用原编配器和实际可演奏性验证。
# 保音持续按弦与整句八度衔接：修改新生成可显式走整句统一配音，历史调用与既有工程保持原入口。
# def arrange_requested(shared, vocal, capo=None):
# 歌词自动加载与伴随声部音区保护：修改通用编配选择器接收同源伴随音区参考，不改变旧调用。
# def arrange_requested(shared, vocal, capo=None, phrase_register=False):
def arrange_requested(shared, vocal, capo=None, phrase_register=False, companion_reference=None):
    instruments = requested_instruments(shared)
    # 保音持续按弦与整句八度衔接：修改新初始配音先整体规划，原逐音入口留作历史重放。
    # result = {'guitar': arrange_guitar(shared, vocal, capo)}
    if phrase_register:
        from guitar_phrase_voicing import arrange_phrase_guitar
        # 歌词自动加载与伴随声部音区保护：修改首次旋律和既有伴随声部在同一次持续音求解中衔接。
        # guitar = arrange_phrase_guitar(shared, vocal, capo)
        # 歌词自动加载与伴随声部音区保护：修改无参考的旧调用保持参数形态，旧重放和旧调用方不受影响。
        # guitar = arrange_phrase_guitar(shared, vocal, capo, companion_reference=companion_reference)
        guitar = (arrange_phrase_guitar(shared, vocal, capo) if companion_reference is None else
                  arrange_phrase_guitar(shared, vocal, capo, companion_reference=companion_reference))
    else:
        guitar = arrange_guitar(shared, vocal, capo)
    result = {'guitar': guitar}
    if 'piano' in instruments:
        result['piano'] = arrange_piano(shared, vocal)
    return result
