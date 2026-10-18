"""自动拍层级与首拍盲测：原声证据打包与无人答案的通用命令入口。"""
# 自动拍层级与首拍盲测：新增只读来源入口；不运行音高解码、和弦分析、歌词对齐或曲谱生成。
import argparse
from pathlib import Path
import json
import numpy as np
from scipy.ndimage import gaussian_filter1d, uniform_filter1d
from scipy.signal import find_peaks, stft
from score_export import read_json, save_json, sha256
from source_timing_evidence import read_source_model
from source_timing_acceptance import require_isolated_output
from source_meter_selection import ROLES, RAW_MODEL_KEYS, select_meter, validate_evidence

ROOT = Path(__file__).resolve().parents[1]


def _novelty(times, activations, low=False):
    # 自动拍层级与首拍盲测：新增原声色度变化证据，固定物理窗口，不生成和弦名或新音符。
    chroma = np.zeros((12, activations.shape[1]))
    count = min(29, len(activations)) if low else len(activations)
    for i in range(count):
        chroma[(i + 24) % 12] += activations[i]
    dt = float(np.median(np.diff(times)))
    smooth = uniform_filter1d(chroma, size=max(1, round(.16 / dt)), axis=1)
    offset = max(1, round(.18 / dt))
    before = smooth[:, np.maximum(0, np.arange(len(times)) - offset)]
    after = smooth[:, np.minimum(len(times) - 1, np.arange(len(times)) + offset)]
    dot = np.sum(before * after, axis=0)
    norm = np.linalg.norm(before, axis=0) * np.linalg.norm(after, axis=0)
    return np.where(norm > 1e-12, np.clip(1 - dot / np.maximum(norm, 1e-12), 0., 1.), 0.)


def _normalize(values):
    # 自动拍层级与首拍盲测：新增只读幅度归一；安静分轨不会因别的乐器很响被抹掉。
    return np.clip(values / max(1e-9, float(np.percentile(values, 90))), 0., 3.)


