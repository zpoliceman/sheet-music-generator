"""和弦弹唱与伴奏编配：绑定同源输入，并实测可选六源分离。"""
# 和弦弹唱与伴奏编配：新增独立输入层，不改现有人声工程或分轨。
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import random
import time
import numpy as np
import soundfile as sf
from score_export import read_json, save_json, sha256

ROOT = Path(__file__).resolve().parents[1]
OFFICIAL_MODEL_DOCUMENTATION = 'https://github.com/facebookresearch/demucs'


# 和弦弹唱与伴奏编配：新增同源、时长、偏移和指纹校验，拒绝混用不同录音。
def bind_inputs(vocal_project, demucs_report, references=()):
    vocal_project, demucs_report = Path(vocal_project).resolve(), Path(demucs_report).resolve()
    project, report = read_json(vocal_project), read_json(demucs_report)
    run = report['checks']['demucs_short_inference']
    mix = Path(project['inputs']['mix_audio_path']).resolve()
    if sha256(mix) != project['inputs']['mix_audio_sha256']:
        raise ValueError('原混音指纹与认可人声工程不一致。')
    if sha256(Path(run['input'])) != sha256(mix):
        raise ValueError('分轨报告来源与人声工程来源不是同一录音。')
    vocal = project['inputs']['transcription_source']
    if abs(vocal.get('offset_seconds', 0)) > 1e-7:
        raise ValueError('首版只接受零偏移同源分轨，不能默默错位。')
    expected = sf.info(mix)
    sources = {'mix': str(mix), **run['outputs']}
    records = {}
    for name, path in sources.items():
        path = Path(path).resolve()
        info = sf.info(path)
        if abs(info.duration - expected.duration) > 2 / min(info.samplerate, expected.samplerate):
            raise ValueError(f'{name}与源音频长度不一致。')
        digest = sha256(path)
        if name == 'vocals' and digest != vocal['sha256']:
            raise ValueError('分离人声不是认可谱工程的同一音轨。')
        records[name] = {'path': str(path), 'sha256': digest, 'duration_seconds': info.duration,
                         'sample_rate': info.samplerate, 'channels': info.channels,
                         'offset_seconds': 0.0, 'method': 'original_mix' if name == 'mix' else 'htdemucs'}
    refs = [{'path': str(Path(p).resolve()), 'sha256': sha256(p),
             'role': 'manual_comparison_only_not_recognizer_input'} for p in references]
    return {'version': 1, 'vocal_project': str(vocal_project), 'vocal_project_sha256': sha256(vocal_project),
            'demucs_report': str(demucs_report), 'demucs_report_sha256': sha256(demucs_report),
            'sources': records, 'references': refs, 'duration_seconds': expected.duration,
            'source_time_unit': 'original_song_seconds', 'independent_instruments_proven': False}


