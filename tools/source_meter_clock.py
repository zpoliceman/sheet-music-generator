"""原曲拍轴与歌词拍位通用修复：独立原轨脉冲、连续拍计数和低音小节相位。"""
# 原曲拍轴与歌词拍位通用修复：新增独立版本；不读取歌曲名、歌词文字、谱面音符或旧记谱拍序来投票。
from copy import deepcopy
# 工作目录改名兼容：文件仍逐个验证摘要，证据保留原绝对路径名称以便重放历史记录。
from pathlib import Path
import math
import numpy as np
from scipy.ndimage import gaussian_filter1d, median_filter
from scipy.signal import find_peaks
from scipy.optimize import minimize_scalar
from score_export import read_json, save_json, sha256

POLICY = {'version': 1, 'sample_rate': 22050, 'hop': 128, 'fft': 2048,
          'tempo_search_ratios': [.88, 1.12], 'tempo_search_step_bpm': .004,
          'minimum_attacks': 24, 'minimum_pulse_span': 16., 'minimum_coherence': .12,
          'fit_window_quarters': .11, 'robust_residual_quarters': .036,
          'minimum_bass_changes': 8, 'minimum_bar_phase_margin': .18,
          'bass_max_midi': 52, 'bass_certainty': .40, 'bass_duration_quarters': .90,
          'bass_attack_distance_quarters': .18, 'bass_gap_quarters': .36,
          'local_window_quarters': 24., 'local_step_quarters': 8.,
          'local_change_minimum_quarters': .035, 'maximum_local_change_quarters': .16,
          'source_family_votes_averaged': False, 'notation_used_for_phase': False,
          'unobserved_tail_certified': False}

# 源拍轴频段候选通用修复：新增完整候选验收策略，原攻击缓存政策及历史v1拍轴保持。
RECOVERY_POLICY = {**deepcopy(POLICY), 'version': 2,
                   'candidate_gates': ['periodic_source_attacks', 'robust_pulse_fit', 'local_phase_consistency', 'independent_bass_downbeat'],
                   'candidate_priority': ['validated_original_selection', 'drums_full', 'other_validated_source_tracks'],
                   'recovery_uses_song_names_lyrics_or_reference_answers': False,
                   'old_clock_v1_replay_preserved': True}


# 原曲拍轴与歌词拍位通用修复：新增绑定源SHA的直接频谱攻击缓存；只有原轨时间，没有旧谱标签。
def extract_source_onsets(binding, cache):
    import librosa
    import soundfile as sf
    from threadpoolctl import threadpool_limits
    cache = Path(cache); cache.mkdir(parents=True, exist_ok=True)
    sources = binding['sources']; rows = {}
    backing = next((name for name in ('accompaniment', 'other', 'mix') if name in sources), None)
    if backing is None:
        raise ValueError('原曲独立拍轴缺少伴奏／混音来源。')
    with threadpool_limits(limits=4):
        for name in dict.fromkeys([n for n in ('drums', 'bass', backing) if n in sources]):
            source = sources[name]
            if sha256(source['path']) != source['sha256']:
                raise ValueError('独立源节拍输入已改变：' + name)
            token = 'source_onsets_v1_' + source['sha256'][:20]
            metadata, archive = cache / (token + '.json'), cache / (token + '.npz')
            if metadata.exists() and archive.exists():
                saved = read_json(metadata)
                if saved['policy'] != POLICY or saved['source_sha256'] != source['sha256']:
                    raise ValueError('独立源攻击缓存版本／指纹不一致。')
                peaks = saved['peaks']
            else:
                wave, rate = sf.read(source['path'], always_2d=True, dtype='float32')
                mono = librosa.resample(wave.mean(axis=1), orig_sr=rate, target_sr=POLICY['sample_rate'])
                magnitude = np.abs(librosa.stft(mono, n_fft=POLICY['fft'], hop_length=POLICY['hop']))
                frequency = librosa.fft_frequencies(sr=POLICY['sample_rate'], n_fft=POLICY['fft'])
                times = librosa.frames_to_time(np.arange(magnitude.shape[1]), sr=POLICY['sample_rate'], hop_length=POLICY['hop'])
                bands = [(35, 180, 'low'), (500, 5000, 'full')] if name == 'drums' else [(30, 260, 'low'), (260, 8000, 'full')]
                arrays, peaks = {'times': times}, {}
                for low, high, label in bands:
                    selection = (frequency >= low) & (frequency < high)
                    spectral = np.log1p(magnitude[selection] * 10)
                    flux = np.pad(np.maximum(0, spectral[:, 2:] - spectral[:, :-2]).mean(axis=0), (2, 0))
                    flux = gaussian_filter1d(flux, .7)
                    floor = max(float(np.percentile(flux, 75)) * .7, float(flux.max()) * .008)
                    indexes, _ = find_peaks(flux, height=floor, prominence=floor * .7,
                        distance=round(.09 * POLICY['sample_rate'] / POLICY['hop']))
                    arrays[label] = flux
                    peaks[label] = [{'seconds': float(times[i]) + float(source.get('offset_seconds', 0)),
                                     'strength': float(flux[i])} for i in indexes]
                np.savez_compressed(archive, **arrays)
                save_json(metadata, {'policy': deepcopy(POLICY), 'source_sha256': source['sha256'], 'peaks': peaks})
            for band, attacks in peaks.items():
                rows[name + '_' + band] = {'source': name, 'band': band, 'attacks': attacks,
                    'source_sha256': source['sha256'], 'cache_path': str(metadata.absolute())}
    return rows, backing