def _rhythm_audio(source, role):
    # 自动拍层级与首拍盲测：新增鼓／人声纯能量与频带攻击，不识别人声音高或歌词。
    import soundfile as sf
    from scipy.signal import resample_poly
    import math
    audio, rate = sf.read(source['path'], dtype='float32', always_2d=True)
    audio = audio.mean(axis=1)
    target = 11025
    common = math.gcd(rate, target)
    audio = resample_poly(audio, target // common, rate // common)
    _, times, spectrum = stft(audio, fs=target, nperseg=1024, noverlap=768,
                              boundary='zeros', padded=True)
    magnitude = abs(spectrum)
    frequency = np.fft.rfftfreq(1024, 1 / target)
    flux = np.maximum(0., np.diff(magnitude, axis=1, prepend=magnitude[:, :1]))
    low = flux[(frequency >= 40) & (frequency < 250)].sum(axis=0)
    high = flux[(frequency >= 1000) & (frequency < 5000)].sum(axis=0)
    rms = np.sqrt(np.sum(magnitude ** 2, axis=0))
    phrase = np.zeros(len(times))
    if role == 'vocals':
        floor = max(1e-7, float(np.percentile(rms, 85)) * .09)
        smooth = uniform_filter1d(rms, size=9)
        active = smooth > floor
        starts = np.flatnonzero(active & ~np.r_[False, active[:-1]])
        dt = float(np.median(np.diff(times)))
        for start in starts:
            prior = active[max(0, start - round(.45 / dt)):start]
            if len(prior) and not prior.any():
                phrase[start] = 1.
    return {'times': times + float(source.get('offset_seconds', 0.)),
            'novelty': np.zeros(len(times)), 'onset_low': _normalize(low),
            'onset_high': _normalize(high), 'rms': rms, 'phrase': phrase}


# 慢拍单位与两曲最小修订：新增可选有序证据，原三参数行为保持供历史重放。
# def _cached_track(source, role, caches):
def _cached_track(source, role, caches, ordered=False):
    # 自动拍层级与首拍盲测：新增严格只读声学缓存；缺失时明确报错，禁止偷偷整曲重算音高与和弦。
    token = 'v1_' + source['sha256'][:16] + '_22050_512_24_96'
    found = next((Path(cache) / (token + '.json') for cache in caches
                  if (Path(cache) / (token + '.json')).is_file()
                  and (Path(cache) / (token + '.npz')).is_file()), None)
    if found is None:
        raise ValueError('缺少来源绑定的只读声学缓存：' + role)
    saved = read_json(found)
    if saved.get('version') != 1 or saved.get('source_sha256') != source['sha256']:
        raise ValueError('声学缓存版本或原音来源不匹配')
    with np.load(found.with_suffix('.npz'), allow_pickle=False) as archive:
        times = archive['times'].copy() + float(source.get('offset_seconds', 0.))
        activation = archive['activations'].copy()
        rms, flux = archive['rms'].copy(), archive['flux'].copy()
    novelty = _novelty(times, activation, low=role == 'bass')
    novelty[rms < max(1e-7, float(np.percentile(rms, 85)) * .015)] = 0.
    # 慢拍单位与两曲最小修订：修改直接返回式，增加原缓存向量；原式注释保存。
    # return {'times': times, 'novelty': novelty, 'onset_low': _normalize(flux),
    #         'onset_high': np.zeros(len(times)), 'rms': rms, 'phrase': np.zeros(len(times))}, {
    evidence = {'times': times, 'novelty': novelty, 'onset_low': _normalize(flux),
                'onset_high': np.zeros(len(times)), 'rms': rms, 'phrase': np.zeros(len(times))}
    if ordered:
        from source_meter_sequence import ordered_vectors
        evidence.update(ordered_vectors(times, activation, low=role == 'bass'))
    return evidence, {
                'metadata': str(found.resolve()), 'metadata_sha256': sha256(found),
                'archive': str(found.with_suffix('.npz').resolve()),
                'archive_sha256': sha256(found.with_suffix('.npz'))}


# 慢拍单位与两曲最小修订：新增版本开关，默认新证据保留时间顺序；显式旧版仍可重放。
# def prepare_evidence(binding, work, model_cache=None, feature_caches=()):
def prepare_evidence(binding, work, model_cache=None, feature_caches=(), ordered=True):
    # 自动拍层级与首拍盲测：新增白名单打包；仅原音路径／SHA／时长可从工程进入这一层。
    work = require_isolated_output(work, ROOT)
    if work.exists():
        raise ValueError('盲测证据目录已存在，请另建目录，不覆盖旧版本')
    sources = {role: binding['sources'][role] for role in ('mix', *ROLES)
               if role in binding['sources']}
    if 'mix' not in sources:
        raise ValueError('缺少原混音来源')
    for role, source in sources.items():
        if sha256(source['path']) != source['sha256']:
            raise ValueError('原声来源SHA改变：' + role)
    work.mkdir(parents=True)
    arrays, model_provenance = read_source_model(sources['mix'], work / 'raw_model', model_cache)
    packed = {key: np.asarray(arrays[key]).reshape(-1).copy() for key in RAW_MODEL_KEYS}
    tracks, provenance = [], {}
    for role in ROLES:
        if role not in sources:
            continue
        source = sources[role]
        if role in ('drums', 'vocals'):
            evidence = _rhythm_audio(source, role)
            # 慢拍单位与两曲最小修订：新增非有音乐器的空向量；不从人声重新识别音高。
            if ordered:
                from source_meter_sequence import VECTOR_KEYS
                evidence.update({key: np.zeros(len(evidence['times'])) for key in VECTOR_KEYS})
            provenance[role] = {'method': 'raw_audio_energy_and_spectral_flux_only',
                                'source_sha256': source['sha256']}
        else:
            # 慢拍单位与两曲最小修订：修改打包调用，保留旧调用供历史追溯。
            # evidence, provenance[role] = _cached_track(source, role, feature_caches)
            evidence, provenance[role] = _cached_track(source, role, feature_caches, ordered=ordered)
        prefix = 't' + str(len(tracks))
        tracks.append({'role': role, 'source_sha256': source['sha256'], 'prefix': prefix})
        packed.update({prefix + '_' + key: np.asarray(value, dtype=float)
                       for key, value in evidence.items()})
    target = work / 'raw_evidence.npz'
    np.savez_compressed(target, **packed)
    # 慢拍单位与两曲最小修订：修改证据版本与验证分流，旧格式不会被默默解释为有序证据。
    # metadata = {'version': 1, 'duration_seconds': float(binding['duration_seconds']),
    metadata = {'version': 2 if ordered else 1, 'duration_seconds': float(binding['duration_seconds']),
                'mix_sha256': sources['mix']['sha256'], 'model_archive_sha256': model_provenance['archive_sha256'],
                'tracks': tracks, 'array_sha256': sha256(target), 'raw_only': True}
    # validate_evidence(metadata, packed)
    if ordered:
        from source_meter_sequence import validate_ordered_evidence
        validate_ordered_evidence(metadata, packed)
    else:
        validate_evidence(metadata, packed)
    save_json(work / 'raw_evidence.json', metadata)
    # 自动拍层级与首拍盲测：新增来源审计与算法输入分离；路径／曲名和旧工程均不进入预测包。
    save_json(work / 'preparation_audit.json', {'sources': sources, 'model': model_provenance,
        'feature_caches': provenance, 'human_review_files_read': False, 'score_timing_used': False,
        'pitch_or_chord_decoder_called': False})
    return work / 'raw_evidence.json'


def choose_evidence(metadata_path, output):
    # 自动拍层级与首拍盲测：新增独立预测入口；证据包之外不读取任何谱子或人工表单。
    metadata_path, output = Path(metadata_path).resolve(), Path(output).resolve()
    require_isolated_output(output.parent, ROOT)
    if output.exists():
        raise ValueError('预测已存在，不得用看过人工标签的新结果覆盖它')
    meta = read_json(metadata_path)
    archive = metadata_path.with_suffix('.npz')
    if sha256(archive) != meta['array_sha256']:
        raise ValueError('匿名证据包SHA改变')
    with np.load(archive, allow_pickle=False) as stored:
        arrays = {key: stored[key].copy() for key in stored.files}
    result = select_meter(meta, arrays)
    save_json(output, result)
    return result


def select_from_sources(binding, work, model_cache=None, feature_caches=()):
    # 自动拍层级与首拍盲测：新增供既有诊断入口调用的通用路径，拒绝使用人工复核参数。
    metadata = prepare_evidence(binding, work, model_cache, feature_caches)
    return choose_evidence(metadata, Path(work) / 'automatic_selection.json')


def main():
    # 自动拍层级与首拍盲测：新增显式prepare／choose子命令，便于先隔离输入再启动受审计预测进程。
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    prepare = sub.add_parser('prepare')
    prepare.add_argument('--binding', type=Path, required=True)
    prepare.add_argument('--work', type=Path, required=True)
    prepare.add_argument('--model-cache', type=Path)
    prepare.add_argument('--features-from', type=Path, action='append', default=[])
    choose = sub.add_parser('choose')
    choose.add_argument('--evidence', type=Path, required=True)
    choose.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.command == 'prepare':
        result = {'evidence': str(prepare_evidence(read_json(args.binding), args.work,
                                                 args.model_cache, args.features_from))}
    else:
        selected = choose_evidence(args.evidence, args.output)
        result = {key: selected[key] for key in ('status', 'notation_level', 'bar_first_beat')}
    print(json.dumps(result, ensure_ascii=False, indent=2))


# 自动拍层级与首拍盲测：新增直接命令入口，导入模块不触发任何任务。
if __name__ == '__main__':
    main()
