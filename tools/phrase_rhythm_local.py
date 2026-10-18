"""局部拍轴与原唱同步纠错：新增多入口、跨句边界联合求解，旧策略仍用于历史重建。"""
from copy import deepcopy
from collections import defaultdict
import math
import statistics
# 局部拍轴与原唱同步纠错：修改，保留原导入；新版在原时值代价上增加相邻字时长证据的权重。
# from phrase_rhythm import (PPQ, word_models, phrase_entry, latency_profile, start_candidates,
#                            end_candidates, onset_cost, slot_cost, has_sounding_gap, release_cost)
# 局部拍轴与原唱同步纠错：修改，保留原导入；新版单独处理音高平台早于语音字界的时长证据。
# from phrase_rhythm import (PPQ, word_models, phrase_entry, start_candidates,
#                            end_candidates, onset_cost, slot_cost as source_slot_cost, has_sounding_gap, release_cost)
from phrase_rhythm import (PPQ, word_models as source_word_models, phrase_entry, start_candidates,
                           end_candidates, onset_cost, slot_cost as source_slot_cost, has_sounding_gap, release_cost)

VERSION = 2
POLICY = {'version': VERSION, 'entry_search_quarters': .35,
          'entry_observation_weight': .4, 'entry_legacy_soft_weight': .08,
          # 局部拍轴与原唱同步纠错：修改，原较强八分入口偏好保留；清楚的十六分弱起应能胜过启发式。
          # 'binary_entry_penalty': .30, 'rapid_entry_penalty': .35,
          'binary_entry_penalty': .20, 'rapid_entry_penalty': .35,
          'job_boundary_gap_quarters': .45, 'long_word_span_quarters': 1.5,
          # 局部拍轴与原唱同步纠错：修改，明确十六分弱起不受长音终止偏好覆盖；仅近小节线且长音的歧义做软比较。
          # 'cadence_barline_window_quarters': .25, 'cadence_barline_penalty': .25,
          # 局部拍轴与原唱同步纠错：修改，移除重复延迟补偿后恢复轻量终止先验，不强迫长音整拍化。
          # 'cadence_barline_window_quarters': .20, 'cadence_barline_penalty': .65,
          'cadence_barline_window_quarters': .20, 'cadence_barline_penalty': .25,
          # 局部拍轴与原唱同步纠错：新增局部拍轴已经处理演奏速度，不再把句尾释放滞后投射到字首。
          'terminal_release_latency': 'not_projected_to_word_onsets',
          # 局部拍轴与原唱同步纠错：新增词时长与音素位置共同竞争，不让有误差的字界压倒相邻长短关系。
          'duration_fit_weight': 1.2,
          # 局部拍轴与原唱同步纠错：新增字界之前的音高平台不能强迫本字时值扩大；音素字界只提供时长证据。
          'prephoneme_plateau_quarters': .15, 'early_platform_duration_evidence': 'aligned_phoneme_span',
          'voiced_onset_weight': .1, 'short_rest_penalty': .08,
          'repeat_core_pitch_tolerance': 1, 'repeat_core_match_fraction': .8}


# 局部拍轴与原唱同步纠错：新增保留音段但避免把前字的同音平台时长重复算给后字。
def word_models(pieces, characters, mapping, timing):
    words=source_word_models(pieces,characters,mapping,timing)
    for word in words:
        phones=[p for p in word['char'].get('phonemes',[]) if not p.get('skipped')
                and p.get('start_seconds') is not None and p.get('end_seconds') is not None]
        if not word['orphan'] and phones and word['start']-word['voiced_start']>POLICY['prephoneme_plateau_quarters']:
            word['source_platform_span']=word['observed_span']
            word['observed_span']=max(.025,word['end']-word['start'])
            word['duration_evidence']='aligned_phoneme_span_after_early_pitch_platform'
    return words


