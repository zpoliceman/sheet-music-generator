"""最小拍轴与词音伴奏修复：来源绑定的局部听辨、短过门和整曲拍轴。"""
# 最小拍轴与词音伴奏修复：新增独立时间入口；不读取旧音符／和弦推断拍轴，也不修改正常谱库。
from copy import deepcopy
from pathlib import Path
import math
import numpy as np
from score_export import TempoMap, sha256
from source_timing_decoder import decode_four_beat_candidate
from source_timing_evidence import source_changes, candidate_phase_scores
from source_timing_acceptance import fingerprint

TASK = '最小拍轴与词音伴奏修复'
POLICY = {'version': 1, 'source_bound_local_review': True, 'minimum_downbeat_probability_short_bar': .85,
          'short_bar_endpoint_attack_tolerance_seconds': .15, 'source_window_seconds': 16,
          'minimum_source_phase_contrast': .03, 'silent_tail_is_not_new_beats': True,
          'pitch_chord_and_old_score_used_to_decode': False}


def verify_source_review(review, binding):
    # 最小拍轴与词音伴奏修复：新增核对原音与实际试听文件；全曲认可字段不能替代局部锚点。
    if (review.get('version') != 1 or review.get('mix_sha256') != binding['sources']['mix']['sha256']
            or review.get('reviewer') != 'user' or review.get('notation_meter') != [4, 4]
            or len(review.get('downbeat_seconds', [])) < 2 or not review.get('basis')):
        raise ValueError('局部听辨来源、拍号或首拍证据不完整')
    if sha256(review['sample_path']) != review['sample_sha256']:
        raise ValueError('首拍试听文件已改变')
    for interval in review.get('unmetered_ranges', []):
        if (not interval.get('basis') or interval['end_seconds'] <= interval['start_seconds']
                or sha256(interval['source_sample']) != interval['source_sample_sha256']):
            raise ValueError('自由引子证据不完整')
    intervals = np.diff(review['downbeat_seconds']) / 4
    if np.any(intervals <= 0) or np.max(intervals) / np.min(intervals) > 1.10:
        raise ValueError('听辨锚点不足以确定同一四拍层级')
    return float(np.median(intervals))


def endpoint_attack(feature, second):
    # 最小拍轴与词音伴奏修复：新增独立分轨实际起音证据，不用已选择的拍点自证。
    rows = [a for a in feature.attacks if abs(a['seconds'] - second) <= .15]
    local = feature.flux[feature.window(second - 4, second + 4)]
    threshold = max(1e-8, float(np.percentile(local, 65)))
    rows = [a for a in rows if a['strength'] >= threshold]
    return min((abs(a['seconds'] - second) for a in rows), default=None)


def make_timeline(beats, mapping):
    # 最小拍轴与词音伴奏修复：新增真实小节边界表；弱起、两拍过门与四拍段不再用统一取模编号。
    starts = [i for i, row in enumerate(beats) if row['beat'] == 1]
    bounds = sorted(set([0, *starts, len(beats) - 1]))
    rows = []
    for a, b in zip(bounds, bounds[1:]):
        count = b - a
        if not count:
            continue
        pickup = a == 0 and beats[0]['beat'] != 1
        if count not in (2, 4) and not pickup:
            raise ValueError('存在尚未支持的小节长度，不强行按四拍写出')
        rows.append({'number': len(rows) + 1, 'start_tick': a * 480, 'end_tick': b * 480,
                     'meter': [4, 4] if pickup else [count, 4], 'pickup': pickup,
                     'start_seconds': mapping.quarters_to_seconds(a), 'end_seconds': mapping.quarters_to_seconds(b)})
    return rows


