"""结构稳定伴奏与人声合播：实际拍格、重复段和四小节谱面的独立核查。"""
# 结构稳定伴奏与人声合播：新增以音符/可见字形为准的验证，拒绝只改标签。
from collections import Counter, defaultdict
# 小节划分与拍速层级纠错：新增循环范围与真实四分拍换算。
import math
import xml.etree.ElementTree as ET
from guitar_pattern_grid import pattern_schedule, pattern_duration
from guitar_capo import capo_at

NS='{http://www.w3.org/2000/svg}'
MUSIC_FIELDS=('id','pitch_midi','start_tick','end_tick','velocity','role','source_melody_id','source','chord_id')


def validate_structured_rhythm(shared,guitar):
    # 器乐背景休止与旋律突出：新增原节奏保护不删不放宽；器乐背景与力度变化必须有实际来源重放。
    if guitar.get('instrumental_expression'):
        from guitar_instrumental_expression import validate_expression_rhythm
        return validate_expression_rhythm(shared,guitar,validate_structured_rhythm)
    from guitar_right_hand_patterns import library
    # 小节划分与拍速层级纠错：修改，原固定拍单位保留；按复核后的拍单位解释旧循环，不改拨弦音序。
    # patterns={p['id']:p for p in library()['patterns']};bar=shared['statistics']['bar_ticks']
    from accompaniment_rebar import notation_pattern
    patterns={p['id']:notation_pattern(guitar,p) for p in library()['patterns']};bar=shared['statistics']['bar_ticks']
    errors=[];counts=Counter();by_tick=defaultdict(list);events={e['start_tick']:e for e in guitar['attack_events']}
    for n in guitar['notes']:
        if n.get('right_hand_pattern_id'):by_tick[n['start_tick']].append(n)
    for tick,notes in by_tick.items():
        n=notes[0];pattern=patterns.get(n['right_hand_pattern_id']);slot=n['right_hand_slot'];event=events.get(tick)
        if pattern is None:errors.append('unknown_regular_pattern');continue
        # 小节划分与拍速层级纠错：修改，原按整个小节取模保留；支持四拍小节内两个同样的两拍循环。
        # if tick%bar!=slot*pattern['step_ticks']:errors.append('ordinary_pattern_phase_shift:'+str(tick))
        cycle=len(pattern['slots'])*pattern['step_ticks']
        # 强拍相位与伴奏同步纠错：修改，原全局取模保留；真正重启的起点必须落在四分拍。
        # if tick%cycle!=slot*pattern['step_ticks']:errors.append('ordinary_pattern_phase_shift:'+str(tick))
        origin=n.get('pattern_cycle_origin_tick',0)
        if (tick-origin)%cycle!=slot*pattern['step_ticks']:errors.append('ordinary_pattern_phase_shift:'+str(tick))
        if guitar['configuration'].get('beat_synchronous_patterns') and origin%480:
            errors.append('ordinary_cycle_origin_off_quarter:'+str(origin))
        if pattern['slots'][slot]=='-':errors.append('attack_on_continuation_slot:'+str(tick))
        expected=pattern_duration(pattern,slot)
        # 小节划分与拍速层级纠错：修改，原三个细分保留；重记谱仅转换既有音乐，可保留明确的32分细节。
        # if expected not in (120,240,480) or tick%480+expected>480:errors.append('ordinary_dotted_or_cross_beat_slot:'+str(tick))
        durations=(60,120,240,480,960) if guitar.get('grid_correction') else (120,240,480)
        if expected not in durations or expected<480 and tick%480+expected>480:errors.append('ordinary_dotted_or_cross_beat_slot:'+str(tick))
        if not event or event.get('right_hand_duration_ticks')!=expected or event.get('right_hand_duration_source')!='regular_pattern_slot':
            errors.append('right_hand_mixed_duration_mismatch:'+str(tick))
        counts[expected]+=1
    # 结构稳定伴奏与人声合播：新增实际拨弦成组核查；休止/混合小节的受保护部分不硬套。
    plans=guitar['right_hand_patterns']['measures'];ticks=set(by_tick)
    for plan in plans:
        # 小节划分与拍速层级纠错：修改，旧整小节范围注释保留；每个已实现循环保留实际起止范围。
        # pattern=patterns[plan['pattern_id']];start=(plan['measure']-1)*bar
        # regular_beats=set(plan.get('regular_beats',range(bar//480)))
        # for beat in regular_beats:
        #     begin=start+beat*480;end=begin+480
        pattern=patterns[plan['pattern_id']];start=plan.get('pattern_start_tick',(plan['measure']-1)*bar)
        stop=plan.get('pattern_end_tick',start+bar)
        ranges=plan.get('regular_tick_ranges',[(start+beat*480,min(stop,start+(beat+1)*480))
                      for beat in plan.get('regular_beats',range(math.ceil((stop-start)/480)))])
        for begin,end in ranges:
            if begin<plan['leading_rest_end_tick'] or begin>=plan['active_end_tick']:continue
            if any(a<=begin<b for a,b in plan['protected_silence_gaps']):continue
            # 强拍相位与伴奏同步纠错：修改，原整小节预测保留；按实际和弦/休止的循环重启边界重算。
            # wanted={start+r['offset'] for r in pattern_schedule(pattern) if begin<=start+r['offset']<end}
            origins=plan.get('cycle_origins',[start]);wanted=set()
            for i,origin in enumerate(origins):
                limit=origins[i+1] if i+1<len(origins) else stop
                wanted.update(origin+r['offset'] for r in pattern_schedule(pattern)
                              if begin<=origin+r['offset']<min(end,limit))
            actual={t for t in ticks if begin<=t<end}
            if actual and actual!=wanted:errors.append('incomplete_regular_beat_group:'+str(begin))
    present={n['id']:n for n in guitar['notes']}
    # 吉他器乐低把位与指型复用：新增一次指纹核查，避免对每个保护音重复序列化整首工程。
    from guitar_instrumental_register import projected_source_note,fingerprint,POLICY as REGISTER_POLICY
    metadata=guitar.get('instrumental_register')
    trusted=metadata and metadata.get('policy')==REGISTER_POLICY and metadata.get('result_notes_sha256')==fingerprint(guitar['notes']) and metadata.get('source_notes_sha256')==fingerprint(metadata.get('source_notes',[]))
    # 器乐低弦分解填充：新增必须完整复演的织体保护投影，旧账本与来源指纹不得替换成新音集合。
    if guitar.get('instrumental_flow'):
        from guitar_instrumental_flow import validate_flow
        flow_check=validate_flow(shared,source_vocal(guitar),guitar)
        trusted=flow_check['valid']
        if not flow_check['valid']:errors.extend(flow_check['errors'])
    # 原曲器乐旋律骨干重提取：新增旧主线修订的真实源证据检查，不能靠删保护清单让错误通过。
    from instrumental_source_melody import validate_source_backbone,superseded_ids
    backbone_check=validate_source_backbone(shared,source_vocal(guitar),guitar) if guitar.get('instrumental_source_backbone') else None
    if backbone_check and not backbone_check['valid']:errors.extend(backbone_check['errors'])
    replaced=superseded_ids(guitar,backbone_check)
    for source in guitar['regular_rhythm'].get('preserved_notes',[]):
        # 原曲器乐旋律骨干重提取：新增明确的旧旋律替换，不跳过仍须保留的低音、和声及唱段。
        if source['id'] in replaced:continue
        actual=present.get(source['id'])
        # 吉他器乐低把位与指型复用：修改，旧保护比较保留；来源账本不改，仅器乐授权字段按新派生比较。
        # if actual is None or any(actual.get(k)!=source.get(k) for k in MUSIC_FIELDS):errors.append('protected_feature_music_changed:'+source['id'])
        # 吉他器乐低把位与指型复用：修改，原循环内重复核验保留；改用上面独立的一次策略／源音指纹核查。
        # from guitar_instrumental_register import projected_source_note,fingerprint
        # metadata=guitar.get('instrumental_register')
        # trusted=metadata and metadata.get('result_notes_sha256')==fingerprint(guitar['notes'])
        expected=projected_source_note(source,guitar) if trusted else source
        if actual is None or any(actual.get(k)!=expected.get(k) for k in MUSIC_FIELDS):errors.append('protected_feature_music_changed:'+source['id'])
    return {'valid':not errors,'errors':errors,'ordinary_attack_groups':len(by_tick),
            'right_hand_duration_counts':{str(k):v for k,v in sorted(counts.items())},
            'regular_policy_version':2,'no_dotted_regular_slots':True}


