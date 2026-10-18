"""跨曲低音与强拍复用通用修复：用原伴奏低音变化确认小节首拍，再重编共同和声。"""
from copy import deepcopy
from pathlib import Path
import math
import numpy as np
from accompaniment_analysis import SongClock, extract_features
from score_export import PPQ, TempoMap, attach_lyrics, tempo_events, read_json, save_json

# 跨曲低音与强拍复用通用修复：新增来源绑定的独立派生，不覆盖人工拍位复核或旧时钟版本。
POLICY = {'version': 1, 'minimum_changes': 8, 'minimum_phase_margin': .18,
          'maximum_attack_distance_pulses': .18, 'local_attack_floor_percentile': 40,
          'long_bass_span_fraction': .80, 'tonic_return_weight': .7,
          'reviewed_phase_has_priority': True, 'original_seconds_and_pitches_preserved': True,
          'reference_score_and_lyrics_used_for_phase': False, 'harmonic_quality_version': 2}


# 跨曲低音与强拍复用通用修复：新增持续低音变化观察，重复拨同一低音不冒充新的和声入口。
def low_changes(vocal, binding, cache):
    from accompaniment_analysis import section_ranges
    clock = SongClock(vocal); pulse = PPQ * 4 / vocal['timing']['meter'][1]
    backing_name = 'accompaniment' if 'accompaniment' in binding['sources'] else 'other'
    backing = extract_features(binding['sources'][backing_name], cache, backing_name)
    bass = extract_features(binding['sources']['bass'], cache, 'bass') if 'bass' in binding['sources'] else None
    result = []
    for index, section in enumerate(section_ranges(vocal, binding['duration_seconds'])):
        if section['kind'] != 'vocal':
            continue
        a, b = section['start_seconds'], section['end_seconds']
        backing_rms = float(backing.rms[backing.window(a, b)].mean())
        bass_rms = float(bass.rms[bass.window(a, b)].mean()) if bass is not None else 0.
        independent = bass is not None and bass_rms >= max(1e-7, backing_rms * .015)
        f = bass if independent else backing; source = 'bass' if independent else backing_name
        observations = []
        for attack in f.attacks:
            if not a <= attack['seconds'] < b:
                continue
            t = clock.tick(attack['seconds']) / pulse
            if abs(t - round(t)) > POLICY['maximum_attack_distance_pulses']:
                continue
            notes = [p for p in attack['pitches'] if 24 <= p['pitch_midi'] <= 55 and p['relative_weight'] >= .30]
            if notes:
                p = max(notes, key=lambda r: r['weight'])
                observations.append({'pulse': float(t), 'seconds': attack['seconds'],
                    'pitch_midi': p['pitch_midi'], 'weight': float(p['weight']), 'source': source,
                    'section_index': index, 'tonic_pc': clock.key(round(t * pulse))['tonic_pc']})
        if not observations:
            continue
        floor = float(np.percentile([r['weight'] for r in observations], POLICY['local_attack_floor_percentile']))
        scale = max(1e-9, float(np.percentile([r['weight'] for r in observations], 85)))
        groups = []
        for row in observations:
            if row['weight'] < floor:
                continue
            if (groups and row['pitch_midi'] % 12 == groups[-1][0]['pitch_midi'] % 12
                    and row['pulse'] - groups[-1][-1]['pulse'] < 2 * vocal['timing']['meter'][0]):
                groups[-1].append(row)
            else:
                groups.append([row])
        for left, right in zip(groups, groups[1:]):
            row = deepcopy(left[0]); length = right[0]['pulse'] - row['pulse']
            if not .6 <= length <= 2 * vocal['timing']['meter'][0]:
                continue
            row.update(duration_pulses=float(length), relative_strength=min(1., row['weight'] / scale))
            result.append(row)
    return result


