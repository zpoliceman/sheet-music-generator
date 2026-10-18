"""演唱段稳定右手型：整段选简单型，原和声配音，保护器乐及已认可时间轴。"""
# 演唱段稳定右手型：新增通用段落规划；根音弦变化不换型，不重识别人声／和弦。
from collections import Counter
from copy import deepcopy
from itertools import product
import hashlib
import json

from accompaniment_analysis import SongClock, chord_name
from accompaniment_arrange import TUNING, grip_info
from guitar_capo import capo_at
from guitar_readable_arrangement import guitar_shared_view, measure_timeline, _merge_diagrams, SourceEvidence

# 演唱段稳定右手型：删除未执行的最短段落字段；短桥段仍可沿既有结构使用固定型。
# POLICY = {'version': 1, 'name': 'simple_section_vocal_patterns', 'minimum_section_bars': 4,
POLICY = {'version': 1, 'name': 'simple_section_vocal_patterns',
          'maximum_attacks_per_full_bar': 8, 'maximum_main_patterns_per_section': 1,
          'minimum_note_ticks': 120, 'preferred_maximum_fret': 4, 'maximum_fret': 12,
          'preserve_instrumental_notes_exactly': True, 'change_harmony_analysis': False,
          'root_string_changes_are_not_pattern_changes': True,
          'mixed_instrumental_boundary_bars': 'preserve_and_explain',
          'source_silence_bars': 'preserve_and_explain', 'whole_song_recognition': False}
PATTERNS = {
    'arp_4_4_sparse': {'step': 480, 'tokens': ['B', '3', '2', '1']},
    'arp_4_4_up': {'step': 240, 'tokens': ['B', '3', '2', '1', 'B', '3', '2', '1']},
    'arp_4_4_roll': {'step': 240, 'tokens': ['B', '3', '2', '3', '1', '3', '2', '3']}}


def fingerprint(value):
    # 演唱段稳定右手型：新增真实材料摘要，验收不能沿用旧结果。
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':'), allow_nan=True).encode('utf-8')).hexdigest()


def ordinary(note):
    # 演唱段稳定右手型：新增明确编辑范围；器乐旋律即使在人声区也不能改。
    return note.get('section') == 'vocal' and note.get('role') in ('bass', 'harmony') and not note.get('source_melody_id')


def section_blocks(project):
    # 演唱段稳定右手型：新增沿既有演唱活动分组，不把歌词每一句当作新段落。
    notes = project['arrangements']['guitar']['notes']
    rows = measure_timeline(project['accepted_vocal_project'])
    blocks = []
    for row in rows:
        if not any(ordinary(n) and row['start_tick'] <= n['start_tick'] < row['end_tick'] for n in notes):
            continue
        if blocks and blocks[-1]['measures'][-1] + 1 == row['number']:
            blocks[-1]['measures'].append(row['number']); blocks[-1]['end_tick'] = row['end_tick']
        else:
            blocks.append({'id': f'vocal_section_{len(blocks)+1:03}', 'measures': [row['number']],
                           'start_tick': row['start_tick'], 'end_tick': row['end_tick']})
    return blocks


def simple_library_candidates(patterns):
    # 演唱段稳定右手型：新增初次编配共用候选筛选，不再逐句挑混合型或十六分密集型。
    return [p for p in patterns if p['id'] in PATTERNS]


def constrain_section_choices(shared, phrases, details, selected):
    # 演唱段稳定右手型：新增初次联合编配段级硬一致，句级声学小差异不触发换型。
    parent = {p['id']: p['id'] for p in phrases}
    def find(key):
        while parent[key] != key:
            parent[key] = parent[parent[key]]; key = parent[key]
        return key
    def union(a, b):
        a, b = find(a), find(b)
        if a != b: parent[b] = a
    for section in shared.get('sections', []):
        if section.get('kind') != 'vocal': continue
        members = [p['id'] for p in phrases if p['start_tick'] < section['end_tick'] and p['end_tick'] > section['start_tick']]
        for identity in members[1:]: union(members[0], identity)
    for family in shared.get('phrase_harmony_plan', {}).get('families', []):
        members = [m['phrase_id'] for m in family['members'] if m['phrase_id'] in parent]
        for identity in members[1:]: union(members[0], identity)
    groups = {}
    for p in phrases: groups.setdefault(find(p['id']), []).append(p['id'])
    for members in groups.values():
        winner = min(range(len(details[members[0]])), key=lambda j: sum(details[i][j]['score'] for i in members))
        for identity in members: selected[identity] = winner
    return groups


