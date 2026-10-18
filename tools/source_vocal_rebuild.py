"""原曲拍轴与歌词拍位通用修复：在独立源拍网上重解有声字头、音值和真实休止。"""
# 原曲拍轴与歌词拍位通用修复：新增独立字音策略，旧连续／legacy量化版本不改变。
from collections import defaultdict
from copy import deepcopy
import math
import numpy as np
from score_export import PPQ, TempoMap, read_json, sha256
# 原曲拍轴与歌词拍位通用修复：修改，保留首轮使用旧乐句求解器的导入；新源策略的音符边界独立受真实秒约束。
# from phrase_rhythm import quantize_phrase
from phrase_rhythm import allocate_playback, notation_events

POLICY = {'version': 1, 'stable_pitch_tolerance_semitones': 1., 'minimum_voiced_frames': 3,
          'minimum_grace_head_quarters': .20, 'grace_head_voiced_support': .50,
          'trim_unvoiced_prefix_quarters': .15, 'prefix_early_quarters': .20,
          'prefix_nucleus_distance_quarters': .08, 'source_pitch_reselected': False,
          'source_audio_and_f0_unchanged': True, 'lyric_text_reselected': False,
          # 原曲拍轴与歌词拍位通用修复：新增联合网格与最大声学误差，不能用乐句规整奖励挤压真实短音。
          'source_word_ownership_recorded': True, 'grid_ticks': 60,
          'maximum_onset_error_quarters': .24, 'onset_sigma_quarters': .10,
          # 原曲拍轴与歌词拍位通用修复：修改，旧细格奖励保留；字头优先规整拍位，但明确十六分证据仍可胜出。
          # 'sixteenth_penalty': .20, 'fine_grid_penalty': .65}
          'sixteenth_penalty': .20, 'fine_grid_penalty': 1.,
          'word_head_sixteenth_penalty': 1.8, 'word_head_fine_penalty': 2.3,
          'minimum_cross_word_tail_quarters': .25, 'minimum_cross_word_left_quarters': .06,
          'maximum_word_boundary_gap_quarters': .10}


# 原曲拍轴与歌词拍位通用修复：新增原音段／音素依赖强核验；原f0只读，新增候选可由同一来源严格重建。
def source_dependencies(vocal):
    result = {}
    for label in ('notes', 'lyrics'):
        path = vocal['inputs'][label + '_path']; expected = vocal['inputs'][label + '_sha256']
        if sha256(path) != expected:
            raise ValueError('原轨字音重建的源音段或音素已改变。')
        result[label] = {'path': path, 'sha256': expected}
    return result


# 原曲拍轴与歌词拍位通用修复：新增稳定有声首点，不将气声／静音开始当作有音高的歌唱音符。
def voiced_span(note, frames, midi, times):
    a = np.searchsorted(times, note['start_seconds']); b = np.searchsorted(times, note['end_seconds'])
    target = note.get('source_pitch_midi', note['pitch_midi'])
    valid = np.isfinite(midi[a:b]) & (np.abs(midi[a:b] - target) <= POLICY['stable_pitch_tolerance_semitones'])
    if not len(valid):
        return None, 0.
    size = POLICY['minimum_voiced_frames']
    runs = np.convolve(valid.astype(int), np.ones(size, dtype=int), mode='valid') if len(valid) >= size else []
    starts = np.flatnonzero(np.asarray(runs) == size)
    onset = float(times[a + starts[0]]) if len(starts) else None
    return onset, float(np.mean(valid))


