"""乐句节奏与音值分组：新增声学/音素候选的乐句联合推断，不读取歌曲名或人工每字答案。"""
from __future__ import annotations
from collections import defaultdict
from copy import deepcopy
from functools import lru_cache
import math

VERSION = 1


class RhythmConflict(ValueError):
    """No complete notation fits the bounded acoustic candidates."""

PPQ = 480
GRID = 60
POLICY = {'version': VERSION, 'word_grid_ticks': 120, 'fine_grid_ticks': 60,
          'maximum_phrase_latency_quarters': .30, 'minimum_phrase_gap_quarters': .65,
          'phoneme_candidate_sigma_quarters': .25, 'unknown_support_is_zero': False,
          'terminal_latency_affects_latter_half_only': True,
          'grace_budget': 'semantic_anchor_third_capped_below_fine_grid'}


# 乐句节奏与音值分组：新增词内音序模型，源秒时间与音高保持，候选拍位独立保存。
def word_models(pieces, characters, mapping, timing):
    origin = timing['score_start_quarter']
    q = lambda s: mapping.seconds_to_quarters(s) - origin
    lookup = {c['index']: c for c in characters}
    groups = defaultdict(list)
    for serial, piece in enumerate(pieces):
        if piece.get('grace'):
            continue
        key = ('word', piece['lyric_index']) if piece.get('lyric_index') is not None else ('orphan', serial)
        groups[key].append(piece)
    models = []
    for key, notes in groups.items():
        notes = sorted(notes, key=lambda n: n['start_seconds'])
        char = lookup.get(key[1], {}) if key[0] == 'word' else {}
        voiced_begin = q(notes[0]['start_seconds'])
        voiced_end = q(notes[-1]['end_seconds'])
        phoneme_begin = q(char['start_seconds']) if char.get('start_seconds') is not None else voiced_begin
        phoneme_end = q(char['end_seconds']) if char.get('end_seconds') is not None else voiced_end
        phonemes = [p for p in char.get('phonemes', []) if not p.get('skipped') and p.get('start_seconds') is not None]
        initial = next((p for p in phonemes if p.get('role') == 'initial'), None)
        durations = [max(.025, q(n['end_seconds']) - q(n['start_seconds'])) for n in notes]
        models.append({'key': key, 'notes': notes, 'char': char,
                       'start': phoneme_begin, 'end': phoneme_end,
                       'voiced_start': voiced_begin, 'voiced_end': voiced_end,
                       'observed_span': max(sum(durations), phoneme_end - phoneme_begin),
                       'durations': durations, 'initial_interval': (q(initial['start_seconds']), q(initial['end_seconds'])) if initial else None,
                       'job': char.get('phrase_job_id'), 'orphan': key[0] != 'word'})
    return sorted(models, key=lambda w: w['notes'][0]['start_seconds'])


# 乐句节奏与音值分组：新增真实声学空隙和音素桥判断，禁止凭同一歌词行填0.40拍空白。
def has_sounding_gap(left, right):
    gap = right['voiced_start'] - left['voiced_end']
    if gap <= .06:
        return False
    initial = right['initial_interval']
    if initial and initial[0] <= left['voiced_end'] + .06 and initial[1] >= right['voiced_start'] - .06:
        return False
    return gap >= .18


# 乐句节奏与音值分组：新增按识别句窗及实际停顿联合分句，不强制所有歌曲四小节一句。
def phrase_models(words):
    phrases = []
    for word in words:
        if not phrases:
            phrases.append([word])
            continue
        previous = phrases[-1][-1]
        gap = word['voiced_start'] - previous['voiced_end']
        different_job = word['job'] is not None and previous['job'] is not None and word['job'] != previous['job']
        if gap >= POLICY['minimum_phrase_gap_quarters'] or different_job or word['orphan'] != previous['orphan']:
            phrases.append([word])
        else:
            phrases[-1].append(word)
    return phrases