def build_reviewed_clock(arrays, binding, features, review, provenance):
    # 最小拍轴与词音伴奏修复：新增先验只来自实际原音听辨；快慢层级不沿用出错旧谱。
    nominal = verify_source_review(review, binding)
    options = {'phase_anchors': review['downbeat_seconds'], 'unmetered_ranges': review.get('unmetered_ranges', [])}
    fixed = decode_four_beat_candidate(arrays, nominal, **options)
    candidate = decode_four_beat_candidate(arrays, nominal, allow_short_bars=True, **options)
    beats = deepcopy(candidate['beats'])
    issues, short_checks = [], []
    for i, (a, b) in enumerate(zip(beats, beats[1:])):
        if a['beat'] == 2 and b['beat'] == 1:
            head = beats[i - 1]
            attacks = {name: [endpoint_attack(feature, head['seconds']), endpoint_attack(feature, b['seconds'])]
                       for name, feature in features.items()}
            # 最小拍轴与词音伴奏修复：修改休止过门验收，原双端攻击式保留；休止本身没有攻击，需前一整小节和下一首拍夹证。
            # supported = (min(head['model_downbeat_probability'], b['model_downbeat_probability']) >= .85
            #              and any(all(value is not None for value in values) for values in attacks.values()))
            previous = next((r for r in reversed(beats[:i - 1]) if r['beat'] == 1), None)
            rest_context = {}
            for name, feature in features.items():
                relative_rms = float(np.median(feature.rms[feature.window(head['seconds'], head['seconds'] + .5)])
                                     / max(1e-8, np.percentile(feature.rms[feature.window(head['seconds'] - 4, head['seconds'] + 4)], 85)))
                previous_attack = endpoint_attack(feature, previous['seconds']) if previous else None
                rest_context[name] = {'relative_rms': relative_rms, 'previous_downbeat_attack_error': previous_attack}
            supported = (min(head['model_downbeat_probability'], b['model_downbeat_probability']) >= .85
                         and any(values[1] is not None and (values[0] is not None or
                                 (rest_context[name]['relative_rms'] < .35 and rest_context[name]['previous_downbeat_attack_error'] is not None))
                                 for name, values in attacks.items()))
            short_checks.append({'start_seconds': head['seconds'], 'end_seconds': b['seconds'],
                                 'endpoint_attack_errors': attacks, 'rest_context': rest_context, 'supported': supported,
                                 'endpoint_downbeat_probabilities': [head['model_downbeat_probability'], b['model_downbeat_probability']]})
            if not supported:
                issues.append({'kind': 'short_bar_lacks_independent_endpoint_support', 'seconds': head['seconds']})
    # 最小拍轴与词音伴奏修复：新增模型失去拍点后的余音边界；只为延音封口外推，不声称外推点有起音。
    reliable = [i for i, row in enumerate(beats) if row['model_beat_probability'] >= .5]
    if not reliable:
        raise ValueError('整曲没有可靠拍点')
    last = reliable[-1]
    observed = beats[:last + 1]
    period = float(np.median(np.diff([r['seconds'] for r in observed[-9:]])))
    next_downbeat_steps = 5 - observed[-1]['beat']
    for offset in range(1, next_downbeat_steps + 1):
        observed.append({'seconds': observed[last]['seconds'] + offset * period,
                         'beat': (observed[last]['beat'] + offset - 1) % 4 + 1,
                         'model_observed': False, 'purpose': 'held_note_measure_closure_only'})
    beats = observed
    mapping = TempoMap([{'quarter': float(i), 'seconds': row['seconds']} for i, row in enumerate(beats)])
    positions = {i: row['beat'] - 1 for i, row in enumerate(beats)}
    changes = {name: source_changes(feature, mapping, 0, last, positions) for name, feature in features.items()}
    # 最小拍轴与词音伴奏修复：新增先检查尾部是否确为低活动余音，再决定是否对不足一小节的末窗评价相位。
    tail = {}
    for name, feature in features.items():
        part = feature.window(last_second := observed[last]['seconds'] + 3, binding['duration_seconds'])
        tail[name] = {'relative_peak_flux': float(np.max(feature.flux[part]) / max(1e-8, np.percentile(feature.flux, 90))),
                      'relative_median_rms': float(np.median(feature.rms[part]) / max(1e-8, np.percentile(feature.rms, 90)))}
    decay_only = tail['accompaniment']['relative_peak_flux'] <= .25 and tail['accompaniment']['relative_median_rms'] <= .08
    windows = []
    first_second, last_second = mapping.seconds[0], observed[last]['seconds']
    for start in range(0, math.ceil(last_second), 16):
        if start + 16 <= first_second:
            continue
        phases = {name: candidate_phase_scores(rows, 1., window=(start, start + 16)) for name, rows in changes.items()}
        primary = phases['accompaniment']
        best = primary[0]
        current = next(row for row in primary if row['phase_fine_quarters'] == 0)
        local_beats = [b for b in observed[:last + 1] if start <= b['seconds'] < start + 16]
        downs = [b['model_downbeat_probability'] for b in local_beats if b['beat'] == 1]
        counter = [b['model_downbeat_probability'] for b in local_beats if b['beat'] == 3]
        boundary = any(start <= row['start_seconds'] < start + 16 and row['supported'] for row in short_checks)
        # 最小拍轴与词音伴奏修复：新增过门上下文；半小节换和弦不自动等于小节首拍，需两端起音和模型相位同时支持。
        transition_context = (best['phase_fine_quarters'] == 2 and boundary and current['contrast'] > .10
                              and downs and np.median(downs) > .9 and counter and np.median(counter) < .1)
        # 最小拍轴与词音伴奏修复：修改尾部不足一小节时的相位统计，原式保留；没有两组首拍就不以余音偶然变化反推拍号。
        # good = (best['phase_fine_quarters'] == 0 and best['contrast'] >= .03) or bool(transition_context)
        partial_decay = last_second - start < 4 and current['count'] < 2 and decay_only
        good = (best['phase_fine_quarters'] == 0 and best['contrast'] >= .03) or bool(transition_context) or partial_decay
        windows.append({'start': start, 'phases': phases, 'valid': bool(good),
                        'transition_context': bool(transition_context), 'partial_decay': partial_decay, 'beat_count': len(local_beats),
                        'median_downbeat_probability': float(np.median(downs)) if downs else 0.})
        if not good:
            issues.append({'kind': 'source_phase_window_unresolved', 'start_seconds': start})
    # 最小拍轴与词音伴奏修复：新增逐个审查锚点回读；短小节之后不能仍用全曲模4核对。
    for second in review['downbeat_seconds']:
        nearest = min((b for b in beats if b['beat'] == 1), key=lambda b: abs(b['seconds'] - second))
        if abs(nearest['seconds'] - second) > .09:
            issues.append({'kind': 'reviewed_downbeat_missed', 'seconds': second})
    # 最小拍轴与词音伴奏修复：删除重复尾部计算，原块保留于上方新增的先验检查；下方继续按相同门限拒绝活跃尾部。
    if tail['accompaniment']['relative_peak_flux'] > .25 or tail['accompaniment']['relative_median_rms'] > .08:
        issues.append({'kind': 'unobserved_tail_has_active_music', 'start_seconds': last_second + 3})
    candidate.update(knots=mapping.knots, beats=beats, meter=[4, 4], source_mix_sha256=binding['sources']['mix']['sha256'],
                     measure_timeline=make_timeline(beats, mapping), source_windows=windows,
                     model_provenance=provenance, review=deepcopy(review), short_bar_checks=short_checks,
                     observed_last_beat_seconds=last_second, source_duration_seconds=binding['duration_seconds'],
                     decay_tail_evidence=tail, fixed_four_beat_counterfactual={'path_score': fixed['path_score'],
                     'period_p05_p95': np.percentile(np.diff([r['seconds'] for r in fixed['beats']]), [5, 95]).tolist()},
                     audio_origin_seconds=0., status='clock_verified' if not issues else 'clock_needs_review')
    assessment = {'version': 1, 'policy': deepcopy(POLICY), 'status': 'passed' if not issues else 'needs_review',
                  'valid': not issues, 'issues': issues, 'candidate_sha256': fingerprint(candidate),
                  'mix_sha256': binding['sources']['mix']['sha256'], 'downstream_timing_revision_allowed': not issues,
                  'normal_publication_allowed': False, 'pitch_or_chord_recognition_changed': False,
                  'whole_song_human_confirmed': False, 'review_id': review['review_id']}
    return candidate, assessment


