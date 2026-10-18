"""器乐合理分句与十二品硬限制：先检查整句八度域，再在有音乐依据的释放边界划分音区动机。"""
# 器乐合理分句与十二品硬限制：新增纯音乐规划；不读取曲名、歌词、参考谱或歌曲时间答案。
from copy import deepcopy
from functools import lru_cache

from guitar_capo import capo_at
from score_export import PPQ

MINIMUM_MOTIF_QUARTERS = 2
REGISTER_HANDOVER_SEMITONES = 5


# 器乐合理分句与十二品硬限制：新增瞬时可行性下界，完整路径仍由持续手指／跨度／换位搜索严格验证。
def event_possible(active, original, editable, capo, shift, maximum, voicing_version):
    from guitar_instrumental_register import locations, role_order_valid, grip_info
    options = [(n, locations(n, capo, shift, maximum, editable, voicing_version)) for n in active]
    if any(not values for _, values in options):
        return False
    options.sort(key=lambda item: len(item[1]))

    def visit(index, chosen):
        if index == len(options):
            return True
        note, values = options[index]
        occupied = {value[0] for value in chosen.values()}
        for value in values:
            if value[0] in occupied:
                continue
            added = {**chosen, note['id']: value}
            if not role_order_valid(added, original):
                continue
            if grip_info({v[0]: v[1] for v in added.values()}) is None:
                continue
            if visit(index + 1, added):
                return True
        return False

    return visit(0, {})


# 器乐合理分句与十二品硬限制：新增仅在已释放且有休止／音区交接／和声拍界依据处允许另择八度。
def boundary_evidence(notes, index, shared):
    left = notes[:index]
    previous, current = notes[index - 1], notes[index]
    tick = current['start_tick']
    if max(n['end_tick'] for n in left) > tick:
        return None
    pulse = int(PPQ * 4 / shared['timing']['meter'][1])
    bar = shared['statistics']['bar_ticks']
    gap = tick - max(n['end_tick'] for n in left)
    interval = current['pitch_midi'] - previous['pitch_midi']
    if gap >= PPQ / 2:
        return {'reason': 'released_rest', 'rank': 0, 'gap_ticks': gap}
    if abs(interval) >= REGISTER_HANDOVER_SEMITONES:
        return {'reason': 'released_register_handover', 'rank': 1,
                'interval_semitones': interval}
    harmony = {h['id']: h for h in shared.get('harmony', [])}
    before = harmony.get(previous.get('chord_id'), {})
    after = harmony.get(current.get('chord_id'), {})
    changed = bool(before and after and (before.get('root_pc'), before.get('bass_pc')) !=
                   (after.get('root_pc'), after.get('bass_pc')))
    if tick % bar == 0 or changed and tick % pulse == 0:
        return {'reason': 'released_metric_harmony_boundary', 'rank': 2,
                'harmonic_change': changed}
    return None


