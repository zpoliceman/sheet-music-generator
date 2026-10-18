"""相似乐句和弦框架复用：共同进行驱动两乐器实音，保护人声与器乐。"""
# 相似乐句和弦框架复用：新增实际编配层，不只替换和弦名称或指型图片。
from __future__ import annotations
from collections import defaultdict
from copy import deepcopy
import math
# 相似乐句和弦框架复用：修改，旧导入保留；性质/显示名称校验须读取真实和弦定义。
# from accompaniment_analysis import SongClock, chord_name, pc_name
from accompaniment_analysis import SongClock, chord_name, pc_name, CHORD_TYPES
from accompaniment_arrange import compact_voicing, piano_hand_positions, validate_playability
from guitar_capo import capo_at
from guitar_grip_policy import grip_position_path
# 连续源拍序与人声联合重解通用修复：修改，旧导入保留；重编ID必须避开保留下来的旧模板与特色源音。
# from guitar_right_hand_patterns import library, measure_notes, complete_quality, shape_for
from guitar_right_hand_patterns import library, measure_notes, complete_quality, shape_for, next_note_serial
from guitar_structure_patterns import score_pattern, ornament_aliases, lyric_lines, collect_rhythm_evidence
# 相似乐句和弦框架复用：修改，旧单音符摘要导入保留；新增联合音乐状态指纹。
# from phrase_harmony_plan import POLICY, build_phrase_harmony, arrangement_view, fingerprint, shared_fingerprint
from phrase_harmony_plan import POLICY, build_phrase_harmony, arrangement_view, vocal_fingerprint, shared_fingerprint
from score_export import PPQ, key_definition

MUSIC_FIELDS = ('id', 'pitch_midi', 'start_tick', 'end_tick', 'velocity', 'role', 'string', 'fret', 'hand')
DERIVED_GUITAR = ('fingering_diagrams', 'notation_regions', 'grip_hand_positions', 'grip_fingerings',
                  'tab_display', 'rhythm_display', 'time_alignment_display', 'exact_pitch_refingering')


# 跨歌曲和弦复用与器乐准备：新增选择与实际编配范围一致的验收；完整拍新音检查强拍，固定源边界检查逐音保护。
def needs_joint_pulse_validation(shared):
    plan = shared.get('phrase_harmony_plan', {})
    return bool(plan.get('phrases')) and (shared['timing']['meter'] != [4, 4]
            or plan.get('beat_boundary_version') == 1
            or any(p['action'].startswith('preserve_source') for p in plan['phrases']))


# 相似乐句和弦框架复用：新增半开演唱范围，真正器乐/特色填句音全部固定。
def ordinary(shared, note):
    # 跨歌曲和弦复用与器乐准备：新增完整拍规划以外的短边界保留实音，原历史计划不改变保护语义。
    plan = shared.get('phrase_harmony_plan', {})
    if plan.get('beat_boundary_version') == 1 and not any(
            p['start_tick'] <= note['start_tick'] < p['end_tick'] for p in plan.get('phrases', [])):
        return False
    # 相似乐句和弦框架复用：新增弱证据句保护，旧声学/实音不足时保持源编配而不是猜新和弦。
    if any(p['action'] == 'preserve_source_insufficient_evidence' and p['start_tick'] <= note['start_tick'] < p['end_tick']
           for p in shared.get('phrase_harmony_plan', {}).get('phrases', [])):
        return False
    return (note.get('role') in ('bass', 'harmony') and not note.get('source_melody_id')
            and any(s['kind'] == 'vocal' and s['start_tick'] <= note['start_tick'] < s['end_tick']
                    for s in shared.get('sections', [])))


def music(note):
    return {k: note[k] for k in MUSIC_FIELDS if k in note}


# 相似乐句和弦框架复用：新增完整乐句右手型共同选型，原轨细分决定混合/八分/十六分候选。
def rhythm_plans(shared, vocal, guitar, cache_dir):
    meter = shared['timing']['meter']; bar = shared['statistics']['bar_ticks']
    # 演唱段稳定右手型：修改初次编配候选，原混合／密集候选保留注释；段落从简单均匀型中选择。
    # patterns = [p for p in library()['patterns'] if p['meter'] == meter and p['family'] == 'arpeggio'
    #             and (p.get('default_candidate') or p.get('structured_candidate'))]
    from guitar_section_patterns import simple_library_candidates,constrain_section_choices
    patterns = simple_library_candidates([p for p in library()['patterns'] if p['meter']==meter and p['family']=='arpeggio'])
    if not guitar.get('source_rhythm_evidence') and shared.get('input_binding', {}).get('sources') and cache_dir:
        guitar['source_rhythm_evidence'] = collect_rhythm_evidence(shared, vocal, cache_dir)
    # 相似乐句和弦框架复用：新增无源音频时明确默认降级，不拿旧编配密度当作原曲证据。
    guitar.setdefault('source_rhythm_evidence', {'measures': [], 'status': 'no_audio_evidence_basic_pattern'})
    phrases = shared['phrase_harmony_plan']['phrases']; by_id = {p['id']: p for p in phrases}
    details = {}
    for phrase in phrases:
        if patterns:
            details[phrase['id']] = [score_pattern(shared, guitar, phrase['measures'], p) for p in patterns]
        else:
            # 相似乐句和弦框架复用：新增其它拍号的明确基本分解降级，按拍号实际长度构造，不套4/4库。
            details[phrase['id']] = [{'pattern_id': 'meter_basic_arpeggio', 'phase_tick': 0, 'score': 0.,
                                     'rhythm_fallback': 'basic_meter_pulse_without_library_match'}]
    selected = {p['id']: min(range(len(details[p['id']])), key=lambda j: details[p['id']][j]['score']) for p in phrases}
    for family in shared['phrase_harmony_plan']['families']:
        ids = [m['phrase_id'] for m in family['members']]
        best = min(range(len(details[ids[0]])), key=lambda j: sum(details[i][j]['score'] for i in ids))
        for identity in ids:
            loss = details[identity][best]['score']-min(r['score'] for r in details[identity])
            if loss <= .65:
                selected[identity] = best
    # 演唱段稳定右手型：新增整段硬一致并联结已确认乐句族，覆盖逐句小差异挑新型的旧结果。
    section_groups=constrain_section_choices(shared,phrases,details,selected)
    counts = defaultdict(int)
    for p in phrases: counts[p['family_id']] += 1
    plans = []
    for p in phrases:
        choice = details[p['id']][selected[p['id']]]
        plans.append({**p, **choice, 'all_candidates': details[p['id']], 'line_index': None,
                      'repeat_group': p['family_id'] if counts[p['family_id']] > 1 else None,
                      'repeat_action': 'reuse_main_pattern' if counts[p['family_id']] > 1 else None,
                      'repeat_source': 'shared_phrase_harmony_family'})
    # 相似乐句和弦框架复用：新增源节奏变化如需变体，仍记录真实选择，不能冒称完全复用。
    for family in shared['phrase_harmony_plan']['families']:
        members = [p for p in plans if p['family_id'] == family['id']]
        if len({p['pattern_id'] for p in members}) > 1:
            winner = max(members, key=lambda p: sum(q['pattern_id'] == p['pattern_id'] for q in members))['pattern_id']
            for p in members:
                if p['pattern_id'] != winner:
                    p['repeat_action'] = 'original_rhythm_variant'
    # 演唱段稳定右手型：修改策略报告，原版本1返回式保留，不把新段级规则冒充旧缓存策略。
    # guitar['structure_stability'] = {'version': 1, 'lyric_lines': lyric_lines(vocal), 'phrases': plans,
    guitar['structure_stability'] = {'version': 2, 'simple_section_pattern_groups':section_groups, 'lyric_lines': lyric_lines(vocal), 'phrases': plans,
        'repeat_groups': {f['id']: [i for i, p in enumerate(plans) if p['family_id'] == f['id']]
                          for f in shared['phrase_harmony_plan']['families'] if len(f['members']) > 1},
        'source_only_pattern_selection': True, 'old_arrangement_density_used': False,
        'left_hand': 'joint_phrase_harmony_and_consistent_common_grips'}
    return plans