# 原曲拍轴与歌词拍位通用修复：新增独立周期搜索，检测缺拍／额外攻击不能改写连续拍索引。
def periodic_candidate(attacks, tempo_hint):
    if len(attacks) < POLICY['minimum_attacks']:
        return {'status': 'insufficient_attacks', 'count': len(attacks)}
    t = np.array([a['seconds'] for a in attacks]); w = np.array([a['strength'] for a in attacks])
    w = np.minimum(w, np.percentile(w, 90))
    if not np.any(w > 0) or t[-1] - t[0] < POLICY['minimum_pulse_span'] * 60 / tempo_hint:
        return {'status': 'insufficient_span', 'count': len(attacks)}
    def score(bpm):
        return abs(np.sum(w * np.exp(2j * np.pi * t * bpm / 60))) / np.sum(w)
    lower, upper = [tempo_hint * ratio for ratio in POLICY['tempo_search_ratios']]
    bpms = np.arange(lower, upper + POLICY['tempo_search_step_bpm'], POLICY['tempo_search_step_bpm'])
    values = np.array([score(bpm) for bpm in bpms]); best = float(bpms[np.argmax(values)])
    step = POLICY['tempo_search_step_bpm'] * 2
    fitted = minimize_scalar(lambda bpm: -score(bpm), bounds=(best - step, best + step), method='bounded')
    bpm = float(fitted.x); period = 60 / bpm
    phase = float(np.angle(np.sum(w * np.exp(2j * np.pi * t / period))) % (2 * np.pi) / (2 * np.pi) * period)
    return {'status': 'periodic' if score(bpm) >= POLICY['minimum_coherence'] else 'ambiguous_period',
            'bpm': bpm, 'period': period, 'phase': phase, 'coherence': float(score(bpm)),
            'count': len(attacks), 'span_seconds': float(t[-1] - t[0])}


# 原曲拍轴与歌词拍位通用修复：新增真实攻击整数拍计数与Huber拟合，不把检测数组下标当音乐拍序。
def robust_pulse_fit(attacks, candidate):
    t = np.array([a['seconds'] for a in attacks]); strength = np.array([a['strength'] for a in attacks])
    period, phase = candidate['period'], candidate['phase']
    indexes = np.rint((t - phase) / period).astype(int)
    keep = np.abs(t - phase - indexes * period) < POLICY['fit_window_quarters'] * period
    if keep.sum() < POLICY['minimum_attacks']:
        raise ValueError('独立拍序的真实攻击支持不足。')
    weights = np.minimum(strength[keep], np.percentile(strength, 90))
    design = np.column_stack([np.ones(keep.sum()), indexes[keep]])
    fit = np.array([phase, period])
    for _ in range(8):
        residual = t[keep] - design @ fit
        w = weights * np.minimum(1., POLICY['robust_residual_quarters'] * period / np.maximum(1e-6, np.abs(residual)))
        fit = np.linalg.lstsq(design * np.sqrt(w[:, None]), t[keep] * np.sqrt(w), rcond=None)[0]
    phase, period = map(float, fit)
    witnesses = [{'seconds': float(second), 'quarter': int(q), 'residual_seconds': float(second - phase - q * period), 'strength': float(w)}
                 for second, q, w in zip(t[keep], indexes[keep], weights)]
    return phase, period, witnesses


