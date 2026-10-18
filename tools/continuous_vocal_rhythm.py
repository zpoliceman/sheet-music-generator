"""连续源拍序与人声联合重解通用修复：确认源拍轴后联合字头、主音、音值与人工未决保护。"""
from collections import defaultdict
from copy import deepcopy
import math
from score_export import PPQ, TempoMap, attach_lyrics, tempo_events
from phrase_rhythm import allocate_durations, allocate_playback, notation_events
from rhythm_notation import validate_grouping

# 连续源拍序与人声联合重解通用修复：新增独立版本的 articulation 与格位策略，不读取文字内容。
POLICY = {'version': 1, 'unvoiced_initial_early_quarters': .18, 'voiced_head_early_quarters': .30,
          'late_allowance_quarters': .08, 'interval_sigma_quarters': .12,
          'fine_onset_penalty': .26, 'minimum_onset_improvement': .24,
          'maximum_candidate_shift_quarters': 1., 'maximum_prefix_quarters': .6,
          'maximum_prefix_stable_quarters': .25, 'grace_core_confidence_margin': .15,
          'source_note_identity_pitch_seconds_lyric_preserved': True,
          # 连续源拍序与人声联合重解通用修复：修改，旧末项保留；未确认的连续组件必须同时保护人声记谱。
          # 'review_preserve_is_reference_answer': False}
          'review_preserve_is_reference_answer': False, 'uncertain_pulse_preserves_notation': True}


# 连续源拍序与人声联合重解通用修复：新增源指纹和音段身份核验的人工保留，不能把别曲清单误用到当前音乐。
def review_locks(base, binding, review=None):
    locks = {}
    if review:
        if (review.get('schema_version') != 1 or review.get('action') != 'preserve_unresolved_notation'
                or review.get('source_vocal_project_sha256') != binding['vocal_project_sha256']):
            raise ValueError('未决记谱保留清单的策略或人声源指纹不符。')
        actual = {n['id']: n for n in base['quantized_notes']}
        fields = ('id', 'source_note_id', 'lyric_index', 'pitch_midi', 'start_seconds', 'end_seconds')
        for note in review['notes']:
            if note['id'] not in actual or any(actual[note['id']].get(k) != note.get(k) for k in fields):
                raise ValueError('未决保留音段无法从绑定来源确认。')
            locks[note['id']] = deepcopy(note)
    # 连续源拍序与人声联合重解通用修复：新增已确认人声拍位范围保护；人工16拍等复核优先于自动候选。
    phase = base['timing'].get('beat_phase') or {}
    beats = phase.get('vocal_beats', []) if phase.get('review_id') else []
    if beats:
        origin = base['timing']['score_start_quarter']
        a = round((min(x['quarter'] for x in beats) - origin) * PPQ)
        b = round((max(x['quarter'] for x in beats) - origin + 4 / base['timing']['meter'][1]) * PPQ)
        for note in base['quantized_notes']:
            if note['start_tick'] < b and note['end_tick'] > a:
                locks.setdefault(note['id'], deepcopy(note))
    # 连续源拍序与人声联合重解通用修复：新增真实连音组原形保护，新二等分候选不能强写三连音或其它非二等分。
    tuplets = base['timing'].get('rhythm_tuplet_groups', [])
    tuplet_words = {n.get('lyric_index') for n in base['quantized_notes']
                   if not n.get('grace') and (n['start_tick'] % 60 or n['end_tick'] % 60
                   or any(n['start_tick'] < t['end_tick'] and n['end_tick'] > t['start_tick'] for t in tuplets))}
    for note in base['quantized_notes']:
        if note.get('lyric_index') in tuplet_words:
            locks.setdefault(note['id'], deepcopy(note))
    return locks