# 原曲拍轴与歌词拍位通用修复：新增首音计量时值与装饰前缀的挂词范围；所有旧源身份／原秒／原音高单独保留。
def prepare_pieces(base, timing):
    dependencies = source_dependencies(base)
    analysis = read_json(dependencies['notes']['path'])
    frames = analysis.get('pitch_frames', [])
    times = np.array([f['time_seconds'] for f in frames])
    f0 = np.array([f['f0_hz'] for f in frames])
    midi = np.where(f0 > 0, 69 + 12 * np.log2(np.maximum(1e-9, f0) / 440), np.nan)
    chars = {c['index']: c for c in base['lyrics']['characters']}
    period = 60 / timing['steady_tempo_bpm']
    pieces, decisions = [], []
    for original in base['quantized_notes']:
        n = deepcopy(original); index = n.get('lyric_index'); char = chars.get(index)
        n['source_lyric_index'] = original.get('source_lyric_index', index)
        n['source_notation_grace'] = bool(original.get('grace'))
        n['source_interval_seconds'] = [original['start_seconds'], original['end_seconds']]
        for key in ('notation_onset_prior', 'rhythm_decision', 'grace_semantic_ticks', 'grace_steal_percent'):
            n.pop(key, None)
        onset, support = voiced_span(n, frames, midi, times)
        # 原曲拍轴与歌词拍位通用修复：新增任意有声证据；滑音暂离目标音高仍是有声，不能误裁成“无声前缀”。
        a, b = np.searchsorted(times, [n['start_seconds'], n['end_seconds']])
        any_voiced = np.isfinite(midi[a:b])
        runs = np.convolve(any_voiced.astype(int), np.ones(POLICY['minimum_voiced_frames'], dtype=int), mode='valid') if len(any_voiced) >= POLICY['minimum_voiced_frames'] else []
        voiced_indexes = np.flatnonzero(np.asarray(runs) == POLICY['minimum_voiced_frames'])
        audible_onset = float(times[a + voiced_indexes[0]]) if len(voiced_indexes) else None
        phonemes = [p for p in (char or {}).get('phonemes', []) if not p.get('skipped')]
        nucleus = next((p for p in phonemes if p.get('role') == 'nucleus'), None)
        action = []
        if char and nucleus:
            # 原曲拍轴与歌词拍位通用修复：新增真实元音内稳定首音保护，不能仅因短于0.4拍就零时值化。
            overlap = min(n['end_seconds'], nucleus['end_seconds']) - max(n['start_seconds'], nucleus['start_seconds'])
            # 原曲拍轴与歌词拍位通用修复：修改，旧目标音高支持保留；首音滑入时使用有声覆盖，不删除真实滑音时长。
            # if n.get('grace') and overlap >= period * POLICY['minimum_grace_head_quarters'] and support >= POLICY['grace_head_voiced_support']:
            # 原曲拍轴与歌词拍位通用修复：修改，元音内首音判据保留；声母起点附近的长有声滑入也须保留实测时值。
            # if n.get('grace') and overlap >= period * POLICY['minimum_grace_head_quarters'] and float(np.mean(any_voiced)) >= POLICY['grace_head_voiced_support']:
            speech_overlap = min(n['end_seconds'], char['end_seconds']) - max(n['start_seconds'], char['start_seconds'])
            metered_head = overlap >= period * POLICY['minimum_grace_head_quarters'] or (
                n['end_seconds'] - n['start_seconds'] >= period * POLICY['minimum_grace_head_quarters'] and speech_overlap >= .16 * period)
            if n.get('grace') and metered_head and float(np.mean(any_voiced)) >= POLICY['grace_head_voiced_support']:
                n.update(grace=False, role='turn', anchor=False)
                n.pop('anchor_id', None); n.pop('grace_steal_from', None)
                action.append('voiced_syllable_head_restored_metered')
            # 原曲拍轴与歌词拍位通用修复：新增前缀不抢后字，源音保留为无词装饰音；有声母／元音界证据才排除首字挂词。
            early = n['start_seconds'] < char['start_seconds'] - period * POLICY['prefix_early_quarters']
            before_nucleus = n['end_seconds'] <= nucleus['start_seconds'] + period * POLICY['prefix_nucleus_distance_quarters']
            if early and before_nucleus and n.get('role') == 'turn' and not n.get('anchor'):
                n['lyric_index'] = None
                n['line_index'] = None
                n['lyric_display_reason'] = 'source_supported_prefix_before_word_nucleus'
                action.append('pre_word_ornament_not_lyric_anchor')
        # 原曲拍轴与歌词拍位通用修复：新增原f0无声前缀的记谱起点修正；原音段文件和输出源秒记录保持。
        # 原曲拍轴与歌词拍位通用修复：修改，旧按目标音高稳定点裁剪保留；只有真实无基频前缀才延后记谱起点。
        # if onset is not None and onset - n['start_seconds'] > period * POLICY['trim_unvoiced_prefix_quarters']:
        #     n['start_seconds'] = onset
        if audible_onset is not None and audible_onset - n['start_seconds'] > period * POLICY['trim_unvoiced_prefix_quarters']:
            n['start_seconds'] = audible_onset
            action.append('notation_onset_after_stable_voiced_attack')
        n['notation_source_start_seconds'] = n['start_seconds']
        n['notation_source_end_seconds'] = n['end_seconds']
        # 原曲拍轴与歌词拍位通用修复：新增源片段账本，后续同音跨字分音仍完整覆盖原音段，原音段文件不变。
        n['rebuild_source_piece_id'] = original['id']
        n['rebuild_source_part_seconds'] = [original['start_seconds'], original['end_seconds']]
        decisions.append({'id': n['id'], 'source_lyric_index': index, 'derived_lyric_index': n.get('lyric_index'),
            'source_start_seconds': original['start_seconds'], 'notation_source_start_seconds': n['start_seconds'],
            'stable_voiced_support': support, 'source_grace': bool(original.get('grace')), 'derived_grace': bool(n.get('grace')), 'actions': action})
        pieces.append(n)
    # 原曲拍轴与歌词拍位通用修复：新增跨字的同一有声源音分段；只接受相邻音素边界和真实持续音支持，不手填字起点。
    # 原曲拍轴与歌词拍位通用修复：新增被后字整段抢走的前字有声尾音；相邻音素连续且两边有足够真实音长才分开。
    owned_first = {}
    for n in pieces:
        if n.get('lyric_index') is not None and not n.get('grace'):
            owned_first.setdefault(n['lyric_index'], n['id'])
    corrected = []; early_splits = []
    for n in pieces:
        index = n.get('lyric_index'); char = chars.get(index); previous = chars.get(index - 1) if index is not None else None
        boundary = char.get('start_seconds') if char else None
        eligible = bool(char and previous and owned_first.get(index) == n['id'] and not n.get('grace') and
            abs(previous['end_seconds'] - boundary) <= period * POLICY['maximum_word_boundary_gap_quarters'] and
            boundary - n['start_seconds'] >= period * POLICY['prefix_early_quarters'] and
            n['end_seconds'] - boundary >= period * POLICY['minimum_cross_word_tail_quarters'])
        if eligible:
            a, b = np.searchsorted(times, [n['start_seconds'], boundary])
            eligible = b > a and float(np.mean(np.isfinite(midi[a:b]))) >= .70
        if eligible:
            tail = deepcopy(n); tail.update(id=n['id'] + '.word_' + str(index), start_seconds=boundary,
                notation_source_start_seconds=boundary, rebuild_source_part_seconds=[boundary, n['rebuild_source_part_seconds'][1]])
            n.update(end_seconds=boundary, notation_source_end_seconds=boundary, lyric_index=index - 1,
                line_index=previous['line_index'], role='turn', anchor=False)
            n['rebuild_source_part_seconds'][1] = boundary
            early_splits.append({'source_id': n['id'], 'tail_id': tail['id'], 'source_lyric_index': index,
                'derived_prefix_lyric_index': index - 1, 'boundary_seconds': boundary,
                'evidence': 'adjacent_previous_phonemes_and_voiced_prefix'})
            corrected.extend([n, tail])
        else:
            corrected.append(n)
    split_pieces = []
    splits = []
    # 原曲拍轴与歌词拍位通用修复：修改，旧待分段序列保留；后向尾音归属确认后再检查前向跨字音。
    # for n in pieces:
    for n in corrected:
        index = n.get('lyric_index'); left, right = chars.get(index), chars.get(index + 1) if index is not None else None
        boundary = right.get('start_seconds') if right else None
        next_nucleus = next((p for p in (right or {}).get('phonemes', []) if p.get('role') == 'nucleus' and not p.get('skipped')), None)
        allowed = bool(left and right and next_nucleus and not n.get('grace') and
            abs(left['end_seconds'] - boundary) <= period * POLICY['maximum_word_boundary_gap_quarters'] and
            boundary - n['start_seconds'] >= period * POLICY['minimum_cross_word_left_quarters'] and
            n['end_seconds'] - boundary >= period * POLICY['minimum_cross_word_tail_quarters'] and
            next_nucleus['start_seconds'] - boundary <= .15 * period)
        if allowed:
            a, b = np.searchsorted(times, [boundary, n['end_seconds']])
            allowed = b > a and float(np.mean(np.isfinite(midi[a:b]))) >= .75
        if allowed:
            tail = deepcopy(n); tail.update(id=n['id'] + '.word_' + str(index + 1), lyric_index=index + 1,
                line_index=right['line_index'], start_seconds=boundary, notation_source_start_seconds=boundary,
                anchor=False, role='turn', rebuild_source_part_seconds=[boundary, n['rebuild_source_part_seconds'][1]])
            n['end_seconds'] = boundary; n['notation_source_end_seconds'] = boundary
            n['rebuild_source_part_seconds'][1] = boundary
            splits.append({'source_id': n['id'], 'tail_id': tail['id'], 'source_lyric_index': index,
                'derived_lyric_index': index + 1, 'boundary_seconds': boundary, 'evidence': 'adjacent_phonemes_and_continuous_voicing'})
            split_pieces.extend([n, tail])
        else:
            split_pieces.append(n)
    # 原曲拍轴与歌词拍位通用修复：修改，旧单向审计保留；两个方向的来源分区都须可重放。
    # return split_pieces, {'policy': deepcopy(POLICY), 'source_dependencies': dependencies, 'pieces': decisions, 'cross_word_splits': splits}
    return split_pieces, {'policy': deepcopy(POLICY), 'source_dependencies': dependencies, 'pieces': decisions, 'cross_word_splits': splits, 'early_word_splits': early_splits}


