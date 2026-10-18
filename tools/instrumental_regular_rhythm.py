"""器乐声部恢复与规整节奏：保留旋律、低音及和声，在编配层整理共同拍格。"""
# 器乐声部恢复与规整节奏：新增可跨曲复用的策略，不读取曲名、小节答案或人工音符表。
from __future__ import annotations
from collections import Counter, defaultdict
from copy import deepcopy
import math
from accompaniment_analysis import SongClock
# 器乐声部恢复与规整节奏：修改，保留旧导入；跨换夹起音需要实际定弦换算。
# from accompaniment_arrange import grip_info, piano_hand_positions, validate_playability
from accompaniment_arrange import TUNING, grip_info, piano_hand_positions, validate_playability
from guitar_grip_policy import grip_position_path
# 器乐声部恢复与规整节奏：修改，旧导入保留；新起音也按实际生效夹位计算相对品数。
# from guitar_capo import fret_at
from guitar_capo import capo_at, fret_at
# 器乐声部恢复与规整节奏：新增与整个工程相同的四分拍单位；timing不是PPQ存储位置。
from score_export import PPQ

POLICY = {
    'version': 1, 'mode': 'full_texture_regular_rhythm',
    'scope': ['intro', 'interlude', 'outro'],
    'minimum_division_of_quarter': 4,
    'preferred_division_of_quarter': 2,
    'maximum_melody_displacement_quarters': 1,
    'preserve_distinct_melody_order': True,
    'preserve_bass_attacks': True,
    'short_same_pitch_repetition': 'merge_only_below_minimum_note_value',
    'quality_status': 'automatic_arrangement_requires_listening',
}
MUSIC_FIELDS = ('id', 'pitch_midi', 'start_tick', 'end_tick', 'velocity', 'role', 'string', 'fret', 'hand')


# 器乐声部恢复与规整节奏：新增实际半开段落边界，混合小节的演唱音仍为不可修改的固定音。
def sections_for(shared):
    return [s for s in shared.get('sections', []) if s['kind'] in POLICY['scope']]


# 器乐声部恢复与规整节奏：新增半开范围判断，避免段尾首个人声音被归入器乐。
def in_section(note, section):
    return section['start_tick'] <= note['start_tick'] < section['end_tick']


# 器乐声部恢复与规整节奏：新增短同音连发归并；普通八分/十六分重复与低音攻击完整保留。
def coalesce_short_repetitions(notes, grid, instrument):
    lanes = defaultdict(list)
    for note in notes:
        lane = ('melody',) if note['role'] == 'instrumental_melody' else (
            note['role'], note.get('string') if instrument == 'guitar' else note.get('hand'), note['pitch_midi'])
        lanes[lane].append(note)
    result, audit = [], []
    for lane in lanes.values():
        previous = None
        for note in sorted(lane, key=lambda n: (n['start_tick'], n['id'])):
            if (previous and note['role'] != 'bass' and previous['pitch_midi'] == note['pitch_midi']
                    and 0 < note['start_tick'] - previous['start_tick'] < grid
                    and previous['end_tick'] - previous['start_tick'] < grid
                    and note['end_tick'] - note['start_tick'] < grid):
                previous['end_tick'] = max(previous['end_tick'], note['end_tick'])
                previous.setdefault('regularized_merged_ids', []).append(note['id'])
                audit.append({'type': 'merge_sub_sixteenth_same_pitch_repetition', 'note_id': note['id'],
                              'into_note_id': previous['id'], 'pitch_midi': note['pitch_midi']})
            else:
                result.append(note)
                previous = note
    return sorted(result, key=lambda n: (n['start_tick'], n['id'])), audit


