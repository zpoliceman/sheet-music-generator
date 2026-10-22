"""在制谱前核对音源并准备模型输入；原文件保持，输出必须使用新目录。"""
from __future__ import annotations
import argparse
import json
import math
from pathlib import Path
import sys
from audio_inventory import process, run, save_json, sha256, tool

SUPPORTED_AUDIO = ('.mp3', '.ncm', '.wav', '.flac', '.m4a')


def validate_audio_path(source):
    source = Path(source).resolve()
    if source.suffix.lower() == '.lrc':
        raise ValueError('LRC是带时间戳的歌词文件，不是音源；请选择MP3、NCM、FLAC、WAV或M4A音频。')
    if not source.is_file() or source.suffix.lower() not in SUPPORTED_AUDIO:
        raise ValueError('请选择存在的MP3、NCM、FLAC、WAV或M4A音源文件。')
    if source.stat().st_size == 0 or source.stat().st_size > 500 * 1024 * 1024:
        raise ValueError('音源为空或超过500MB，请选择单首歌曲。')
    return source


def check_pcm_audio(path, inventory):
    """Read actual lossless/PCM frames without altering rate, channels or samples."""
    import numpy as np
    import soundfile as sf
    info = sf.info(path)
    frames = 0
    peak = 0.
    with sf.SoundFile(path) as audio:
        for block in audio.blocks(blocksize=65536, dtype='float64', always_2d=True):
            if not np.isfinite(block).all():
                raise ValueError('音源包含非有限采样值，不能送入模型。')
            frames += len(block)
            if len(block):
                peak = max(peak, float(np.abs(block).max()))
    if not frames or frames != info.frames:
        raise ValueError('实际解码帧数与音源头记录不同，文件可能被截断。')
    if info.samplerate != inventory['sample_rate'] or info.channels != inventory['channels']:
        raise ValueError('实际音源的采样率或声道数与格式检查结果不同。')
    if abs(frames / info.samplerate - inventory['duration_seconds']) > .06:
        raise ValueError('实际解码时长与音源格式记录不同，不能继续制谱。')
    return {'frames': frames, 'sample_rate': info.samplerate, 'channels': info.channels,
            'subtype': info.subtype, 'duration_seconds': frames / info.samplerate,
            'peak_amplitude': peak, 'all_frames_decoded': True,
            'normalization_applied': False, 'resampling_applied': False}


def prepare(source, output, *, expected_sha256=None, max_duration_seconds=900):
    source = validate_audio_path(source)
    output = Path(output).resolve()
    if not math.isfinite(max_duration_seconds) or max_duration_seconds <= 0:
        raise ValueError('允许的歌曲时长必须为正数。')
    if output.exists():
        raise FileExistsError('音源预处理目录已存在，请使用新目录；已有文件不会覆盖。')
    if source.is_relative_to(output):
        raise ValueError('预处理目录不能包含原音源，请另选新目录。')
    output.mkdir(parents=True, exist_ok=False)
    before = sha256(source)
    report = {'schema_version': 1, 'status': 'pending', 'source': str(source),
              'source_sha256_before': before, 'requested_extension': source.suffix.lower()}
    try:
        if expected_sha256 is not None and before != expected_sha256:
            raise ValueError('音源与本次任务登记的内容摘要不同，请重新选择稳定文件。')
        inventory = process(source, tool('ncmdump') if source.suffix.lower() == '.ncm' else None,
                            tool('ffprobe'), tool('ffmpeg'), workspace=output)
        save_json(output / 'validation.json', inventory)
        if inventory['status'] != 'verified':
            raise ValueError(inventory.get('error', '音源未通过完整解码检查。'))
        duration = inventory['duration_seconds']
        if not math.isfinite(duration) or duration <= 0 or duration > max_duration_seconds:
            raise ValueError('音源时长无效或超过当前单首时长上限（' + str(max_duration_seconds) + '秒）。')
        mixed = Path(inventory['audio']).resolve()
        report.update(actual_codec=inventory['codec'], actual_container=inventory['container'],
                      validation_report=str(output / 'validation.json'),
                      action='decoded_ncm' if source.suffix.lower() == '.ncm' else 'verified_original_audio')
        if mixed.suffix.lower() == '.m4a':
            wav = output / 'model_input.wav'
            result, elapsed = run([str(tool('ffmpeg')), '-v', 'error', '-nostdin', '-n', '-i', str(mixed),
                                   '-map', '0:a:0', '-vn', '-c:a', 'pcm_s24le', str(wav)], output / 'm4a_to_wav.log')
            if result.returncode or result.stderr.strip():
                raise ValueError('M4A转为模型WAV输入时失败，详见m4a_to_wav.log。')
            mixed = wav
            report.update(action='m4a_to_pcm_wav', conversion_seconds=elapsed)
        if mixed.suffix.lower() in ('.flac', '.wav'):
            report['pcm_check'] = check_pcm_audio(mixed, inventory)
        if sha256(source) != before or sha256(Path(inventory['audio'])) != inventory['audio_sha256']:
            raise ValueError('原音源或已验证音频在预处理期间改变，拒绝继续。')
        report.update(status='verified', processing_audio={'path': str(mixed), 'sha256': sha256(mixed)},
                      duration_seconds=duration, sample_rate=inventory['sample_rate'], channels=inventory['channels'],
                      trim_applied=False, lossy_transcoding_applied=False, source_unchanged=True)
    except Exception as error:
        report.update(status='failed', error=str(error))
    finally:
        report['source_sha256_after'] = sha256(source) if source.is_file() else None
        report['source_unchanged'] = report['source_sha256_after'] == before
        if not report['source_unchanged']:
            report.update(status='failed', error='原音源在预处理期间改变，任务已停止。')
        save_json(output / 'preparation.json', report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True, help='原音源；LRC不能作为音频')
    parser.add_argument('--output', type=Path, required=True, help='不存在的新预处理目录')
    parser.add_argument('--expected-sha256', help='桌面任务登记的原音源摘要')
    parser.add_argument('--max-duration-seconds', type=float, default=900)
    args = parser.parse_args()
    try:
        report = prepare(args.input, args.output, expected_sha256=args.expected_sha256,
                         max_duration_seconds=args.max_duration_seconds)
    except Exception as error:
        print('ValueError: ' + str(error), flush=True)
        return 1
    print(json.dumps(report, ensure_ascii=False), flush=True)
    if report['status'] != 'verified':
        print('ValueError: ' + report['error'], flush=True)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
