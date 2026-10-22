"""器乐低弦分解填充：固定旋律，按源活动与真实持续弦规划独立低声部。"""
# 器乐低弦分解填充：新增通用派生层，歌名、歌词和参考谱答案不参与选择。
from __future__ import annotations
from collections import Counter
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
import math
import numpy as np
import soundfile as sf
from scipy.ndimage import maximum_filter1d, uniform_filter1d
from scipy.signal import resample_poly
from accompaniment_analysis import SongClock
from accompaniment_arrange import TUNING, grip_info, validate_playability
from guitar_capo import capo_at, fret_at
from guitar_grip_library import common_grips, fret_map
from guitar_instrumental_register import fingerprint, register_shared_view, unit_candidates
from score_export import PPQ, read_json, save_json, sha256

POLICY = {'version': 1, 'scope': ['intro', 'interlude', 'outro'], 'strings': [4, 5, 6],
    'preferred_maximum_fret': 4, 'maximum_fret': 12, 'minimum_ticks': 120,
    'frame_seconds': .04, 'quiet_ratio': .004, 'active_ratio': .012,
    'minimum_quiet_seconds': .16, 'fixed_existing_pitches_and_attacks': True,
    'fixed_melody_releases': True, 'fill_velocity': 63, 'reference_answers_used': False}

# 器乐填充密度随主体伴奏：新增版本2，版本1参数／历史重放保持，正文密度独立绑定在活动计划。
POLICY_V2={**POLICY,'version':2,'density_mode':'follow_stable_vocal_accompaniment',
    'existing_attacks_count_toward_density':True,'quarter_fill_is_arpeggio_not_root_each_beat':True,
    'preferred_string_weight':1.15}


