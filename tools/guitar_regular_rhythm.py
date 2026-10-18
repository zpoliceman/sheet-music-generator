"""规整分解节奏与延音显示：普通伴奏规则及独立拍格核查。"""
# 规整分解节奏与延音显示：新增明确默认偏好，自动分轨观察不等于原曲完美匹配。
from collections import Counter, defaultdict
from copy import deepcopy
from guitar_right_hand_patterns import apply_common_patterns, library
# 规整分解节奏与延音显示：新增混合边界只整理普通伴奏拍，器乐起音和原持续字典继续保留。
# 乐句节奏与音值分组：修改，旧导入注释保留；混合小节也采用唯一生成序号。
# from guitar_right_hand_patterns import measure_notes,complete_quality
from guitar_right_hand_patterns import measure_notes,complete_quality,next_note_serial
# 结构稳定伴奏与人声合播：修改，原代码注释保留。
# from guitar_grip_policy import grip_position_path
from guitar_grip_policy import grip_position_path
# 结构稳定伴奏与人声合播：新增混合时值查询。
from guitar_pattern_grid import pattern_duration


def regularize_vocal_fragments(shared, vocal, guitar, original):
    # 乐句节奏与音值分组：修改，旧固定序号注释保留；既有v12种子可能已经含100000序号。
    # bar = shared['statistics']['bar_ticks']; serial = 100000; rows = []; failures = []
    bar = shared['statistics']['bar_ticks']; serial = next_note_serial(original['notes']+guitar['notes'],100000); rows = []; failures = []
    covered = set(guitar['right_hand_patterns']['applied_this_run'])
    for measure in range(1, shared['statistics']['measure_count']+1):
        if measure in covered: continue
        begin = (measure-1)*bar; old = [n for n in original['notes'] if begin<=n['start_tick']<begin+bar]
        ordinary = [n for n in old if n.get('role') in ('bass','harmony') and not n.get('source_melody_id') and
                    any(s['kind']=='vocal' and s['start_tick']<=n['start_tick']<s['end_tick'] for s in shared['sections'])]
        if not ordinary: continue
        beats = set()
        for beat in range(bar//480):
            start, finish = begin+beat*480, begin+(beat+1)*480
            voiced = any(s['kind']=='vocal' and s['start_tick']<finish and s['end_tick']>start for s in shared['sections'])
            # 规整分解节奏与延音显示：修改，旧所有边界延音阻止整理保留；普通和声延响可共存，真实器乐旋律仍保护。
            # feature = any(n['start_tick']<finish and n['end_tick']>start for n in old if n not in ordinary)
            feature = any(n['start_tick']<finish and n['end_tick']>start for n in old
                          if n not in ordinary and (n.get('role') not in ('bass','harmony') or n.get('source_melody_id')))
            if voiced and not feature and any(start<=n['start_tick']<finish for n in ordinary): beats.add(beat)
        if not beats: continue
        selected = [n for n in ordinary if (n['start_tick']-begin)//480 in beats]
        removed = {n['id'] for n in selected}
        pattern_rows = guitar['right_hand_patterns']['measures']
        nearest = min(pattern_rows, key=lambda r: abs(r['measure']-measure)) if pattern_rows else {'pattern_id':'arp_4_4_roll'}
        plan = {'pattern_id': nearest['pattern_id'], 'phase_tick':0}
        source = {**original, 'configuration':guitar['configuration'], 'notes':selected}
        ns, es, row, serial = measure_notes(shared, source, measure, plan, serial)
        ns = [n for n in ns if (n['start_tick']-begin)//480 in beats]
        for n in ns: n['end_tick'] = min(n['end_tick'], begin+((n['start_tick']-begin)//480+1)*480)
        ticks = {n['start_tick'] for n in ns}; es = [e for e in es if e['start_tick'] in ticks]
        # 结构稳定伴奏与人声合播：修改，原代码注释保留。
        # complete_quality(shared, ns, es, [row], guitar['configuration']['capo_fret'], serial)
        complete_quality(shared, ns, es, [row], guitar['configuration']['capo_fret'], serial, guitar=guitar)
        serial += len(ns)+20
        candidate = sorted([n for n in guitar['notes'] if n['id'] not in removed]+ns, key=lambda n:(n['start_tick'],n['string']))
        check = grip_position_path({**guitar,'notes':candidate,'fingering_diagrams':[]}, vocal)
        if not check['valid']:
            failures.append({'measure':measure,'reason':check.get('reason')}); continue
        guitar['notes'] = candidate; guitar['hand_positions'] = check['positions']
        positions = {r['tick']:r['position'] for r in check['positions']}
        for n in ns: n['hand_position'] = positions[n['start_tick']]
        kept_events = [e for e in guitar['attack_events'] if e['start_tick'] not in {n['start_tick'] for n in selected}]
        guitar['attack_events'] = sorted(kept_events+es, key=lambda e:e['start_tick'])
        row['scope']='vocal_ordinary_beats_in_mixed_measure'; row['regular_beats'] = sorted(beats)
        row['realized_attacks'] = [r for r in row['realized_attacks'] if r['tick'] in ticks]
        rows.append(row); guitar['right_hand_patterns']['source_notes'].extend(deepcopy(selected))
        guitar['right_hand_patterns']['measures'] = [r for r in guitar['right_hand_patterns']['measures'] if r['measure']!=measure]+[row]
        guitar['right_hand_patterns']['changed_measures'] = sorted(set(guitar['right_hand_patterns']['changed_measures'])|{measure})
    return rows, failures

POLICY = {'name': 'regular_arpeggio_first', 'version': 1, 'phase_tick': 0,
          'preferred_steps': [240, 480], 'rest_unit_ticks': 480,
          'rhythm_source': 'right_hand_slots', 'sounding_duration': 'independent_per_string',
          'irregular_exceptions': 'explicit_original_match_or_user_review_required',
          'protected_feature_and_instrumental_notes': True}


# 规整分解节奏与延音显示：新增显式重编入口，普通编辑重导不再改动已经编辑的音序。
# 结构稳定伴奏与人声合播：修改，原代码注释保留。
# def apply_regular_patterns(shared, vocal, guitar):
    # if guitar.get('regular_rhythm', {}).get('version') == POLICY['version']: return guitar
def apply_regular_patterns(shared, vocal, guitar, policy=None):
    # 结构稳定伴奏与人声合播：新增调用方策略参数，旧入口继续用版本1。
    policy = policy or POLICY
    if guitar.get('regular_rhythm', {}).get('version') == policy['version']: return guitar
    # 规整分解节奏与延音显示：新增4/4适用边界，其它拍号沿用既有选型，不能套用4/4边界拍格。
    if shared['timing']['meter'] != [4, 4]: return apply_common_patterns(shared, vocal, guitar)
    # 结构稳定伴奏与人声合播：修改，原代码注释保留。
    # original = deepcopy(guitar); guitar['configuration']['regular_rhythm_policy'] = deepcopy(POLICY)
    original = deepcopy(guitar); guitar['configuration']['regular_rhythm_policy'] = deepcopy(policy)
    apply_common_patterns(shared, vocal, guitar)
    # 规整分解节奏与延音显示：新增混合小节按完整可用拍整理普通伴奏，保留器乐边界前后的音。
    fragments, failures = regularize_vocal_fragments(shared, vocal, guitar, original)
    patterns = {p['id']: p for p in library()['patterns']}
    applied = set(guitar['right_hand_patterns']['applied_this_run'])
    applied.update(r['measure'] for r in fragments)
    for event in guitar['attack_events']:
        # 规整分解节奏与延音显示：修改，旧按整小节盖章保留；只为本轮新模板事件添加右手拍格。
        # if event['start_tick'] // shared['statistics']['bar_ticks'] + 1 not in applied: continue
        if event['start_tick']//shared['statistics']['bar_ticks']+1 not in applied or not event.get('right_hand_pattern_id'): continue
        # 结构稳定伴奏与人声合播：修改，原代码注释保留。
        # event['right_hand_duration_ticks'] = patterns[event['right_hand_pattern_id']]['step_ticks']
        event['right_hand_duration_ticks'] = pattern_duration(patterns[event['right_hand_pattern_id']],event['right_hand_slot'])
        event['right_hand_duration_source'] = 'regular_pattern_slot'
    present = {n['id']: n for n in guitar['notes']}
    # 规整分解节奏与延音显示：修改，旧整小节保护保留；混合拍中未替换的旧音也逐字段保护。
    # preserved = [n for n in original['notes'] if n['start_tick']//shared['statistics']['bar_ticks']+1 not in applied]
    preserved = [n for n in original['notes'] if n['id'] in present]
    if any(present.get(n['id']) != n for n in preserved): raise ValueError('规整节奏改动受保护音符。')
    # 结构稳定伴奏与人声合播：修改，原代码注释保留。
    # guitar['regular_rhythm'] = {'version': POLICY['version'],
    guitar['regular_rhythm'] = {'version': policy['version'], 'changed_measures': sorted(applied),
                               'preserved_note_ids': [n['id'] for n in preserved],
                               'preserved_notes': preserved, 'source_notes': original['notes'],
                               # 规整分解节奏与延音显示：修改，旧结尾保留；保存混合拍范围及真实可弹失败。
                               # 'exceptions': [], 'quality_status': 'arrangement_choice_requires_listening'}
                               'fragments':fragments, 'fragment_failures':failures,
                               'exceptions': [], 'quality_status': 'arrangement_choice_requires_listening'}
    return guitar


# 规整分解节奏与延音显示：新增从实际起音检查成对八分/四分拍格，不只检查显示没有附点。
# 结构稳定伴奏与人声合播：修改，原代码注释保留。
# def validate_regular_rhythm(shared, guitar):
    # info = guitar.get('regular_rhythm')
def validate_regular_rhythm(shared, guitar):
    # 原声覆盖与选音归属通用修复：新增先验证认可音乐合并，再在真实基础工程验证旧节奏来源。
    if guitar.get('approved_section_preservation'):
        from approved_music_sections import validate_rhythm_chain
        return validate_rhythm_chain(shared,guitar,validate_regular_rhythm)
    # 器乐背景休止与旋律突出：新增旧节奏在真实上游完整验收，当前自动休止／力度按严格派生另验收。
    if guitar.get('instrumental_expression'):
        from guitar_instrumental_expression import validate_expression_rhythm
        return validate_expression_rhythm(shared,guitar,validate_regular_rhythm)
    # 小节划分与拍速层级纠错：新增重记谱工程统一检查真实循环与模板时值，兼容旧规整版本。
    if guitar.get('grid_correction') and guitar.get('regular_rhythm'):
        from guitar_structure_validation import validate_structured_rhythm
        return validate_structured_rhythm(shared,guitar)
    # 结构稳定伴奏与人声合播：新增十六分/混合型真实起音验证；旧版本保留原验证。
    if guitar.get('regular_rhythm',{}).get('version',1)>=2:
        from guitar_structure_validation import validate_structured_rhythm
        return validate_structured_rhythm(shared,guitar)
    info = guitar.get('regular_rhythm')
    if not info: return None
    errors = []; bar = shared['statistics']['bar_ticks']; changed = set(info['changed_measures'])
    patterns = {p['id']: p for p in library()['patterns']}; counts = Counter(); attacks = defaultdict(list)
    event_by_tick = {e['start_tick']: e for e in guitar['attack_events']}
    for note in guitar['notes']:
        # 规整分解节奏与延音显示：修改，旧按整小节纳入保留；器乐边界旧音不冒充普通模板起音。
        # if note['start_tick']//bar+1 in changed: attacks[note['start_tick']].append(note)
        if note['start_tick']//bar+1 in changed and note.get('right_hand_pattern_id'):
            attacks[note['start_tick']].append(note)
    by_measure = defaultdict(set)
    for tick, notes in attacks.items():
        event = event_by_tick.get(tick, {}); pid = notes[0].get('right_hand_pattern_id'); step = patterns[pid]['step_ticks']
        if tick % step: errors.append('off_grid_attack:'+str(tick))
        if step not in (240, 480) or event.get('right_hand_duration_ticks') != step or event.get('right_hand_duration_source') != 'regular_pattern_slot':
            errors.append('right_hand_slot_invalid:'+str(tick))
        by_measure[tick//bar+1].add(tick); counts[step] += 1
    for measure, ticks in by_measure.items():
        for tick in ticks:
            pid = attacks[tick][0]['right_hand_pattern_id']; step = patterns[pid]['step_ticks']
            if step == 240:
                mate = tick+240 if tick % 480 == 0 else tick-240
                if mate not in ticks: errors.append('unpaired_eighth_attack:'+str(tick))
    present = {n['id']: n for n in guitar['notes']}
    if any(present.get(n['id']) != n for n in info['preserved_notes']): errors.append('protected_note_changed')
    return {'valid': not errors, 'errors': errors, 'regular_measures': len(changed),
            'eighth_attacks': counts[240], 'quarter_attacks': counts[480],
            'dotted_regular_attacks': 0, 'unpaired_regular_eighths': sum('unpaired_eighth' in e for e in errors),
            'preserved_notes': len(info['preserved_notes']), 'approved_irregular_exceptions': len(info['exceptions'])}