# 器乐声部恢复与规整节奏：新增有序音序的最小改动动态规划；保留音高顺序而非各自取整导致挤音。
def ordered_grid(onsets, section, grid, quarter, prefer_strength=0.035):
    if not onsets:
        return {}
    low = math.ceil(section['start_tick'] / grid) * grid
    high = math.floor(section['end_tick'] / grid) * grid - grid
    candidates, costs, traces = [], [], []
    for i, onset in enumerate(onsets):
        values = [t for t in range(max(low, math.ceil((onset-quarter) / grid) * grid),
                                  min(high, math.floor((onset+quarter) / grid) * grid) + 1, grid)]
        current, trace = [], []
        for tick in values:
            # 器乐声部恢复与规整节奏：新增八分/正拍软偏好，不为整齐而反转音序或抹掉必需的十六分。
            local = ((tick-onset)/grid)**2 + (prefer_strength if tick % (grid*2) else 0)
            if i == 0:
                current.append(local); trace.append(-1)
                continue
            choices = [(costs[-1][j], j) for j, old in enumerate(candidates[-1]) if old+grid <= tick]
            best, parent = min(choices, default=(math.inf, -1))
            current.append(best+local); trace.append(parent)
        if not current or not any(math.isfinite(c) for c in current):
            raise ValueError('器乐旋律在一个四分拍的容许整理范围内无法保留音序；拒绝自动删掉异音。')
        candidates.append(values); costs.append(current); traces.append(trace)
    best = min(range(len(costs[-1])), key=costs[-1].__getitem__)
    chosen = [best]
    for trace in traces[:0:-1]:
        best = trace[best]; chosen.append(best)
    chosen.reverse()
    return {onset: candidates[i][j] for i, (onset, j) in enumerate(zip(onsets, chosen))}


# 器乐声部恢复与规整节奏：新增常规非附点持续音；实际延音仍由后续持音和换把限制决定。
def regular_duration(duration, grid):
    values = [grid*(2**i) for i in range(8)]
    return min(values, key=lambda d: (abs(d-duration), d))


# 器乐声部恢复与规整节奏：新增攻击组静态可覆盖检查，同时固定段落外正在按住的音。
def attack_fits(instrument, current, fixed, arrangement, tick):
    all_notes = current + [n for n in fixed if n['start_tick'] <= tick < n['end_tick']]
    if instrument == 'guitar':
        # 器乐声部恢复与规整节奏：新增相对品数边界，移过换夹入口不能生成负品或超范围品数。
        if any(not 0 <= fret_at(n, arrangement, tick) <= arrangement['configuration'].get('maximum_fret', 20) for n in all_notes):
            return False
        if len({n['string'] for n in all_notes}) != len(all_notes):
            return False
        return grip_info({n['string']: fret_at(n, arrangement, tick) for n in all_notes}) is not None
    for hand in ('left', 'right'):
        pitches = [n['pitch_midi'] for n in all_notes if n['hand'] == hand]
        if pitches and (len(pitches) != len(set(pitches)) or len(pitches) > 5 or max(pitches)-min(pitches) > 12):
            return False
    return True


# 器乐声部恢复与规整节奏：新增移动起音时按夹位重算相对品数，实际音高保持。
def moved_attack(note, tick, arrangement):
    result = {**note, 'start_tick': tick}
    if arrangement['instrument'] == 'guitar':
        result['fret'] = note['pitch_midi']-TUNING[note['string']]-capo_at(arrangement, tick)
    return result