# 跨曲低音与强拍复用通用修复：新增整曲独立首拍候选；没有足够变化、优势或人工相位冲突时保持并报告。
def phase_from_changes(rows, meter, reviewed=False):
    count = meter[0]; scores = np.zeros(count); counts = np.zeros(count, dtype=int)
    for row in rows:
        phase = round(row['pulse']) % count; length = row['duration_pulses']
        weight = row['relative_strength'] * min(count, length)
        if length >= count * POLICY['long_bass_span_fraction']:
            weight *= 1.7
        if row['pitch_midi'] % 12 == row['tonic_pc']:
            weight *= 1 + POLICY['tonic_return_weight']
        scores[phase] += weight; counts[phase] += 1
    order = np.argsort(scores)[::-1]; best = int(order[0]); second = float(scores[order[1]]) if count > 1 else 0.
    margin = (float(scores[best]) - second) / max(1e-9, float(scores[best]))
    sufficient = len(rows) >= POLICY['minimum_changes'] and margin >= POLICY['minimum_phase_margin']
    shift = (-best) % count
    if shift > count / 2:
        shift -= count
    sections = sorted({r['section_index'] for r in rows})
    audit = {'changes': rows, 'scores': scores.tolist(), 'change_counts': counts.tolist(),
             'strongest_current_phase_pulses': best, 'margin': margin,
             'proposed_shift_pulses': shift, 'source_sections': sections,
             'status': 'reviewed_phase_preserved' if reviewed else 'source_phase_confirmed' if sufficient else 'ambiguous_phase_preserved',
             'shift_ticks': 0 if reviewed or not sufficient else round(shift * PPQ * 4 / meter[1])}
    return audit