# 局部拍轴与原唱同步纠错：新增软句窗边界，短促连续字音不因识别任务换窗被硬拆。
def music_phrases(words):
    result = []
    for word in words:
        if not result:
            result.append([word]); continue
        last = result[-1][-1]
        gap = word['voiced_start']-last['voiced_end']
        changed_job = word['job'] is not None and last['job'] is not None and word['job'] != last['job']
        if (gap >= .65 or changed_job and gap >= POLICY['job_boundary_gap_quarters'] or
                word['orphan'] != last['orphan']):
            result.append([word])
        else:
            result[-1].append(word)
    return result


# 局部拍轴与原唱同步纠错：新增多个入口；原八分/快速组启发式仅提供软代价，不再锁死首字。
def entry_candidates(words, beat_quarters):
    legacy, _, method = phrase_entry(words, beat_quarters)
    observed = words[0]['start']
    values = {legacy}
    for k in range(math.floor((observed-.35)*4), math.ceil((observed+.35)*4)+1):
        if k >= 0 and abs(k/4-observed) <= POLICY['entry_search_quarters']:
            values.add(k/4)
    result = []
    for entry in sorted(values):
        latency = max(-.30, min(.30, observed-entry))
        cost = POLICY['entry_observation_weight']*((entry-observed)/.25)**2
        cost += POLICY['entry_legacy_soft_weight']*((entry-legacy)/.25)**2
        if method == 'binary_entry_candidate' and round(entry*PPQ) % (PPQ//2):
            cost += POLICY['binary_entry_penalty']
        if method == 'rapid_syllabic_group_with_sustained_cadence' and abs(entry/beat_quarters-round(entry/beat_quarters)) > 1e-8:
            cost += POLICY['rapid_entry_penalty']
        result.append((entry, latency, method, cost))
    return result


# 局部拍轴与原唱同步纠错：新增声学字首/发声起点软证据与长终止音的拍层级，不禁真实弱起。
def musical_onset_cost(word, tick, latency, bar_ticks):
    value = onset_cost(word, tick, latency)
    value += POLICY['voiced_onset_weight']*((tick/PPQ-word['voiced_start']+latency)/.25)**2
    if not word['orphan'] and word['observed_span'] >= POLICY['long_word_span_quarters']:
        center = (word['start']+word['voiced_start'])/2-latency
        bar = bar_ticks/PPQ
        if abs(center-round(center/bar)*bar) <= POLICY['cadence_barline_window_quarters'] and tick % bar_ticks:
            value += POLICY['cadence_barline_penalty']
    return value


# 局部拍轴与原唱同步纠错：新增通用词时长拟合，保留真实音序分配与短音/附点候选。
def slot_cost(word, begin, end, latency):
    cost, lengths = source_slot_cost(word, begin, end, latency)
    if lengths:
        cost += (POLICY['duration_fit_weight']-.8)*math.log(max(.001, (end-begin)/PPQ/word['observed_span']))**2
    return cost, lengths


# 局部拍轴与原唱同步纠错：新增保留多种句尾的候选路径，前后句不能各自固定入口后再强挤。
def phrase_options(words, entries, maximum, beat_quarters, bar_ticks, reference=None):
    options = []
    for entry, latency, method, entry_cost in entries:
        # 局部拍轴与原唱同步纠错：修改，原启发式保留；实测拍轴下释放与字首独立，避免双重提前末字。
        # local_latency, terminal_latency = latency_profile(words, latency, beat_quarters)
        local_latency, terminal_latency = [latency]*len(words), latency
        first = round(entry*PPQ)
        states = {first: (entry_cost+musical_onset_cost(words[0], first, latency, bar_ticks), ())}
        for index, word in enumerate(words[:-1]):
            nxt = words[index+1]
            following = {}
            gap = has_sounding_gap(word, nxt)
            for begin, (cost, path) in states.items():
                for next_begin in start_candidates(nxt, local_latency[index+1]):
                    if next_begin <= begin or next_begin >= maximum:
                        continue
                    endings = set(end_candidates(word, local_latency[index], next_begin)) if gap else {next_begin}
                    # 局部拍轴与原唱同步纠错：新增短发声空隙的连读候选，真实休止仍参与竞争。
                    if gap and nxt['voiced_start']-word['voiced_end'] < .4:
                        endings.add(next_begin)
                    for end in endings:
                        if end <= begin:
                            continue
                        value, lengths = slot_cost(word, begin, end, local_latency[index])
                        if not math.isfinite(value):
                            continue
                        value += cost+musical_onset_cost(nxt, next_begin, local_latency[index+1], bar_ticks)
                        if reference is not None:
                            value += .10*((next_begin-first-reference[index+1])/PPQ/.25)**2
                        if gap and end < next_begin:
                            value += release_cost(word, end, local_latency[index], round(beat_quarters*PPQ))
                            observed_gap = nxt['voiced_start']-word['voiced_end']
                            value += .18*((next_begin-end)/PPQ-observed_gap)**2/.25**2
                            if observed_gap < .4:
                                value += POLICY['short_rest_penalty']
                        if next_begin not in following or value < following[next_begin][0]:
                            following[next_begin] = (value, path+((begin, end, lengths),))
            states = following
            if not states:
                break
        last = words[-1]
        final = {}
        for begin, (cost, path) in states.items():
            for end in end_candidates(last, terminal_latency, maximum):
                if end <= begin:
                    continue
                value, lengths = slot_cost(last, begin, end, local_latency[-1])
                value += cost+release_cost(last, end, terminal_latency, round(beat_quarters*PPQ))
                if math.isfinite(value) and (end not in final or value < final[end]['cost']):
                    final[end] = {'cost': value, 'path': path+((begin, end, lengths),),
                                  'entry': entry, 'latency': latency, 'method': method,
                                  'terminal_latency': terminal_latency, 'local_latency': local_latency}
        options.extend(final.values())
    if not options:
        raise ValueError('局部拍轴下乐句无可用完整候选，拒绝强制推迟字音。')
    return options


# 局部拍轴与原唱同步纠错：新增相邻乐句联合选择，跨句释放与弱起保持顺序和真实空隙。
def choose_phrases(phrases, all_options):
    states = [(p['cost'], (p,)) for p in all_options[0]]
    for index, options in enumerate(all_options[1:], 1):
        following = []
        raw_gap = max(0., phrases[index][0]['voiced_start']-phrases[index-1][-1]['voiced_end'])
        for option in options:
            begin = option['path'][0][0]
            candidates = []
            for cost, path in states:
                end = path[-1]['path'][-1][1]
                if end <= begin:
                    boundary_cost = .06*((begin-end)/PPQ-raw_gap)**2/.25**2
                    candidates.append((cost+option['cost']+boundary_cost, path+(option,)))
            if candidates:
                following.append(min(candidates, key=lambda x: x[0]))
        if not following:
            raise ValueError('相邻乐句边界冲突，不能把下一句歌词向后挤。')
        states = following
    return min(states, key=lambda x: x[0])[1]


# 局部拍轴与原唱同步纠错：新增允许装饰差异的主音骨架重复；来源只用实际词音，不搬人工节奏。
def repeat_groups(phrases):
    groups = []
    signatures = []
    for phrase in phrases:
        text = tuple(w['char'].get('text', '').casefold() for w in phrase)
        pitches = [max(w['notes'], key=lambda n: (n.get('role')=='main', n['end_seconds']-n['start_seconds']))['pitch_midi'] for w in phrase]
        signatures.append((text, tuple(p-pitches[0] for p in pitches)))
    used = set()
    for i, (text, pitches) in enumerate(signatures):
        if i in used or len(text) < 4 or any(w['orphan'] for w in phrases[i]):
            continue
        ids = [i]
        for j in range(i+1, len(phrases)):
            other_text, other = signatures[j]
            if text == other_text and sum(abs(a-b) <= POLICY['repeat_core_pitch_tolerance'] for a,b in zip(pitches,other))/len(pitches) >= POLICY['repeat_core_match_fraction']:
                ids.append(j)
        if len(ids) > 1:
            groups.append(ids); used.update(ids)
    return groups


# 局部拍轴与原唱同步纠错：新增新版整曲接口，原音高/音段角色/原秒时间及字音归属保持。
def solve_words(pieces, characters, mapping, timing, duration):
    from rhythm_notation import MeterTree
    output = deepcopy(pieces)
    words = word_models(output, characters, mapping, timing)
    if not words:
        return output, {'version': VERSION, 'policy': deepcopy(POLICY), 'phrases': [], 'observed_repeat_groups': [],
                        'source_piece_count': len(output), 'preserved_pitch_ids_and_source_seconds': True,
                        'human_beat_answers_used_by_solver': False}
    phrases = music_phrases(words)
    tree = MeterTree.from_meter(timing['meter'], timing.get('beat_groups'))
    beat_quarters = tree.groups[0]*tree.unit_ticks/PPQ
    entries = [entry_candidates(p, beat_quarters) for p in phrases]
    audio_end = math.ceil((mapping.seconds_to_quarters(duration)-timing['score_start_quarter'])*PPQ)
    maxima = [math.ceil((phrases[i+1][0]['start']+.5)*PPQ) if i+1 < len(phrases) else audio_end for i in range(len(phrases))]
    options = [phrase_options(p,e,m,beat_quarters,tree.bar_ticks) for p,e,m in zip(phrases,entries,maxima)]
    selected = choose_phrases(phrases, options)
    repeats = repeat_groups(phrases)
    references = {}
    for ids in repeats:
        for index in ids:
            others = [i for i in ids if i != index]
            references[index] = [statistics.median(selected[i]['path'][k][0]-selected[i]['path'][0][0] for i in others) for k in range(len(phrases[index]))]
    if references:
        for index, reference in references.items():
            options[index] = phrase_options(phrases[index], entries[index], maxima[index], beat_quarters, tree.bar_ticks, reference)
        selected = choose_phrases(phrases, options)
    decisions = []
    for index, (phrase, option) in enumerate(zip(phrases, selected)):
        for word, latency, (begin, end, lengths) in zip(phrase, option['local_latency'], option['path']):
            at = begin
            for note, length in zip(word['notes'], lengths):
                note.pop('notation_onset_prior', None)
                note.update(start_tick=at, end_tick=at+length, collapsed_to_grace=False,
                            rhythm_decision={'version': VERSION, 'phrase': index,
                                             'performance_latency_quarters': latency, 'source_boundary_unchanged': True})
                at += length
        decisions.append({'phrase': index, 'first_character_index': phrase[0]['char'].get('index'),
                          'last_character_index': phrase[-1]['char'].get('index'),
                          'entry_tick': round(option['entry']*PPQ), 'entry_candidate_count': len(entries[index]),
                          'latency_quarters': option['latency'], 'terminal_latency_quarters': option['terminal_latency'],
                          'method': 'multiple_entries_and_adjacent_phrases', 'candidate_cost': option['cost'],
                          'observed_repeat_soft_reference': index in references, 'word_count': len(phrase),
                          'end_tick': option['path'][-1][1],
                          # 局部拍轴与原唱同步纠错：修改，保留原简要决策；记录时长证据来源，原秒时间不动。
                          # 'words': [{'character_index':w['char'].get('index'),'begin_tick':p[0],'end_tick':p[1]} for w,p in zip(phrase,option['path'])]})
                          'words': [{'character_index':w['char'].get('index'),'begin_tick':p[0],'end_tick':p[1],
                                     'duration_evidence':w.get('duration_evidence','source_pitch_and_phoneme_span')} for w,p in zip(phrase,option['path'])]})
    by_id = {n['id']:n for n in output}
    for note in output:
        if note.get('grace'):
            anchor = by_id[note['anchor_id']]
            note.update(start_tick=anchor['start_tick'], end_tick=anchor['start_tick'], collapsed_to_grace=False)
    main = sorted((n for n in output if not n.get('grace')), key=lambda n:n['start_tick'])
    if any(a['end_tick'] > b['start_tick'] for a,b in zip(main, main[1:])):
        raise ValueError('局部乐句联合求解出现重叠，拒绝导出。')
    return output, {'version': VERSION, 'policy': deepcopy(POLICY), 'phrases': decisions,
                    'observed_repeat_groups': repeats, 'source_piece_count': len(output),
                    'preserved_pitch_ids_and_source_seconds': True, 'human_beat_answers_used_by_solver': False}
