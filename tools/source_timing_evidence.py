"""最小拍轴与词音伴奏修复：只分析原曲节拍的隔离候选与首拍证据。"""
# 最小拍轴与词音伴奏修复：新增独立政策；不调用音高／和弦解码，不修改任何历史拍轴政策或默认入口。
from copy import deepcopy
from pathlib import Path
import math
import numpy as np
from scipy.ndimage import gaussian_filter1d
from score_export import read_json, save_json, sha256, TempoMap

POLICY = {'version': 1, 'mode': 'source_timing_only', 'level_scales': [.5, 1., 2.],
          'minimum_neighbour_period_fraction': .55, 'local_window_seconds': 16.,
          'model_frames_per_second': 50, 'maximum_anchor_refinement_seconds': .07,
          'notation_and_lyrics_used_to_infer_clock': False,
          'new_pitch_or_chord_decoder_called': False, 'unresolved_candidates_publishable': False}
CHECKPOINT_SHA256 = '8c328b45f59d8dd3dff219253ff6a8d6482be57d0133a29140e2febbf8eb8331'


def read_source_model(source, cache, existing=None):
    # 最小拍轴与词音伴奏修复：新增来源验证；仅复用原始模型激活，绝不复用失败版的选定拍轴／音符。
    if sha256(source['path']) != source['sha256']:
        raise ValueError('时间修订的原混音SHA已改变')
    cache = Path(cache)
    cache.mkdir(parents=True, exist_ok=True)
    metadata = cache / ('timing_model_v1_' + source['sha256'][:20] + '.json')
    if existing is not None or metadata.exists():
        prior = Path(existing) if existing is not None else metadata
        saved = read_json(prior)
        source_sha = saved.get('source_sha256')
        policy = saved['policy']
        archive = Path(saved['archive'])
        if (source_sha != source['sha256'] or policy.get('checkpoint_sha256') != CHECKPOINT_SHA256
                or policy.get('frames_per_second') != 50 or sha256(archive) != saved['archive_sha256']):
            raise ValueError('原混音节拍模型候选的来源／权重／激活缓存不符')
        with np.load(archive) as arrays:
            result = {key: arrays[key].copy() for key in ('beats', 'downbeats', 'beat_logits', 'downbeat_logits')}
        return result, {'metadata': str(prior.resolve()), 'metadata_sha256': sha256(prior),
                        'archive_sha256': saved['archive_sha256'], 'source_sha256': source_sha,
                        'model_outputs_are_candidates': True}
    # 最小拍轴与词音伴奏修复：新增无旧缓存时的本机原混音推断；不加载失败音乐流程。
    import soundfile as sf
    import torch
    from importlib.metadata import version
    from beat_this.inference import Audio2Frames
    from beat_this.model.postprocessor import Postprocessor
    if version('beat-this') != '1.1.0':
        raise ValueError('原混音节拍模型版本不匹配')
    root = Path(__file__).resolve().parents[1]
    checkpoint = root / '.cache/torch/hub/checkpoints/beat_this-final0.ckpt'
    if not checkpoint.is_file() or sha256(checkpoint) != CHECKPOINT_SHA256:
        raise ValueError('本地节拍权重缺失／指纹不符')
    torch.set_num_threads(4)
    signal, rate = sf.read(source['path'], dtype='float32', always_2d=True)
    model = Audio2Frames(checkpoint_path=str(checkpoint), device='cuda' if torch.cuda.is_available() else 'cpu', float16=False)
    with torch.inference_mode():
        beat_logits, downbeat_logits = model(signal.mean(axis=1), rate)
    beats, downbeats = Postprocessor(type='minimal')(beat_logits, downbeat_logits)
    result = {'beats': np.asarray(beats), 'downbeats': np.asarray(downbeats),
              'beat_logits': beat_logits.cpu().numpy(), 'downbeat_logits': downbeat_logits.cpu().numpy()}
    archive = metadata.with_suffix('.npz')
    np.savez_compressed(archive, **result)
    saved = {'policy': {'version': 1, 'checkpoint_sha256': CHECKPOINT_SHA256, 'frames_per_second': 50},
             'source_sha256': source['sha256'], 'archive': str(archive.resolve()), 'archive_sha256': sha256(archive)}
    save_json(metadata, saved)
    return read_source_model(source, cache)