# 连续源拍序与人声联合重解通用修复：新增语音/有声核心的软区间，不把声母前沿、元音和音符起点混为同一秒。
def head_interval(notes, char, mapping, origin):
    normal = [n for n in notes if not n.get('grace')]
    core = next((n for n in normal if n.get('anchor') or n.get('role') == 'main'), normal[0])
    phonemes = [p for p in char.get('phonemes', []) if not p.get('skipped') and p.get('start_seconds') is not None]
    nucleus = next((p for p in phonemes if p.get('role') == 'nucleus'), None)
    initial = next((p for p in phonemes if p.get('role') in ('initial', 'voiced_initial')), None)
    q = lambda seconds: mapping.seconds_to_quarters(seconds) - origin
    if initial and nucleus and initial['role'] == 'initial':
        center = q(nucleus['start_seconds']); early = POLICY['unvoiced_initial_early_quarters']
    else:
        center = q(min(core['start_seconds'], nucleus['start_seconds']) if nucleus else core['start_seconds'])
        early = POLICY['voiced_head_early_quarters']
    return center - early, center + POLICY['late_allowance_quarters'], core, bool(nucleus)


# 连续源拍序与人声联合重解通用修复：新增短弱滑入音转倚音的多证据候选；源音不删除，明确主音承载歌词。
def prefix_graces(notes, core, nominal, has_nucleus):
    if not has_nucleus:
        return []
    prefix = [n for n in notes if not n.get('grace') and n['start_seconds'] < core['start_seconds']]
    if not prefix:
        return []
    if ((core['start_seconds'] - prefix[0]['start_seconds']) / nominal > POLICY['maximum_prefix_quarters']
            or any(n.get('role') != 'turn' or n.get('anchor') for n in prefix)
            or any(n.get('confidence', 0.) + POLICY['grace_core_confidence_margin'] >= core.get('confidence', 0.) for n in prefix)
            or any(n.get('stable_duration_seconds', 0.) / nominal > POLICY['maximum_prefix_stable_quarters'] for n in prefix)):
        return []
    return prefix


