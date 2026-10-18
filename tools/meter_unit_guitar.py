"""慢拍单位与两曲最小修订：局部十六分整理，完整保留音符和持续时长。"""
# 慢拍单位与两曲最小修订：新增只在冲突邻域移动起音，低把位与音高不重新规划。
from collections import defaultdict
from copy import deepcopy
import math
from itertools import product
# 慢拍单位与两曲最小修订：修改导入，只有原弦不通时允许同音高低品替代弦，不改八度。
# from accompaniment_arrange import grip_info
from accompaniment_arrange import grip_info, TUNING

POLICY = {'version': 1, 'grid_ticks': 120, 'maximum_shift_ticks': 120,
          'beam_width': 96, 'maximum_fret': 12, 'drop_notes': False, 'shorten_duration': False}


# 慢拍单位与两曲最小修订：新增有界第二阶段，固定弦位无解才尝试同音高局部用弦。
# def regularize_complete_sustain(guitar, total):
# 慢拍单位与两曲最小修订：修改只允许失败邻域换弦，原全曲冲突邻域重试会破坏其它已认可换把准备。
# def regularize_complete_sustain(guitar, total, allow_refinger=False):
# 慢拍单位与两曲最小修订：修改搜索同时携带可达手位，不能把延音延长到换把空隙后仍报可演奏。
# def regularize_complete_sustain(guitar, total, allow_refinger=False, refinger_centres=()):
def regularize_complete_sustain(guitar, total, allow_refinger=False, refinger_centres=(), vocal=None):
    # 慢拍单位与两曲最小修订：新增全声部同一拨弦格的有界搜索；同弦占用和实际持握贯穿整条路径。
    notes = guitar['notes']
    if any(not 0 <= n['fret'] <= 12 for n in notes):
        raise ValueError('输入包含12品以上音，不能通过节奏整理放宽把位')
    groups = defaultdict(list)
    for n in notes:
        groups[n['start_tick']].append(n)
    starts = sorted(groups)
    bad = {n['start_tick'] for n in notes if n['start_tick'] % 120 or n['end_tick'] % 120 or n['end_tick'] - n['start_tick'] < 120}
    bad.update(b for a, b in zip(starts, starts[1:]) if b - a < 120)
    if not bad:
        return deepcopy(guitar), {'policy': deepcopy(POLICY), 'changed_notes': [], 'status': 'already_compliant'}
    movable = {s for s in starts if any(abs(s - b) <= 360 for b in bad)}
    movable.update(s for s in starts if any(abs(s - center) <= 360 for center in refinger_centres))
    # 慢拍单位与两曲最小修订：新增状态中的六弦结束时刻与按品；只保留有限最佳状态，失败明确报告。
    # 慢拍单位与两曲最小修订：修改末项路径保持，新增可能手位集合；同一占弦不同准备位置不能提前合并。
    # states = [(0., -120, -120, (0,) * 6, (-1,) * 6, ())]
    states = [(0., -120, -120, (0,) * 6, (-1,) * 6, None, ())]
    from accompaniment_analysis import SongClock
    clock = SongClock(vocal) if vocal is not None else None
    for old_start in starts:
        group = groups[old_start]
        # 慢拍单位与两曲最小修订：新增同音高候选，仅冲突邻域可换弦；0–4优先，硬12，原夹位从原音反算。
        locations = []
        for note in group:
            options = [(note['string'], note['fret'])]
            # 慢拍单位与两曲最小修订：修改用弦候选只覆盖实际失败的三拍邻域，不顺带重选其它位置。
            # if allow_refinger and old_start in movable:
            if allow_refinger and any(abs(old_start - center) <= 360 for center in refinger_centres):
                capo = note['pitch_midi'] - TUNING[note['string']] - note['fret']
                options += [(string, note['pitch_midi'] - capo - pitch) for string, pitch in TUNING.items()
                            if 0 <= note['pitch_midi'] - capo - pitch <= 12 and string != note['string']]
            locations.append(options)
        placements = list(product(*locations))
        lower, upper = max(0, math.ceil((old_start - 120) / 120) * 120), min(total - 120, math.floor((old_start + 120) / 120) * 120)
        choices = range(lower, upper + 1, 120) if old_start in movable else [old_start]
        following = {}
        melody = any(n.get('role') in ('instrumental_melody', 'countermelody') for n in group)
        # 慢拍单位与两曲最小修订：修改解包保留完整持续期内可达位置。
        # for cost, prior, prior_melody, ends, frets, path in states:
        for cost, prior, prior_melody, ends, frets, reachable, path in states:
            for tick in choices:
                if tick < prior or (tick != prior and tick - prior < 120) or (melody and tick <= prior_melody):
                    continue
                # 慢拍单位与两曲最小修订：修改固定弦分支为候选枚举，原实现已随本轮源码快照保留；完整逻辑注释如下。
                # new_ends = list(ends); new_frets = [f if end > tick else -1 for f, end in zip(frets, ends)]
                # resolved, valid = [], True
                # for note in group:
                #     string = note['string'] - 1
                #     if new_ends[string] > tick: valid = False; break
                #     length = note['end_tick'] - note['start_tick']
                #     end = math.ceil(max(note['end_tick'], tick + max(120, length)) / 120) * 120
                #     if end > total: valid = False; break
                #     new_ends[string], new_frets[string] = end, note['fret']
                #     resolved.append((note['id'], tick, end))
                # if not valid or grip_info({i + 1: f for i, f in enumerate(new_frets) if f >= 0}) is None: continue
                # next_melody = tick if melody else prior_melody
                # score = cost + (tick - old_start) ** 2 * (3 if melody else 1) + sum((e - n['end_tick']) ** 2 * .1 for (_, _, e), n in zip(resolved, group))
                # key = (tick, next_melody, tuple(new_ends), tuple(new_frets))
                # row = (score, tick, next_melody, tuple(new_ends), tuple(new_frets), path + (tuple(resolved),))
                # if key not in following or score < following[key][0]: following[key] = row
                for placement in placements:
                    new_ends = list(ends)
                    new_frets = [f if end > tick else -1 for f, end in zip(frets, ends)]
                    resolved, valid, location_cost = [], True, 0.
                    for note, (string_number, fret) in zip(group, placement):
                        string = string_number - 1
                        if new_ends[string] > tick:
                            valid = False
                            break
                        length = note['end_tick'] - note['start_tick']
                        end = math.ceil(max(note['end_tick'], tick + max(120, length)) / 120) * 120
                        if end > total:
                            valid = False
                            break
                        new_ends[string], new_frets[string] = end, fret
                        resolved.append((note['id'], tick, end, string_number, fret))
                        location_cost += (300 * abs(string_number - note['string']) + 2000 * max(0, fret - 4))
                    if not valid or grip_info({i + 1: f for i, f in enumerate(new_frets) if f >= 0}) is None:
                        continue
                    positions = _reachable_positions(guitar, clock, prior, ends, frets, tick, new_frets, reachable)
                    if clock is not None and not positions:
                        continue
                    next_melody = tick if melody else prior_melody
                    score = cost + (tick - old_start) ** 2 * (3 if melody else 1) + location_cost + sum((x[2] - n['end_tick']) ** 2 * .1 for x, n in zip(resolved, group))
                    # 慢拍单位与两曲最小修订：修改状态签名和路径记录，换把前瞻参与真实搜索而非事后降低门槛。
                    # key = (tick, next_melody, tuple(new_ends), tuple(new_frets))
                    # row = (score, tick, next_melody, tuple(new_ends), tuple(new_frets), path + (tuple(resolved),))
                    key = (tick, next_melody, tuple(new_ends), tuple(new_frets), positions)
                    row = (score, tick, next_melody, tuple(new_ends), tuple(new_frets), positions, path + (tuple(resolved),))
                    if key not in following or score < following[key][0]:
                        following[key] = row
        if not following:
            # 慢拍单位与两曲最小修订：新增仅一次受约束重试；不删音、不减尾、不改音高、不放宽12品。
            # 慢拍单位与两曲最小修订：修改有界局部重试，旧全域换弦式保留。
            # if not allow_refinger:
            #     return regularize_complete_sustain(guitar, total, allow_refinger=True)
            if len(refinger_centres) < 16 and not any(abs(old_start - center) <= 360 for center in refinger_centres):
                return regularize_complete_sustain(guitar, total, allow_refinger=True,
                                                   # 慢拍单位与两曲最小修订：修改局部恢复仍遵守同一原秒和持续按弦约束。
                                                   refinger_centres=(*refinger_centres, old_start), vocal=vocal)
            raise ValueError('保留音符／完整持续时长的十六分局部路径未找到，停在原tick：' + str(old_start))
        states = sorted(following.values(), key=lambda r: r[0])[:POLICY['beam_width']]
    selected = min(states, key=lambda r: r[0])
    # 慢拍单位与两曲最小修订：修改路径载荷，实际弦品一同登记。
    # target = {identity: (start, end) for group in selected[-1] for identity, start, end in group}
    target = {r[0]: r[1:] for group in selected[-1] for r in group}
    revised, edits = deepcopy(guitar), []
    for note in revised['notes']:
        before = [note['start_tick'], note['end_tick']]
        # 慢拍单位与两曲最小修订：修改差异报告，必要换弦不能虚称原弦品保持。
        # after = list(target[note['id']])
        after = list(target[note['id']][:2])
        string, fret = target[note['id']][2:]
        if before != after or (string, fret) != (note['string'], note['fret']):
            # edits.append({'id': note['id'], 'before': before, 'after': after, 'pitch_string_fret_preserved': True,
            edits.append({'id': note['id'], 'before': before, 'after': after, 'pitch_preserved': True,
                          'old_string_fret': [note['string'], note['fret']], 'new_string_fret': [string, fret],
                          'duration_shortened': False})
            note.update(start_tick=after[0], end_tick=after[1], right_hand_duration_ticks=after[1] - after[0],
                        right_hand_duration_source='meter_unit_local_complete_sustain', string=string, fret=fret)
    positions = []
    for tick in sorted({n[key] for n in revised['notes'] for key in ('start_tick', 'end_tick')}):
        active = [n for n in revised['notes'] if n['start_tick'] <= tick < n['end_tick']]
        if not active:
            continue
        info = grip_info({n['string']: n['fret'] for n in active})
        positions.append({'tick': tick, 'position': info['position'], 'span': info['span']})
    revised['hand_positions'] = positions
    revised['grip_hand_positions'] = deepcopy(positions)
    # 慢拍单位与两曲最小修订：修改保留范围声明，完整低品及必要换弦逐项见差异。
    # return revised, {'policy': deepcopy(POLICY), 'changed_notes': edits,
    #                  'note_identity_pitch_fret_and_full_duration_preserved': True, 'status': 'requires_actual_playability_recheck'}
    return revised, {'policy': deepcopy(POLICY), 'changed_notes': edits, 'same_pitch_local_refingering_used': allow_refinger,
                    'refinger_failure_centres': list(refinger_centres),
                    'note_identity_pitch_and_full_duration_preserved': True, 'status': 'requires_actual_playability_recheck'}


def _reachable_positions(guitar, clock, prior, ends, frets, tick, new_frets, reachable):
    # 慢拍单位与两曲最小修订：新增完整延音期间的手位可达性，沿用真实换把上限24品/秒与持弦范围。
    if clock is None:
        return None
    from guitar_capo import capo_at
    def allowed(values):
        positive = [f for f in values if f > 0]
        return tuple(range(max(1, max(positive, default=1) - 5), min(positive, default=20) + 1))
    if reachable is None:
        return allowed(new_frets)
    previous_allowed = allowed(frets)
    current_time = prior
    positions = reachable
    boundaries = sorted({end for end in ends if prior < end < tick} | {tick})
    for boundary in boundaries:
        active = new_frets if boundary == tick else [f if end > boundary else -1 for f, end in zip(frets, ends)]
        target = allowed(active)
        seconds = max(.001, clock.seconds(boundary) - clock.seconds(current_time))
        shift = capo_at(guitar, boundary) - capo_at(guitar, current_time)
        positions = tuple(p for p in target if p + shift in previous_allowed and
                          any(abs(p + shift - old) <= 24 * seconds + 1e-8 for old in positions))
        if not positions:
            return ()
        previous_allowed, current_time = target, boundary
    return positions