# 器乐低弦分解填充：新增实际拍号对应的低弦拨弦单位，复拍默认八分而非强制十六分。
def pulse_and_step(meter):
    numerator, denominator = meter
    unit = PPQ * 4 // denominator
    compound = denominator == 8 and numerator >= 6 and numerator % 3 == 0
    return (unit * 3, unit) if compound else (unit, max(120, unit // 2))


# 器乐低弦分解填充：新增原秒轴音量、音色与起音证据；分离轨缺音不等同全伴奏休止。
def audio_curve(binding):
    y, rate = sf.read(binding['path'], dtype='float32', always_2d=True)
    y = y.mean(axis=1)
    divisor = math.gcd(rate, 11025)
    y = resample_poly(y, 11025 // divisor, rate // divisor).astype('float32')
    hop, size = 441, 512
    y = np.pad(y, (0, max(0, size - len(y))))
    windows = np.lib.stride_tricks.sliding_window_view(y, size)[::hop]
    rms = np.sqrt(np.mean(windows ** 2, axis=1))
    magnitude = abs(np.fft.rfft(windows * np.hanning(size), axis=1))
    frequencies = np.fft.rfftfreq(size, 1 / 11025)
    band = magnitude[:, (frequencies >= 43) & (frequencies <= 3500)]
    flux = np.r_[0., np.maximum(0., np.diff(band, axis=0)).sum(axis=1)]
    flatness = np.exp(np.mean(np.log(band + 1e-9), axis=1)) / np.maximum(1e-9, band.mean(axis=1))
    times = np.arange(len(rms)) * hop / 11025 + size / (2 * 11025) + binding.get('offset_seconds', 0.)
    return {'times': times, 'rms': rms, 'flux': flux, 'flatness': flatness,
            'end_seconds': binding.get('offset_seconds', 0.) + len(y) / 11025}


# 器乐低弦分解填充：新增连续静音与终止尾响分类，不能把持音下没有攻击判成休止。
def classify_curve(curve, sections, clock, support=()):
    times, rms, flux = (curve[k] for k in ('times', 'rms', 'flux'))
    anchor = max(float(np.percentile(rms, 95)), 1e-7)
    quiet_floor = max(1e-6, anchor * POLICY['quiet_ratio'])
    states = np.full(len(times), 'uncertain', dtype=object)
    states[(rms >= max(quiet_floor * 2, anchor * POLICY['active_ratio'])) & (curve['flatness'] < .40)] = 'active'
    for track in support:
        strength = np.interp(times, track['times'], track['rms'], left=0., right=0.)
        if float(np.percentile(track['rms'], 95)) > 1e-7:
            states[(rms >= anchor * POLICY['active_ratio']) &
                (strength >= float(np.percentile(track['rms'], 95)) * .03)] = 'active'
    quiet = rms < quiet_floor
    boundaries = np.r_[0, np.flatnonzero(quiet[1:] != quiet[:-1]) + 1, len(quiet)]
    for a, b in zip(boundaries, boundaries[1:]):
        if quiet[a] and (b - a) * POLICY['frame_seconds'] >= POLICY['minimum_quiet_seconds']:
            states[a:b] = 'source_rest'
    audible_flux = flux[rms > anchor * .04]
    threshold = max(float(np.percentile(audible_flux, 75)) * .8 if len(audible_flux) else 1.,
                    float(np.percentile(flux, 95)) * .18, 1e-7)
    onsets = np.flatnonzero((flux >= maximum_filter1d(flux, 3)) & (flux > threshold) & (rms > anchor * .04))
    smooth = uniform_filter1d(rms, 9)
    for section in sections:
        if section['kind'] != 'outro':
            continue
        a, b = clock.seconds(section['start_tick']), clock.seconds(section['end_tick'])
        local = [i for i in onsets if a <= times[i] < b]
        if not local:
            continue
        last = local[-1]
        quarter = clock.seconds(section['start_tick'] + PPQ) - a
        tail_start = times[last] + max(.35, quarter * .75)
        later = np.flatnonzero((times >= times[last] + max(1., quarter * 2)) & (times < b))
        # 器乐低弦分解填充：新增只有无后续真实起音、明确衰减的结尾才禁止机械续奏。
        if len(later) and smooth[later[0]] < smooth[last] * .55:
            mask = (times >= tail_start) & (times < b) & (states != 'source_rest')
            states[mask] = 'terminal_ringout'
    return states, {'reference_rms': anchor, 'quiet_floor': quiet_floor, 'onset_threshold': threshold,
        'real_onset_seconds': [round(float(times[i]), 6) for i in onsets]}


# 器乐低弦分解填充：新增绑定原轨、声学分类和实际拍轴的只增来源计划。
# 器乐填充密度随主体伴奏：修改，旧声明保留；新计划可携带版本化的正文密度证据。
# def build_activity_plan(shared, vocal, work):
def build_activity_plan(shared, vocal, work, density_plan=None):
    shared = register_shared_view(shared, vocal)
    sections = [deepcopy(s) for s in shared['sections'] if s['kind'] in POLICY['scope']]
    sources = shared.get('input_binding', {}).get('sources', {})
    if 'accompaniment' not in sources:
        raise ValueError('低弦填充需要完整伴奏原轨，不能把旋律空拍当作源活动证据。')
    selected = [k for k in ('accompaniment', 'bass', 'other') if k in sources]
    curves = {k: audio_curve(sources[k]) for k in selected}
    clock = SongClock(vocal)
    main = curves['accompaniment']
    states, evidence = classify_curve(main, sections, clock, [v for k, v in curves.items() if k != 'accompaniment'])
    # 尾段原声局部补证：新增已重放的原声尾响优先于弱局部波动，禁止低弦填充重新敲出假尾音；已有旋律持续不动。
    terminal=None
    if vocal.get('first_source_meter_correction'):
        from first_generation_tail import verified_tail_observation
        terminal=verified_tail_observation(vocal,shared['input_binding'])
        if terminal:
            mask=(main['times']>=terminal['start_seconds'])&(main['times']<=terminal['end_seconds'])&(states!='source_rest')
            states[mask]='terminal_ringout'
    segments = []
    cuts = np.r_[0, np.flatnonzero(states[1:] != states[:-1]) + 1, len(states)]
    for a, b in zip(cuts, cuts[1:]):
        segments.append({'start_seconds': round(max(sources['accompaniment'].get('offset_seconds', 0.),
            float(main['times'][a]) - POLICY['frame_seconds'] / 2), 6),
            'end_seconds': round(min(main['end_seconds'], float(main['times'][b - 1]) + POLICY['frame_seconds'] / 2), 6),
            'state': str(states[a]), 'maximum_rms': round(float(main['rms'][a:b].max()), 8)})
    plan = {'version': 1, 'policy': deepcopy(POLICY), 'sections': sections, 'activity': segments,
        'sources': [{'name': k, 'binding': deepcopy(sources[k])} for k in selected],
        'shared_sha256': fingerprint(shared), 'vocal_sha256': fingerprint(vocal), 'acoustic_evidence': evidence}
    if density_plan is not None:
        plan.update(version=2,policy=deepcopy(POLICY_V2),density_plan=deepcopy(density_plan))
    # 尾段原声局部补证：新增真实局部证据进入活动计划摘要，历史无此层的计划完全保持。
    if terminal:plan['verified_terminal_decay_constraint']=deepcopy(terminal)
    path = Path(work) / ('instrumental_flow_activity_' + fingerprint(plan)[:20] + '.json')
    if path.exists() and fingerprint(read_json(path)) != fingerprint(plan):
        raise ValueError('已绑定活动证据不可覆盖。')
    if not path.exists():
        save_json(path, plan)
    return plan, path


# 器乐低弦分解填充：新增区间活动查询，源边界外、休止及不确定区间不生成假攻击。
def activity_at(plan, seconds):
    return next((a for a in plan['activity'] if a['start_seconds'] <= seconds < a['end_seconds']), None)


# 器乐低弦分解填充：新增固定旧手指的完整持音覆盖，填充不能借走仍发声的旋律手指。
def fixed_finger_fits(active, candidate):
    values = active + [candidate]
    geometry = tuple(sorted((n['string'], n['fret']) for n in values))
    if len({s for s, _ in geometry}) != len(geometry) or grip_info(dict(geometry)) is None:
        return False
    for units in unit_candidates(geometry):
        used = []
        valid = True
        for unit in units:
            labels = {n.get('finger', 0) for n in values if (n['string'], n['fret']) in unit and n['fret'] > 0}
            labels.discard(0)
            if len(labels) > 1:
                valid = False
                break
            used.extend(labels)
        if valid and len(used) == len(set(used)):
            return True
    return False


# 器乐低弦分解填充：新增候选与全时段约束；优先沿用当前图式、低品和同一分解弦序。
# 器乐填充密度随主体伴奏：修改，旧声明保留；新慢分解可加强常用低弦轮换，旧候选排序仍用原权重。
# def choose_fill(notes, arrangement, shared, chord, tick, end, preferred_string, bass_step):
def choose_fill(notes, arrangement, shared, chord, tick, end, preferred_string, bass_step,preferred_weight=.65):
    capo = capo_at(arrangement, tick)
    pcs = set(chord.get('pitch_classes', [])) | {chord['bass_pc']}
    bases = common_grips(chord['root_pc'], chord['quality'], chord['bass_pc'], capo)
    ordinary = [fret_map(e) for e in bases if e['max_fret'] <= 4]
    positions = arrangement.get('hand_positions', [])
    # 原曲拍轴与歌词拍位通用修复：新增填充不能堵住下一音的提前换把，版本1继续原候选路径。
    motion_version=arrangement['configuration'].get('instrumental_flow_motion_version',1)
    if motion_version not in (1,2):raise ValueError('未知器乐填充运动版本。')
    best = None
    for string in POLICY['strings']:
        for fret in range(POLICY['maximum_fret'] + 1):
            pitch = TUNING[string] + capo + fret
            if pitch % 12 not in pcs:
                continue
            conflicts = [n for n in notes if n['string'] == string and n['start_tick'] < end and n['end_tick'] > tick]
            # 器乐低弦分解填充：新增只允许重拨已释放到足够时值的同音伴奏；旋律不可切断。
            if any(n['role'] == 'instrumental_melody' or n['start_tick'] >= tick or
                n['pitch_midi'] != pitch or tick - n['start_tick'] < 120 or not any(
                    s['kind'] in POLICY['scope'] and s['start_tick'] <= n['start_tick'] < s['end_tick'] for s in shared['sections'])
                for n in conflicts):
                continue
            checkpoints = sorted({tick, *[n[k] for n in notes for k in ('start_tick', 'end_tick') if tick < n[k] < end],
                *[p['tick'] for p in positions if tick < p['tick'] < end]})
            for finger in (0,) if fret == 0 else range(1, 5):
                candidate = {'string': string, 'fret': fret, 'pitch_midi': pitch, 'finger': finger}
                fits = True
                for point in checkpoints:
                    active = [n for n in notes if n not in conflicts and n['start_tick'] <= point < n['end_tick']]
                    position = next((p['position'] for p in reversed(positions) if p['tick'] <= point), 1)
                    # 器乐低弦分解填充：新增真实低音声部保护，内声部不能在既有低音下另造不必要的转位。
                    basses = [n['pitch_midi'] for n in active if n['role'] == 'bass']
                    if (fret and not position <= fret <= position + 5 or
                        basses and pitch < min(basses) and pitch % 12 != chord['bass_pc'] or
                        any(n['role'] == 'instrumental_melody' and pitch > n['pitch_midi'] for n in active) or
                        not fixed_finger_fits([{**n, 'fret': fret_at(n, arrangement, point)} for n in active], candidate)):
                        fits = False
                        break
                if not fits:
                    continue
                # 原曲拍轴与歌词拍位通用修复：新增释放端点仍须允许抵达下一手位；保持上一持续音至端点时，不能只核验区间内部静态跨度。
                if motion_version==2 and any(
                    (actual_fret:=pitch-TUNING[string]-capo_at(arrangement,p['tick']))>0 and
                    not p['position']<=actual_fret<=p['position']+5
                    for p in [*positions,{'tick':end,'position':next((p['position'] for p in reversed(positions) if p['tick']<=end),1)}]
                    if tick<p['tick']<=end):
                    continue
                base_match = any(base.get(string) == fret for base in ordinary)
                # 器乐填充密度随主体伴奏：修改，旧成本式保留；新型保留弦序偏好，避免稀疏分解总重复同一内声音。
                # cost = (max(0, fret - 4) * 3 + fret * .15 + (0 if base_match else 1.2) +
                #     (0 if string == preferred_string else .65) + len(conflicts) * .65 +
                #     (0 if not bass_step or pitch % 12 == chord['bass_pc'] else 3))
                cost = (max(0, fret - 4) * 3 + fret * .15 + (0 if base_match else 1.2) +
                    (0 if string == preferred_string else preferred_weight) + len(conflicts) * .65 +
                    (0 if not bass_step or pitch % 12 == chord['bass_pc'] else 3))
                rank = (cost, string, fret, finger)
                if best is None or rank < best[0]:
                    best = (rank, candidate, conflicts)
    return None if best is None else (best[1], best[2])


# 器乐低弦分解填充：新增确定性织体编配，固定全部旧音高和起音，仅审计同弦伴奏重起的尾部。
def arrange_flow(shared, vocal, original, plan):
    shared = register_shared_view(shared, vocal)
    result = deepcopy(original)
    notes = result['notes']
    clock = SongClock(vocal)
    pulse, step = pulse_and_step(vocal['timing']['meter'])
    # 器乐填充密度随主体伴奏：新增每段固定密度，旧计划不携带此证据时逐音保持版本1算法。
    density_plan=plan.get('density_plan');fallback_step=step
    decisions, additions, releases = [], [], []
    original_ids = {n['id'] for n in notes}
    for section in plan['sections']:
        if density_plan is not None:
            from guitar_instrumental_density import section_step
            step=section_step(density_plan,section,fallback_step)
        start, finish = section['start_tick'], section['end_tick']
        for tick in range(math.ceil(start / step) * step, finish, step):
            chord = next((h for h in shared['harmony'] if h['start_tick'] <= tick < h['end_tick']), None)
            activity = activity_at(plan, clock.seconds(tick))
            reason = None
            if not activity or activity['state'] != 'active':
                reason = activity['state'] if activity else 'outside_source'
            elif not chord or chord['name'] == 'N.C.':
                reason = 'uncertain_harmony'
            existing = [n for n in notes if tick <= n['start_tick'] < min(finish, tick + step)]
            bass_step = tick % pulse == 0
            # 器乐填充密度随主体伴奏：新增四分型只在小节起点优先根音，其余拍按低弦分解，避免每拍同低音。
            if density_plan is not None and step==pulse:bass_step=tick%clock.bar_ticks==0
            # 器乐填充密度随主体伴奏：修改，旧覆盖规则保留；新版只可在同刻合拨补低音，不能在占用格另加起音。
            # if not reason and existing and (not bass_step or any(n['role'] == 'bass' for n in existing)):
            covered=existing and (not bass_step or any(n['role']=='bass' for n in existing))
            if density_plan is not None and existing and not all(n['start_tick']==tick for n in existing):covered=True
            if not reason and covered:
                reason = 'existing_attack_covers_slot'
            if reason:
                decisions.append({'tick': tick, 'decision': reason})
                continue
            end = min(finish, tick + step, chord['end_tick'],
                math.floor(clock.tick(activity['end_seconds']) / 120) * 120)
            for mark in result['configuration'].get('capo_segments', []):
                if tick < mark['start_tick'] < end:
                    end = mark['start_tick']
            end = tick + (end - tick) // 120 * 120
            # 器乐填充密度随主体伴奏：新增新填充按可读时值收束，和弦／源边界裁剪不制造附点八分。
            if density_plan is not None:
                lengths=(120,240,480,720) if pulse==720 else (120,240,480)
                end=tick+max((d for d in lengths if d<=end-tick),default=0)
            if end - tick < 120:
                decisions.append({'tick': tick, 'decision': 'activity_or_harmony_boundary_too_close'})
                continue
            cycle = (tick // step) % (pulse // step * 2)
            # 器乐填充密度随主体伴奏：修改，旧弦序保留；四分型按小节拍序分解到4／5／6弦。
            # preferred = 6 if bass_step else (4 if cycle % 4 in (1, 3) else 5)
            sequence=(tick//step)%4 if density_plan is not None and step==pulse else cycle%4
            preferred = 6 if bass_step else (4 if sequence in (1, 3) else 5)
            # 器乐填充密度随主体伴奏：修改，旧调用保留；新版只对四分／整拍织体加强轮换，八分型保持既有风格。
            # chosen = choose_fill(notes, result, shared, chord, tick, end, preferred, bass_step)
            weight=POLICY_V2['preferred_string_weight'] if density_plan is not None and step==pulse else .65
            chosen = choose_fill(notes, result, shared, chord, tick, end, preferred, bass_step,weight)
            if chosen is None:
                decisions.append({'tick': tick, 'decision': 'no_playable_lower_string_with_held_melody'})
                continue
            value, conflicts = chosen
            for old in conflicts:
                releases.append({'note_id': old['id'], 'original_end_tick': old['end_tick'], 'end_tick': tick,
                    'reason': 'same_pitch_same_string_rearticulation', 'pitch_midi': old['pitch_midi'], 'string': old['string']})
                old['end_tick'] = tick
            note = {**value, 'id': f'guitar_flow_{len(additions) + 1:05}', 'start_tick': tick, 'end_tick': end,
                'velocity': POLICY['fill_velocity'], 'role': 'harmony', 'hand_position': next((p['position'] for p in
                    reversed(result.get('hand_positions', [])) if p['tick'] <= tick), 1), 'chord_id': chord['id'],
                'source': 'arranged_lower_arpeggio', 'section': section['kind'], 'instrumental_flow_fill': True,
                # 器乐填充密度随主体伴奏：修改，旧固定名称保留；实际格长作为可核查填充密度。
                # 'flow_pattern': 'lower_common_eighth', 'flow_bass_step': bass_step, 'source_melody_id': None,
                'flow_pattern': f'lower_common_{step}_ticks' if density_plan is not None else 'lower_common_eighth', 'flow_bass_step': bass_step, 'source_melody_id': None,
                'onset_origin': 'arranged_lower_string_fill', 'right_hand_duration_source': 'instrumental_flow_grid',
                'right_hand_duration_ticks': end - tick}
            notes.append(note)
            additions.append(deepcopy(note))
            decisions.append({'tick': tick, 'decision': 'added_lower_arpeggio', 'note_id': note['id'],
                'source_state': activity['state'], 'chord_id': chord['id'], 'string': note['string'], 'fret': note['fret']})
    result['notes'] = sorted(notes, key=lambda n: (n['start_tick'], n['id']))
    events = [deepcopy(e) for e in original['attack_events'] if not any(
        s['start_tick'] <= e['start_tick'] < s['end_tick'] for s in plan['sections'])]
    for section in plan['sections']:
        if density_plan is not None:
            from guitar_instrumental_density import section_step
            step=section_step(density_plan,section,fallback_step)
        rows = [n for n in result['notes'] if section['start_tick'] <= n['start_tick'] < section['end_tick']]
        ticks = sorted({n['start_tick'] for n in rows})
        for index, tick in enumerate(ticks):
            group = [n for n in rows if n['start_tick'] == tick]
            horizon = min(ticks[index + 1] - tick if index + 1 < len(ticks) else step,
                          pulse - tick % pulse, min(n['end_tick'] - tick for n in group))
            # 器乐填充密度随主体伴奏：修改，旧候选保留；复拍的整拍720tick也可准确表达，不改历史版本。
            # duration = max((d for d in (120, 240, 480, 960) if d <= horizon), default=120)
            durations=(120,240,480,720,960) if density_plan is not None else (120,240,480,960)
            duration = max((d for d in durations if d <= horizon), default=120)
            events.append({'start_tick': tick, 'kind': 'arpeggio', 'chord_id': group[0]['chord_id'],
                'source': 'instrumental_flow', 'onset_origin': 'backbone_with_lower_arpeggio',
                'note_ids': sorted(n['id'] for n in group), 'stroke': None,
                'right_hand_duration_ticks': duration, 'right_hand_duration_source': 'instrumental_flow_grid'})
            if result['configuration'].get('instrumental_flow_regular_events_version')==1 and any(n.get('right_hand_pattern_id') for n in group):
                prior=next((e for e in original['attack_events'] if e['start_tick']==tick and
                            e.get('right_hand_duration_source')=='regular_pattern_slot'),None)
                if prior:
                    for field in ('right_hand_pattern_id','right_hand_slot','right_hand_duration_ticks',
                                  'right_hand_duration_source','pattern_cycle_origin_tick'):
                        if field in prior:events[-1][field]=deepcopy(prior[field])
    result['attack_events'] = sorted(events, key=lambda e: e['start_tick'])
    for field in ('tab_display', 'rhythm_display', 'time_alignment_display'):
        result.pop(field, None)
    report = {'valid': True, 'added_notes': len(additions), 'fixed_original_notes': len(original_ids),
        'filled_strings': dict(Counter(n['string'] for n in additions)), 'release_adjustments': releases,
        'decision_counts': dict(Counter(d['decision'] for d in decisions)), 'decisions': decisions}
    if density_plan is not None:report['density_plan']=deepcopy(density_plan)
    # 原曲拍轴与歌词拍位通用修复：新增实际填充后的完整持续握位核验，不能把静态可按误报为可连续演奏。
    if result['configuration'].get('instrumental_flow_motion_version',1)==2:
        from guitar_grip_policy import grip_position_path
        motion=grip_position_path({**result,'fingering_diagrams':[]},vocal)
        if not motion['valid']:raise ValueError('器乐填充阻碍连续换把：'+str(motion))
        report['motion_version']=2
        report['continuous_motion']=motion
    return result, report


# 器乐低弦分解填充：新增内容寻址的输入工程与原轨活动绑定，不覆盖历史模型／谱。
# 器乐填充密度随主体伴奏：修改，旧声明保留；新歌可采用正文密度，旧谱显式升级可重放并恢复填充前真实持音。
# def apply_flow(shared, vocal, guitar, upstream_path, work):
def apply_flow(shared, vocal, guitar, upstream_path, work, follow_density=False):
    upgrade_path=None
    if follow_density and guitar.get('instrumental_expression'):
        from guitar_instrumental_expression import validate_expression,expression_parent
        check=validate_expression(shared,vocal,guitar,replay=True)
        if not check['valid']:raise ValueError('填充密度升级的既有表现来源不符：'+str(check['errors'][:6]))
        upgrade_path=upstream_path;guitar=deepcopy(expression_parent(guitar)['arrangements']['guitar'])
    if guitar.get('instrumental_flow'):
        check = validate_flow(shared, vocal, guitar, replay=True)
        if not check['valid']:
            raise ValueError('连续织体来源不符：' + str(check['errors'][:6]))
        # 器乐填充密度随主体伴奏：修改，旧直接保持语句保留；明确升级版本1时恢复实际填充前工程，不能只删填音。
        # return deepcopy(guitar), deepcopy(guitar['instrumental_flow']['report'])
        if not follow_density or guitar['instrumental_flow']['version']==2:
            return deepcopy(guitar), deepcopy(guitar['instrumental_flow']['report'])
        upgrade_path=upgrade_path or upstream_path
        upstream_path=guitar['instrumental_flow']['upstream_project']
        guitar=deepcopy(flow_parent(guitar)['arrangements']['guitar'])
    work = Path(work)
    # 器乐填充密度随主体伴奏：修改，旧活动计划调用保留；密度从真实填充前正文攻击推断并绑定。
    # plan, path = build_activity_plan(shared, vocal, work)
    density_plan=None
    if follow_density:
        from guitar_instrumental_density import build_density_plan
        parent=read_json(upstream_path)
        if (fingerprint(parent['arrangements']['guitar'])!=fingerprint(guitar) or fingerprint(parent['accepted_vocal_project'])!=fingerprint(vocal)
            or fingerprint(register_shared_view(parent['shared_analysis'],vocal))!=fingerprint(register_shared_view(shared,vocal))):
            raise ValueError('密度升级必须绑定实际填充前吉他、人声和共同拍轴。')
        density_plan=build_density_plan(shared,vocal,guitar)
    plan, path = build_activity_plan(shared, vocal, work,density_plan)
    result, report = arrange_flow(shared, vocal, guitar, plan)
    # 器乐填充密度随主体伴奏：修改，旧版本字段保留；根据实际采用的密度计划保存可重放策略。
    # result['instrumental_flow'] = {'version': 1, 'policy': deepcopy(POLICY),
    result['instrumental_flow'] = {'version': 2 if follow_density else 1, 'policy': deepcopy(POLICY_V2 if follow_density else POLICY),
        'upstream_project': str(Path(upstream_path).resolve()), 'upstream_sha256': sha256(upstream_path),
        'activity_plan_path': str(path.resolve()), 'activity_plan_sha256': sha256(path),
        'source_notes_sha256': fingerprint(guitar['notes']), 'result_notes_sha256': fingerprint(result['notes']),
        'report': report}
    if upgrade_path:
        result['instrumental_flow'].update(density_upgrade_from_project=str(Path(upgrade_path).resolve()),
            density_upgrade_from_sha256=sha256(upgrade_path))
    check = validate_playability(result, SongClock(vocal))
    if not check['valid']:
        raise ValueError('低弦填充破坏实际持续音／手位：' + str(check['errors'][:8]))
    return result, report


# 器乐低弦分解填充：新增不可伪造的上游缓存；每次验证都检查真实文件SHA。
@lru_cache(maxsize=8)
def cached_parent(path, digest, mtime, size):
    if sha256(path) != digest:
        raise ValueError('低弦织体的源工程已改变。')
    return read_json(path)


def flow_parent(guitar):
    info = guitar['instrumental_flow']
    path = Path(info['upstream_project'])
    # 器乐低弦分解填充：新增每次校验真实上游字节，mtime／大小相同也不能借缓存掩盖改写。
    if sha256(path) != info['upstream_sha256']:
        raise ValueError('低弦织体的源工程已改变。')
    stat = path.stat()
    return cached_parent(str(path), info['upstream_sha256'], stat.st_mtime_ns, stat.st_size)


# 器乐低弦分解填充：新增分层核验，原保护在真实输入检查，新增ID仅允许确定重放的填充。
def validate_flow(shared, vocal, guitar, replay=False):
    # 原声覆盖与选音归属通用修复：新增认可段落来源严格合并验证，不重填已认可音乐。
    if guitar.get('approved_section_preservation'):
        from approved_music_sections import validate_chain
        return validate_chain(shared,vocal,guitar,replay,validate_flow)
    # 器乐背景休止与旋律突出：新增先在实际上游核查旧织体，再独立严格重放休止／力度表现，不放松旧保护。
    if guitar.get('instrumental_expression'):
        from guitar_instrumental_expression import validate_expression_chain
        return validate_expression_chain(shared,vocal,guitar,replay,validate_flow)
    info = guitar.get('instrumental_flow')
    if not info:
        return None
    errors = []
    try:
        parent = flow_parent(guitar)
        base = parent['arrangements']['guitar']
        # 原曲拍轴与歌词拍位通用修复：新增候选版本绑定真实源工程，篡改派生配置不能绕过下一拍准备核验。
        if guitar['configuration'].get('instrumental_flow_motion_version',1)!=base['configuration'].get('instrumental_flow_motion_version',1):
            errors.append('instrumental_flow_motion_version_changed')
        if guitar['configuration'].get('instrumental_flow_regular_events_version',0)!=base['configuration'].get('instrumental_flow_regular_events_version',0):
            errors.append('instrumental_flow_regular_events_version_changed')
        # 器乐填充密度随主体伴奏：修改，旧固定版本1判别保留；历史与主体密度版本分别严格复演。
        # if info['version'] != 1 or info['policy'] != POLICY:
        expected_policy=POLICY if info['version']==1 else POLICY_V2 if info['version']==2 else None
        if expected_policy is None or info['policy'] != expected_policy:
            errors.append('unknown_instrumental_flow_policy')
        if fingerprint(base['notes']) != info['source_notes_sha256'] or fingerprint(guitar['notes']) != info['result_notes_sha256']:
            errors.append('instrumental_flow_notes_fingerprint_changed')
        if parent['accepted_vocal_project'] != vocal or fingerprint(register_shared_view(parent['shared_analysis'], vocal)) != fingerprint(register_shared_view(shared, vocal)):
            errors.append('instrumental_flow_harmony_vocal_or_clock_changed')
        path = Path(info['activity_plan_path'])
        if sha256(path) != info['activity_plan_sha256']:
            errors.append('instrumental_flow_activity_plan_changed')
        plan = read_json(path)
        # 器乐填充密度随主体伴奏：修改，旧版本1计划保护保留；新计划同时绑定实际正文密度。
        # if plan['policy'] != POLICY or plan['vocal_sha256'] != fingerprint(vocal) or plan['shared_sha256'] != fingerprint(register_shared_view(shared, vocal)):
        if plan['policy'] != expected_policy or plan['vocal_sha256'] != fingerprint(vocal) or plan['shared_sha256'] != fingerprint(register_shared_view(shared, vocal)):
            errors.append('instrumental_flow_activity_binding_changed')
        if info['version']==2:
            from guitar_instrumental_density import build_density_plan
            density=build_density_plan(shared,vocal,base)
            if fingerprint(density)!=fingerprint(plan.get('density_plan')):errors.append('instrumental_density_evidence_replay_changed')
            if info.get('density_upgrade_from_project'):
                previous_path=info['density_upgrade_from_project']
                if sha256(previous_path)!=info['density_upgrade_from_sha256']:errors.append('instrumental_density_previous_project_changed')
        expected_sources = [k for k in ('accompaniment', 'bass', 'other') if k in shared['input_binding']['sources']]
        if [s['name'] for s in plan['sources']] != expected_sources:
            errors.append('instrumental_flow_sources_missing_or_duplicated')
        for source in plan['sources']:
            bound = shared['input_binding']['sources'][source['name']]
            if source['binding'] != bound or sha256(bound['path']) != bound['sha256']:
                errors.append('instrumental_flow_audio_changed:' + source['name'])
        rebuilt, report = arrange_flow(shared, vocal, base, plan)
        if rebuilt['notes'] != guitar['notes'] or fingerprint(report) != fingerprint(info['report']) or rebuilt['attack_events'] != guitar['attack_events']:
            errors.append('instrumental_flow_deterministic_music_changed')
        for field in ('instrumental_register', 'instrumental_source_backbone', 'regular_rhythm', 'phrase_harmony_performance'):
            # 渴首次吉他编配：修改，旧Python字典比较把指型整数弦号经JSON变为字符串误判为账本变化，原式保留。
            # if base.get(field) != guitar.get(field):
            # 渴首次吉他编配：新增按同一规范JSON指纹严格比较；真实字段或指型改写仍拒绝，不放松音乐重放。
            if fingerprint(base.get(field)) != fingerprint(guitar.get(field)):
                errors.append('instrumental_flow_original_protection_ledger_changed:' + field)
        if guitar['configuration'].get('capo_segments') != base['configuration'].get('capo_segments'):
            errors.append('instrumental_flow_capo_changed')
        # 器乐低弦分解填充：新增固定手位和调弦配置保护，不能仅修改演奏声明绕过原候选约束。
        if guitar.get('hand_positions') != base.get('hand_positions') or any(
            guitar['configuration'].get(k) != base['configuration'].get(k) for k in ('capo_fret', 'maximum_fret')):
            errors.append('instrumental_flow_hand_position_or_tuning_changed')
        if replay and not errors:
            # 器乐填充密度随主体伴奏：修改，旧活动重放保留；版本2连同实际正文密度重新读取原音轨。
            # raw, _ = build_activity_plan(shared, vocal, path.parent)
            raw, _ = build_activity_plan(shared, vocal, path.parent,plan.get('density_plan'))
            if fingerprint(raw) != fingerprint(plan):
                errors.append('instrumental_flow_source_activity_replay_changed')
    except (OSError, KeyError, ValueError, TypeError) as exc:
        errors.append('instrumental_flow_invalid_binding:' + str(exc))
    return {'valid': not errors, 'errors': errors, 'replayed': replay, 'added_notes': info.get('report', {}).get('added_notes', 0)}