# 乐句节奏与音值分组：新增快速等分短音组与较长起句的节拍候选，弱起候选保留。
# 乐句节奏与音值分组：修改原型声明保留；起句强拍由实际拍号的大拍长度提供。
# def phrase_entry(words):
def phrase_entry(words, beat_quarters=1.):
    first = words[0]
    observed = first['start']
    if first['orphan']:
        return round(observed * 4) / 4, 0., 'unmapped_acoustic_candidate'
    rapid = len(words) >= 4 and all(len(w['notes']) == 1 and w['observed_span'] <= .46 for w in words[:3]) and words[3]['observed_span'] >= .50
    # 乐句节奏与音值分组：修改，原四分拍假设保留；6/8应按附点四分大拍取入口候选。
    # whole = round(observed)
    whole = round(observed/beat_quarters)*beat_quarters
    if rapid and abs(observed - whole) <= .30:
        entry, method = whole, 'rapid_syllabic_group_with_sustained_cadence'
    elif len(first['notes']) >= 2 or first['observed_span'] >= .45:
        entry, method = round(observed * 2) / 2, 'binary_entry_candidate'
    else:
        entry, method = round(observed * 4) / 4, 'short_pickup_candidate'
    latency = max(-.30, min(.30, observed - entry))
    return max(0., entry), latency, method


# 乐句节奏与音值分组：新增常见音值与可靠细节的代价，不一律禁止附点、三十二分或切分。
def duration_penalty(ticks, observed):
    if ticks in (120, 240, 480, 960, 1440, 1920):
        return 0.
    if ticks in (360, 720):
        return .12
    if ticks == 60:
        return .18 if observed < .18 else 1.0
    if ticks == 180:
        return .9
    if ticks >= 480 and ticks % 120 == 0:
        return .12
    return 1.1


# 乐句节奏与音值分组：新增词内动态规划，保持真实转音音序，联合选择各段时值和边界。
@lru_cache(maxsize=50000)
def allocate_durations(raw_durations, span):
    n = len(raw_durations)
    if span < n * GRID:
        return math.inf, ()
    raw_total = sum(raw_durations)
    states = {0: (0., ())}
    for index, observed in enumerate(raw_durations):
        following = {}
        for used, (cost, lengths) in states.items():
            maximum = span - used - (n - index - 1) * GRID
            for length in range(GRID, maximum + 1, GRID):
                fraction = length / span
                ratio_cost = 12 * (fraction - observed / raw_total) ** 2
                value = cost + ratio_cost + duration_penalty(length, observed)
                end = used + length
                if end not in following or value < following[end][0]:
                    following[end] = (value, lengths + (length,))
        states = following
    return states.get(span, (math.inf, ()))


# 乐句节奏与音值分组：新增词时值与语音起点软证据，多音等分结构可回看，避免单向游标。
def slot_cost(word, start, end, latency):
    span = end - start
    allocation_cost, lengths = allocate_durations(tuple(round(x, 6) for x in word['durations']), span)
    if not lengths:
        return math.inf, ()
    total_fit = .8 * math.log(max(.001, span / PPQ / word['observed_span'])) ** 2
    # 乐句节奏与音值分组：新增音高平台内部边界检查，未知独立支持保持未知，不以0代替。
    body_cost = 0.
    at = start
    for i, length in enumerate(lengths):
        if i:
            target = word['voiced_start'] + sum(word['durations'][:i]) - latency
            body_cost += .08 * ((at / PPQ - target) / .25) ** 2
        at += length
    return allocation_cost + total_fit + body_cost, lengths


# 乐句节奏与音值分组：新增候选起点范围及轻量拍结构先验，真实细网格在词内有独立候选。
def start_candidates(word, latency):
    center = word['start'] - latency
    lower = math.floor((center - .40) * 4)
    upper = math.ceil((center + .40) * 4)
    return tuple(max(0, k * 120) for k in range(lower, upper + 1) if abs(k / 4 - center) <= .45)


# 乐句节奏与音值分组：新增词起点代价，清辅音/元音只作软证据，不绝对覆盖原攻击。
def onset_cost(word, tick, latency):
    candidate = tick / PPQ
    prediction = word['start'] - latency
    value = .4 * ((candidate - prediction) / .25) ** 2
    if tick % 240:
        value += .06
    return value