# 器乐合理分句与十二品硬限制：新增全句域交集；只有同一八度不可行时才增加动机边界，不为逐音低品任意切句。
# 保音持续按弦与整句八度衔接：修改来源候选显式传入，历史调用保持原三组；新来源允许必要的多个八度。
# def plan_phrases(shared, arrangement, editable, original_phrases):
def plan_phrases(shared, arrangement, editable, original_phrases, octave_candidates=None):
    from guitar_instrumental_register import locations
    notes = arrangement['notes']
    original = {n['id']: n for n in notes}
    events = sorted({t for n in notes for t in (n['start_tick'], n['end_tick'])})
    voicing = arrangement['configuration'].get('instrumental_register_voicing_version', 1)
    # 保音持续按弦与整句八度衔接：修改从来源根音高一次选择整句八度，原固定候选留历史路径。
    # shifts = (0, -12, -24)
    shifts = (0, -12, -24) if octave_candidates is None else tuple(octave_candidates)
    if not shifts or any(shift > 0 or shift % 12 for shift in shifts):
        raise ValueError('整句器乐音区必须使用非正的整八度候选。')
    cache = {}

    @lru_cache(maxsize=None)
    def note_domain(identity):
        note = original[identity]
        domain = []
        for shift in shifts:
            possible = True
            for tick in events:
                if not note['start_tick'] <= tick < note['end_tick']:
                    continue
                active = [n for n in notes if n['start_tick'] <= tick < n['end_tick']]
                capo = capo_at(arrangement, tick)
                key = (tuple(n['id'] for n in active), capo, shift)
                if key not in cache:
                    cache[key] = event_possible(active, original, editable, capo, shift, 12, voicing)
                if not cache[key]:
                    possible = False
                    break
            if possible:
                domain.append(shift)
        return tuple(domain)

    def domain_for(selected):
        return tuple(s for s in shifts if all(s in note_domain(n['id']) for n in selected))

    def preference(selected, domain):
        scores = []
        for shift in domain:
            frets = [min(value[1] for value in locations(n, capo_at(arrangement, n['start_tick']),
                shift, 12, editable, voicing)) for n in selected]
            scores.append((sum(f > 4 for f in frets), sum(max(0, f - 4) for f in frets),
                           sum(frets), abs(shift)))
        return min(scores)

    result = []
    decisions = []
    for source_phrase in original_phrases:
        selected = [original[i] for i in source_phrase['note_ids']]
        domains = [note_domain(n['id']) for n in selected]
        whole_domain = domain_for(selected)
        groups = [(0, len(selected), whole_domain, None)]
        if not whole_domain:
            boundaries = {i: boundary_evidence(selected, i, shared) for i in range(1, len(selected))}
            eligible = [0] + [i for i, reason in boundaries.items() if reason] + [len(selected)]
            # 器乐合理分句与十二品硬限制：新增最少分句动态规划；各新动机至少两拍，短促级进不能逐音变八度。
            best = {0: ((0, 0, 0, 0, 0), [])}
            for end in eligible[1:]:
                candidates = []
                for start in eligible:
                    if start >= end or start not in best:
                        continue
                    chunk = selected[start:end]
                    duration = max(n['end_tick'] for n in chunk) - chunk[0]['start_tick']
                    if duration < MINIMUM_MOTIF_QUARTERS * PPQ:
                        continue
                    domain = domain_for(chunk)
                    if not domain:
                        continue
                    previous_score, previous_groups = best[start]
                    low_count, excess, frets, _ = preference(chunk, domain)
                    evidence = boundaries.get(start)
                    score = (previous_score[0] + 1, previous_score[1] + low_count,
                             previous_score[2] + excess, previous_score[3] + frets,
                             previous_score[4] + (evidence['rank'] if evidence else 0))
                    candidates.append((score, previous_groups + [(start, end, domain, evidence)]))
                if candidates:
                    best[end] = min(candidates, key=lambda value: (value[0],
                        tuple(item[0] for item in value[1])))
            if len(selected) not in best:
                # 器乐合理分句与十二品硬限制：修改，旧错误描述保留；兼容既有“无可行路径”诊断识别并说明合理分句失败。
                # raise ValueError('器乐十二品内未找到合理乐句八度方案；不会自动放宽品位。' +
                raise ValueError('器乐十二品内未找到可行路径：合理乐句八度方案不可行；不会自动放宽品位。' +
                    str({'phrase': source_phrase['id'], 'note_octave_domains': domains,
                         'eligible_boundaries': [selected[i]['start_tick'] for i in eligible[1:-1]],
                         'minimum_motif_quarters': MINIMUM_MOTIF_QUARTERS}))
            groups = best[len(selected)][1]
        for start, end, domain, evidence in groups:
            chunk = selected[start:end]
            origin, pitch = chunk[0]['start_tick'], chunk[0]['pitch_midi']
            phrase = deepcopy(source_phrase)
            phrase.update(id=f'instrumental_phrase_{len(result) + 1:04}',
                start_tick=origin, end_tick=max(n['end_tick'] for n in chunk),
                note_ids=[n['id'] for n in chunk],
                signature=tuple((n['start_tick'] - origin, n['end_tick'] - n['start_tick'],
                                 n['pitch_midi'] - pitch) for n in chunk),
                octave_candidates=list(domain), source_phrase_id=source_phrase['id'])
            # 器乐合理分句与十二品硬限制：新增交接音程约束；不能把一次五度交接变成突兀的两八度下跳。
            if evidence:
                interval = chunk[0]['pitch_midi'] - selected[start - 1]['pitch_midi']
                phrase.update(register_handover_from_phrase_id=result[-1]['id'],
                    register_handover_source_interval=interval,
                    register_handover_maximum_interval=max(12, abs(interval)))
            result.append(phrase)
            if evidence:
                decisions.append({'source_phrase_id': source_phrase['id'],
                    'phrase_id': phrase['id'], 'tick': origin, **evidence,
                    'reason_for_replanning': 'no_single_octave_within_twelve',
                    'minimum_motif_quarters': MINIMUM_MOTIF_QUARTERS})
    return result, {'version': 2, 'maximum_fret': 12, 'source_phrase_count': len(original_phrases),
        'result_phrase_count': len(result), 'additional_boundaries': decisions,
        'source_note_octave_domains': {i: list(note_domain(i)) for p in original_phrases for i in p['note_ids']},
        'never_split_held_melody': True, 'never_fold_individual_notes': True}