# 器乐声部恢复与规整节奏：新增保留次声部的近邻插入，不把低音及和声当作主线噪声丢弃。
def arrange_section(instrument, notes, fixed, section, arrangement, quarter):
    grid = quarter // POLICY['minimum_division_of_quarter']
    notes, audit = coalesce_short_repetitions(deepcopy(notes), grid, instrument)
    melody = [n for n in notes if n['role'] == 'instrumental_melody']
    mapping = ordered_grid(sorted({n['start_tick'] for n in melody}), section, grid, quarter)
    # 器乐声部恢复与规整节奏：新增独立低音音序，不因邻近冲突把后一个根音安排到前一个之前。
    bass_mapping = ordered_grid(sorted({n['start_tick'] for n in notes if n['role'] == 'bass'}),
                                section, grid, quarter, prefer_strength=0.15)
    groups = defaultdict(list)
    source = {n['id']: deepcopy(n) for n in notes}
    low = math.ceil(section['start_tick']/grid)*grid
    high = math.floor(section['end_tick']/grid)*grid-grid
    for note in melody:
        # 器乐声部恢复与规整节奏：修改，旧直接赋起音保留；跨换夹同步重算弦品。
        # old = note['start_tick']; note['start_tick'] = mapping[old]
        old = note['start_tick']; note.update(moved_attack(note, mapping[old], arrangement))
        groups[note['start_tick']].append(note)
    for tick, values in groups.items():
        if not attack_fits(instrument, values, fixed, arrangement, tick):
            raise ValueError(f'器乐旋律整理后与受保护声部不能同奏：{tick}')
    # 器乐声部恢复与规整节奏：新增低音优先、和声次之；共同原攻击优先共同整理位置，必要时留出分解槽位。
    secondary = sorted((n for n in notes if n['role'] != 'instrumental_melody'),
                       key=lambda n: (n['role'] != 'bass', n['start_tick'], n['id']))
    previous_bass_tick = None; previous_bass_source_tick = None
    for note in secondary:
        # 器乐声部恢复与规整节奏：修改，旧共同旋律锚点优先保留；低音用自己的有序拍格保持根音走向。
        # old = note['start_tick']; anchor = mapping.get(old, round(old/grid)*grid)
        old = note['start_tick']; anchor = (bass_mapping[old] if note['role'] == 'bass' else mapping.get(old, round(old/grid)*grid))
        options = list(range(max(low, math.ceil((old-quarter)/grid)*grid),
                             min(high, math.floor((old+quarter)/grid)*grid)+1, grid))
        options.sort(key=lambda t: (abs(t-old)/grid + (0.1 if t % (grid*2) else 0)
                                   + (0 if t == anchor else 0.05), abs(t-anchor), t))
        # 器乐声部恢复与规整节奏：修改，旧未验证低音顺序的插入保留；候选按生效夹位和低音先后约束。
        # selected = next((t for t in options if attack_fits(instrument, groups[t]+[note], fixed, arrangement, t)), None)
        if note['role'] == 'bass' and previous_bass_tick is not None:
            options = [t for t in options if t >= previous_bass_tick+(grid if old != previous_bass_source_tick else 0)]
        selected = next((t for t in options if attack_fits(instrument, groups[t]+[moved_attack(note, t, arrangement)], fixed, arrangement, t)), None)
        if selected is None:
            raise ValueError(f'规整器乐拍格无法保留{note["role"]}：{note["id"]}')
        # 器乐声部恢复与规整节奏：修改，旧直接赋值保留；提交完整相对弦品并保存低音顺序。
        # note['start_tick'] = selected; groups[selected].append(note)
        note.update(moved_attack(note, selected, arrangement)); groups[selected].append(note)
        if note['role'] == 'bass':
            previous_bass_tick = selected; previous_bass_source_tick = old
    output = [n for tick in sorted(groups) for n in sorted(groups[tick], key=lambda n: n['id'])]
    for note in output:
        old = source[note['id']]
        duration = regular_duration(old['end_tick']-old['start_tick'], grid)
        note['end_tick'] = min(note['start_tick']+duration, math.floor(section['end_tick']/grid)*grid)
        # 器乐声部恢复与规整节奏：新增换夹处释放旧器乐按弦，不能让滑动夹改变原持音音高。
        if instrument == 'guitar':
            changes = [s['start_tick'] for s in arrangement['configuration'].get('capo_segments', [])
                       if note['start_tick'] < s['start_tick'] < note['end_tick']]
            if changes:
                note['end_tick'] = math.floor(min(changes)/grid)*grid
        note['instrumental_rhythm_version'] = POLICY['version']
        note['instrumental_source_interval'] = [old['start_tick'], old['end_tick']]
        note['right_hand_duration_ticks'] = duration
        note['right_hand_duration_source'] = 'instrumental_regular_grid'
        audit.append({'type': 'regularize_instrumental_interval', 'note_id': note['id'],
                      'from': [old['start_tick'], old['end_tick']], 'to': [note['start_tick'], note['end_tick']]})
    return output, audit