# 原曲拍轴与歌词拍位通用修复：新增独立低音变化相位，前段无低音分轨时按实际能量切换完整伴奏证据。
def bass_phase_evidence(binding, cache, backing, phase, period, meter):
    from accompaniment_analysis import extract_features, LOW_MIDI
    from performance_beat_clock import copy_features
    copy_features(binding, cache)
    accompaniment = extract_features(binding['sources'][backing], cache, backing)
    bass = extract_features(binding['sources']['bass'], cache, 'bass') if 'bass' in binding['sources'] else None
    count = POLICY['bass_max_midi'] - LOW_MIDI + 1
    low = accompaniment.activations[:count].copy()
    sources = np.full(low.shape[1], backing, dtype=object)
    if bass is not None:
        eligible = bass.rms[:low.shape[1]] >= np.maximum(accompaniment.rms[:low.shape[1]] * .015,
            max(1e-7, float(np.percentile(bass.rms, 90)) * .035))
        low[:, eligible] = bass.activations[:count, :low.shape[1]][:, eligible]
        sources[eligible] = 'bass'
    pc = np.zeros((12, low.shape[1]))
    for offset in range(count):
        pc[(offset + LOW_MIDI) % 12] += low[offset]
    winners = median_filter(np.argmax(pc, axis=0), size=7)
    maximum = np.max(pc, axis=0); certainty = maximum / np.maximum(1e-9, pc.sum(axis=0))
    # 原曲拍轴与歌词拍位通用修复：新增每个物理来源独立音量门限，不能用响亮贝斯压掉开头安静钢琴证据。
    valid = certainty > POLICY['bass_certainty']
    for name in set(sources):
        subset = sources == name
        floor = max(1e-9, float(np.percentile(maximum[subset], 85)) * .07)
        valid[subset] &= maximum[subset] > floor
    groups = []
    times = accompaniment.times
    for i in np.flatnonzero(valid):
        if groups and int(winners[i]) == groups[-1]['pc'] and times[i] - times[groups[-1]['last']] < period * POLICY['bass_gap_quarters']:
            groups[-1]['last'] = int(i)
        else:
            groups.append({'first': int(i), 'last': int(i), 'pc': int(winners[i]), 'source': str(sources[i])})
    changes = []
    for group in groups:
        first, last = group['first'], group['last']; duration = float(times[last] - times[first])
        if duration < period * POLICY['bass_duration_quarters']:
            continue
        second = float(times[first]); source = bass if group['source'] == 'bass' else accompaniment
        nearby = [a for a in source.attacks if abs(a['seconds'] - second) < period * .20]
        if nearby:
            second = max(nearby, key=lambda a: a['strength'])['seconds']
        quarter = (second - phase) / period
        if abs(quarter - round(quarter)) > POLICY['bass_attack_distance_quarters']:
            continue
        changes.append({'seconds': float(second), 'quarter': float(quarter), 'nearest_quarter': round(quarter),
            'pitch_class': group['pc'], 'duration_seconds': duration, 'source': group['source']})
    beats = meter[0]; unit = 4 / meter[1]
    phases = [sum(min(beats, c['duration_seconds'] / period / unit)
                  for c in changes if round(c['quarter'] / unit) % beats == i) for i in range(beats)]
    ranked = sorted(range(beats), key=lambda i: (-phases[i], i))
    best = ranked[0]; second = phases[ranked[1]] if len(ranked) > 1 else 0.
    margin = (phases[best] - second) / max(1e-9, phases[best])
    confirmed = len(changes) >= POLICY['minimum_bass_changes'] and margin >= POLICY['minimum_bar_phase_margin']
    return {'changes': changes, 'phase_scores': phases, 'phase_beats': best,
            'margin': margin, 'status': 'independent_downbeat_supported' if confirmed else 'ambiguous_downbeat'}