def canonical_pulses(beats, tempo_hint):
    # 最小拍轴与词音伴奏修复：新增连续整数细分编号；模型倍半切换用缺失细分解释，近邻假峰记录排除，不能硬挤一拍。
    raw = np.asarray(beats, dtype=float)
    if len(raw) < 16 or np.any(np.diff(raw) <= 0):
        raise ValueError('原曲拍点不足或逆序，不能建立时间候选')
    hint = 60 / float(tempo_hint)
    intervals = np.diff(raw)
    powers = 2. ** np.arange(-2, 4)
    folded = intervals[:, None] / powers[None, :]
    nearest = np.argmin(abs(np.log(folded / hint)), axis=1)
    period = float(np.median(folded[np.arange(len(intervals)), nearest]))
    seconds, excluded = [float(raw[0])], []
    for value in raw[1:]:
        if value - seconds[-1] < period * POLICY['minimum_neighbour_period_fraction']:
            excluded.append(float(value))
        else:
            seconds.append(float(value))
    seconds = np.array(seconds)
    increments = np.maximum(1, np.rint(np.diff(seconds) / period).astype(int))
    quarters = np.r_[0, np.cumsum(increments)].astype(float)
    errors = abs(np.diff(seconds) / period - increments)
    conflicts = [{'start_seconds': float(a), 'end_seconds': float(b), 'rounded_pulses': int(n), 'fractional_error': float(error)}
                 for a, b, n, error in zip(seconds[:-1], seconds[1:], increments, errors) if error > .35]
    return seconds, quarters, {'nominal_fine_period_seconds': period, 'excluded_neighbour_peaks': excluded,
                               'interval_conflicts': conflicts, 'pulse_numbering_uses_old_score': False}