# 器乐声部恢复与规整节奏：新增按真实持音释放器乐手指；固定演唱音绝不为了新编配截断。
def release_instrumental_conflicts(arrangement, editable, grid, audit):
    groups = defaultdict(list)
    for note in arrangement['notes']:
        groups[note['start_tick']].append(note)
    active = []
    instrument = arrangement['instrument']
    for tick, current in sorted(groups.items()):
        active = [n for n in active if n['end_tick'] > tick]
        while not attack_fits(instrument, active+current, [], arrangement, tick):
            candidates = [n for n in active if n['id'] in editable and tick-n['start_tick'] >= grid]
            if not candidates:
                raise ValueError(f'新器乐持续音与受保护声部冲突，不能自动截断演唱音：{tick}')
            # 器乐声部恢复与规整节奏：新增先结束被同弦/同键重奏的旧音，再释放次内声，不删除攻击。
            def rank(n):
                collision = any((n['string'] == new['string'] if instrument == 'guitar' else
                                 n['hand'] == new['hand'] and n['pitch_midi'] == new['pitch_midi']) for new in current)
                return (not collision, {'harmony': 0, 'bass': 1, 'instrumental_melody': 2}.get(n['role'], 3), n['start_tick'])
            old = min(candidates, key=rank)
            end = math.floor(tick/grid)*grid
            if end-old['start_tick'] < grid:
                raise ValueError('段落边界不能产生比十六分更短的器乐释音。')
            audit.append({'type': 'regular_grid_release_for_polyphony', 'note_id': old['id'],
                          'from_end_tick': old['end_tick'], 'to_end_tick': end})
            old['end_tick'] = end; active.remove(old)
        active += current