# 原曲拍轴与歌词拍位通用修复：新增小幅真实局部脉冲偏移；有声学覆盖才插结点，衰减尾部只外推并明确标记。
def pulse_knots(phase, period, witnesses):
    start, end = min(w['quarter'] for w in witnesses), max(w['quarter'] for w in witnesses)
    knots = [{'quarter': 0., 'seconds': phase}, {'quarter': 1., 'seconds': phase + period}]
    additions = []
    half = POLICY['local_window_quarters'] / 2
    for quarter in range(math.ceil(start / 8) * 8, end + 1, 8):
        rows = [w for w in witnesses if abs(w['quarter'] - quarter) <= half]
        if len(rows) < 6 or max(w['quarter'] for w in rows) - min(w['quarter'] for w in rows) < half:
            continue
        shift = float(np.median([w['residual_seconds'] for w in rows]))
        if abs(shift) > POLICY['maximum_local_change_quarters'] * period:
            raise ValueError('独立拍序出现无法确认的局部相位变化。')
        if abs(shift) > POLICY['local_change_minimum_quarters'] * period:
            additions.append({'quarter': float(quarter), 'seconds': phase + quarter * period + shift})
    if additions:
        knots += additions
        terminal = max(end + 1, int(additions[-1]['quarter']) + 1)
        knots.append({'quarter': float(terminal), 'seconds': phase + terminal * period})
    return sorted(knots, key=lambda row: row['quarter'])


# 原曲拍轴与歌词拍位通用修复：新增总推断；已有人工作曲拍位优先、未知来源不声称校准，缓存可确定性重放。
# 源拍轴频段候选通用修复：修改旧入口名称，原签名注释保留；原函数体不变用于历史严格重放。
# def infer_source_clock(vocal, binding, cache):
def _infer_source_clock_v1(vocal, binding, cache):
    timing = vocal['timing']
    review = timing.get('beat_phase') or {}
    if review.get('review_id'):
        return deepcopy(timing), {'status': 'reviewed_source_clock_retained', 'review_id': review['review_id'], 'policy': deepcopy(POLICY)}
    hint = float(vocal['audio_analysis']['tempo']['bpm'])
    onset_sets, backing = extract_source_onsets(binding, cache)
    candidates = []
    for name, track in onset_sets.items():
        candidate = periodic_candidate(track['attacks'], hint)
        candidate.update(track=name, source=track['source'])
        candidates.append(candidate)
    eligible = [c for c in candidates if c['status'] == 'periodic']
    if not eligible:
        raise ValueError('原曲独立节拍证据不足，不能将旧记谱轴认作已校准。')
    # 原曲拍轴与歌词拍位通用修复：新增独立鼓低频优先；相关分轨不累加成多票，避免同一混音被重复投票。
    preferred = [c for c in eligible if c['track'] == 'drums_low']
    selected = max(preferred or eligible, key=lambda c: c['coherence'])
    phase, period, witnesses = robust_pulse_fit(onset_sets[selected['track']]['attacks'], selected)
    evidence = bass_phase_evidence(binding, cache, backing, phase, period, timing['meter'])
    if evidence['status'] != 'independent_downbeat_supported':
        raise ValueError('原曲小节首拍仍有歧义，拒绝用人声长音或歌词重音代替首拍。')
    offset = evidence['phase_beats'] * 4 / timing['meter'][1]
    knots = pulse_knots(phase, period, witnesses)
    shifted = [{'quarter': k['quarter'] - offset, 'seconds': k['seconds']} for k in knots]
    origin = -math.ceil(max(0., offset) / (timing['meter'][0] * 4 / timing['meter'][1])) * timing['meter'][0] * 4 / timing['meter'][1]
    updated = deepcopy(timing)
    updated.update(knots=shifted, score_start_quarter=float(origin), beat_origin_seconds=phase + offset * period,
        score_start_seconds=phase + (origin + offset) * period, steady_tempo_bpm=60 / period,
        tempo_source='independent_source_attack_sequence', beat_origin_source='independent_bass_harmonic_changes',
        bar_phase_method='source_audio_only_duration_weighted_bass_changes', requires_confirmation=False)
    audit = {'status': 'independent_source_clock_supported', 'policy': deepcopy(POLICY),
        'source_audio_sha256': {name: source['sha256'] for name, source in binding['sources'].items()},
        'tempo_hint_source': 'raw_mix_audio_analysis_not_notation', 'candidates': candidates,
        'selected_track': selected['track'], 'quarter_period_seconds': period, 'bpm': 60 / period,
        'quarter_zero_seconds': phase, 'bar_phase': evidence, 'witnesses': witnesses,
        'knots': shifted, 'source_notation_used': False, 'lyric_text_used': False,
        'first_supported_seconds': min(w['seconds'] for w in witnesses), 'last_supported_seconds': max(w['seconds'] for w in witnesses),
        'tail_policy': 'last_supported_period_extrapolated_not_music_certified'}
    return updated, audit