# 跨曲低音与强拍复用通用修复：新增只重定小节相位，音符与物理拍轴一起移动，原唱和实际旋律秒时间保持。
def apply_phase(base, audit, correction=None):
    from phrase_rhythm import notation_events
    from rhythm_notation import validate_grouping
    vocal = deepcopy(base); delta = audit['shift_ticks']; shift = delta / PPQ
    if delta:
        # 跨曲低音与强拍复用通用修复：新增负相位时完整小节预留；录音开头的独奏不能因负tick被截掉。
        old_mapping = TempoMap(base['timing']['knots']); bar = vocal['statistics']['bar_ticks']
        first_tick = (old_mapping.seconds_to_quarters(0.) + shift - base['timing']['score_start_quarter']) * PPQ
        padding = max(0, math.ceil(-first_tick / bar) * bar)
        applied_delta = delta + padding
        if padding:
            vocal['timing']['score_start_quarter'] -= padding / PPQ
            vocal['timing']['source_meter_pre_roll_ticks'] = padding
        for knot in vocal['timing']['knots']:
            knot['quarter'] += shift
        for note in vocal['quantized_notes']:
            for field in ('start_tick', 'end_tick', 'playback_start_tick', 'playback_end_tick'):
                if field in note:
                    # 跨曲低音与强拍复用通用修复：修改，原仅相位偏移保留；包含完整预留，原声秒不变。
                    # note[field] += delta
                    note[field] += applied_delta
        for group in vocal['timing'].get('rhythm_tuplet_groups', []):
            for field in ('start_tick', 'end_tick'):
                if field in group:
                    # 跨曲低音与强拍复用通用修复：修改，原仅相位偏移保留；三连音窗口与声部一起迁移。
                    # group[field] += delta
                    group[field] += applied_delta
        bar = vocal['statistics']['bar_ticks']
        for section in vocal['notation'].get('key_segments', []):
            if section.get('start_tick', 0):
                # 跨曲低音与强拍复用通用修复：修改，原仅相位偏移保留；局部调号/实际转调不能漏掉预留小节。
                # section['performance_start_tick'] = section.get('performance_start_tick', section['start_tick']) + delta
                section['performance_start_tick'] = section.get('performance_start_tick', section['start_tick']) + applied_delta
                section['start_tick'] = math.ceil(section['performance_start_tick'] / bar) * bar
                section['start_measure'] = section['start_tick'] // bar + 1
        mapping = TempoMap(vocal['timing']['knots']); origin = vocal['timing']['score_start_quarter']
        audio_end = (mapping.seconds_to_quarters(vocal['audio_analysis']['duration_seconds']) - origin) * PPQ
        total = max(bar, math.ceil(max(audio_end, max(n['end_tick'] for n in vocal['quantized_notes'])) / bar) * bar)
        vocal['statistics'].update(total_ticks=total, measure_count=total // bar)
        events = notation_events(vocal['quantized_notes'], total, vocal['timing'])
        vocal['lyric_mapping'] = attach_lyrics(events, vocal['lyrics']['characters']); vocal['events'] = events
        grouping = validate_grouping(events, vocal['timing']['meter'], vocal['timing'].get('beat_groups'))
        if not grouping['valid']:
            raise ValueError('首拍重分组不符合音值组合：' + str(grouping['errors']))
        vocal['statistics']['rhythm_grouping'] = grouping
        vocal['timing']['score_start_seconds'] = mapping.quarters_to_seconds(origin)
        vocal['tempo_events'] = tempo_events(mapping, vocal['timing'], total)
    vocal['timing']['source_meter_phase'] = {k: deepcopy(v) for k, v in audit.items() if k != 'changes'}
    if correction is not None:
        vocal['source_meter_correction'] = deepcopy(correction)
    return vocal


# 跨曲低音与强拍复用通用修复：新增可严格重放的人声派生，不能用移动播放器或手工和弦表绕过来源校验。
def derive_source_meter_vocal(original, binding, correction):
    from performance_beat_clock import derive_performance_vocal, reconstruct_base
    if (correction.get('version') != 1 or correction.get('policy') != POLICY
            or correction.get('source_vocal_project_sha256') != binding['vocal_project_sha256']
            or correction.get('source_fingerprints') != {n: s['sha256'] for n, s in binding['sources'].items()}):
        raise ValueError('跨乐器低音首拍策略或来源已改变。')
    prior = correction.get('base_performance_correction')
    base = derive_performance_vocal(original, binding, prior) if prior else reconstruct_base(original, binding, correction)
    rows = low_changes(base, binding, Path(correction['feature_cache']))
    # 跨曲低音与强拍复用通用修复：修改，原非空相位字典判断保留；自动猜测不是人工复核，只有源绑定review_id享有优先级。
    # audit = phase_from_changes(rows, base['timing']['meter'], bool(base['timing'].get('beat_phase')))
    # 跨曲低音与强拍复用通用修复：修改，旧字典默认保留；外部工程允许显式null，不能因此跳过源校验。
    # audit = phase_from_changes(rows, base['timing']['meter'], bool(base['timing'].get('beat_phase', {}).get('review_id')))
    audit = phase_from_changes(rows, base['timing']['meter'], bool((base['timing'].get('beat_phase') or {}).get('review_id')))
    if audit != correction['phase_evidence']:
        raise ValueError('多轨低音首拍不能从原曲严格重建。')
    return apply_phase(base, audit, correction)


# 跨曲低音与强拍复用通用修复：新增观察攻击重新定位；旧合成tick提前于真实首拍时不能被误冻成弱起器乐。
def regrid_observed_entries(shared, vocal, arrangements):
    from accompaniment_arrange import harmony_at
    from phrase_harmony_plan import phrase_ranges
    clock = SongClock(vocal); changes = []
    # 跨曲低音与强拍复用通用修复：新增只纠正跨乐句入口的种子，内部普通种子由最终模板重编，避免提前改变持续覆盖。
    boundaries = {p[k] for p in phrase_ranges(shared, vocal) for k in ('start_tick', 'end_tick')}
    for name, arrangement in arrangements.items():
        moved = {}
        for note in arrangement['notes']:
            if (note.get('source_melody_id') or note.get('section') != 'vocal'
                    or note.get('onset_origin') != 'observed' or note.get('arpeggio_step') not in (None, 0)
                    or note.get('source_attack_seconds') is None):
                continue
            target = clock.quantize(note['source_attack_seconds'], PPQ//4)
            delta = target - note['start_tick']
            # 跨曲低音与强拍复用通用修复：修改，原所有观察音重定位范围过宽，保留旧条件；只修跨入口且仍有持续的源首攻击。
            # if not delta or abs(delta) > PPQ//4:
            if not delta or abs(delta) > PPQ//4 or target not in boundaries or target >= note['end_tick']:
                continue
            # 跨曲低音与强拍复用通用修复：修改，原平移持续结尾会撞后续拨弦；仅纠正源起点，释放点保持。
            # old = note['start_tick']; duration = note['end_tick'] - old
            # note['start_tick'] = target; note['end_tick'] = min(clock.total_ticks, target + duration)
            old = note['start_tick']; note['start_tick'] = target
            note['chord_id'] = harmony_at(shared, target)['id']; note['texture_measure'] = target//clock.bar_ticks+1
            note['source_meter_regrid'] = {'old_tick': old, 'new_tick': target,
                'source_attack_seconds': note['source_attack_seconds'], 'source_seconds_changed': False}
            changes.append({'instrument': name, 'note_id': note['id'], **note['source_meter_regrid']})
            moved.setdefault(old, target)
        for event in arrangement.get('attack_events', []):
            if event['start_tick'] in moved:
                event['start_tick'] = moved[event['start_tick']]
                event['chord_id'] = harmony_at(shared, event['start_tick'])['id']
        arrangement['source_meter_observed_regridding'] = [r for r in changes if r['instrument'] == name]
    return changes


# 跨曲低音与强拍复用通用修复：新增新生成入口；旧工程普通重导不升级，原器乐以同源秒迁移。
def correct_source_meter_project(shared, vocal, arrangements, cache_dir):
    from accompaniment_analysis import analyze
    # 渴首次吉他编配：修改，重建阶段继承绑定的乐器范围；原代码注释保留。
    # from accompaniment_arrange import arrange_guitar, arrange_piano
    # 渴首次吉他编配：新增按所选乐器执行，保留各乐器原验证。
    from accompaniment_arrange import arrange_requested
    from accompaniment_texture_policy import add_block_support
    from beat_phase_alignment import seed_existing_music
    from local_beat_clock import reusable_guitar_configuration
    if vocal.get('source_meter_correction'):
        return shared, vocal, arrangements
    binding = shared['input_binding']; cache = Path(cache_dir).resolve()
    rows = low_changes(vocal, binding, cache)
    # 跨曲低音与强拍复用通用修复：修改，原非空相位字典判断保留；旧人工源复核保留，未确认猜测继续独立核查。
    # audit = phase_from_changes(rows, vocal['timing']['meter'], bool(vocal['timing'].get('beat_phase')))
    # 跨曲低音与强拍复用通用修复：修改，旧字典默认保留；null相位与未确认相位一样继续独立调查。
    # audit = phase_from_changes(rows, vocal['timing']['meter'], bool(vocal['timing'].get('beat_phase', {}).get('review_id')))
    audit = phase_from_changes(rows, vocal['timing']['meter'], bool((vocal['timing'].get('beat_phase') or {}).get('review_id')))
    correction = {'version': 1, 'policy': deepcopy(POLICY),
        'source_vocal_project_sha256': binding['vocal_project_sha256'],
        'source_fingerprints': {n: s['sha256'] for n, s in binding['sources'].items()},
        'base_performance_correction': deepcopy(vocal.get('performance_clock_correction')),
        'base_structural_correction': deepcopy(vocal.get('structural_clock_correction')),
        'base_local_correction': deepcopy(vocal.get('local_clock_correction')),
        'base_phase_correction': deepcopy(vocal.get('beat_phase_correction')),
        'base_grid_correction': deepcopy(vocal.get('grid_correction')),
        'feature_cache': str(cache), 'phase_evidence': audit}
    updated = apply_phase(vocal, audit, correction)
    fresh_shared = add_block_support(analyze(binding, updated, cache, harmonic_quality=2), updated, cache)
    for field in ('arrangement_policy', 'musical_structure', 'melodic_motif_matches', 'performance_beat_clock'):
        if field in shared:
            fresh_shared[field] = deepcopy(shared[field])
    fresh_shared['source_meter_phase'] = deepcopy(audit)
    # 渴首次吉他编配：修改，避免未请求乐器阻塞所选乐器；原代码注释保留。
    # fresh = {'guitar': arrange_guitar(fresh_shared, updated, arrangements['guitar']['configuration']['capo_fret']),
    #          'piano': arrange_piano(fresh_shared, updated)}
    # 渴首次吉他编配：新增按所选乐器执行，保留各乐器原验证。
    fresh = arrange_requested(fresh_shared, updated, arrangements['guitar']['configuration']['capo_fret'])
    fresh = seed_existing_music(shared, vocal, arrangements, fresh_shared, updated, fresh, source_time_sections=True)
    # 跨曲低音与强拍复用通用修复：新增先修正普通源攻击的陈旧量化，再冻结边界；真正器乐/填句保持。
    regrid_observed_entries(fresh_shared, updated, fresh)
    fresh['guitar']['configuration'].update(reusable_guitar_configuration(arrangements['guitar']['configuration']))
    fresh['guitar']['configuration']['beat_synchronous_patterns'] = True
    save_json(cache.parent / 'source_meter_phase.json', audit)
    return fresh_shared, updated, fresh