# 器乐声部恢复与规整节奏：新增规整格上的换把准备，禁止历史60tick最小释音偷偷生成32分。
# 器乐声部恢复与规整节奏：修改，保留无共享和声的入口；精确换弦后备也需要原和声候选。
# def prepare_guitar_path(arrangement, vocal, editable, grid, audit):
def prepare_guitar_path(arrangement, shared, vocal, editable, grid, audit):
    probe = {**arrangement, 'fingering_diagrams': []}
    check = grip_position_path(probe, vocal)
    for _ in range(len(editable)+1):
        if check['valid']:
            arrangement['hand_positions'] = check['positions']
            return check
        tick = check['tick']; best = None
        for note in arrangement['notes']:
            if note['id'] not in editable or not note['start_tick'] < tick <= note['end_tick']:
                continue
            old_end = note['end_tick']
            end = math.floor((tick-grid)/grid)*grid
            if end-note['start_tick'] < grid:
                continue
            note['end_tick'] = end
            trial = grip_position_path(probe, vocal)
            note['end_tick'] = old_end
            progress = math.inf if trial['valid'] else trial['tick']
            if progress > tick:
                rank = (old_end-end, note['role'] == 'instrumental_melody', note['role'] == 'bass')
                if best is None or rank < best[0]:
                    best = (rank, note, end, trial)
        if best is None:
            # 器乐声部恢复与规整节奏：新增短音不可再截时的整组移位，留一个完整16分准备槽；音序/音高不删。
            attack_ticks = sorted({n['start_tick'] for n in arrangement['notes'] if n['start_tick'] <= tick})
            attempts = [(tick, grid)]
            if len(attack_ticks) > 1:
                attempts.append((attack_ticks[-2], -grid))
            snapshot = deepcopy(arrangement['notes']); timing_best = None
            source_sections = sections_for(shared)
            for attack, shift in attempts:
                moving = [n for n in arrangement['notes'] if n['start_tick'] == attack]
                if not moving or any(n['id'] not in editable for n in moving):
                    continue
                if any(not any(s['start_tick'] <= n['start_tick']+shift and n['end_tick']+shift <= s['end_tick']
                               for s in source_sections) or
                       abs(n['start_tick']+shift-n['instrumental_source_interval'][0]) > PPQ for n in moving):
                    continue
                for n in moving:
                    n['start_tick'] += shift; n['end_tick'] += shift
                melody = sorted((n for n in arrangement['notes'] if n['id'] in editable and n['role'] == 'instrumental_melody'),
                                key=lambda n: n['instrumental_source_interval'][0])
                ordered = all(a['start_tick']+grid <= b['start_tick'] for a, b in zip(melody, melody[1:]))
                trial_audit = []
                try:
                    if not ordered:
                        raise ValueError('准备换把不能打乱旋律顺序。')
                    release_instrumental_conflicts(arrangement, editable, grid, trial_audit)
                    trial = grip_position_path(probe, vocal)
                    progress = math.inf if trial['valid'] else trial['tick']
                    if progress > tick:
                        rank = sum(abs(n['start_tick']-n.get('instrumental_source_interval', [n['start_tick']])[0])
                                   for n in arrangement['notes'] if n['id'] in editable)
                        if timing_best is None or rank < timing_best[0]:
                            timing_best = (rank, deepcopy(arrangement['notes']), trial,
                                           trial_audit+[{'type': 'regular_grid_shift_for_position_preparation',
                                                         'note_ids': [n['id'] for n in moving], 'from_tick': attack,
                                                         'to_tick': attack+shift}])
                except ValueError:
                    pass
                for n, old in zip(arrangement['notes'], snapshot):
                    n.clear(); n.update(deepcopy(old))
            if timing_best:
                for n, new in zip(arrangement['notes'], timing_best[1]):
                    n.clear(); n.update(new)
                audit.extend(timing_best[3]); check = timing_best[2]
                continue
            # 器乐声部恢复与规整节奏：新增精确同音换弦后备；结构保护模式保证不以历史细格释音代替。
            from guitar_exact_positions import refinger_exact_positions
            arrangement['fingering_diagrams'] = []
            # 器乐声部恢复与规整节奏：修改，保留空和声调用；不丢弃共享和声再尝试精确换弦。
            # refinger_exact_positions({}, vocal, arrangement)
            # 器乐声部恢复与规整节奏：修改，旧一次性后备保留；已前进到下一换把时交回规整格处理。
            # refinger_exact_positions(shared, vocal, arrangement)
            before_locations = {n['id']: (n.get('string'), n.get('fret')) for n in arrangement['notes']}
            try:
                refinger_exact_positions(shared, vocal, arrangement)
            except ValueError:
                trial = grip_position_path(probe, vocal)
                if trial['valid'] or trial['tick'] > tick:
                    audit.extend({'type': 'exact_pitch_refingering_with_regular_rhythm', 'note_id': n['id'],
                                  'from': list(before_locations[n['id']]), 'to': [n['string'], n['fret']]}
                                 for n in arrangement['notes'] if before_locations[n['id']] != (n['string'], n['fret']))
                    check = trial
                    continue
                raise
            check = grip_position_path(probe, vocal)
            if not check['valid']:
                raise ValueError('完整器乐规整后仍无法沿真实持续音换把：'+str(check))
            arrangement['hand_positions'] = check['positions']
            return check
        _, note, end, check = best
        audit.append({'type': 'regular_grid_release_for_position_preparation', 'note_id': note['id'],
                      'from_end_tick': note['end_tick'], 'to_end_tick': end})
        note['end_tick'] = end
    raise ValueError('器乐换把整理未单调推进。')