# 原曲拍轴与歌词拍位通用修复：新增真实起音约束的整曲动态规划，拍网规整只作软代价，不把整句抹平或挤压游标。
def quantize_source_notes(pieces, characters, mapping, timing, duration):
    from score_export import tempo_events
    from rhythm_notation import MeterTree, validate_grouping
    normal = [n for n in pieces if not n.get('grace')]
    normal.sort(key=lambda n: (n['start_seconds'], n['id']))
    origin = timing['score_start_quarter']; grid = POLICY['grid_ticks']
    observed = [(mapping.seconds_to_quarters(n['start_seconds']) - origin) * PPQ for n in normal]
    choices = []
    for value in observed:
        center = round(value / grid)
        candidates = [i * grid for i in range(center - 2, center + 3) if i >= 0
            and abs(i * grid - value) / PPQ <= POLICY['maximum_onset_error_quarters']]
        choices.append(candidates)
    # 原曲拍轴与歌词拍位通用修复：新增字头集合，细格惩罚只在源误差仍可接受时引导规整，不能压掉真实细分。
    seen_words = set(); heads = []
    for n in normal:
        index = n.get('lyric_index')
        heads.append(index is not None and index not in seen_words)
        seen_words.add(index)
    # 原曲拍轴与歌词拍位通用修复：修改代价签名，旧实现保留；加入字头的软节奏先验。
    # def onset_cost(tick, value):
    def onset_cost(tick, value, head=False):
        error = ((tick - value) / PPQ / POLICY['onset_sigma_quarters']) ** 2
        # 原曲拍轴与歌词拍位通用修复：修改，旧普通音规则保留；首字优先半拍，声学边界仍是硬约束。
        # error += 0. if tick % 240 == 0 else POLICY['sixteenth_penalty'] if tick % 120 == 0 else POLICY['fine_grid_penalty']
        error += 0. if tick % 240 == 0 else (POLICY['word_head_sixteenth_penalty'] if head else POLICY['sixteenth_penalty']) if tick % 120 == 0 else (POLICY['word_head_fine_penalty'] if head else POLICY['fine_grid_penalty'])
        return error
    # 原曲拍轴与歌词拍位通用修复：修改首状态，旧式保留；字头证据加入首个音。
    # states = {tick: (onset_cost(tick, observed[0]), (tick,)) for tick in choices[0]}
    states = {tick: (onset_cost(tick, observed[0], heads[0]), (tick,)) for tick in choices[0]}
    for serial in range(1, len(normal)):
        following = {}
        for tick in choices[serial]:
            options = []
            for previous, (cost, path) in states.items():
                if tick - previous < grid:
                    continue
                interval_error = ((tick - previous) - (observed[serial] - observed[serial - 1])) / PPQ
                # 原曲拍轴与歌词拍位通用修复：修改，旧式保留；联合状态采用源字头分类。
                # value = cost + onset_cost(tick, observed[serial]) + .12 * (interval_error / .20) ** 2
                value = cost + onset_cost(tick, observed[serial], heads[serial]) + .12 * (interval_error / .20) ** 2
                options.append((value, path + (tick,)))
            if options:
                following[tick] = min(options, key=lambda row: (row[0], row[1]))
        if not following:
            raise ValueError('真实起音联合网格冲突，拒绝挤压／删音：' + normal[serial]['id'])
        states = following
    _, selected = min(states.values(), key=lambda row: (row[0], row[1]))
    for serial, (note, tick) in enumerate(zip(normal, selected)):
        observed_end = (mapping.seconds_to_quarters(note['end_seconds']) - origin) * PPQ
        end = max(tick + grid, round(observed_end / grid) * grid)
        if serial + 1 < len(normal):
            gap = mapping.seconds_to_quarters(normal[serial + 1]['start_seconds']) - mapping.seconds_to_quarters(note['end_seconds'])
            if gap <= .14:
                end = selected[serial + 1]
            elif end > selected[serial + 1]:
                end = selected[serial + 1]
        note.update(start_tick=tick, end_tick=end, collapsed_to_grace=False,
            rhythm_decision={'version': 1, 'strategy': 'independent_source_bounded_joint_grid'})
    lookup = {n['id']: n for n in pieces}
    for n in pieces:
        if n.get('grace'):
            n['start_tick'] = n['end_tick'] = lookup[n['anchor_id']]['start_tick']
    allocate_playback(pieces, timing)
    tree = MeterTree.from_meter(timing['meter'], timing.get('beat_groups'))
    audio_end = (mapping.seconds_to_quarters(duration) - origin) * PPQ
    total = math.ceil(max(audio_end, max(n['end_tick'] for n in pieces)) / tree.bar_ticks) * tree.bar_ticks
    events = notation_events(pieces, total, timing)
    grouping = validate_grouping(events, timing['meter'], timing.get('beat_groups'))
    if not grouping['valid']:
        raise ValueError('源拍轴联合量化的音值分组失败。')
    errors = [abs(mapping.quarters_to_seconds(n['start_tick'] / PPQ + origin) - n['start_seconds']) for n in normal]
    stats = {'raw_pitched_notes': len({n['source_note_id'] for n in pieces}), 'lyric_split_pieces': len(pieces),
        'classified_grace_notes': sum(bool(n.get('grace')) for n in pieces), 'main_notes': sum(n['role'] == 'main' for n in pieces),
        'turn_notes': sum(n['role'] == 'turn' for n in pieces), 'grid_quarters': grid / PPQ,
        'measure_count': total // tree.bar_ticks, 'bar_ticks': tree.bar_ticks, 'total_ticks': total,
        'rhythm_grouping': grouping, 'quantization_error_seconds': {'median_abs': float(np.median(errors)),
            'p95_abs': float(np.percentile(errors, 95)), 'max_abs': max(errors)},
        'source_grid': {'policy': deepcopy(POLICY), 'all_normal_onsets_acoustically_bounded': True}}
    return events, pieces, stats