def _editable_bars(project, blocks):
    # 演唱段稳定右手型：新增混合器乐边界及跨界延音保护，绝不为模板裁短已认可器乐。
    notes = project['arrangements']['guitar']['notes']; timeline = measure_timeline(project['accepted_vocal_project'])
    selected, exceptions = set(), []
    # 演唱段稳定右手型：新增已绑定原秒数的静默保护，不把真实停顿填成完整分解。
    evidence=SourceEvidence(project,{})
    for block in blocks:
        for number in block['measures']:
            row = timeline[number-1]; a, b = row['start_tick'], row['end_tick']
            fixed = [n for n in notes if not ordinary(n) and n['start_tick'] < b and n['end_tick'] > a]
            local = [n for n in notes if ordinary(n) and a <= n['start_tick'] < b]
            reason = ('instrumental_boundary' if fixed else 'partial_measure' if b-a != 1920 or row.get('meter') != [4,4]
                      else 'preserve_source_silence' if not local else None)
            # 首拍与首尾局部补证：新增跨真实尾响的小节作为明确边界保留，不用完整唱段模板把余音重新拨满。
            from first_generation_tail import pattern_attack_allowed
            if reason is None and not pattern_attack_allowed(project['shared_analysis'],b-1):
                reason='source_terminal_decay_boundary'
            if reason is None:
                observations=[evidence.at(t,min(b,t+480)) for t in range(a,b,480)]
                peak=max((r.get('accompaniment_rms',0.) for r in observations),default=0.)
                for t,r in zip(range(a,b,480),observations):
                    no_old_activity=not any(n['start_tick']<min(b,t+480) and n['end_tick']>t for n in local)
                    if r.get('available') and no_old_activity and r.get('accompaniment_rms',0.)<max(.001,peak*.025):
                        reason='preserve_confirmed_source_break';break
            if reason:
                exceptions.append({'measure': number, 'reason': reason, 'protected_note_ids': [n['id'] for n in fixed]})
            else: selected.add(number)
    # 演唱段稳定右手型：新增双向传播跨界持续音，保留的尾音不能撞到新型。
    changed = True
    while changed:
        changed = False
        for note in notes:
            if not ordinary(note): continue
            covered = [m['number'] for m in timeline if note['start_tick'] < m['end_tick'] and note['end_tick'] > m['start_tick']]
            if any(n not in selected for n in covered):
                for n in covered:
                    if n in selected:
                        selected.remove(n); exceptions.append({'measure': n, 'reason': 'preserve_cross_boundary_sustain', 'protected_note_ids': [note['id']]}); changed=True
    return selected, exceptions