# 器乐声部恢复与规整节奏：新增授权时序变更的保护账本迁移，原音乐和旧音快照保留供独立对照。
def update_protection_ledger(arrangement, editable):
    ledger = arrangement.get('regular_rhythm')
    if not ledger:
        return
    actual = {n['id']: n for n in arrangement['notes']}
    ledger.setdefault('retimed_instrumental_source_notes', []).extend(
        deepcopy(n) for n in ledger.get('preserved_notes', []) if n['id'] in editable)
    ledger['preserved_notes'] = [deepcopy(actual[n['id']]) if n['id'] in editable and n['id'] in actual else n
                                 for n in ledger.get('preserved_notes', []) if n['id'] not in editable or n['id'] in actual]
    ledger['preserved_note_ids'] = [n['id'] for n in ledger['preserved_notes']]


# 器乐声部恢复与规整节奏：新增从最终实音重建器乐攻击事件，旧30tick事件不再驱动谱面和扫弦标记。
def rebuild_instrumental_events(arrangement, shared, quarter, grid):
    sections = sections_for(shared)
    keep = lambda tick: not any(s['start_tick'] <= tick < s['end_tick'] for s in sections)
    events = [e for e in arrangement.get('attack_events', []) if keep(e['start_tick'])]
    groups = defaultdict(list)
    for n in arrangement['notes']:
        if n.get('instrumental_rhythm_version'):
            groups[n['start_tick']].append(n)
    ticks = sorted(groups)
    for i, tick in enumerate(ticks):
        notes = groups[tick]
        available = min(n['end_tick']-tick for n in notes)
        if i+1 < len(ticks):
            available = min(available, ticks[i+1]-tick)
        # 器乐声部恢复与规整节奏：新增按拍起音槽，长延音与拨弦节奏分开；空隙不造新攻击。
        available = min(available, quarter-tick % quarter)
        duration = max(d for d in (grid, grid*2, quarter) if d <= available)
        chord = next((h for h in shared.get('harmony', []) if h['start_tick'] <= tick < h['end_tick']), None)
        for n in notes:
            n['right_hand_duration_ticks'] = duration
            n['right_hand_duration_source'] = 'instrumental_regular_grid'
        events.append({'start_tick': tick, 'kind': 'melody' if len(notes) == 1 else 'arpeggio',
                       'chord_id': chord['id'] if chord else None, 'source': notes[0].get('source'),
                       'onset_origin': 'instrumental_rhythm_regularization',
                       'note_ids': sorted(n['id'] for n in notes), 'stroke': None,
                       'right_hand_duration_ticks': duration, 'right_hand_duration_source': 'instrumental_regular_grid'})
    arrangement['attack_events'] = sorted(events, key=lambda e: e['start_tick'])