# 原曲拍轴与歌词拍位通用修复：新增旧调段按原秒迁移，初始调保持；换调边界按新小节落位，原判据同时保存。
def remap_key_segments(base, output, mapping):
    old = TempoMap(base['timing']['knots']); old_origin = base['timing']['score_start_quarter']
    new_origin = output['timing']['score_start_quarter']; bar = output['statistics']['bar_ticks']
    for index, segment in enumerate(output['notation'].get('key_segments', [])):
        source_second = segment.get('start_seconds', old.quarters_to_seconds(segment.get('start_tick', 0) / PPQ + old_origin))
        tick = round((mapping.seconds_to_quarters(source_second) - new_origin) * PPQ)
        segment['source_boundary_seconds'] = source_second
        segment['start_tick'] = 0 if index == 0 else max(0, round(tick / bar) * bar)
        segment['start_measure'] = segment['start_tick'] // bar + 1


# 原曲拍轴与歌词拍位通用修复：新增整曲联合量化；输出源秒恢复、记谱依据保留，统计同时覆盖实际MIDI与歌词锚点。
def rebuild_source_vocal(base, timing):
    output = deepcopy(base)
    pieces, audit = prepare_pieces(base, timing)
    mapping = TempoMap(timing['knots'])
    # 原曲拍轴与歌词拍位通用修复：修改，首轮旧乐句解法保留；改用有硬声学边界的联合网格，禁止规整挤压。
    # events, notes, statistics = quantize_phrase(pieces, base['lyrics']['characters'], mapping, timing,
    events, notes, statistics = quantize_source_notes(pieces, base['lyrics']['characters'], mapping, timing,
        base['audio_analysis']['duration_seconds'])
    originals = {n['id']: n for n in base['quantized_notes']}
    # 原曲拍轴与歌词拍位通用修复：修改，旧同ID集合限制保留；允许有证据的跨字分音，源音完整分区不丢失或重复。
    # if {n['id'] for n in notes} != set(originals):
    #     raise ValueError('源拍轴重解不得删除已有音段或替换音高。')
    by_source = defaultdict(list)
    for n in notes:
        by_source[n['rebuild_source_piece_id']].append(n)
    if set(by_source) != set(originals):
        raise ValueError('源拍轴重解丢失原音段身份。')
    for identity, parts in by_source.items():
        parts.sort(key=lambda n: n['rebuild_source_part_seconds'][0])
        source = originals[identity]
        bounds = [n['rebuild_source_part_seconds'] for n in parts]
        if abs(bounds[0][0] - source['start_seconds']) > 1e-8 or abs(bounds[-1][1] - source['end_seconds']) > 1e-8 or any(abs(a[1] - b[0]) > 1e-8 for a, b in zip(bounds, bounds[1:])):
            raise ValueError('跨字分音没有完整且无重复地覆盖源音段。')
    for note in notes:
        # 原曲拍轴与歌词拍位通用修复：修改，旧按单一ID恢复整段保留；每个派生音使用原音段内确定的无重复子区间。
        # source = originals[note['id']]
        # note['start_seconds'], note['end_seconds'] = source['start_seconds'], source['end_seconds']
        source = originals[note['rebuild_source_piece_id']]
        note['start_seconds'], note['end_seconds'] = note['rebuild_source_part_seconds']
        if note['pitch_midi'] != source['pitch_midi']:
            raise ValueError('源拍轴重解不得改变原音高。')
        for side in ('start', 'end'):
            value = mapping.quarters_to_seconds(note[side + '_tick'] / PPQ + timing['score_start_quarter'])
            note['quantized_' + side + '_seconds'] = value
            # 原曲拍轴与歌词拍位通用修复：修改，旧整段误差保留；按实际派生片段源边界计算。
            # note[side + '_error_seconds'] = value - source[side + '_seconds']
            note[side + '_error_seconds'] = value - note[side + '_seconds']
    from score_export import attach_lyrics, tempo_events
    output.update(timing=deepcopy(timing), quantized_notes=notes, events=events, statistics=statistics)
    output['lyric_mapping'] = attach_lyrics(events, output['lyrics']['characters'])
    output['tempo_events'] = tempo_events(mapping, timing, statistics['total_ticks'])
    output['statistics']['source_vocal_rebuild'] = deepcopy(audit)
    output['decoder']['source_vocal_rebuild'] = {'version': 1, 'old_source_seconds_preserved': True, 'metered_syllable_heads': True}
    remap_key_segments(base, output, mapping)
    playback = [abs(mapping.quarters_to_seconds(n['playback_start_tick'] / PPQ + timing['score_start_quarter']) - n['notation_source_start_seconds']) for n in notes]
    audit.update(source_note_count=len(notes), source_identity_pitch_interval_preserved=True,
        actual_playback_onset_error_percentiles_seconds=np.percentile(playback, [50, 95, 100]).tolist(),
        mapped_lyric_units=output['lyric_mapping']['mapped_characters'])
    if output['lyric_mapping']['unmapped_character_indices']:
        raise ValueError('源拍轴重解造成未挂词，拒绝导出。')
    return output, audit
