"""慢拍单位与两曲最小修订：保留原声有序向量的节拍比较证据。"""
# 慢拍单位与两曲最小修订：新增独立的第二版证据格式；不识别新音高、和弦或歌词。
import numpy as np
from scipy.ndimage import uniform_filter1d

VECTOR_KEYS = tuple('pitch_class_' + str(i) for i in range(12)) + tuple('register_' + str(i) for i in range(3))


def ordered_vectors(times, activations, low=False):
    # 慢拍单位与两曲最小修订：新增原缓存音高分布与低中高音区，保留先后内容而不只保留变化大小。
    count = min(29, len(activations)) if low else len(activations)
    values = np.asarray(activations, float).copy()
    chroma = np.zeros((12, values.shape[1]))
    for i in range(count):
        chroma[(i + 24) % 12] += values[i]
    registers = np.array([values[:24].sum(axis=0), values[24:48].sum(axis=0), values[48:].sum(axis=0)])
    dt = float(np.median(np.diff(times)))
    ordered = uniform_filter1d(np.vstack([chroma, registers]), size=max(1, round(.08 / dt)), axis=1)
    # 慢拍单位与两曲最小修订：新增消除滑动和的浮点负零，静音分母归一前必须保持非负能量。
    ordered = np.maximum(ordered, 0.)
    for section in (slice(0, 12), slice(12, 15)):
        ordered[section] /= np.maximum(1e-9, np.linalg.norm(ordered[section], axis=0))
    return {key: ordered[i] for i, key in enumerate(VECTOR_KEYS)}


def validate_ordered_evidence(meta, arrays):
    # 慢拍单位与两曲最小修订：新增版本化白名单验证；先用旧格式验证公共字段，再严格验证新增向量。
    from source_meter_selection import validate_evidence
    if meta.get('version') != 2:
        raise ValueError('有序原声证据要求第二版格式')
    vector_names = {row['prefix'] + '_' + key for row in meta['tracks'] for key in VECTOR_KEYS}
    if not vector_names.issubset(arrays):
        raise ValueError('有序原声证据缺少音高分布／音区数组')
    base = {key: value for key, value in arrays.items() if key not in vector_names}
    validate_evidence({**meta, 'version': 1}, base)
    for row in meta['tracks']:
        size = len(arrays[row['prefix'] + '_times'])
        for key in VECTOR_KEYS:
            value = np.asarray(arrays[row['prefix'] + '_' + key])
            if value.shape != (size,) or not np.all(np.isfinite(value)) or np.any(value < 0):
                raise ValueError('有序原声向量维度或数值错误')


def sample_grid(beats, phase, track, start, end, divisions=2):
    # 慢拍单位与两曲最小修订：新增统一半拍格；同一段原音按候选单位排列，绝不更改原拍点秒数。
    seconds = np.array([r['seconds'] for r in beats])
    quarters = np.arange(len(seconds), dtype=float)
    grid = np.arange(0., len(seconds) - 1, 1. / divisions)
    at = np.interp(grid, quarters, seconds)
    origin = beats[0]['beat'] - 1 + phase
    labels = np.rint((grid + origin) * divisions).astype(int) % (4 * divisions)
    use = (at >= start) & (at < end)
    return at[use], labels[use]


def cosine_distance(a, b):
    # 慢拍单位与两曲最小修订：新增保留方向的内容差异；静音不伪装成和声转换。
    norm = np.linalg.norm(a, axis=-1) * np.linalg.norm(b, axis=-1)
    return np.where(norm > 1e-9, np.clip(1 - (a * b).sum(axis=-1) / np.maximum(norm, 1e-9), 0, 1), 0.)


def sequence_profile(beats, phase, track, interval):
    # 慢拍单位与两曲最小修订：新增逐位置攻击和相邻前后音区／音级方向的可复核统计。
    from source_meter_selection import _sample
    at, labels = sample_grid(beats, phase, track, *interval)
    period = float(np.median(np.diff([r['seconds'] for r in beats])))
    times = track['times']
    profiles = {}
    for key in ('novelty', 'onset_low', 'onset_high', 'rms'):
        values = _sample(times, track[key], at, min(.08, period / 8))
        profiles[key] = [float(np.mean(values[labels == i])) if np.any(labels == i) else 0. for i in range(8)]
    if not all(key in track for key in VECTOR_KEYS):
        return profiles
    # 慢拍单位与两曲最小修订：新增每个半拍内部的平均音高分布，避免瞬时起音倍频支配整段比较。
    vectors = np.stack([np.mean([np.interp(at + offset * period, times, track[key])
                       for offset in (.10, .20, .30)], axis=0) for key in VECTOR_KEYS], axis=-1)
    if len(vectors) < 17:
        return profiles
    for lag in (1, 2, 4, 8, 16):
        delta = cosine_distance(vectors[lag:, :12], vectors[:-lag, :12])
        profiles['pitch_distance_lag_' + str(lag)] = float(np.mean(delta))
    difference = cosine_distance(vectors[1:, :12], vectors[:-1, :12])
    profiles['pitch_changes'] = [float(np.mean(difference[labels[1:] == i])) if np.any(labels[1:] == i) else 0. for i in range(8)]
    profiles['registers'] = [[float(np.mean(vectors[labels == i, j])) if np.any(labels == i) else 0.
                             for j in range(12, 15)] for i in range(8)]
    return profiles