# 器乐声部恢复与规整节奏：新增主入口；正常伴奏/人声/共有和声/物理拍轴不因器乐节奏整理而重算。
def regularize_instrumentals(shared, vocal, arrangements):
    result = deepcopy(arrangements); sections = sections_for(shared)
    # 器乐声部恢复与规整节奏：修改，旧不存在的timing字段读取保留；使用规范导出器的拍单位。
    # quarter = vocal['timing']['ppq']; grid = quarter // POLICY['minimum_division_of_quarter']
    quarter = PPQ; grid = quarter // POLICY['minimum_division_of_quarter']
    if quarter % POLICY['minimum_division_of_quarter']:
        raise ValueError('当前PPQ不能表示完整十六分拍格。')
    clock = SongClock(vocal); statistics = {}
    for instrument, arrangement in result.items():
        original = deepcopy(arrangement['notes'])
        editable = {n['id'] for n in original if any(in_section(n, s) for s in sections)}
        fixed = [n for n in arrangement['notes'] if n['id'] not in editable]
        # 器乐声部恢复与规整节奏：新增独立保护快照，不能用同一可变对象自比证明未变。
        fixed_originals = deepcopy(fixed)
        audit, additions = [], []
        for section in sections:
            selected = [n for n in original if in_section(n, section)]
            added, changes = arrange_section(instrument, selected, fixed, section, arrangement, quarter)
            additions.extend(added); audit.extend(changes)
        arrangement['notes'] = sorted(fixed+additions, key=lambda n: (n['start_tick'], n['id']))
        release_instrumental_conflicts(arrangement, editable, grid, audit)
        # 器乐声部恢复与规整节奏：修改，旧仅三项缓存清理保留；包括手指/显示缓存均从新实音重建。
        # for field in ('fingering_diagrams', 'notation_regions', 'exact_pitch_refingering'):
        for field in ('fingering_diagrams', 'notation_regions', 'exact_pitch_refingering', 'grip_hand_positions',
                      'grip_fingerings', 'tab_display', 'rhythm_display', 'time_alignment_display'):
            arrangement.pop(field, None)
        if instrument == 'guitar':
            # 器乐声部恢复与规整节奏：修改，旧入口保留，向精确换弦提供原共享和声。
            # prepare_guitar_path(arrangement, vocal, editable, grid, audit)
            prepare_guitar_path(arrangement, shared, vocal, editable, grid, audit)
        else:
            arrangement['hand_positions'] = piano_hand_positions(arrangement['notes'], clock)
        # 器乐声部恢复与规整节奏：新增换把整理之后再保存事件/保护账本，不能保存过期的起止时间。
        arrangement['notes'].sort(key=lambda n: (n['start_tick'], n['id']))
        rebuild_instrumental_events(arrangement, shared, quarter, grid)
        current = {n['id']: n for n in arrangement['notes']}
        # 器乐声部恢复与规整节奏：修改，旧同对象检查保留，改与执行前独立快照比较。
        # if any(any(n.get(k) != current[n['id']].get(k) for k in MUSIC_FIELDS) for n in fixed):
        if any(any(n.get(k) != current[n['id']].get(k) for k in MUSIC_FIELDS) for n in fixed_originals):
            raise ValueError('器乐整理意外改变了正常演唱的实音或原弦品。')
        if any(n['start_tick'] % grid or n['end_tick'] % grid or n['end_tick']-n['start_tick'] < grid
               for n in additions):
            raise ValueError('器乐整理产生了小于十六分的实际音值或偏离共同拍格。')
        before_bass = [n['id'] for n in original if n['id'] in editable and n['role'] == 'bass']
        if any(identity not in current for identity in before_bass):
            raise ValueError('器乐整理遗漏了原有低音攻击。')
        update_protection_ledger(arrangement, editable)
        arrangement['configuration']['instrumental_policy'] = deepcopy(POLICY)
        arrangement['adjustments'].extend(audit)
        playable = validate_playability(arrangement, clock)
        if not playable['valid']:
            raise ValueError(instrument+'规整器乐不满足演奏约束：'+str(playable['errors'][:8]))
        statistics[instrument] = {
            'before_count': len(editable), 'after_count': len(additions),
            'before_roles': dict(Counter(n['role'] for n in original if n['id'] in editable)),
            'after_roles': dict(Counter(n['role'] for n in additions)),
            'merged_short_repetition_count': sum(a['type'] == 'merge_sub_sixteenth_same_pitch_repetition' for a in audit),
            'maximum_attack_displacement_ticks': max((abs(n['start_tick']-n['instrumental_source_interval'][0]) for n in additions), default=0),
            'protected_normal_note_count': len(fixed), 'all_bass_attacks_retained': True,
            'all_distinct_melody_pitches_retained': True, 'minimum_note_ticks': grid,
            'playability': playable, 'changes': audit,
        }
    return deepcopy(shared), result, {'valid': True, 'policy': deepcopy(POLICY), 'instruments': statistics}