def write_source_clock_preview(candidate, binding, path):
    # 最小拍轴与词音伴奏修复：新增全长原混音与数拍试听，首拍高音，其余低音；引子和无模型起音的尾部不伪造数拍。
    import soundfile as sf
    source = binding['sources']['mix']
    if sha256(source['path']) != source['sha256'] or candidate['source_mix_sha256'] != source['sha256']:
        raise ValueError('数拍试听与原混音来源不一致')
    audio, rate = sf.read(source['path'], dtype='float32', always_2d=True)
    audio *= .7
    length = round(.04 * rate)
    times = np.arange(length) / rate
    for beat in candidate['beats']:
        if beat.get('model_observed') is False:
            continue
        first = round(beat['seconds'] * rate)
        count = min(length, len(audio) - first)
        if count <= 0:
            continue
        tone = .06 * np.sin(2 * np.pi * (1400 if beat['beat'] == 1 else 800) * times[:count])
        tone *= np.sin(np.pi * np.arange(count) / count) ** 2
        audio[first:first + count] += tone[:, None]
    audio *= min(1., .99 / max(1e-8, float(np.max(abs(audio)))))
    sf.write(path, audio, rate, subtype='PCM_16')
    return {'source_mix_sha256': source['sha256'], 'candidate_sha256': fingerprint(candidate),
            'frames': len(audio), 'sample_rate': rate, 'first_beat_tone_hz': 1400, 'other_beat_tone_hz': 800,
            'unmetered_head_and_inferred_decay_beats_not_clicked': True}