# 相似乐句和弦框架复用：新增无现成库拍号的规整分解事件，分组与真实小节长度相符。
def basic_meter_notes(shared, guitar, measure, serial):
    bar = shared['statistics']['bar_ticks']; start, end = (measure-1)*bar, measure*bar
    unit = int(PPQ*4/shared['timing']['meter'][1]); step = min(PPQ//2, unit)
    old = [n for n in guitar['notes'] if start <= n['start_tick'] < end]
    if not old: return [], [], None, serial
    active_end = min(end, max(n['end_tick'] for n in old)); notes = []; events = []
    for tick in range(start, active_end, step):
        # 首拍与首尾局部补证：新增基本拍号分解也遵守同一原声尾响边界，两乐器共用的模板不能重新制造尾音。
        from first_generation_tail import pattern_attack_allowed
        if not pattern_attack_allowed(shared,tick):continue
        h = next((h for h in shared['harmony'] if h['start_tick'] <= tick < h['end_tick']), None)
        if not h or h['name'] == 'N.C.': continue
        shape, mapped = shape_for(h, capo_at(guitar, tick))
        origin = max(start, h['start_tick']); slot = (tick-origin)//step
        # 相似乐句和弦框架复用：修改，旧统一四格循环保留；三拍与复合六拍按实际重音成组。
        # token = ('B', '3', '2', '1')[slot % 4]; string = mapped[token]
        meter = shared['timing']['meter']
        cycle = ('B', '3', '2', '1', '2', '3') if meter == [3, 4] else (
            'B', '3', '2', 'B', '2', '1') if meter == [6, 8] else ('B', '3', '2', '1')
        token = cycle[slot % len(cycle)]; string = mapped[token]
        from accompaniment_arrange import TUNING
        nearest = min(old, key=lambda n: abs(n['start_tick']-tick))
        note = {'id': f'guitar_phrase_note_{serial:06}', 'start_tick': tick, 'end_tick': min(tick+step, h['end_tick'], active_end),
                'pitch_midi': TUNING[string]+capo_at(guitar, tick)+shape['frets'][str(string)],
                'string': string, 'fret': shape['frets'][str(string)], 'finger': shape['fingers'].get(string, 0),
                'velocity': 78 if token == 'B' else 64, 'role': 'bass' if token == 'B' else 'harmony',
                'section': 'vocal', 'chord_id': h['id'], 'source': nearest['source'],
                'source_note_ids': [nearest['id']], 'source_attack_seconds': nearest['source_attack_seconds'],
                'onset_origin': 'arranged_meter_arpeggio', 'arrangement_reason': 'joint_phrase_harmony',
                'harmonic_pattern_id': 'meter_basic_arpeggio'}
        notes.append(note); serial += 1
        events.append({'start_tick': tick, 'kind': 'arpeggio', 'chord_id': h['id'], 'source': nearest['source'],
                       'right_hand_duration_ticks': step, 'right_hand_duration_source': 'regular_pattern_slot'})
    return notes, events, None, serial


# 连续源拍序与人声联合重解通用修复：修改，旧签名保留；末拍补全必须有普通源音持续到对应起音。
# def available_ranges(shared, start, end, fixed, unit=PPQ):
def available_ranges(shared, start, end, fixed, unit=PPQ, source_notes=None):
    ranges = []
    for tick in range(start, end, unit):
        finish = min(end, tick+unit)
        # 跨歌曲和弦复用与器乐准备：修正尾拍范围，以源伴奏实际起音支撑尾拍；所有真实器乐／填句覆盖仍阻止整拍套型。
        # if (any(s['kind'] == 'vocal' and s['start_tick'] <= tick and finish <= s['end_tick'] for s in shared['sections'])
        if (any(s['kind'] == 'vocal' and s['start_tick'] <= tick < s['end_tick'] for s in shared['sections'])
                and not any(n['start_tick'] < finish and n['end_tick'] > tick
                            and (n.get('role') not in ('bass', 'harmony') or n.get('source_melody_id')) for n in fixed)):
            # 连续源拍序与人声联合重解通用修复：修改，旧整拍范围保留；仅到真实唱段或普通伴奏续音支持的末端。
            # ranges.append((tick, finish))
            if source_notes is not None:
                sections = [s for s in shared['sections'] if s['kind'] == 'vocal'
                            and s['start_tick'] <= tick < s['end_tick']]
                supported_end = max([s['end_tick'] for s in sections] + [n['end_tick'] for n in source_notes
                    if n.get('role') in ('bass', 'harmony') and not n.get('source_melody_id')
                    and any(s['start_tick'] <= n['start_tick'] < s['end_tick'] for s in sections)
                    and tick <= n['start_tick'] < finish])
                finish = min(finish, supported_end)
            ranges.append((tick, finish))
    return ranges


# 相似乐句和弦框架复用：新增每乐器独立休止范围/固定声部，模板音只进入可编辑完整拍。
def generate_slots(shared, vocal, original, guitar_configuration, plans, fixed, serial):
    clock = SongClock(vocal); bar = shared['statistics']['bar_ticks']; notes = []; events = []; rows = []
    source_notes = [deepcopy(n) for n in original['notes'] if ordinary(shared, n)]
    for note in source_notes:
        note.setdefault('source', 'shared_harmonic_evidence')
        note.setdefault('source_attack_seconds', clock.seconds(note['start_tick']))
    dummy = {'configuration': guitar_configuration, 'notes': source_notes}
    for measure in range(1, shared['statistics']['measure_count']+1):
        start, end = (measure-1)*bar, measure*bar
        old = [n for n in source_notes if start <= n['start_tick'] < end]
        # 跨曲低音与强拍复用通用修复：修改，原只查小节开头的计划会删除后半小节真实入口，旧语句注释保留。
        # plan = next((p for p in plans if p['start_tick'] <= start < p['end_tick']), None)
        # if not old or plan is None: continue
        # if plan['pattern_id'] == 'meter_basic_arpeggio':
        #     ns, es, row, serial = basic_meter_notes(shared, dummy, measure, serial)
        # else:
        #     ns, es, row, serial = measure_notes(shared, dummy, measure, plan, serial)
        # allowed = available_ranges(shared, start, end, fixed, min(PPQ, int(PPQ*4/shared['timing']['meter'][1])))
        # ns = [n for n in ns if any(a <= n['start_tick'] < b for a, b in allowed)]
        # for note in ns:
        #     a,b=next((a,b) for a,b in allowed if a<=note['start_tick']<b)
        #     conflicts = [n['start_tick'] for n in fixed if n.get('string') == note['string'] and note['start_tick'] < n['start_tick'] < note['end_tick']]
        #     note['end_tick'] = min(note['end_tick'], min(conflicts, default=note['end_tick']))
        #     note['phrase_harmony_generated'] = True
        # notes.extend(ns); ticks = {n['start_tick'] for n in ns}; es = [e for e in es if e['start_tick'] in ticks]
        # events.extend(es)
        # if row:
        #     row['regular_tick_ranges'] = allowed; row['pattern_start_tick'] = start; row['pattern_end_tick'] = end
        #     row['realized_attacks'] = [r for r in row['realized_attacks'] if r['tick'] in ticks]
        #     rows.append(row)
        for plan in (p for p in plans if p['start_tick'] < end and p['end_tick'] > start):
            left, right = max(start, plan['start_tick']), min(end, plan['end_tick'])
            scoped = [n for n in old if left <= n['start_tick'] < right]
            if not scoped:
                continue
            part = {**dummy, 'notes': scoped}
            if plan['pattern_id'] == 'meter_basic_arpeggio':
                ns, es, row, serial = basic_meter_notes(shared, part, measure, serial)
            else:
                ns, es, row, serial = measure_notes(shared, part, measure, plan, serial)
            # 连续源拍序与人声联合重解通用修复：修改，旧无源末拍范围保留；使用当前真实普通伴奏种子的续音范围。
            # allowed = [(max(a,left), min(b,right)) for a,b in available_ranges(
            #     shared, start, end, fixed, min(PPQ, int(PPQ*4/shared['timing']['meter'][1]))) if a < right and b > left]
            allowed = [(max(a,left), min(b,right)) for a,b in available_ranges(
                shared, start, end, fixed, min(PPQ, int(PPQ*4/shared['timing']['meter'][1])),
                source_notes=scoped) if a < right and b > left]
            # 连续源拍序与人声联合重解通用修复：修改，旧只按拍范围筛选保留；尾边界固定同弦音仍在响时不能重建重叠的第二音。
            # ns = [n for n in ns if any(a <= n['start_tick'] < b for a,b in allowed)]
            ns = [n for n in ns if any(a <= n['start_tick'] < b for a,b in allowed)
                  and not any(f.get('string') is not None and f.get('string') == n.get('string')
                              and f['start_tick'] <= n['start_tick'] < f['end_tick'] for f in fixed)]
            for note in ns:
                conflicts = [n['start_tick'] for n in fixed if n.get('string') == note['string'] and
                             note['start_tick'] < n['start_tick'] < note['end_tick']]
                note['end_tick'] = min(note['end_tick'], right, min(conflicts, default=note['end_tick']))
                note['phrase_harmony_generated'] = True
            notes.extend(ns); ticks = {n['start_tick'] for n in ns}
            events.extend(e for e in es if e['start_tick'] in ticks)
            if row:
                row['regular_tick_ranges'] = allowed; row['pattern_start_tick'] = left; row['pattern_end_tick'] = right
                row['realized_attacks'] = [r for r in row['realized_attacks'] if r['tick'] in ticks]
                rows.append(row)
    return notes, events, rows, serial


# 相似乐句和弦框架复用：新增新伴奏可弹性修复，仅释放新声部，固定器乐/填句不能被改动。
def repair_guitar(shared, vocal, guitar, fixed, generated, events, rows):
    bar = shared['statistics']['bar_ticks']; repairs = []; blocked = set()
    for _ in range(64):
        guitar['notes'] = sorted(deepcopy(fixed)+generated, key=lambda n: (n['start_tick'], n['string']))
        check = grip_position_path({**guitar, 'fingering_diagrams': []}, vocal)
        if check['valid']:
            guitar['hand_positions'] = check['positions']; break
        # 相似乐句和弦框架复用：修改，旧优先撤掉当前拍保留；换把速度失败先释放上一拍，保住新和弦正拍低音。
        # tick = check['tick']; relevant = [n for n in generated if n['start_tick'] <= tick < n['end_tick']]
        # if not relevant:
        #     relevant = [n for n in generated if tick-PPQ <= n['start_tick'] < tick]
        tick = check['tick']; prior = [n for n in generated if (tick//PPQ-1)*PPQ <= n['start_tick'] < tick//PPQ*PPQ]
        relevant = prior if check['reason'] == 'complete_grip_position_rate' and prior else [
            n for n in generated if n['start_tick'] <= tick < n['end_tick']]
        if not relevant:
            relevant = [n for n in generated if tick-PPQ <= n['start_tick'] < tick]
        if not relevant: raise ValueError('固定器乐时序无法与新和弦衔接：'+str(check))
        beat = min(n['start_tick']//PPQ for n in relevant)
        removed = [n for n in generated if n['start_tick']//PPQ == beat]
        generated = [n for n in generated if n['start_tick']//PPQ != beat]; blocked.add(beat)
        # 相似乐句和弦框架复用：新增实际换把空档，不以小于十六分的碎音掩盖不可演奏。
        for n in generated:
            if n['start_tick'] < beat*PPQ < n['end_tick']: n['end_tick'] = beat*PPQ
        repairs.append({'tick': tick, 'released_beat': beat*PPQ, 'reason': check['reason'],
                        'removed_note_ids': [n['id'] for n in removed]})
    else: raise ValueError('新和弦伴奏实际手位修复未收敛。')
    ticks = {n['start_tick'] for n in generated}
    events = [e for e in events if e['start_tick'] in ticks]
    for row in rows:
        row['regular_tick_ranges'] = [(a, b) for a, b in row['regular_tick_ranges'] if a//PPQ not in blocked]
        row['realized_attacks'] = [a for a in row['realized_attacks'] if a['tick'] in ticks]
    return generated, events, rows, repairs


# 相似乐句和弦框架复用：新增键盘独立音区/双手配音，不把吉他弦品当作钢琴指法。
def piano_voicing(shared, piano, slots, fixed):
    result = []; by_tick = defaultdict(list); chords = {h['id']: h for h in shared['harmony']}
    for n in slots: by_tick[n['start_tick']].append(n)
    for tick, group in sorted(by_tick.items()):
        chord = chords[group[0]['chord_id']]; voiced = compact_voicing(chord['pitch_classes'], 70)
        by_pc = {p % 12: p for p in voiced}; used = set()
        # 相似乐句和弦框架复用：新增按独立键盘音区分配指号，不把所有右手音随意标成3指。
        finger_order = {2: (1, 5), 3: (1, 3, 5), 4: (1, 2, 3, 5), 5: (1, 2, 3, 4, 5)}.get(len(voiced), (1,)*len(voiced))
        by_finger = dict(zip(sorted(voiced), finger_order))
        for slot in group:
            bass = slot['role'] == 'bass'; pc = slot['pitch_midi'] % 12
            pitch = 36+pc if bass else by_pc[pc]; hand = 'left' if bass else 'right'
            if (hand, pitch) in used: continue
            used.add((hand, pitch))
            if any(n['hand'] == hand and n['pitch_midi'] == pitch and n['start_tick'] <= tick < n['end_tick'] for n in fixed):
                continue
            note = {k: deepcopy(v) for k, v in slot.items() if k not in
                    ('string', 'fret', 'pattern_baseline_frets', 'pattern_string_map', 'path_octave_adjustment')}
            # 相似乐句和弦框架复用：修改，原固定3指保留；音符及节奏不变，指号跟实际右手配音。
            # note.update(id='piano_phrase_'+slot['id'], pitch_midi=pitch, hand=hand, finger=5 if bass else 3)
            note.update(id='piano_phrase_'+slot['id'], pitch_midi=pitch, hand=hand, finger=5 if bass else by_finger[pitch])
            conflicts = [n['start_tick'] for n in fixed if n['hand'] == hand and n['pitch_midi'] == pitch
                         and tick < n['start_tick'] < note['end_tick']]
            note['end_tick'] = min(note['end_tick'], min(conflicts, default=note['end_tick']))
            result.append(note)
    # 相似乐句和弦框架复用：新增同键重起释放，只动新音；保留所有固定器乐起止。
    for hand in ('left', 'right'):
        for pitch in {n['pitch_midi'] for n in result if n['hand'] == hand}:
            ns = sorted([n for n in result if n['hand'] == hand and n['pitch_midi'] == pitch], key=lambda n: n['start_tick'])
            for before, after in zip(ns, ns[1:]): before['end_tick'] = min(before['end_tick'], after['start_tick'])
    return sorted(deepcopy(fixed)+result, key=lambda n: (n['start_tick'], n['hand'], n['pitch_midi']))


# 乐句钢琴持续配音通用修复：新增重配后完整手位门槛，失败时复用通用八度搜索，只调整新和弦内声。
def phrase_piano_positions(piano, clock, fixed):
    try:
        return piano_hand_positions(piano['notes'], clock)
    except ValueError as error:
        if not (str(error).startswith('钢琴持续按键没有单手八度手位') or
                str(error).startswith('钢琴left换位超速') or str(error).startswith('钢琴right换位超速')):
            raise
    from accompaniment_arrange import plan_piano_inner_register
    fixed_by_id = {n['id']: n for n in fixed}; notes = piano['notes']; repairs = []
    # 乐句钢琴持续配音通用修复：新增本次新编低音ID，固定原器乐持续音不能因唱段首音改写。
    generated_bass = {n['id'] for n in notes if n['role'] == 'bass' and n['id'] not in fixed_by_id}
    for hand in ('left', 'right'):
        # 乐句钢琴持续配音通用修复：修改固定所有低音的旧调用，原行保留；新低音同音级换八度须通过完整手位时序。
        # notes, changes = plan_piano_inner_register(notes, clock, hand, locked_ids=fixed_by_id)
        notes, changes = plan_piano_inner_register(notes, clock, hand, locked_ids=fixed_by_id, generated_bass_ids=generated_bass)
        repairs.extend(changes)
    if any(n != fixed_by_id[n['id']] for n in notes if n['id'] in fixed_by_id):
        raise ValueError('乐句钢琴配音不得改变固定器乐音。')
    positions = piano_hand_positions(notes, clock)
    piano['notes'] = notes; piano['adjustments'].extend(repairs)
    return positions


def merged_events(original, fixed, new):
    fixed_ticks = {n['start_tick'] for n in fixed}
    events = {e['start_tick']: deepcopy(e) for e in original['attack_events'] if e['start_tick'] in fixed_ticks}
    events.update({e['start_tick']: e for e in new})
    return [events[t] for t in sorted(events)]


# 相似乐句和弦框架复用：新增踏板边界状态恢复，不能让唱段新踏板误截原器乐延响。
def arranged_pedal(shared, original, notes):
    editable = [(p['start_tick'], p['end_tick']) for p in shared['phrase_harmony_plan']['phrases']
                if not p['action'].startswith('preserve_source')]
    old = sorted(deepcopy(original), key=lambda e: (e['tick'], e['value']))
    if not editable:return old
    result = [e for e in old if not any(a <= e['tick'] < b for a, b in editable)]
    for chord in shared['harmony']:
        if (chord.get('phrase_id') and any(a <= chord['start_tick'] < b for a, b in editable)
                and any(n.get('phrase_harmony_generated') and n['chord_id'] == chord['id'] for n in notes)):
            result.extend([{'tick': chord['start_tick'], 'value': 127, 'chord_id': chord['id']},
                           {'tick': chord['end_tick'], 'value': 0, 'chord_id': chord['id']}])
    for _, finish in editable:
        if any(a <= finish < b for a, b in editable):continue
        if not any(e['tick'] == finish for e in old):
            state = next((e['value'] for e in reversed(old) if e['tick'] <= finish), 0)
            result.append({'tick': finish, 'value': state, 'reason': 'restore_preserved_instrumental_pedal_state'})
    return sorted(result, key=lambda e: (e['tick'], e['value']))


# 相似乐句和弦框架复用：新增明确升级入口，普通编辑重导不自动重配，已应用工程保持人工音符。
def apply_phrase_harmony(shared, vocal, arrangements, cache_dir=None):
    existing = shared.get('phrase_harmony_plan', {})
    if ('arranged_harmony' in shared and existing.get('version') == POLICY['version']
            and existing.get('source_shared_sha256') == shared_fingerprint(shared)
            # 相似乐句和弦框架复用：修改，旧单音符摘要保留；旋律/时间轴/调性均需一致。
            # and existing.get('source_vocal_sha256') == fingerprint(vocal['quantized_notes'])
            and existing.get('source_vocal_sha256') == vocal_fingerprint(vocal)
            and all(a.get('phrase_harmony_performance', {}).get('source_shared_sha256') == existing['source_shared_sha256']
                    for a in arrangements.values())):
        return shared, arrangements, validate_phrase_harmony(shared, vocal, arrangements)
    fresh = deepcopy(shared); plan = build_phrase_harmony(shared, vocal)
    fresh['arranged_harmony'] = plan.pop('arranged_harmony'); fresh['phrase_harmony_plan'] = plan
    if not plan['phrases']:
        return fresh, deepcopy(arrangements), {'valid': True, 'errors': [], 'status': plan['status'], 'changed': False}
    # 连续源拍序与人声联合重解通用修复：修改，旧直接锁定边界续音保留；新版先明确普通伴奏交接，再建立保护账本。
    # active = arrangement_view(fresh, vocal); originals = deepcopy(arrangements); result = deepcopy(arrangements)
    from continuous_accompaniment_seed import release_ordinary_boundary_tails
    active = arrangement_view(fresh, vocal)
    # 尾段原声局部补证：修改首次原型普通伴奏进入完整拍时释放前一原型续音，避免新首拍低音被自身旧尾音挤掉；器乐持续音保持。
    # originals = release_ordinary_boundary_tails(active, deepcopy(arrangements)); result = deepcopy(originals)
    originals = release_ordinary_boundary_tails(active, deepcopy(arrangements),
        first_source=bool(vocal.get('first_source_meter_correction'))); result = deepcopy(originals)
    guitar = result['guitar']; config = guitar['configuration']
    config.update(rows_measures=4, beat_synchronous_patterns=True,
                  regular_rhythm_policy={'name': 'phrase_harmony_regular_arpeggio', 'version': 2})
    for key in DERIVED_GUITAR: guitar.pop(key, None)
    plans = rhythm_plans(active, vocal, guitar, cache_dir)
    guitar['ornament_display'] = {'version': 1, 'aliases': ornament_aliases(active)}
    # 相似乐句和弦框架复用：修改，旧只保护器乐保留；共同视图的缺证据乐句也保留整段源音。
    # fixed = {name: [deepcopy(n) for n in a['notes'] if not ordinary(shared, n)] for name, a in originals.items()}
    fixed = {name: [deepcopy(n) for n in a['notes'] if not ordinary(active, n)] for name, a in originals.items()}
    # 连续源拍序与人声联合重解通用修复：修改，旧固定起号保留；历史编配重编时不能撞上保留的旧ID。
    # ns, es, rows, serial = generate_slots(active, vocal, originals['guitar'], config, plans, fixed['guitar'], 700000)
    ns, es, rows, serial = generate_slots(active, vocal, originals['guitar'], config, plans, fixed['guitar'],
                                          next_note_serial(originals['guitar']['notes'], 700000))
    if rows:
        serial = complete_quality(active, ns, es, rows, config['capo_fret'], serial, guitar=guitar)
    # 相似乐句和弦框架复用：新增补充性质音亦纳入实际和声校验，不能漏验新加七音/三音。
    for n in ns:n['phrase_harmony_generated']=True
    ns, es, rows, repairs = repair_guitar(active, vocal, guitar, fixed['guitar'], ns, es, rows)
    guitar['attack_events'] = merged_events(originals['guitar'], fixed['guitar'], es)
    guitar['right_hand_patterns'] = {'phrases': plans, 'measures': rows, 'changed_measures': sorted({r['measure'] for r in rows}),
        'applied_this_run': sorted({r['measure'] for r in rows}), 'source_notes': deepcopy(originals['guitar']['notes']),
        'protected_note_ids': [n['id'] for n in fixed['guitar']], 'protected_notes_unchanged': True,
        'skipped_measures': [], 'playability_fallbacks': repairs}
    guitar['regular_rhythm'] = {'version': 2, 'changed_measures': guitar['right_hand_patterns']['changed_measures'],
        'preserved_notes': deepcopy(fixed['guitar']), 'preserved_note_ids': [n['id'] for n in fixed['guitar']],
        'source_notes': deepcopy(originals['guitar']['notes']), 'exceptions': [], 'fragments': [], 'fragment_failures': repairs}
    if all(p['pattern_id'] == 'meter_basic_arpeggio' for p in plans):
        # 相似乐句和弦框架复用：新增其它拍号专用审计，不冒用4/4模板验证字段。
        guitar.pop('right_hand_patterns', None); guitar.pop('regular_rhythm', None); guitar.pop('structure_stability', None)
    guitar['chord_charts'] = []
    # 连续源拍序与人声联合重解通用修复：修改，旧固定钢琴槽ID保留；钢琴历史源音同样避开复用ID。
    # pslots, pevents, _, _ = generate_slots(active, vocal, originals['piano'], config, plans, fixed['piano'], 900000)
    # 渴首次吉他编配：修改，和弦复用只编配实际请求的钢琴；原代码注释保留。
    # pslots, pevents, _, _ = generate_slots(active, vocal, originals['piano'], config, plans, fixed['piano'],
    #                                       next_note_serial(originals['piano']['notes'], 900000))
    # piano = result['piano']; piano['notes'] = piano_voicing(active, piano, pslots, fixed['piano'])
    # piano['attack_events'] = merged_events(originals['piano'], fixed['piano'], pevents)
    # piano['hand_positions'] = piano_hand_positions(piano['notes'], SongClock(vocal))
    # # 相似乐句和弦框架复用：修改，旧直接删除演唱踏板保留；器乐起点及弱证据句恢复源踏板状态。
    # # vocal_ranges = [(s['start_tick'], s['end_tick']) for s in shared['sections'] if s['kind'] == 'vocal']
    # # piano['pedal'] = [deepcopy(e) for e in originals['piano'].get('pedal', [])
    # #                   if not any(a <= e['tick'] < b for a, b in vocal_ranges)]
    # # for chord in active['harmony']:
    # #     if chord.get('phrase_id') and any(chord['start_tick'] <= n['start_tick'] < chord['end_tick'] for n in piano['notes']):
    # #         piano['pedal'].extend([{'tick': chord['start_tick'], 'value': 127, 'chord_id': chord['id']},
    # #                                {'tick': chord['end_tick'], 'value': 0, 'chord_id': chord['id']}])
    # # piano['pedal'].sort(key=lambda e: (e['tick'], e['value']))
    # piano['pedal'] = arranged_pedal(active, originals['piano'].get('pedal', []), piano['notes'])
    # 渴首次吉他编配：新增按所选乐器执行，保留各乐器原验证。
    if 'piano' in result:
        pslots, pevents, _, _ = generate_slots(active, vocal, originals['piano'], config, plans, fixed['piano'],
                                              next_note_serial(originals['piano']['notes'], 900000))
        piano = result['piano']; piano['notes'] = piano_voicing(active, piano, pslots, fixed['piano'])
        piano['attack_events'] = merged_events(originals['piano'], fixed['piano'], pevents)
        # 乐句钢琴持续配音通用修复：修改重配后只检查不搜索的旧入口，原调用保留；固定器乐音及按键／换位门限不变。
        # piano['hand_positions'] = piano_hand_positions(piano['notes'], SongClock(vocal))
        piano['hand_positions'] = phrase_piano_positions(piano, SongClock(vocal), fixed['piano'])
        # 相似乐句和弦框架复用：修改，旧直接删除演唱踏板保留；器乐起点及弱证据句恢复源踏板状态。
        # vocal_ranges = [(s['start_tick'], s['end_tick']) for s in shared['sections'] if s['kind'] == 'vocal']
        # piano['pedal'] = [deepcopy(e) for e in originals['piano'].get('pedal', [])
        #                   if not any(a <= e['tick'] < b for a, b in vocal_ranges)]
        # for chord in active['harmony']:
        #     if chord.get('phrase_id') and any(chord['start_tick'] <= n['start_tick'] < chord['end_tick'] for n in piano['notes']):
        #         piano['pedal'].extend([{'tick': chord['start_tick'], 'value': 127, 'chord_id': chord['id']},
        #                                {'tick': chord['end_tick'], 'value': 0, 'chord_id': chord['id']}])
        # piano['pedal'].sort(key=lambda e: (e['tick'], e['value']))
        piano['pedal'] = arranged_pedal(active, originals['piano'].get('pedal', []), piano['notes'])
    for name, arrangement in result.items():
        arrangement['phrase_harmony_performance'] = {'version': POLICY['version'],
            'source_shared_sha256': plan['source_shared_sha256'], 'source_notes': deepcopy(originals[name]['notes']),
            # 相似乐句和弦框架复用：新增源踏板审计，持音释放位置可在交付后独立比较。
            'source_pedal': deepcopy(originals[name].get('pedal', [])),
            'protected_notes': deepcopy(fixed[name]), 'raw_harmony_preserved': True,
            'ordinary_rearrangement': True, 'rhythm_plans': deepcopy(plans)}
        # 跨曲低音与强拍复用通用修复：新增空段验收版本，旧工程重导按原契约保持；真实器乐遮挡和休止仍可为空。
        arrangement['phrase_harmony_performance']['coverage_version'] = 2
        arrangement['configuration']['phrase_harmony_policy'] = deepcopy(POLICY)
        arrangement['adjustments'].append({'type': 'joint_phrase_harmony_rearrangement',
            'source_note_count': len(originals[name]['notes']), 'new_note_count': len(arrangement['notes']),
            'protected_note_count': len(fixed[name]), 'guitar_transition_rests': repairs if name == 'guitar' else []})
        check = validate_playability(arrangement, SongClock(vocal))
        if not check['valid']: raise ValueError(name+'共同和弦实际演奏失败：'+str(check['errors'][:8]))
    check = validate_phrase_harmony(fresh, vocal, result)
    if not check['valid']: raise ValueError('乐句共同和弦实音校验失败：'+str(check['errors'][:8]))
    return fresh, result, check


# 相似乐句和弦框架复用：新增实音独立核查，篡改音高/拍位/器乐不能靠改显示标签过关。
def validate_phrase_harmony(shared, vocal, arrangements):
    # 原声覆盖与选音归属通用修复：新增先核验认可段落与新编配合并，再重放共同和声基础，实际输出仍独立读回。
    if shared.get('approved_section_preservation'):
        from approved_music_sections import verified_base
        try:
            base = verified_base(shared,vocal,arrangements)
            check = validate_phrase_harmony(base['shared_analysis'],base['accepted_vocal_project'],base['arrangements'])
            return {**check,'approved_sections_verified':True}
        except (OSError,KeyError,ValueError) as exc:
            return {'valid':False,'errors':['approved_section_harmony_invalid:'+str(exc)]}
    # 器乐背景休止与旋律突出：新增旧共同和弦和保护音完整在实际源工程核查，新休止／力度另按表现层重放。
    if arrangements.get('guitar',{}).get('instrumental_expression'):
        from guitar_instrumental_expression import expression_parent,validate_expression
        try:
            parent={**arrangements,'guitar':expression_parent(arrangements['guitar'])['arrangements']['guitar']}
            upstream=validate_phrase_harmony(shared,vocal,parent)
            current=validate_expression(shared,vocal,arrangements['guitar'])
            errors=upstream['errors']+current['errors']
            return {**upstream,'valid':not errors,'errors':errors,'instrumental_expression':current}
        except (OSError,KeyError,ValueError,TypeError) as exc:
            return {'valid':False,'errors':['instrumental_expression_joint_source_invalid:'+str(exc)]}
    errors = []; active = arrangement_view(shared, vocal); harmony = active['harmony']
    identities = {h['id']: h for h in harmony}
    # 相似乐句和弦框架复用：新增性质、名称与绝对时钟独立一致性，不能把标签当作实音真值。
    clock = SongClock(vocal)
    for h in harmony:
        # 相似乐句和弦框架复用：修改，旧把未识别N.C.候选当确定和弦保留；明确未知段保留源语义。
        # if h['quality'] not in CHORD_TYPES or set(h['pitch_classes']) != {
        #         (h['root_pc']+p) % 12 for p in CHORD_TYPES.get(h['quality'], [])}:
        if h['name'] != 'N.C.' and (h['quality'] not in CHORD_TYPES or set(h['pitch_classes']) != {
                (h['root_pc']+p) % 12 for p in CHORD_TYPES.get(h['quality'], [])}):
            errors.append('performed_chord_quality_pitch_classes_mismatch:'+h['id'])
        # 相似乐句和弦框架复用：修改，原名称比较保留；N.C.不强行改成内部弱候选的名称。
        # if h['name'] != chord_name(h['root_pc'], h['quality'], h['bass_pc'], h['key']):
        if h['name'] != 'N.C.' and h['name'] != chord_name(h['root_pc'], h['quality'], h['bass_pc'], h['key']):
            errors.append('performed_chord_name_mismatch:'+h['id'])
        if h['end_tick'] <= h['start_tick']: errors.append('performed_chord_nonpositive_duration:'+h['id'])
        for field in ('start', 'end'):
            if abs(h.get(field+'_seconds', clock.seconds(h[field+'_tick']))-clock.seconds(h[field+'_tick'])) > 1e-8:
                errors.append('performed_chord_clock_mismatch:'+h['id'])
    if len(identities) != len(harmony): errors.append('duplicate_performed_harmony_id')
    if harmony and (harmony[0]['start_tick'] != shared['harmony'][0]['start_tick']
                    or harmony[-1]['end_tick'] != shared['harmony'][-1]['end_tick']):
        errors.append('performed_harmony_extent_changed')
    for a, b in zip(harmony, harmony[1:]):
        if a['end_tick'] != b['start_tick']: errors.append('performed_harmony_gap_or_overlap')
    # 相似乐句和弦框架复用：新增复用账本对照真实和弦跨度，拒绝仅改元数据宣称共用。
    families = {f['id']: f for f in shared['phrase_harmony_plan']['families']}
    for p in shared['phrase_harmony_plan']['phrases']:
        if p['action'].startswith('preserve_source'): continue
        spans = [h for h in harmony if h.get('phrase_id') == p['id']]
        observed = [{'offset_tick': h['start_tick']-p['start_tick'], 'duration_ticks': h['end_tick']-h['start_tick'],
                     'root_degree_pc': (h['root_pc']-h['key']['tonic_pc']) % 12, 'quality': h['quality'],
                     'bass_pc': h['bass_pc'], 'name': h['name']} for h in spans]
        if observed != p['progression']:errors.append('performed_progression_audit_mismatch:'+p['id'])
        if p['action'] == 'shared_progression':
            for row in families[p['family_id']]['prototype']:
                chord = next((h for h in spans if h['start_tick'] <= p['start_tick']+row['offset_tick'] < h['end_tick']), None)
                if not chord or ((chord['root_pc']-chord['key']['tonic_pc']) % 12, chord['quality']) != (row['root_degree_pc'], row['quality']):
                    errors.append('performed_family_prototype_mismatch:'+p['id'])
        if p['action'] == 'supported_local_variant' and any(not x['witness']['supported'] for x in p['variants']):
            errors.append('unsupported_local_harmony_variant:'+p['id'])
    instruments = {}
    for name, arrangement in arrangements.items():
        info = arrangement.get('phrase_harmony_performance', {}); present = {n['id']: n for n in arrangement['notes']}
        # 吉他器乐低把位与指型复用：新增明确的后续器乐派生核验，不能删除旧保护来源清单来绕过检查。
        from guitar_instrumental_register import projected_source_note,validate_instrumental_register
        register_check=validate_instrumental_register(shared,vocal,arrangement) if name=='guitar' else None
        if register_check and not register_check['valid']:
            errors.extend('guitar:register:'+e for e in register_check['errors'])
        # 原曲器乐旋律骨干重提取：新增音频来源修订验收，旧主线有完整授权修订证据才允许替换。
        from instrumental_source_melody import validate_source_backbone,superseded_ids
        backbone_check=validate_source_backbone(shared,vocal,arrangement) if name=='guitar' else None
        if backbone_check and not backbone_check['valid']:
            errors.extend('guitar:source_backbone:'+e for e in backbone_check['errors'])
        replaced=superseded_ids(arrangement,backbone_check)
        for old in info.get('protected_notes', []):
            # 原曲器乐旋律骨干重提取：新增保留原账本，只跳过经音频证据核验且明确被替换的旧主线音。
            if old['id'] in replaced:continue
            # 吉他器乐低把位与指型复用：修改，保留旧实音比较；仅在严格绑定的器乐派生音上接受新八度／弦品。
            # if old['id'] not in present or music(present[old['id']]) != music(old): errors.append(name+':protected_music_changed:'+old['id'])
            expected=projected_source_note(old,arrangement) if name=='guitar' and register_check and register_check['valid'] else old
            if old['id'] not in present or music(present[old['id']]) != music(expected): errors.append(name+':protected_music_changed:'+old['id'])
        # 相似乐句和弦框架复用：新增由升级前源音重建保护集合，删除保护清单也不能掩盖器乐丢失。
        expected_protected = {n['id']: music(n) for n in info.get('source_notes', []) if not ordinary(active, n)}
        if expected_protected != {n['id']: music(n) for n in info.get('protected_notes', [])}:
            errors.append(name+':protected_source_ledger_mismatch')
        # 相似乐句和弦框架复用：新增器乐/缺证据范围的踏板状态证明，音符不变仍可能被新踏板截音。
        if name == 'piano' and 'source_pedal' in info:
            editable = [(p['start_tick'], p['end_tick']) for p in shared['phrase_harmony_plan']['phrases']
                        if not p['action'].startswith('preserve_source')]
            old_pedal = sorted(info['source_pedal'], key=lambda e: (e['tick'], e['value']))
            new_pedal = sorted(arrangement.get('pedal', []), key=lambda e: (e['tick'], e['value']))
            ticks = sorted({e['tick'] for e in old_pedal+new_pedal} | {b for _, b in editable})
            for tick in ticks:
                if any(a <= tick < b for a, b in editable):continue
                before = next((e['value'] for e in reversed(old_pedal) if e['tick'] <= tick), 0)
                after = next((e['value'] for e in reversed(new_pedal) if e['tick'] <= tick), 0)
                if before != after:errors.append('piano:protected_pedal_state_changed:'+str(tick))
        count = 0
        for note in arrangement['notes']:
            if not note.get('phrase_harmony_generated'): continue
            count += 1; chord = identities.get(note['chord_id'])
            if (not chord or not chord['start_tick'] <= note['start_tick'] < chord['end_tick']
                    or note['pitch_midi'] % 12 not in set(chord['pitch_classes']) | {chord['bass_pc']}):
                errors.append(name+':performed_note_harmony_mismatch:'+note['id'])
            if chord and (note['end_tick'] > chord['end_tick'] or note['end_tick'] <= note['start_tick']):
                errors.append(name+':performed_note_duration_mismatch:'+note['id'])
            if chord and note['role'] == 'bass' and note['pitch_midi'] % 12 != chord['bass_pc']:
                errors.append(name+':performed_bass_mismatch:'+note['id'])
        # 相似乐句和弦框架复用：新增每个真正有新伴奏的和弦入口必须先弹正拍低音；休止不强行填满。
        pulse = int(PPQ*4/shared['timing']['meter'][1])
        for h in harmony:
            group = [n for n in arrangement['notes'] if n.get('phrase_harmony_generated') and n['chord_id'] == h['id']]
            # 跨曲低音与强拍复用通用修复：修改，原空段跳过会把漏音判为休止；有源普通攻击且可编辑时必须有实音。
            # if not group:continue
            if not group:
                if info.get('coverage_version') == 2 and h.get('phrase_id'):
                    required = [n for n in info.get('source_notes', []) if ordinary(active, n)
                                and h['start_tick'] <= n['start_tick'] < h['end_tick']]
                    allowed = available_ranges(active, h['start_tick']//pulse*pulse,
                        math.ceil(h['end_tick']/pulse)*pulse, info.get('protected_notes', []), pulse)
                    if any(any(a <= n['start_tick'] < b for a,b in allowed) for n in required):
                        errors.append(name+':source_backed_chord_entry_missing:'+h['id'])
                continue
            first = min(n['start_tick'] for n in group)
            if first % pulse or not any(n['start_tick'] == first and n['role'] == 'bass' and n['pitch_midi'] % 12 == h['bass_pc'] for n in group):
                errors.append(name+':performed_chord_entry_not_pulse_bass:'+h['id'])
        instruments[name] = {'generated_notes': count, 'protected_notes': len(info.get('protected_notes', []))}
    return {'valid': not errors, 'errors': errors, 'status': 'actual_joint_harmony_checked',
            'changed': True, 'raw_harmony_count': len(shared['harmony']), 'performed_harmony_count': len(harmony),
            'phrases': len(shared['phrase_harmony_plan']['phrases']),
            'reused_families': sum(len(f['members']) > 1 for f in shared['phrase_harmony_plan']['families']),
            'instruments': instruments}