# 乐句节奏与音值分组：新增明确休止后的释放候选与终止边界，保留真实空隙而非拉长前音。
def end_candidates(word, latency, maximum):
    center = max(word['end'], word['voiced_end']) - latency
    values = [k * 120 for k in range(math.floor((center - .45) * 4), math.ceil((center + .45) * 4) + 1)
              if 0 <= k * 120 <= maximum and abs(k / 4 - center) <= .45]
    return tuple(values)


# 乐句节奏与音值分组：新增句尾释放证据与拍内终止偏好，不按歌词空拍强制删除延音。
# 乐句节奏与音值分组：修改，原声明保留；句尾音值偏好同样遵守实际大拍。
# def release_cost(word, tick, latency):
def release_cost(word, tick, latency, beat_ticks=PPQ):
    target = max(word['end'], word['voiced_end']) - latency
    value = .2 * ((tick / PPQ - target) / .25) ** 2
    if word['observed_span'] >= .6:
        # 乐句节奏与音值分组：修改，原4/4专用模数保留；复合拍不把每个四分当强拍。
        # value += .45 if tick % 240 else .12 if tick % 480 else 0.
        value += .45 if tick % (beat_ticks//2) else .12 if tick % beat_ticks else 0.
    return value


# 乐句节奏与音值分组：新增长句终止的缓慢演唱延迟模型，释放和字首不是同一个声学边界。
# 乐句节奏与音值分组：修改原型声明保留；释放候选取实际大拍，不继承4/4常数。
# def latency_profile(words, entry_latency):
def latency_profile(words, entry_latency, beat_quarters=1., maximum=None):
    last = words[-1]
    release = max(last['end'], last['voiced_end'])
    # 乐句节奏与音值分组：修改，原四分终止先验保留；依据拍号推断长句释放。
    # terminal = release - round(release)
    terminal = release - round(release/beat_quarters)*beat_quarters
    if last['observed_span'] < .6 or abs(terminal) > .32:
        terminal = entry_latency
    terminal = max(-.30, min(.30, terminal))
    # A separately inferred next phrase may start before this terminal prior.
    # Only replace an infeasible prior when the observed release itself supports
    # the shared boundary within the same bounded performance-latency budget.
    if maximum is not None and not end_candidates(last, terminal, maximum):
        boundary = (maximum // 120) * 120 / PPQ
        constrained = release - boundary
        if abs(constrained) <= POLICY['maximum_phrase_latency_quarters']:
            terminal = constrained
    length = max(.25, release - words[0]['start'])
    # 乐句节奏与音值分组：新增句末呼吸/拖腔只影响后半句，禁止把尾音释放滞后投射到起句强拍。
    return [entry_latency + (terminal - entry_latency) *
            min(1., max(0., 2 * (w['start'] - words[0]['start']) / length - 1)) for w in words], terminal


# 乐句节奏与音值分组：新增完整乐句边界联合求解，前音可缩短/延长，不再把冲突推给后音。
# 乐句节奏与音值分组：修改原型声明保留；重复段仅提供相对节奏软证据，不搬运固定字时刻。
# def solve_phrase(words, entry, latency, maximum):
# 乐句节奏与音值分组：修改原型声明及调用保留；整个候选求解共享实际大拍。
# def solve_phrase(words, entry, latency, maximum, reference=None):
#     local_latency, terminal_latency = latency_profile(words, latency)
def solve_phrase(words, entry, latency, maximum, reference=None, beat_quarters=1.):
    local_latency, terminal_latency = latency_profile(words, latency, beat_quarters, maximum)
    first = round(entry * PPQ)
    states = {first: (onset_cost(words[0], first, latency), ())}
    for index, word in enumerate(words[:-1]):
        nxt = words[index + 1]
        candidates = start_candidates(nxt, local_latency[index + 1])
        following = {}
        gap = has_sounding_gap(word, nxt)
        for begin, (cost, path) in states.items():
            for next_begin in candidates:
                if next_begin <= begin:
                    continue
                endings = end_candidates(word, local_latency[index], next_begin) if gap else (next_begin,)
                for end in endings:
                    if end <= begin:
                        continue
                    value, lengths = slot_cost(word, begin, end, local_latency[index])
                    if not math.isfinite(value):
                        continue
                    value += cost + onset_cost(nxt, next_begin, local_latency[index + 1])
                    if reference is not None:
                        value += .10 * (((next_begin-first-reference[index+1])/PPQ)/.25) ** 2
                    if gap:
                        # 乐句节奏与音值分组：修改，原调用保留；休止释放按实际大拍。
                        # value += release_cost(word, end, local_latency[index])
                        value += release_cost(word, end, local_latency[index],round(beat_quarters*PPQ))
                        observed_gap = nxt['voiced_start'] - word['voiced_end']
                        value += .18 * (((next_begin - end) / PPQ - observed_gap) / .25) ** 2
                    if next_begin not in following or value < following[next_begin][0]:
                        following[next_begin] = (value, path + ((begin, end, lengths),))
        if not following:
            raise RhythmConflict('乐句节奏候选冲突；需复核音段/字界，未用游标强行推后。')
        states = following
    word = words[-1]
    best = (math.inf, ())
    for begin, (cost, path) in states.items():
        for end in end_candidates(word, terminal_latency, maximum):
            if end <= begin:
                continue
            value, lengths = slot_cost(word, begin, end, local_latency[-1])
            # 乐句节奏与音值分组：修改，原调用保留；句尾强弱拍与拍号一致。
            # value += cost + release_cost(word, end, terminal_latency)
            value += cost + release_cost(word, end, terminal_latency,round(beat_quarters*PPQ))
            if value < best[0]:
                best = (value, path + ((begin, end, lengths),))
    if not best[1]:
        raise RhythmConflict('乐句末音无可用完整节奏候选。')
    return best


# 乐句节奏与音值分组：新增整曲联合结果和逐音可追溯审计，原秒时间/音高/身份不改。
def solve_phrase_boundaries(phrases, defaults, last_limit, beat_quarters):
    """Reconsider adjacent entry candidates together only if the original path failed.

    Entries remain within the existing acoustic latency budget. No note, lyric,
    source time, or pitch is removed, and a previously feasible default is kept.
    """
    candidates=[]
    budget=POLICY['maximum_phrase_latency_quarters']
    for words, default in zip(phrases, defaults):
        choices=[default]
        if not words[0]['orphan']:
            observed=words[0]['start']
            for k in range(math.floor((observed-budget)*4),math.ceil((observed+budget)*4)+1):
                entry=k/4
                if entry<0 or abs(observed-entry)>budget+1e-9 or entry==default[0]:continue
                choices.append((entry,observed-entry,'joint_adjacent_phrase_boundary'))
        candidates.append(choices)
    # Objective: change the fewest prior entries, then the least distance, then
    # minimize the existing acoustic/rhythmic cost among the feasible paths.
    states={entry:((0,0.,0.),(),()) for entry in candidates[0]}
    for index, words in enumerate(phrases):
        following={}
        next_entries=candidates[index+1] if index+1<len(phrases) else [(last_limit/PPQ,0.,'audio_end')]
        for choice,(objective,selected,paths) in states.items():
            entry,latency,method=choice
            for next_choice in next_entries:
                maximum=round(next_choice[0]*PPQ)
                if maximum<=round(entry*PPQ):continue
                try:
                    path=solve_phrase(words,entry,latency,maximum,beat_quarters=beat_quarters)
                except RhythmConflict:
                    continue
                cost=(objective[0]+int(entry!=defaults[index][0]),
                      objective[1]+abs(entry-defaults[index][0]),objective[2]+path[0])
                if next_choice not in following or cost<following[next_choice][0]:
                    following[next_choice]=(cost,selected+(choice,),paths+(path,))
        if not following:
            text=''.join(w['char'].get('text','') for w in words)
            raise RhythmConflict('相邻乐句无法在原声允许的时间范围内完整记谱；第'+str(index+1)+'句“'+text+'”需要校对，未删除音符或强推后句。')
        states=following
    best=min(states.values(),key=lambda value:value[0])
    return list(best[1]),list(best[2])


def solve_words(pieces, characters, mapping, timing, duration):
    output = deepcopy(pieces)
    words = word_models(output, characters, mapping, timing)
    phrases = phrase_models(words)
    # 乐句节奏与音值分组：修改，旧4/4隐含入口保留；不规则拍的强拍候选需另作显式复核。
    # entries = [phrase_entry(p) for p in phrases]
    from rhythm_notation import MeterTree
    tree=MeterTree.from_meter(timing['meter'],timing.get('beat_groups'))
    beat_quarters=tree.groups[0]*tree.unit_ticks/PPQ
    entries = [phrase_entry(p,beat_quarters) for p in phrases]
    # 乐句节奏与音值分组：新增整曲已观测重复乐句的相对节奏共识；标题和人工拍点不参与。
    repeats = defaultdict(list)
    defaults = list(entries)
    last_limit = math.ceil((mapping.seconds_to_quarters(duration)-timing['score_start_quarter'])*PPQ)
    maxima = [round(entries[i+1][0]*PPQ) if i+1<len(entries) else last_limit for i in range(len(entries))]
    try:
        paths = [solve_phrase(p,entry,latency,maximum,beat_quarters=beat_quarters)
                 for p,(entry,latency,method),maximum in zip(phrases,entries,maxima)]
    except RhythmConflict:
        entries, paths = solve_phrase_boundaries(phrases,defaults,last_limit,beat_quarters)
        maxima = [round(entries[i+1][0]*PPQ) if i+1<len(entries) else last_limit for i in range(len(entries))]
    for index, phrase in enumerate(phrases):
        if len(phrase) >= 4 and not any(w['orphan'] for w in phrase):
            root = phrase[0]['notes'][0]['pitch_midi']
            signature = tuple((w['char'].get('text','').casefold(),tuple(n['pitch_midi']-root for n in w['notes'])) for w in phrase)
            repeats[signature].append(index)
    repeat_groups = [ids for ids in repeats.values() if len(ids) >= 2]
    references = {}
    for ids in repeat_groups:
        import statistics
        for index in ids:
            others = [i for i in ids if i != index]
            reference = [statistics.median(paths[i][1][k][0]-paths[i][1][0][0] for i in others) for k in range(len(phrases[index]))]
            references[index] = reference
    for index, reference in references.items():
        # 乐句节奏与音值分组：修改，旧重复段调用保留；复拍重复仍使用实际大拍。
        # paths[index] = solve_phrase(phrases[index],entries[index][0],entries[index][1],maxima[index],reference)
        paths[index] = solve_phrase(phrases[index],entries[index][0],entries[index][1],maxima[index],reference,beat_quarters)
    decisions = []
    for index, phrase in enumerate(phrases):
        entry, latency, method = entries[index]
        maximum = round(entries[index + 1][0] * PPQ) if index + 1 < len(entries) else math.ceil((mapping.seconds_to_quarters(duration) - timing['score_start_quarter']) * PPQ)
        # 乐句节奏与音值分组：修改，旧重复计算注释保留；采用可追溯的整句联合结果。
        # cost, path = solve_phrase(phrase, entry, latency, maximum)
        cost, path = paths[index]
        # 乐句节奏与音值分组：修改，旧审计调用保留；元数据与实际求解共享大拍。
        # local_latency, terminal_latency = latency_profile(phrase, latency)
        local_latency, terminal_latency = latency_profile(phrase, latency, beat_quarters, maximum)
        for word, word_latency, (begin, end, lengths) in zip(phrase, local_latency, path):
            at = begin
            for note, length in zip(word['notes'], lengths):
                note.pop('notation_onset_prior', None)
                note.update(start_tick=at, end_tick=at + length, collapsed_to_grace=False,
                            rhythm_decision={'version': VERSION, 'phrase': index,
                                             'performance_latency_quarters': word_latency,
                                             'source_boundary_unchanged': True})
                at += length
        decisions.append({'phrase': index, 'first_character_index': phrase[0]['char'].get('index'),
                          'last_character_index': phrase[-1]['char'].get('index'),
                          'entry_tick': round(entry * PPQ), 'latency_quarters': latency,
                          'terminal_latency_quarters': terminal_latency,
                          'method': method, 'candidate_cost': cost,
                          'observed_repeat_soft_reference': index in references,
                          'word_count': len(phrase), 'end_tick': path[-1][1],
                          'words': [{'character_index': w['char'].get('index'), 'begin_tick': p[0], 'end_tick': p[1]} for w, p in zip(phrase, path)]})
        if entries[index] != defaults[index]:
            decisions[-1]['joint_boundary_constraint'] = {
                'version':1,'original_entry_tick':round(defaults[index][0]*PPQ),
                'selected_entry_tick':round(entry*PPQ),
                'maximum_latency_quarters':POLICY['maximum_phrase_latency_quarters'],
                'source_times_and_pitches_unchanged':True,'accuracy_verified':False}
        _, unbounded_terminal = latency_profile(phrase, latency, beat_quarters)
        if terminal_latency != unbounded_terminal:
            decisions[-1]['terminal_boundary_constraint'] = {
                'version': 1, 'next_phrase_or_audio_limit_tick': maximum,
                'unconstrained_latency_quarters': unbounded_terminal,
                'constrained_latency_quarters': terminal_latency,
                'source_times_and_pitches_unchanged': True,
                'accuracy_verified': False}
    by_id = {n['id']: n for n in output}
    for note in output:
        if note.get('grace'):
            anchor = by_id[note['anchor_id']]
            note.update(start_tick=anchor['start_tick'], end_tick=anchor['start_tick'], collapsed_to_grace=False)
    main = sorted((n for n in output if not n.get('grace')), key=lambda n: n['start_tick'])
    if any(a['end_tick'] > b['start_tick'] for a, b in zip(main, main[1:])):
        raise ValueError('乐句联合结果重叠，拒绝导出。')
    return output, {'version': VERSION, 'policy': dict(POLICY), 'phrases': decisions,
                    'observed_repeat_groups': repeat_groups,
                    'source_piece_count': len(output), 'preserved_pitch_ids_and_source_seconds': True,
                    'human_beat_answers_used_by_solver': False}


# 乐句节奏与音值分组：新增语义演奏分配，倚音预算取自主音和细网格，独立于显示拆符。
def allocate_playback(notes, timing):
    by_id = {n['id']: n for n in notes}
    grace_groups = defaultdict(list)
    for note in notes:
        note['playback_start_tick'], note['playback_end_tick'] = note['start_tick'], note['end_tick']
        if note.get('grace'):
            grace_groups[note['anchor_id']].append(note)
    for anchor_id, graces in grace_groups.items():
        anchor = by_id[anchor_id]
        budget = min((anchor['end_tick'] - anchor['start_tick']) // 3, GRID - 1)
        if len(graces) > budget:
            raise ValueError('倚音组超出语义播放预算。')
        remaining = budget
        at = anchor['start_tick']
        for i, grace in enumerate(graces):
            measured = max(1, round((grace['end_seconds'] - grace['start_seconds']) * PPQ * timing['steady_tempo_bpm'] / 60))
            length = min(measured, remaining - (len(graces) - i - 1))
            grace['playback_start_tick'], grace['playback_end_tick'] = at, at + length
            grace['grace_semantic_ticks'] = length
            at += length
            remaining -= length
        anchor['playback_start_tick'] = at


# 乐句节奏与音值分组：新增共享记谱层，音符和休止显露拍界，原语义音段只用延音线拆写。
def notation_events(notes, total, timing):
    from rhythm_notation import split_rhythm, MeterTree
    meter = timing['meter']; groups = timing.get('beat_groups')
    tree = MeterTree.from_meter(meter, groups)
    # 通用段落强拍与乐句节奏修复：修改，保留二等分拆写；新增明确连音窗口传入共享记谱层。
    # split = lambda a, b, rest=False: split_rhythm(a, b, meter, groups, rest)
    from rhythm_notation import split_rhythm_tuplets
    tuplets=timing.get('rhythm_tuplet_groups',[])
    split = lambda a,b,rest=False: split_rhythm_tuplets(a,b,meter,groups,rest,tuplets) if tuplets else split_rhythm(a,b,meter,groups,rest)
    events = []; cursor = 0
    ordered = sorted(notes, key=lambda n: (n['start_tick'], not bool(n.get('grace')), n['start_seconds']))
    by_id = {n['id']: n for n in notes}
    def rests(a, b):
        return [dict(p, piece_id=None, pitch_midi=None, grace=False, ties=[], lyric_index=None) for p in split(a, b, True)]
    for note in ordered:
        begin, end = note['start_tick'], note['end_tick']
        if begin > cursor:
            events.extend(rests(cursor, begin)); cursor = begin
        if note.get('grace'):
            anchor = by_id[note['anchor_id']]
            first_duration = split(anchor['start_tick'], anchor['end_tick'])[0]['duration_ticks']
            # 乐句节奏与音值分组：新增XML显示百分比只由已固定播放tick换算，不能反向改变试听。
            percent = 100 * note['grace_semantic_ticks'] / first_duration
            note['grace_steal_percent'] = percent
            events.append(dict(start_tick=begin, duration_ticks=0, type='eighth', dots=0,
                               piece_id=note['id'], pitch_midi=note['pitch_midi'], grace=True,
                               ties=[], lyric_index=None, grace_steal_percent=percent,
                               anchor_id=note['anchor_id']))
        else:
            parts = split(begin, end)
            for i, part in enumerate(parts):
                events.append(dict(part, piece_id=note['id'], pitch_midi=note['pitch_midi'], grace=False,
                                   ties=(['stop'] if i else []) + (['start'] if i < len(parts)-1 else []),
                                   lyric_index=note.get('lyric_index'), role=note['role']))
            cursor = end
    events.extend(rests(cursor, total))
    for i, event in enumerate(events):
        event.update(id=f'music_n{i+1}', measure=event['start_tick']//tree.bar_ticks+1,
                     offset_ticks=event['start_tick']%tree.bar_ticks)
    # 乐句节奏与音值分组：新增真实转音连奏和跨字滑音，保留同音延音/不同音slur的区别。
    by_char = defaultdict(list); by_piece = defaultdict(list); number = 0
    for event in events:
        if event.get('pitch_midi') is not None and not event.get('grace'):
            by_piece[event['piece_id']].append(event)
            if event.get('lyric_index') is not None:
                by_char[event['lyric_index']].append(event)
    for group in by_char.values():
        if len({e['pitch_midi'] for e in group}) > 1:
            number += 1
            group[0].setdefault('slurs', []).append({'type':'start','number':number%6+1})
            group[-1].setdefault('slurs', []).append({'type':'stop','number':number%6+1})
    seen = set()
    for note in ordered:
        pairs = []
        if note.get('legato_target_piece_id'): pairs.append((note['id'], note['legato_target_piece_id']))
        if note.get('legato_source_piece_id'): pairs.append((note['legato_source_piece_id'], note['id']))
        for pair in pairs:
            if pair in seen: continue
            seen.add(pair); left, right = (by_piece[p] for p in pair)
            if not left or not right or left[-1]['pitch_midi'] == right[0]['pitch_midi'] or left[-1].get('lyric_index') == right[0].get('lyric_index'): continue
            number += 1; bridge = number%4+13
            left[-1].setdefault('slurs', []).append({'type':'start','number':bridge})
            right[0].setdefault('slurs', []).append({'type':'stop','number':bridge})
    for event in events:
        if event.get('grace'):
            number += 1; grace_number = number%6+7
            event.setdefault('slurs', []).append({'type':'start','number':grace_number})
            by_piece[event['anchor_id']][0].setdefault('slurs', []).append({'type':'stop','number':grace_number})
    # 通用段落强拍与乐句节奏修复：新增真实连音开始/结束语义，转音碎片和休止共同覆盖整拍。
    tuplet_events=defaultdict(list)
    for event in events:
        if event.get('tuplet'):tuplet_events[event['tuplet']['id']].append(event)
    for group in tuplet_events.values():
        a,b=group[0]['tuplet']['start_tick'],group[0]['tuplet']['end_tick']
        if group[0]['start_tick']!=a or sum(e['duration_ticks'] for e in group)!=b-a:
            raise ValueError('三连音没有完整覆盖该拍。')
        group[0]['tuplet_start']=True;group[-1]['tuplet_stop']=True
    return events


# 乐句节奏与音值分组：新增完整派生接口与分层审计，后续导出必须通过音值和覆盖检查。
def quantize_phrase(pieces, characters, mapping, timing, duration):
    import statistics
    import numpy as np
    from rhythm_notation import MeterTree, validate_grouping
    # 局部拍轴与原唱同步纠错：修改，原句首单候选调用注释保留；历史工程仍用旧策略，实测局部拍轴用新版联合求解。
    # notes, audit = solve_words(pieces, characters, mapping, timing, duration)
    # 通用段落强拍与乐句节奏修复：修改，旧局部策略仍可重建；新版本才启用结构求解和真实连音。
    # if timing.get('local_beat_clock', {}).get('status') == 'tracked':
    if timing.get('structural_rhythm'):
        from phrase_rhythm_structure import solve_words as solve_structural_words
        notes,audit=solve_structural_words(pieces,characters,mapping,timing,duration)
        timing['rhythm_tuplet_groups']=deepcopy(audit['tuplet_groups'])
    elif timing.get('local_beat_clock', {}).get('status') == 'tracked':
        from phrase_rhythm_local import solve_words as solve_local_words
        notes, audit = solve_local_words(pieces, characters, mapping, timing, duration)
    else:
        notes, audit = solve_words(pieces, characters, mapping, timing, duration)
    allocate_playback(notes, timing)
    tree = MeterTree.from_meter(timing['meter'], timing.get('beat_groups'))
    last = max((n['end_tick'] for n in notes), default=0)
    audio_end = (mapping.seconds_to_quarters(duration) - timing['score_start_quarter'])*PPQ
    total = max(tree.bar_ticks, math.ceil(max(last, audio_end)/tree.bar_ticks)*tree.bar_ticks)
    events = notation_events(notes, total, timing)
    grouping = validate_grouping(events, timing['meter'], timing.get('beat_groups'))
    if not grouping['valid']: raise ValueError(str(grouping['errors']))
    errors = []
    for note in notes:
        for edge in ('start','end'):
            second = mapping.quarters_to_seconds(note[edge+'_tick']/PPQ + timing['score_start_quarter'])
            note['quantized_'+edge+'_seconds'] = second
            note[edge+'_error_seconds'] = second - note[edge+'_seconds']
            if not note.get('grace'): errors.append(abs(note[edge+'_error_seconds']))
    stats = {'raw_pitched_notes':len({p['source_note_id'] for p in pieces}), 'lyric_split_pieces':len(pieces),
             'grace_notes_from_collapsed_grid':0, 'classified_grace_notes':sum(bool(n.get('grace')) for n in notes),
             'main_notes':sum(n['role']=='main' for n in notes), 'turn_notes':sum(n['role']=='turn' for n in notes),
             'grid_quarters':GRID/PPQ, 'measure_count':total//tree.bar_ticks, 'bar_ticks':tree.bar_ticks, 'total_ticks':total,
             'quantization_error_seconds':{'median_abs':statistics.median(errors) if errors else 0,
                                          'p95_abs':float(np.percentile(errors,95)) if errors else 0,'max_abs':max(errors,default=0)},
             'phrase_rhythm':audit, 'rhythm_grouping':grouping}
    return events, notes, stats