def _pattern_choice(project, block, features):
    # 演唱段稳定右手型：新增整段原伴奏攻击密度选4／8个均匀音；不拟合逐小节碎节奏。
    clock = SongClock(project['accepted_vocal_project']); feature = (features or {}).get('accompaniment')
    counts = []
    for m in measure_timeline(project['accepted_vocal_project']):
        if m['number'] not in block['measures']: continue
        if feature is not None:
            a, b = clock.seconds(m['start_tick']), clock.seconds(m['end_tick'])
            counts.append(sum(a <= float(t['seconds']) + float(feature.source.get('offset_seconds',0.)) < b for t in feature.attacks))
    typical = sorted(counts)[len(counts)//2] if counts else None
    # 演唱段稳定右手型：修改只数到四拍脉冲就稀疏化的旧判据；默认规整八分，极稀疏来源才选四分。
    # choice = 'arp_4_4_sparse' if typical is not None and typical <= 4 else 'arp_4_4_up'
    choice = 'arp_4_4_sparse' if typical is not None and typical <= 2 else 'arp_4_4_up'
    return choice, {'source': 'bound_accompaniment_attack_density' if counts else 'conservative_uniform_eighth_default',
                    'median_source_attacks_per_bar': typical, 'observed_bars': len(counts), 'per_bar_style_selection': False}


def _shape_candidates(chord, capo, target_bass):
    # 演唱段稳定右手型：新增固定3／2／1高弦的简单配音，五音可省、性质音必须保留，根低音仍按原和弦。
    pcs = set(chord['pitch_classes']) | {int(chord['bass_pc'])}
    essential = set(chord['pitch_classes']) - {(int(chord['root_pc'])+7)%12}
    candidates=[]
    for bass in (6,5,4):
        strings=(bass,3,2,1)
        frets = [[f for f in range(13) if (TUNING[s]+capo+f)%12 in ({int(chord['bass_pc'])} if s==bass else pcs)] for s in strings]
        for values in product(*frets):
            held=dict(zip(strings,values)); positive=[f for f in values if f>0]
            if positive and max(positive)-min(positive)>5: continue
            pitches={s:TUNING[s]+capo+f for s,f in held.items()}
            if pitches[bass] > min(pitches.values()) or not essential <= {p%12 for p in pitches.values()}:continue
            info=grip_info(held)
            if info is None:continue
            above=sum(f>4 for f in values)
            cost=(above, sum(max(0,f-4) for f in values), abs(pitches[bass]-target_bass), info['finger_count'], sum(values))
            shape={**info,'frets':{str(s):f for s,f in held.items()},'position':max(1,min(positive,default=1)),
                   'capo':capo,'sounding_name':chord['name'],
                   # 演唱段稳定右手型：修改无显式调性旧工程的名称后备，不影响实际和弦或音高。
                   # 'shape_name':chord_name((chord['root_pc']-capo)%12,chord['quality'],(chord['bass_pc']-capo)%12,chord.get('key')),
                   'shape_name':chord_name((chord['root_pc']-capo)%12,chord['quality'],(chord['bass_pc']-capo)%12,chord.get('key') or {}),
                   'root_pc':chord['root_pc'],'quality':chord['quality'],'bass_pc':chord['bass_pc'],
                   'simplified':False,'omitted_pitch_classes':sorted(pcs-{p%12 for p in pitches.values()}),
                   'source':'same_existing_harmony_simple_four_string_voicing'}
            candidates.append((cost,shape,bass))
    return sorted(candidates,key=lambda x:x[0])[:24]


def _subtract_ranges(rows, intervals):
    # 演唱段稳定右手型：新增仅替换演唱窗口图式，保留所有器乐区间的旧显示和实际持握。
    result=[]
    for row in rows:
        pieces=[(row['start_tick'],row['end_tick'])]
        for left,right in intervals:
            pieces=[q for a,b in pieces for q in ([(a,min(b,left))] if a<left else [])+([(max(a,right),b)] if b>right else []) if q[1]>q[0]]
        result.extend({**deepcopy(row),'start_tick':a,'end_tick':b} for a,b in pieces)
    return result


def _voicing_handover(guitar,vocal,harmony,target_bass,budget=96):
    # 演唱段稳定右手型：新增完整持握前瞻与有界局部配音；只动新生成音，右手格和全部器乐不变。
    from guitar_grip_policy import grip_position_path
    check=grip_position_path(guitar,vocal);attempts=0;edits=[];seen=set();current=guitar
    while not check['valid'] and attempts<budget:
        tick=check.get('tick')
        if tick is None:break
        nearby=[d for d in current['fingering_diagrams'] if d.get('stable_vocal_shape_key') and
                d['start_tick']<=tick and d['end_tick']>=tick-1920]
        # 演唱段稳定右手型：新增优先为前一组B321准备下一副按法，而非改后续原器乐或整段换节奏。
        nearby.sort(key=lambda d:(d['start_tick']>=tick,abs(d['end_tick']-tick)))
        progress=None
        for chart in nearby[:3]:
            chord=next((h for h in harmony if h['id']==chart.get('chord_id')),None)
            if chord is None:continue
            if chart['end_tick']<=tick:
                a,b=max(chart['start_tick'],chart['end_tick']-960),chart['end_tick']
            else:a,b=chart['start_tick'],min(chart['end_tick'],chart['start_tick']+960)
            for _,shape,bass in _shape_candidates(chord,chart['capo'],target_bass):
                if shape['frets']==chart['frets']:continue
                signature=(a,b,tuple(sorted(shape['frets'].items())))
                if signature in seen:continue
                seen.add(signature);attempts+=1
                trial={**current,'notes':deepcopy(current['notes']),
                       'fingering_diagrams':deepcopy(current['fingering_diagrams'])}
                replacements=[]
                for d in trial['fingering_diagrams']:
                    if d['id']!=chart['id']:
                        replacements.append(d);continue
                    if d['start_tick']<a:replacements.append({**deepcopy(d),'end_tick':a})
                    replacements.append({**deepcopy(d),**deepcopy(shape),'id':d['id']+'_handover',
                        'start_tick':a,'end_tick':b,'reason':'section_pattern_boundary_voicing_handover'})
                    if b<d['end_tick']:replacements.append({**deepcopy(d),'id':d['id']+'_after_handover','start_tick':b})
                trial['fingering_diagrams']=sorted(replacements,key=lambda d:(d['start_tick'],d['end_tick']))
                for note in trial['notes']:
                    if not note.get('stable_vocal_pattern_id') or not a<=note['start_tick']<b:continue
                    string=bass if note['right_hand_token']=='B' else int(note['right_hand_token'])
                    fret=shape['frets'][str(string)]
                    note.update(string=string,fret=fret,pitch_midi=TUNING[string]+shape['capo']+fret,
                                finger=shape['fingers'].get(string,shape['fingers'].get(str(string),0)),
                                hand_position=shape['position'])
                path=grip_position_path(trial,vocal)
                edit={'start_tick':a,'end_tick':b,'before_frets':chart['frets'],'after_frets':shape['frets'],
                      'reason':check['reason'],'right_hand_pattern_and_times_unchanged':True}
                if path['valid']:
                    trial['notes'].sort(key=lambda n:(n['start_tick'],n['string'],n['id']))
                    return trial,path,{'attempts':attempts,'budget':budget,'local_voicing_edits':edits+[edit]}
                if path.get('tick',-1)>tick and progress is None:progress=(trial,path,edit)
                if attempts>=budget:break
            if attempts>=budget:break
        if progress is None:break
        current,check,edit=progress;edits.append(edit)
    return current,check,{'attempts':attempts,'budget':budget,'local_voicing_edits':edits}


def arrange_section_patterns(project, features=None):
    # 演唱段稳定右手型：新增唯一重编核心；明确只授权演唱伴奏，段内型固定、器乐逐字段保持。
    revised=deepcopy(project); original=project['arrangements']['guitar']; guitar=revised['arrangements']['guitar']
    blocks=section_blocks(project); selected,exceptions=_editable_bars(project,blocks)
    if not blocks or not selected:raise ValueError('没有可独立整理的完整演唱小节，保留原工程')
    timeline=measure_timeline(project['accepted_vocal_project']); harmony=guitar_shared_view(project)['harmony']
    clock=SongClock(project['accepted_vocal_project']); intervals=[(timeline[n-1]['start_tick'],timeline[n-1]['end_tick']) for n in sorted(selected)]
    removed=[n for n in original['notes'] if ordinary(n) and any(a<=n['start_tick']<b for a,b in intervals)]
    removed_ids={n['id'] for n in removed}; notes=[deepcopy(n) for n in original['notes'] if n['id'] not in removed_ids]
    # 慢拍单位与两曲最小修订：新增二次规整不能复用被替换的旧音符身份；源ID保持独立便于完整保护验收。
    occupied_ids = {n['id'] for n in original['notes']}
    generation_id = fingerprint(original['notes'])[:16]
    diagrams=_subtract_ranges(original.get('fingering_diagrams',[]),intervals)
    regions=_subtract_ranges(original.get('notation_regions',[]),intervals)
    cache={}; plans=[]; events=[]; basses=[n['pitch_midi'] for n in removed if n.get('role')=='bass']; target_bass=sorted(basses)[len(basses)//2] if basses else 48
    for block in blocks:
        pattern_id,observation=_pattern_choice(project,block,features); pattern=PATTERNS[pattern_id]
        plan={**block,'pattern_id':pattern_id,'step_ticks':pattern['step'],'tokens':pattern['tokens'],
              'arranged_measures':[n for n in block['measures'] if n in selected], 'selection_evidence':observation}
        plans.append(plan)
        for number in plan['arranged_measures']:
            bar=timeline[number-1]; a,b=bar['start_tick'],bar['end_tick']; step=pattern['step']
            for tick in range(a,b,step):
                chord=next((h for h in harmony if h['start_tick']<=tick<h['end_tick'] and h.get('name')!='N.C.'),None)
                if chord is None:raise ValueError('演唱段固定型缺少已确认和声，不猜和弦：'+str(number))
                if tick+step>chord['end_tick']:raise ValueError('固定型跨过非整拍和弦边界，须先核对和声')
                capo=capo_at(guitar,tick); key=(int(chord['root_pc']),chord['quality'],int(chord['bass_pc']),capo)
                if key not in cache:
                    candidates=_shape_candidates(chord,capo,target_bass)
                    if not candidates:raise ValueError('固定高三弦配音无12品以内完整性质音方案：'+chord['name'])
                    cache[key]=candidates[0][1:]
                shape,bass=cache[key]; shape=deepcopy(shape); shape.update(sounding_name=chord['name'])
                token=pattern['tokens'][(tick-a)//step]
                adaptation=None
                # 演唱段稳定右手型：删除逐次和弦边界强换低音的旧适配，仍按固定拨弦型；高弦直接使用当时和弦。
                # if tick==chord['start_tick'] and token!='B': token='B';adaptation='existing_harmony_change_bass_on_existing_slot'
                string=bass if token=='B' else int(token); fret=shape['frets'][str(string)]
                identity=f'section_pattern_note_{number:04}_{(tick-a)//step:02}'
                # 慢拍单位与两曲最小修订：新增仅身份冲突时采用来源摘要命名，首次生成与历史重放的身份保持原样。
                if identity in occupied_ids:
                    identity = f'section_pattern_{generation_id}_note_{number:04}_{(tick-a)//step:02}'
                if identity in occupied_ids:
                    raise ValueError('稳定右手新旧音符身份冲突，不能把旧音冒充新配音')
                note={'id':identity,'pitch_midi':TUNING[string]+capo+fret,'string':string,'fret':fret,
                      'finger':shape['fingers'].get(string,shape['fingers'].get(str(string),0)),
                      'hand_position':shape['position'],'role':'bass' if token=='B' else 'harmony','section':'vocal',
                      'start_tick':tick,'end_tick':tick+step,'velocity':76 if token=='B' else 64,
                      'chord_id':chord['id'],'source':'existing_harmony_section_stable_arpeggio',
                      'source_attack_seconds':clock.seconds(tick),'texture_measure':number,
                      'right_hand_duration_ticks':step,'right_hand_duration_source':'section_uniform_pattern',
                      'stable_vocal_pattern_id':pattern_id,'stable_vocal_section_id':block['id'],
                      'right_hand_token':token,'pattern_adaptation':adaptation}
                notes.append(note);events.append({'start_tick':tick,'kind':'arpeggio','chord_id':chord['id'],
                    'note_ids':[identity],'right_hand_duration_ticks':step,'right_hand_duration_source':'section_uniform_pattern'})
                if not diagrams or diagrams[-1].get('stable_vocal_shape_key')!=list(key) or diagrams[-1]['end_tick']!=tick:
                    diagrams.append({**shape,'id':f'section_pattern_grip_{len(diagrams)+1:04}', 'start_tick':tick,'end_tick':tick+step,
                                     'chord_id':chord['id'],'stable_vocal_shape_key':list(key),'reason':'section_stable_actual_grip'})
                else:diagrams[-1]['end_tick']=tick+step
            regions.append({'id':f'section_pattern_region_{number:04}','start_tick':a,'end_tick':b,
                            'mode':'chord_grip','section':'vocal','reason':'section_stable_actual_pattern'})
    # 演唱段稳定右手型：新增旧全曲认证移入来源账本；保留原源工程作重放证据，不能伪改其音符摘要。
    # 演唱段稳定右手型：修改旧指法／模板认证的失效清理；原证据完整留账，不把旧图式表当新配音。
    # stale=('instrumental_register','instrumental_expression','instrumental_source_backbone','right_hand_patterns','regular_rhythm',
    #        'phrase_harmony_performance','structure_stability','guitar_readability_revision')
    stale=('instrumental_register','instrumental_expression','instrumental_source_backbone','right_hand_patterns','regular_rhythm',
           'phrase_harmony_performance','structure_stability','guitar_readability_revision','readability_ancestor_evidence',
           'capo_refingering','instrumental_register_preparations','grip_fingerings','chord_charts','readable_reuse')
    prior={key:guitar.pop(key) for key in stale if key in guitar}
    guitar['section_pattern_provenance']={'prior_certifications':prior,'source_notes_sha256':fingerprint(original['notes']),
                                           'scope':'original_project_replay_and_exact_protected_note_comparison'}
    kept_events=[deepcopy(e) for e in original.get('attack_events',[]) if not any(a<=e['start_tick']<b for a,b in intervals)]
    guitar.update(notes=sorted(notes,key=lambda n:(n['start_tick'],n['string'],n['id'])),
                  attack_events=sorted(kept_events+events,key=lambda e:e['start_tick']),
                  readable_harmony=deepcopy(harmony),fingering_diagrams=_merge_diagrams(diagrams),
                  notation_regions=sorted(regions,key=lambda r:(r['start_tick'],r['end_tick'])))
    guitar['configuration']['stable_vocal_patterns']=deepcopy(POLICY)
    guitar['section_patterns']={'policy':deepcopy(POLICY),'sections':plans,'exceptions':exceptions,
                                'arranged_measures':sorted(selected),'removed_vocal_note_ids':sorted(removed_ids)}
    # 演唱段稳定右手型：新增只继承自然乐句边界，真正共用范围由实际新音符重新规划。
    # 全曲目固定右手预览：修改缺省空列表遮蔽共享自然乐句的问题；原构造保留，不能丢失已有长段回跳边界。
    # guitar['readable_reuse']={'phrases':deepcopy(original.get('readable_reuse',{}).get('phrases',[])),
    inherited_phrases=original.get('readable_reuse',{}).get('phrases')
    if inherited_phrases is None:
        inherited_phrases=revised['shared_analysis'].get('phrase_harmony_plan',{}).get('phrases',[])
    guitar['readable_reuse']={'phrases':deepcopy(inherited_phrases),
        'shared_bars':[],'rhythm_plans':deepcopy(plans),'existing_source_backed_performance_preserved':False,
        'vocal_rhythm_rearranged_with_explicit_authorization':True}
    # 演唱段稳定右手型：修改贪心单个指型后才停止的旧式，联合实际持续声部检验局部衔接方案。
    # from guitar_grip_policy import grip_position_path
    # path=grip_position_path(guitar,project['accepted_vocal_project'])
    guitar,path,handover=_voicing_handover(guitar,project['accepted_vocal_project'],harmony,target_bass)
    revised['arrangements']['guitar']=guitar
    guitar['section_patterns']['voicing_handover']=handover
    if not path['valid']:raise ValueError('稳定右手型持握／换把失败：'+str(path))
    guitar['hand_positions']=path['positions']; guitar['grip_hand_positions']=deepcopy(path['positions'])
    # 演唱段稳定右手型：新增当前结果准确状态；旧调整记录仍保留为历史。
    guitar['quality_status']='section_stable_vocal_arrangement_requires_listening'
    guitar['fingering_status']='complete_grip_geometry_checked_requires_player_review'
    guitar['grip_position_rate']=path.get('max_frets_per_second',0.)
    guitar.setdefault('adjustments',[]).append({'type':'section_stable_vocal_patterns',
        'replaced_vocal_notes':len(removed),'new_vocal_notes':len(events),'protected_notes':len(original['notes'])-len(removed)})
    revised['vocal_pattern_revision']={'version':1,'policy':deepcopy(POLICY),'normal_entry_replacement_allowed':False}
    # 演唱段稳定右手型：新增旧整曲通过记录归档；新工程在实际验收前不能携带旧全曲通过摘要。
    revised['vocal_pattern_revision']['prior_project_certifications']={key:revised.pop(key) for key in
        ('guitar_register_revision','guitar_readability_acceptance','guitar_source_bass_acceptance','guitar_score_layout') if key in revised}
    revised['guitar_readability_revision']={'version':2,'normal_entry_replacement_allowed':False,'previous_music_acceptance_invalidated':True}
    revised['music_acceptance']={**deepcopy(project.get('music_acceptance',{})),'status':'needs_review','publication_allowed':False,
                               'scope':'stable_vocal_guitar_patterns_preserve_approved_clock_and_instrumentals'}
    audit={'sections':plans,'exceptions':exceptions,'arranged_measures':sorted(selected),'old_vocal_notes_replaced':len(removed),
           'new_vocal_notes':len(events),'protected_notes':len(original['notes'])-len(removed),
           # 演唱段稳定右手型：修改报告纳入真实衔接搜索；旧单一路径报告式保留。
           # 'source_harmony_changed':False,'hand_path':{k:v for k,v in path.items() if k!='positions'}}
           'source_harmony_changed':False,'hand_path':{k:v for k,v in path.items() if k!='positions'},'voicing_handover':handover}
    return revised,audit


def assess_section_patterns(project, baseline=None):
    # 演唱段稳定右手型：新增实际时值／拨弦次序验收，拒绝只写稳定策略却保留杂乱音符。
    # 4/4可选右手与实时谱面试听：新增显式动作独立重建验收；未选沿用原均匀单音判据。
    from guitar_pattern_selection import has_selection, assess_selection
    if has_selection(project):
        return assess_selection(project, baseline)
    guitar=project['arrangements']['guitar']; plan=guitar.get('section_patterns')
    active=bool(project.get('vocal_pattern_revision') or guitar['configuration'].get('stable_vocal_patterns') or
                any(n.get('stable_vocal_pattern_id') for n in guitar['notes']))
    if not active:return {'valid':True,'status':'not_requested_for_preserved_legacy_music'}
    errors=[]; stats=[];timeline=measure_timeline(project['accepted_vocal_project']);harmony=guitar_shared_view(project)['harmony']
    # 演唱段稳定右手型：新增普通导出也必须读取真实绑定原工程，不能把验收基线藏在可改元数据里。
    if baseline is None:
        from pathlib import Path
        source=project.get('vocal_pattern_source',{})
        path=Path(source.get('project','__missing_pattern_source__'))
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=source.get('project_sha256'):
            errors.append('stable_pattern_source_missing_or_changed')
        else:baseline=json.loads(path.read_text(encoding='utf-8-sig'))
    if not plan or plan.get('policy')!=POLICY or guitar['configuration'].get('stable_vocal_patterns')!=POLICY:
        return {'valid':False,'errors':['stable_pattern_plan_missing_or_obsolete']}
    for section in plan['sections']:
        pattern=PATTERNS.get(section['pattern_id'])
        if pattern is None:errors.append('unapproved_complex_main_pattern');continue
        signatures=[]
        for number in section['arranged_measures']:
            row=timeline[number-1];a,b=row['start_tick'],row['end_tick'];step=pattern['step']
            notes=sorted((n for n in guitar['notes'] if a<=n['start_tick']<b),key=lambda n:n['start_tick'])
            expected=list(range(a,b,step));starts=[n['start_tick'] for n in notes]
            if starts!=expected:errors.append('nonuniform_section_attacks:'+str(number))
            for note in notes:
                if note['end_tick']-note['start_tick']!=step or note.get('right_hand_duration_ticks')!=step:
                    errors.append('mixed_section_note_values:'+str(number))
                if note.get('stable_vocal_pattern_id')!=section['pattern_id'] or note.get('stable_vocal_section_id')!=section['id']:
                    errors.append('section_pattern_identity_changed:'+str(number))
                slot=(note['start_tick']-a)//step; token=pattern['tokens'][slot%len(pattern['tokens'])]
                chord=next((h for h in harmony if h['start_tick']<=note['start_tick']<h['end_tick']),None)
                if chord is None:errors.append('stable_pattern_harmony_missing');continue
                # 演唱段稳定右手型：修改只在固定低音槽核对根音，不能默许换和弦时另改拨弦次序。
                # root=token=='B' or note['start_tick']==chord['start_tick']
                root=token=='B'
                if root:
                    if note['string'] not in (4,5,6) or note['pitch_midi']%12!=chord['bass_pc']:
                        errors.append('incorrect_section_bass:'+str(number))
                elif note['string']!=int(token):errors.append('unstable_upper_string_order:'+str(number))
                if note['pitch_midi']%12 not in set(chord['pitch_classes'])|{chord['bass_pc']}:
                    errors.append('section_note_outside_existing_harmony:'+str(number))
            signatures.append(tuple((n['start_tick']-a,n['end_tick']-n['start_tick']) for n in notes))
        stats.append({'section':section['id'],'pattern':section['pattern_id'],'measures':section['arranged_measures'],
                      'actual_rhythm_signatures':len(set(signatures)),'note_values_ticks':sorted({d for sig in signatures for _,d in sig})})
        if len(set(signatures))>1:errors.append('section_has_multiple_rhythm_skeletons:'+section['id'])
    if baseline is not None:
        before=baseline['arrangements']['guitar'];selected=set(plan['arranged_measures'])
        original_blocks=section_blocks(baseline)
        if [(p['id'],p['measures']) for p in plan['sections']]!=[(p['id'],p['measures']) for p in original_blocks]:
            errors.append('section_boundaries_changed_to_hide_pattern_switches')
        expected,exceptions=_editable_bars(baseline,original_blocks)
        if selected!=expected or plan['exceptions']!=exceptions:errors.append('editable_scope_changed_without_source_evidence')
        def selected_note(n):
            return ordinary(n) and any(timeline[m-1]['start_tick']<=n['start_tick']<timeline[m-1]['end_tick'] for m in selected)
        fixed={n['id']:n for n in before['notes'] if not selected_note(n)}; actual={n['id']:n for n in guitar['notes']}
        changed=[identity for identity,note in fixed.items() if actual.get(identity)!=note]
        if changed:errors.append('protected_instrumental_or_boundary_note_changed')
        removed={n['id'] for n in before['notes'] if selected_note(n)}
        if removed & set(actual):errors.append('old_scattered_vocal_notes_not_replaced')
        extras=[n['id'] for n in guitar['notes'] if n['id'] not in fixed and not n.get('stable_vocal_pattern_id')]
        if extras:errors.append('untracked_added_notes_outside_pattern')
        # 演唱段稳定右手型：新增新型标记也不能授权在器乐或未改小节外加音。
        if any(n['id'] not in fixed and not selected_note(n) for n in guitar['notes']):
            errors.append('new_pattern_note_outside_authorized_vocal_bar')
        if project['accepted_vocal_project']!=baseline['accepted_vocal_project']:errors.append('approved_voice_or_clock_changed')
        if project['shared_analysis']!=baseline['shared_analysis']:errors.append('approved_source_harmony_changed')
        if guitar_shared_view(project)['harmony']!=guitar_shared_view(baseline)['harmony']:errors.append('approved_guitar_harmony_changed')
        if project['arrangements'].get('piano')!=baseline['arrangements'].get('piano'):errors.append('protected_piano_changed')
    return {'valid':not errors,'status':'passed' if not errors else 'failed','errors':sorted(set(errors)),
            'scope':'actual_vocal_guitar_rhythm_and_string_order_not_whole_song_listening_certification',
            'sections':stats,'arranged_measures':plan['arranged_measures'],'boundary_exceptions':plan['exceptions']}


def pattern_guide_html(project):
    # 4/4可选右手与实时谱面试听：新增实际选择记忆表，旧固定型及旧分组显示保持。
    from guitar_pattern_selection import has_selection
    if has_selection(project):
        from guitar_pattern_selection_ui import selection_guide
        return selection_guide(project)
    # 局部两拍过渡听辨修订：新增记忆表的边界小节按新分组注明衔接，不重编原固定型。
    if project.get('bar_boundary_revision'):
        from reviewed_bar_boundaries import display_pattern_project
        project=display_pattern_project(project)
    # 演唱段稳定右手型：新增演奏者能直接使用的段落记忆表；不把源码、摘要等实现细节放到谱面。
    import html
    plan=project['arrangements']['guitar'].get('section_patterns')
    if not plan:return ''
    rows=[]
    for section in plan['sections']:
        bars=section['arranged_measures']
        if not bars:continue
        ranges=[]
        for number in bars:
            if ranges and ranges[-1][-1]+1==number:ranges[-1].append(number)
            else:ranges.append([number])
        caption='、'.join(str(r[0]) if len(r)==1 else str(r[0])+'–'+str(r[-1]) for r in ranges)
        pattern=PATTERNS[section['pattern_id']]; tokens=' '.join(pattern['tokens'])
        rows.append('<tr><td>第'+caption+'小节</td><td><strong>'+html.escape(tokens)+'</strong></td><td>'+
                    ('每格八分音符' if pattern['step']==240 else '每格四分音符')+'</td></tr>')
    exceptions='、'.join(str(r['measure']) for r in sorted(plan['exceptions'],key=lambda r:r['measure']))
    return ('<section class="vocal-pattern-guide" style="margin:18px 0;padding:12px;border:1px solid #b8cbd0;border-radius:8px">'
            '<h2 style="font-size:18px">演唱伴奏 · 固定右手型</h2><p>B＝当前低音弦（4／5／6弦），其余数字为弦号。低音换弦时沿用同一节奏；高弦按当时和弦图弹奏。</p>'
            '<table style="border-spacing:16px 5px"><thead><tr><th>范围</th><th>拨弦顺序</th><th>音值</th></tr></thead><tbody>'+''.join(rows)+'</tbody></table>'
            # 演唱段稳定右手型：新增沿用器乐黑点的演奏含义，旧原值／连奏并未改变。
            # +('<p>第'+exceptions+'小节保留原器乐衔接或停顿，按原谱演奏。</p>' if exceptions else '')+'</section>')
            +('<p>第'+exceptions+'小节保留原器乐衔接或停顿，按原谱演奏。</p>' if exceptions else '')
            +('<p>器乐主旋律上方黑点表示旋律突出，保持原时值与连贯演奏。</p>'
              if any(n.get('melody_accent') for n in project['arrangements']['guitar']['notes']) else '')+'</section>')