# 连续源拍序与人声联合重解通用修复：新增 onset 区间代价，确实有十六分证据的音仍能胜出。
def onset_cost(word, tick):
    q = tick / PPQ
    outside = max(word['lower'] - q, 0., q - word['upper'])
    value = (outside / POLICY['interval_sigma_quarters']) ** 2
    if tick % (PPQ // 2):
        value += POLICY['fine_onset_penalty']
    return value


# 连续源拍序与人声联合重解通用修复：新增所有字的联合顺序求解，保留弱起、真休止与人工未决的完整记谱形状。
# 连续源拍序与人声联合重解通用修复：修改，旧签名保留；允许传入实际拍轴覆盖与冲突结果。
# def solve_rhythm(base, knots, binding, review=None):
def solve_rhythm(base, knots, binding, review=None, clock_audit=None):
    output = deepcopy(base); mapping = TempoMap(knots); origin = base['timing']['score_start_quarter']
    nominal = 60 / base['timing']['steady_tempo_bpm']; locks = review_locks(base, binding, review)
    # 连续源拍序与人声联合重解通用修复：新增拍轴失败段整字保留；没有新攻击证据时保留原记谱，不把音素模型当拍轴真值。
    clock_locked_ids = set()
    if clock_audit is not None:
        weak = [r for r in clock_audit.get('components', [])
                if r['status'] != 'continuous_source_sequence_selected']
        lack_all_events = not clock_audit.get('observations')
        affected_words = {n.get('lyric_index') for n in base['quantized_notes']
            if lack_all_events or any(r.get('start_seconds', float('inf')) <= n['start_seconds']
                                      <= r.get('end_seconds', -float('inf')) for r in weak)}
        for n in base['quantized_notes']:
            if n.get('lyric_index') in affected_words:
                locks.setdefault(n['id'], deepcopy(n)); clock_locked_ids.add(n['id'])
    groups = defaultdict(list)
    for note in output['quantized_notes']:
        if note.get('lyric_index') is not None:
            groups[note['lyric_index']].append(note)
    chars = {c['index']: c for c in base['lyrics']['characters']}; words = []
    for index, notes in groups.items():
        notes.sort(key=lambda n: n['start_seconds'])
        normal = [n for n in notes if not n.get('grace')]
        if not normal:
            continue
        lower, upper, core, supported = head_interval(notes, chars[index], mapping, origin)
        locked = any(n['id'] in locks for n in notes)
        prefix = [] if locked else prefix_graces(notes, core, nominal, supported)
        old = normal[0]['start_tick']; end = max(n['end_tick'] for n in normal)
        word = {'index': index, 'notes': notes, 'char': chars[index], 'lower': lower, 'upper': upper,
                'old': old, 'old_end': end, 'core': core, 'prefix': prefix, 'locked': locked,
                'first_seconds': notes[0]['start_seconds'], 'end_seconds': notes[-1]['end_seconds']}
        min_slots = len(normal) - len(prefix)
        word['minimum_ticks'] = max(60, min_slots * 60)
        candidates = {old}
        # 连续源拍序与人声联合重解通用修复：修改，原只按音素支持开候选保留；清楚有声起音已支持旧格位时不能为规整删掉真实十六分。
        # if supported and not locked:
        phonemes = chars[index].get('phonemes', [])
        initial = next((p for p in phonemes if p.get('role') == 'initial' and not p.get('skipped')), None)
        nucleus = next((p for p in phonemes if p.get('role') == 'nucleus' and not p.get('skipped')), None)
        long_unvoiced_initial = bool(initial and nucleus and (nucleus['start_seconds'] - initial['start_seconds']) / nominal > .12)
        voiced_quarter = mapping.seconds_to_quarters(core['start_seconds']) - origin
        old_source_supported = abs(voiced_quarter - old / PPQ) <= .10 and not prefix and not long_unvoiced_initial
        if supported and not locked and not old_source_supported:
            first = math.floor((lower - .20) * 4); last = math.ceil((upper + .20) * 4)
            alternatives = [q * 120 for q in range(first, last + 1) if q >= 0 and abs(q / 4 - old / PPQ) <= 1.]
            best = min(alternatives, key=lambda tick: (onset_cost(word, tick), abs(tick - old), tick)) if alternatives else old
            improvement = onset_cost(word, old) - onset_cost(word, best)
            if improvement >= POLICY['minimum_onset_improvement'] or prefix:
                candidates.update(alternatives)
        word['candidates'] = sorted(candidates); words.append(word)
    words.sort(key=lambda w: (w['first_seconds'], w['index']))
    if not words:
        return output, {'version': 1, 'policy': deepcopy(POLICY), 'words': [], 'source_changed': False}
    states = {tick: (onset_cost(words[0], tick), (tick,)) for tick in words[0]['candidates']}
    for left, right in zip(words, words[1:]):
        following = {}
        for tick in right['candidates']:
            options = []
            for previous, (cost, path) in states.items():
                minimum = left['old_end'] - previous if left['locked'] else left['minimum_ticks']
                if tick - previous < minimum:
                    continue
                raw_delta = mapping.seconds_to_quarters(right['first_seconds']) - mapping.seconds_to_quarters(left['first_seconds'])
                continuity = .025 * (((tick - previous) / PPQ - raw_delta) / .25) ** 2
                value = cost + onset_cost(right, tick) + continuity + .02 * ((tick - right['old']) / PPQ / .25) ** 2
                options.append((value, path + (tick,)))
            if options:
                following[tick] = min(options, key=lambda row: (row[0], row[1]))
        if not following:
            raise ValueError('人声联合候选与未决保留冲突，拒绝游标挤压或删除原音。')
        states = following
    _, path = min(states.values(), key=lambda row: (row[0], row[1]))
    audit = []
    for serial, (word, begin) in enumerate(zip(words, path)):
        notes = word['notes']; normal = [n for n in notes if not n.get('grace') and n not in word['prefix']]
        following = words[serial + 1] if serial + 1 < len(words) else None
        next_begin = path[serial + 1] if following else base['statistics']['total_ticks']
        end = word['old_end'] + begin - word['old']
        # 连续源拍序与人声联合重解通用修复：新增临近连读联合边界，真实停顿不填平；保护锁定音完整形状。
        continuous = following and ((following['first_seconds'] - word['end_seconds']) / nominal < .18)
        if continuous:
            end = next_begin
        elif end > next_begin:
            end = next_begin
        if word['locked']:
            for note in notes:
                if note['id'] in locks:
                    note.update(deepcopy(locks[note['id']]))
            # 连续源拍序与人声联合重解通用修复：修改，旧把所有保护称人工复核保留；自动弱拍轴保护须明确来源。
            # audit.append({'character_index': word['index'], 'action': 'reviewed_notation_preserved', 'start_tick': word['old']})
            action = 'uncertain_pulse_notation_preserved' if any(n['id'] in clock_locked_ids for n in notes) else 'reviewed_notation_preserved'
            audit.append({'character_index': word['index'], 'action': action, 'start_tick': word['old']})
            continue
        if begin == word['old'] and end == word['old_end'] and not word['prefix']:
            audit.append({'character_index': word['index'], 'action': 'supported_previous_rhythm_retained', 'start_tick': begin})
            continue
        lengths = allocate_durations(tuple(round((n['end_seconds'] - n['start_seconds']) / nominal, 6) for n in normal), end - begin)[1]
        if not lengths:
            # 连续源拍序与人声联合重解通用修复：修改，保留旧报错；新增字身份与时值诊断，不用删音掩盖冲突。
            # raise ValueError('人声词内主音不能完整落入联合候选，拒绝删音。')
            raise ValueError(f'人声词内主音不能完整落入联合候选，拒绝删音：字ID={word["index"]}，范围={begin}:{end}，音数={len(normal)}。')
        at = begin
        for note, length in zip(normal, lengths):
            note.update(start_tick=at, end_tick=at + length, rhythm_decision={
                'version': 1, 'strategy': 'continuous_source_sequence_joint',
                'source_boundary_unchanged': True, 'phoneme_start_is_musical_onset': False})
            at += length
        for note in word['prefix']:
            note.update(grace=True, role='grace', anchor_id=word['core']['id'], start_tick=begin, end_tick=begin,
                        collapsed_to_grace=True, rhythm_decision={'version': 1, 'strategy': 'source_supported_prefix_grace'})
        for note in notes:
            if note.get('grace'):
                anchor = next(n for n in notes if n['id'] == note['anchor_id'])
                note.update(start_tick=anchor['start_tick'], end_tick=anchor['start_tick'])
        audit.append({'character_index': word['index'], 'action': 'source_supported_joint_rhythm',
                      'old_start_tick': word['old'], 'start_tick': begin, 'end_tick': end,
                      'prefix_grace_ids': [n['id'] for n in word['prefix']],
                      'musical_onset_interval_quarters': [word['lower'], word['upper']],
                      'original_performance_offset_seconds': word['core']['start_seconds'] - mapping.quarters_to_seconds(begin / PPQ + origin)})
    output['timing'].update(knots=deepcopy(knots), score_start_seconds=mapping.quarters_to_seconds(origin))
    notes = output['quantized_notes']; allocate_playback(notes, output['timing'])
    # 连续源拍序与人声联合重解通用修复：新增保留倚音语义播放的完整人工锁，普通音更新可回放的演唱偏移字段。
    for note in notes:
        if note['id'] in locks:
            for key in ('playback_start_tick', 'playback_end_tick', 'grace_semantic_ticks', 'grace_steal_percent'):
                if key in locks[note['id']]:
                    note[key] = locks[note['id']][key]
        for side in ('start', 'end'):
            seconds = mapping.quarters_to_seconds(note[side + '_tick'] / PPQ + origin)
            note['quantized_' + side + '_seconds'] = seconds
            note[side + '_error_seconds'] = seconds - note[side + '_seconds']
    total = max(base['statistics']['total_ticks'], max(n['end_tick'] for n in notes))
    events = notation_events(notes, total, output['timing'])
    output['lyric_mapping'] = attach_lyrics(events, output['lyrics']['characters']); output['events'] = events
    grouping = validate_grouping(events, output['timing']['meter'], output['timing'].get('beat_groups'))
    if not grouping['valid']:
        raise ValueError('共同人声重解的音值组合失败：' + str(grouping['errors'][:5]))
    output['statistics']['rhythm_grouping'] = grouping
    output['tempo_events'] = tempo_events(mapping, output['timing'], total)
    result = {'version': 1, 'policy': deepcopy(POLICY), 'words': audit,
              'locked_note_ids': sorted(locks), 'source_note_identity_pitch_seconds_lyric_preserved': True,
              'reference_score_used': False, 'musical_and_phonetic_onsets_separated': True}
    # 连续源拍序与人声联合重解通用修复：新增弱拍轴保护独立账本，不冒称这些音已获音乐确认。
    result['uncertain_clock_locked_note_ids'] = sorted(clock_locked_ids)
    output['statistics']['continuous_vocal_rhythm'] = deepcopy(result)
    output['decoder']['continuous_vocal_rhythm'] = {'version': 1, 'source_seconds_preserved': True}
    return output, result