# 和弦弹唱与伴奏编配：新增官方权重白名单、哈希核验及先短段后整曲的GPU试跑。
def separate_six_sources(binding, output_dir, full=True):
    import torch
    import torchaudio
    from demucs.pretrained import get_model, _parse_remote_files, REMOTE_ROOT
    from demucs.apply import apply_model
    from check_environment import legacy_official_demucs_checkpoint
    output_dir = Path(output_dir).resolve()
    if not output_dir.is_relative_to(ROOT / 'test_outputs'):
        raise ValueError('新分离输出必须位于项目test_outputs独立目录。')
    output_dir.mkdir(parents=True, exist_ok=True)
    torch.hub.set_dir(str(ROOT / '.cache' / 'torch' / 'hub'))
    torch.set_num_threads(4)
    random.seed(20261007); np.random.seed(20261007); torch.manual_seed(20261007)
    url = _parse_remote_files(REMOTE_ROOT / 'files.txt')['5c90dfd2']
    if not url.startswith('https://dl.fbaipublicfiles.com/demucs/'):
        raise ValueError('权重来源不属于官方白名单。')
    weight = Path(torch.hub.get_dir()) / 'checkpoints' / url.rsplit('/', 1)[-1]
    prefix = weight.stem.split('-')[1]
    cached = weight.exists()
    started = time.perf_counter()
    if not cached:
        weight.parent.mkdir(parents=True, exist_ok=True)
        torch.hub.download_url_to_file(url, str(weight), hash_prefix=prefix, progress=True)
    digest = sha256(weight)
    if not digest.startswith(prefix):
        raise ValueError('官方六源权重指纹不符。')
    try:
        model = get_model('htdemucs_6s')
    except Exception as exc:
        # 和弦弹唱与伴奏编配：新增仅已核验官方旧权重可使用现有兼容入口。
        if 'Weights only load failed' not in str(exc):
            raise
        with legacy_official_demucs_checkpoint():
            model = get_model('htdemucs_6s')
    if not torch.cuda.is_available():
        raise RuntimeError('六源补充分离需要当前已验证的CUDA环境。')
    samples, sr = sf.read(binding['sources']['mix']['path'], dtype='float32', always_2d=True)
    wave = torch.from_numpy(samples.T.copy())
    if sr != model.samplerate:
        wave = torchaudio.functional.resample(wave, sr, model.samplerate)
    if wave.shape[0] == 1:
        wave = wave.repeat(2, 1)
    if wave.shape[0] != model.audio_channels:
        raise ValueError('六源模型不支持此声道数。')

    # 和弦弹唱与伴奏编配：新增保存实测短片段，结构通过不等同于音乐分离质量通过。
    def infer(chunk, folder):
        mean, std = chunk.mean(), chunk.std()
        if std < 1e-8:
            raise ValueError('六源试跑输入静音。')
        torch.cuda.synchronize(); t0 = time.perf_counter()
        with torch.inference_mode():
            out = apply_model(model, ((chunk - mean) / std)[None], device='cuda', shifts=1,
                              split=True, overlap=.25, segment=7, progress=True)[0].cpu() * std + mean
        torch.cuda.synchronize()
        array = out.numpy()
        if not np.isfinite(array).all() or array.shape[-1] != chunk.shape[-1]:
            raise ValueError('六源结果非有限或长度错误。')
        folder.mkdir(parents=True, exist_ok=True)
        files = {}
        for name, data in zip(model.sources, array):
            target = folder / f'{name}.wav'
            sf.write(target, data.T, model.samplerate, subtype='FLOAT')
            files[name] = {'path': str(target), 'sha256': sha256(target),
                           'rms': float(np.sqrt(np.mean(data ** 2))),
                           'duration_seconds': data.shape[-1] / model.samplerate,
                           'sample_rate': model.samplerate, 'channels': data.shape[0],
                           'offset_seconds': 0.0, 'method': 'htdemucs_6s_experimental'}
        return files, time.perf_counter() - t0

    short_frames = min(wave.shape[-1], round(24 * model.samplerate))
    short, short_time = infer(wave[:, :short_frames], output_dir / 'short_test')
    result = {'model': 'htdemucs_6s', 'documentation': OFFICIAL_MODEL_DOCUMENTATION,
              'weight': {'path': str(weight), 'url': url, 'sha256': digest, 'cached_before': cached},
              'sources': list(model.sources), 'short_test': short, 'short_inference_seconds': short_time,
              'structural_short_test': 'passed', 'musical_separation_quality': 'requires_listening',
              'limitation': '官方说明钢琴源有串音/伪影；仅作补充证据，原混音与完整伴奏仍参与分析。',
              'full_outputs': {}, 'elapsed_seconds': time.perf_counter() - started}
    save_json(output_dir / 'separation_report.json', result)
    if full:
        outputs, full_time = infer(wave, output_dir / 'separated')
        result['full_outputs'] = outputs; result['full_inference_seconds'] = full_time
        result['elapsed_seconds'] = time.perf_counter() - started
        save_json(output_dir / 'separation_report.json', result)
    return result


# 和弦弹唱与伴奏编配：新增独立CLI，输入绑定与补充分离报告均可复用。
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vocal-project', type=Path, required=True)
    parser.add_argument('--demucs-report', type=Path, required=True)
    parser.add_argument('--reference', type=Path, action='append', default=[])
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--six-sources', action='store_true')
    parser.add_argument('--short-only', action='store_true')
    args = parser.parse_args()
    binding = bind_inputs(args.vocal_project, args.demucs_report, args.reference)
    args.output.mkdir(parents=True, exist_ok=True)
    save_json(args.output / 'input_binding.json', binding)
    if args.six_sources:
        report = separate_six_sources(binding, args.output, full=not args.short_only)
        for name in ('guitar', 'piano', 'other'):
            if name in report['full_outputs']:
                binding['sources']['six_' + name] = report['full_outputs'][name]
        binding['supplemental_separation_report'] = str((args.output / 'separation_report.json').resolve())
        save_json(args.output / 'input_binding.json', binding)
    print(json.dumps({'input_binding': str(args.output / 'input_binding.json'),
                      'sources': list(binding['sources'])}, ensure_ascii=False))


if __name__ == '__main__':
    main()