def track_source_pulses(feature, model_beats, tempo_hint):
    # 最小拍轴与词音伴奏修复：新增原声起音连续跟踪；模型只给局部速度范围，不继承其漏拍／额外首拍编号。
    import librosa
    from scipy.ndimage import median_filter, percentile_filter
    raw = np.asarray(model_beats, dtype=float)
    hint = 60 / float(tempo_hint)
    intervals = np.diff(raw)
    powers = 2. ** np.arange(-2, 4)
    folded = intervals[:, None] / powers[None, :]
    selected = np.argmin(abs(np.log(folded / hint)), axis=1)
    values = folded[np.arange(len(intervals)), selected]
    median = float(np.median(values))
    valid = abs(np.log(values / median)) < .12
    if valid.sum() < 12:
        raise ValueError('局部速度的可信原曲证据不足')
    centers = (raw[:-1] + raw[1:]) / 2
    dt = float(np.median(np.diff(feature.times)))
    periods = np.interp(feature.times, centers[valid], values[valid])
    periods = median_filter(periods, size=max(3, round(2. / dt) // 2 * 2 + 1))
    periods = gaussian_filter1d(periods, max(1., .8 / dt))
    smooth = gaussian_filter1d(feature.activations, .7, axis=1)
    flux = np.maximum(0., np.diff(smooth, prepend=smooth[:, :1], axis=1)).sum(axis=0)
    normalizer = percentile_filter(flux, percentile=90, size=max(5, round(6. / dt)))
    envelope = np.minimum(4., flux / np.maximum(1e-8, normalizer))
    envelope *= np.minimum(1., feature.rms / max(1e-7, float(np.percentile(feature.rms, 85)) * .015))
    _, indexes = librosa.beat.beat_track(onset_envelope=envelope, sr=22050, hop_length=512,
                                       bpm=60 / periods, tightness=100., trim=False)
    if len(indexes) < 16:
        raise ValueError('原声起音不能支持连续拍序')
    seconds = feature.times[indexes]
    quarters = np.arange(len(seconds), dtype=float)
    windows = []
    for begin in np.arange(0., feature.times[-1], 16.):
        end = min(begin + 16., float(feature.times[-1]))
        selected = (seconds >= begin) & (seconds < end)
        strength = envelope[indexes[selected]]
        windows.append({'start_seconds': float(begin), 'end_seconds': float(end), 'pulse_count': int(selected.sum()),
                        'supported_count': int((strength >= .25).sum()),
                        'median_strength': float(np.median(strength)) if len(strength) else 0.})
    return TempoMap([{'quarter': float(q), 'seconds': float(t)} for q, t in zip(quarters, seconds)]), {
        'method': 'dynamic_program_original_source_flux_with_local_tempo_only',
        'source_sha256': feature.source['sha256'], 'old_score_or_model_counter_used': False,
        'fine_period_percentiles_seconds': np.percentile(np.diff(seconds), [5, 50, 95]).tolist(),
        'windows': windows}


def feature_chroma(feature, low=False):
    # 最小拍轴与词音伴奏修复：新增仅用于变化验证的原声色度；不选择和弦名、调性或替换任何旋律音。
    size = min(29, feature.activations.shape[0]) if low else feature.activations.shape[0]
    result = np.zeros((12, feature.activations.shape[1]))
    for i in range(size):
        result[(24 + i) % 12] += feature.activations[i]
    result = gaussian_filter1d(result, 1., axis=1)
    return result


# 最小拍轴与词音伴奏修复：修改相位验证接口，原签名保留；不把两拍短小节之后的正确首拍错当成整体漂移。
# def source_changes(feature, mapping, first, last):
def source_changes(feature, mapping, first, last, bar_positions=None):
    # 最小拍轴与词音伴奏修复：新增全候选网格都检查的原声前后变化，不能先筛已接近某个首拍的点再证明它。
    chroma = feature_chroma(feature)
    low = feature_chroma(feature, True)
    rows = []
    for quarter in range(first, last + 1):
        second = mapping.quarters_to_seconds(quarter)
        period = mapping.quarters_to_seconds(quarter + 1) - second
        if second < feature.times[0] + .15 or second > feature.times[-1] - .15:
            continue
        windows = [feature.window(second - period * .70, second - period * .12),
                   feature.window(second + period * .12, second + period * .70)]
        def novelty(values):
            a, b = [values[:, window].mean(axis=1) for window in windows]
            return max(0., float(1 - np.dot(a, b) / max(1e-12, np.linalg.norm(a) * np.linalg.norm(b))))
        index = min(len(feature.rms) - 1, int(np.searchsorted(feature.times, second)))
        active = feature.rms[index] > max(1e-7, float(np.percentile(feature.rms, 85)) * .012)
        rows.append({'fine_quarter': quarter, 'seconds': float(second), 'chroma_change': novelty(chroma),
                     'low_change': novelty(low), 'active': bool(active)})
        if bar_positions is not None:
            rows[-1]['bar_phase_quarter'] = float(bar_positions[quarter])
    return rows


def candidate_phase_scores(changes, scale, meter=(4, 4), window=None):
    # 最小拍轴与词音伴奏修复：新增各快慢层与所有组头分别评分；仅给证据，不将最高分自动当音乐验收通过。
    span = meter[0] * 4 / meter[1] / scale
    resolution = 2 if span < 2 else 1
    phases = np.arange(0., span, 1. / resolution)
    rows = [r for r in changes if r['active'] and (window is None or window[0] <= r['seconds'] < window[1])]
    result = []
    for phase in phases:
        # 最小拍轴与词音伴奏修复：修改分组参考，原固定相位式保留；实际小节内拍号优先，未提供短小节则与原式相同。
        # selected = [r for r in rows if abs(((r['fine_quarter'] - phase + span / 2) % span) - span / 2) < .1]
        selected = [r for r in rows if abs(((r.get('bar_phase_quarter', r['fine_quarter']) - phase + span / 2) % span) - span / 2) < .1]
        rest = [r for r in rows if r not in selected]
        weights = [r['chroma_change'] + .7 * r['low_change'] for r in selected]
        score = float(np.mean(weights)) if weights else 0.
        reference = float(np.mean([r['chroma_change'] + .7 * r['low_change'] for r in rest])) if rest else 0.
        result.append({'phase_fine_quarters': float(phase), 'mean_change': score,
                       'offbeat_mean_change': reference, 'contrast': score - reference, 'count': len(selected)})
    return sorted(result, key=lambda row: (-row['contrast'], row['phase_fine_quarters']))


def infer_timing_candidates(vocal, binding, features, model_arrays, model_provenance):
    # 最小拍轴与词音伴奏修复：新增候选集合；默认不选择旧谱或模型首拍，也不清除原有未决状态。
    hint = float(vocal['audio_analysis']['tempo']['bpm'])
    seconds, quarters, pulse_audit = canonical_pulses(model_arrays['beats'], hint)
    mapping = TempoMap([{'quarter': float(q), 'seconds': float(t)} for q, t in zip(quarters, seconds)])
    period = pulse_audit['nominal_fine_period_seconds']
    first = int(math.floor(-seconds[0] / period))
    last = int(math.ceil(quarters[-1] + (binding['duration_seconds'] - seconds[-1]) / period))
    changes = {name: source_changes(feature, mapping, first, last) for name, feature in features.items()}
    candidates = []
    for scale in POLICY['level_scales']:
        tracks = {name: candidate_phase_scores(rows, scale, vocal['timing']['meter']) for name, rows in changes.items()}
        windows = []
        for start in np.arange(0., binding['duration_seconds'], POLICY['local_window_seconds']):
            end = min(float(start + POLICY['local_window_seconds']), binding['duration_seconds'])
            windows.append({'start_seconds': float(start), 'end_seconds': end,
                            'tracks': {name: candidate_phase_scores(rows, scale, vocal['timing']['meter'], (start, end))[:2] for name, rows in changes.items()}})
        candidates.append({'scale': scale, 'nominal_bpm': 60 / period * scale,
                           'phase_tracks': tracks, 'local_phase_windows': windows})
    return {'version': 1, 'policy': deepcopy(POLICY), 'status': 'timing_candidates_require_independent_phase_review',
            'source_fingerprints': {name: source['sha256'] for name, source in binding['sources'].items()},
            'model_provenance': model_provenance, 'pulse_audit': pulse_audit,
            'fine_knots': mapping.knots, 'candidates': candidates, 'source_changes': changes,
            'first_model_supported_seconds': float(seconds[0]), 'last_model_supported_seconds': float(seconds[-1]),
            'human_downbeat_evidence_required_when_ambiguous': True, 'music_accepted': False}