# 原曲器乐旋律骨干重提取：新增不改变旧调用签名的认可人声来源，源骨干验收使用真实绑定工程。
def source_vocal(guitar):
    from instrumental_source_melody import source_parent
    parent=source_parent(guitar)
    if parent is None and guitar.get('instrumental_flow'):
        # 新音源已直接保留器乐请求，可能没有旧旋律重提取账本；
        # 使用同样经过文件摘要校验的低弦织体来源，不能凭空补人声。
        from guitar_instrumental_flow import flow_parent
        parent=flow_parent(guitar)
    if parent is None:
        raise ValueError('缺少可验证的人声来源，不能核查器乐节奏。')
    return parent['accepted_vocal_project']


# 结构稳定伴奏与人声合播：新增真实来源与重复选择核查，记录明确原曲变体理由。
def validate_structure(shared,vocal,guitar,rows=None):
    info=guitar.get('structure_stability')
    if not info:return None
    errors=[];evidence=guitar.get('source_rhythm_evidence',{})
    if not info.get('source_only_pattern_selection') or info.get('old_arrangement_density_used'):
        errors.append('old_arrangement_used_as_source_rhythm')
    for source in evidence.get('sources',[]):
        bound=shared['input_binding']['sources'].get(source['source'],{})
        if bound.get('sha256')!=source['sha256']:errors.append('rhythm_source_binding_mismatch')
    if not evidence.get('no_fourteen_attack_cap') or len(evidence.get('sources',[]))<2:errors.append('missing_complete_multisource_evidence')
    reused=defaultdict(set);variants=[]
    for p in info['phrases']:
        if p.get('repeat_action')=='reuse_main_pattern':reused[p['repeat_group']].add(p['pattern_id'])
        if p.get('repeat_action')=='original_rhythm_variant':variants.append(p['line_index'])
        if not p.get('all_candidates') or any(r.get('phase_tick')!=0 for r in p['all_candidates']):errors.append('missing_source_candidate_audit')
    if any(len(ids)>1 for ids in reused.values()):errors.append('compatible_repeated_phrase_main_pattern_changed')
    from guitar_structure_patterns import ornament_aliases
    if guitar.get('ornament_display',{}).get('aliases')!=ornament_aliases(shared):errors.append('unsupported_ornament_display_alias')
    layout={}
    if rows is not None:
        # 强拍相位与伴奏同步纠错：修改，原固定分组保留；弱起独立，其余仍严格四个正式小节一行。
        # count=vocal['statistics']['measure_count'];expected=[(i,min(i+3,count)) for i in range(1,count+1,4)]
        from beat_phase_alignment import score_row_ranges
        count=vocal['statistics']['measure_count'];expected=score_row_ranges(vocal)
        observed=[];markers=[]
        for row in rows:
            root=ET.fromstring(row['guitar']);first=int(root.get('data-first-measure'));last=int(root.get('data-last-measure'))
            observed.append((first,last))
            bars={float(line.get('x1')) for line in root.iter(NS+'line')
                  if line.get('x1')==line.get('x2') and float(line.get('y1','-1'))==222}
            if len(bars)!=last-first+2:errors.append('four_bar_visible_barlines_wrong:'+str(first))
            for group in root.iter(NS+'g'):
                if group.get('class')!='capo-change-marker':continue
                tick=int(group.get('data-start-tick'));fret=int(group.get('data-capo-fret'))
                text=group.find(NS+'text')
                if text is None or '夹' not in text.text or str(fret)+'品' not in text.text:errors.append('invisible_capo_change_label')
                if fret!=capo_at(guitar,tick):errors.append('visible_capo_change_wrong_fret')
                markers.append((tick,fret))
        if observed!=expected:errors.append('four_bar_rows_missing_or_wrong_range')
        wanted=[(s['start_tick'],s['capo_fret']) for s in guitar['configuration'].get('capo_segments',[])[1:]]
        if sorted(markers)!=wanted:errors.append('capo_change_markers_missing_or_extra')
        layout={'rows':len(observed),'last_row':list(observed[-1]) if observed else [],'capo_change_markers':markers}
    return {'valid':not errors,'errors':errors,'lyric_phrases':len(info['phrases']),
            'reused_repeat_groups':len(reused),'explicit_original_rhythm_variants':variants,
            'short_ornament_candidates':len(guitar.get('ornament_display',{}).get('aliases',{})),
            'complete_rhythm_sources':len(evidence.get('sources',[])),**layout}