# 源拍轴频段候选通用修复：新增候选按完整门槛验证的入口，低频失败才能尝试其它可测频段。
def infer_source_clock(vocal, binding, cache, quality=False):
    if not quality: return _infer_source_clock_v1(vocal, binding, cache)
    try:
        timing, audit = _infer_source_clock_v1(vocal, binding, cache)
        audit['policy'] = deepcopy(RECOVERY_POLICY)
        audit['candidate_selection'] = {'method': 'original_selection_passed_all_gates', 'rejected_candidates': []}
        return timing, audit
    except ValueError as failure:
        original_error = str(failure)
    onset_sets, backing = extract_source_onsets(binding, cache)
    hint = float(vocal['audio_analysis']['tempo']['bpm']); candidates = []
    for name, track in onset_sets.items():
        candidate = periodic_candidate(track['attacks'], hint)
        candidate.update(track=name, source=track['source']); candidates.append(candidate)
    eligible = [c for c in candidates if c['status'] == 'periodic']
    if not eligible: raise ValueError(original_error)
    preferred = [c for c in eligible if c['track'] == 'drums_low']
    original = max(preferred or eligible, key=lambda c: c['coherence'])
    alternatives = sorted((c for c in eligible if c['track'] != original['track']),
                          key=lambda c: (c['track'] != 'drums_full', -c['coherence'], c['track']))
    rejected = [{'track': original['track'], 'reason': original_error}]
    for selected in alternatives:
        # 源拍轴频段候选通用修复：新增与原门槛相同的整条候选验收，不平均相关分轨投票，不用歌词替代首拍。
        try:
            phase, period, witnesses = robust_pulse_fit(onset_sets[selected['track']]['attacks'], selected)
            knots = pulse_knots(phase, period, witnesses)
            evidence = bass_phase_evidence(binding, cache, backing, phase, period, vocal['timing']['meter'])
            if evidence['status'] != 'independent_downbeat_supported':
                raise ValueError('原曲小节首拍仍有歧义，拒绝用人声长音或歌词重音代替首拍。')
        except ValueError as failure:
            rejected.append({'track': selected['track'], 'reason': str(failure)}); continue
        offset = evidence['phase_beats'] * 4 / vocal['timing']['meter'][1]
        shifted = [{'quarter': k['quarter'] - offset, 'seconds': k['seconds']} for k in knots]
        bar = vocal['timing']['meter'][0] * 4 / vocal['timing']['meter'][1]
        origin = -math.ceil(max(0., offset) / bar) * bar
        updated = deepcopy(vocal['timing'])
        updated.update(knots=shifted, score_start_quarter=float(origin), beat_origin_seconds=phase + offset * period,
            score_start_seconds=phase + (origin + offset) * period, steady_tempo_bpm=60 / period,
            tempo_source='independent_source_attack_sequence', beat_origin_source='independent_bass_harmonic_changes',
            bar_phase_method='source_audio_only_duration_weighted_bass_changes', requires_confirmation=False)
        audit = {'status': 'independent_source_clock_supported', 'policy': deepcopy(RECOVERY_POLICY),
            'source_audio_sha256': {name: source['sha256'] for name, source in binding['sources'].items()},
            'tempo_hint_source': 'raw_mix_audio_analysis_not_notation', 'candidates': candidates,
            'selected_track': selected['track'], 'quarter_period_seconds': period, 'bpm': 60 / period,
            'quarter_zero_seconds': phase, 'bar_phase': evidence, 'witnesses': witnesses, 'knots': shifted,
            'source_notation_used': False, 'lyric_text_used': False,
            'first_supported_seconds': min(w['seconds'] for w in witnesses),
            'last_supported_seconds': max(w['seconds'] for w in witnesses),
            'tail_policy': 'last_supported_period_extrapolated_not_music_certified',
            'candidate_selection': {'method': 'first_alternative_passing_all_original_gates',
                                    'rejected_candidates': rejected, 'selected_track': selected['track']}}
        return updated, audit
    raise ValueError('原曲所有独立节拍候选均未通过完整检查：' + '；'.join(r['track'] + '：' + r['reason'] for r in rejected))
