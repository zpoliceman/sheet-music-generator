# 兼容性与样曲验证：新增一次性源码修订器，原有被替换代码全部注释保留。
from pathlib import Path
path = Path('tools/audio_inventory.py')
text = path.read_text(encoding='utf-8-sig')
text = text.replace('import time\n', 'import time\n# 兼容性与样曲验证：新增 WAV 实际帧数和 UTF-8 标准输出支持。\nimport wave\nimport sys\nif hasattr(sys.stdout, "reconfigure"):\n    sys.stdout.reconfigure(encoding="utf-8")\n', 1)
start = text.index('def process(')
end = text.index('# 兼容性与样曲验证：新增明确偏移', start)
old = text[start:end]
new = r'''# 兼容性与样曲验证：修改素材处理；缓存同时绑定源哈希和产物哈希，新转换验证后再发布。
def process(source: Path, ncmdump: Path, ffprobe: Path, ffmpeg: Path) -> dict:
    logs = ROOT / 'test_outputs' / 'probe'
    output_dir = ROOT / 'test_outputs' / 'converted'
    output_dir.mkdir(parents=True, exist_ok=True)
    record = {'source': str(source), 'filename': source.name, 'conversion_seconds': 0.0, 'status': 'pending'}
    before = None
    pending_publish = False
    cache_path = output_dir / '.conversion_manifest.json'
    cache = {'version': 1, 'entries': {}}
    try:
        # 兼容性与样曲验证：修改源读取失败处理，文件不可读也返回失败记录。
        record['source_bytes'] = source.stat().st_size
        before = sha256(source)
        record['source_sha256_before'] = before
        audio = source
        if source.suffix.lower() == '.ncm':
            with source.open('rb') as stream:
                if stream.read(8) != b'CTENFDAM':
                    raise ValueError('文件扩展名为 NCM，但文件头不匹配')
            if cache_path.exists():
                cache = json.loads(cache_path.read_text(encoding='utf-8'))
                if cache.get('version') != 1 or not isinstance(cache.get('entries'), dict):
                    raise ValueError('转换缓存清单格式无效')
            entry = cache['entries'].get(str(source.resolve()), {})
            cached_audio = Path(entry.get('audio', ''))
            # 兼容性与样曲验证：新增缓存目录/文件名限制，避免清单指向项目外文件。
            cache_valid = (entry.get('source_sha256') == before and cached_audio.is_file()
                           and cached_audio.resolve().is_relative_to(output_dir.resolve())
                           and cached_audio.stem == source.stem and cached_audio.suffix in {'.flac', '.mp3'}
                           and entry.get('audio_sha256') == sha256(cached_audio))
            if cache_valid:
                audio = cached_audio
                record['conversion_cached'] = True
            else:
                # 兼容性与样曲验证：新增唯一暂存目录，失败产物不会成为有效缓存。
                staging = output_dir / '.staging' / f'{before[:16]}_{time.time_ns()}'
                staging.mkdir(parents=True, exist_ok=False)
                conversion, elapsed = run([str(ncmdump), str(source), '-o', str(staging)], logs / (source.stem + '.conversion.log'))
                record.update(conversion_seconds=elapsed, conversion_exit_code=conversion.returncode,
                              conversion_cached=False)
                if conversion.returncode:
                    raise RuntimeError(f'NCM 还原返回码 {conversion.returncode}')
                candidates = [staging / (source.stem + suffix) for suffix in ('.flac', '.mp3')]
                existing = [item for item in candidates if item.is_file()]
                if len(existing) != 1:
                    raise RuntimeError(f'转换产物数量不明确：{len(existing)}')
                audio = existing[0]
                pending_publish = True
        record['audio'] = str(audio)
        record['audio_bytes'] = audio.stat().st_size
        record['audio_sha256'] = sha256(audio)
        probe, probe_seconds = run([str(ffprobe), '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(audio)], logs / (source.stem + '.ffprobe.json'))
        record['probe_seconds'] = probe_seconds
        if probe.returncode:
            raise RuntimeError(f'ffprobe 返回码 {probe.returncode}')
        metadata = json.loads(probe.stdout)
        audio_streams = [stream for stream in metadata.get('streams', []) if stream.get('codec_type') == 'audio']
        if not audio_streams:
            raise RuntimeError('未找到音频流')
        stream = audio_streams[0]
        audio_format = metadata.get('format', {})
        duration = float(audio_format.get('duration', stream.get('duration', 0)))
        record.update({'codec': stream.get('codec_name'), 'container': audio_format.get('format_name'),
                       'duration_seconds': duration, 'sample_rate': int(stream.get('sample_rate', 0)),
                       'channels': stream.get('channels'), 'channel_layout': stream.get('channel_layout'),
                       'sample_format': stream.get('sample_fmt'), 'bits_per_raw_sample': stream.get('bits_per_raw_sample'),
                       'audio_stream_bit_rate': stream.get('bit_rate'), 'container_bit_rate': audio_format.get('bit_rate'),
                       'live_filename': 'live' in source.stem.lower(), 'over_five_minutes': duration > 300})
        decode, decode_seconds = run([str(ffmpeg), '-v', 'error', '-nostdin', '-i', str(audio), '-map', '0:a:0', '-f', 'null', '-'], logs / (source.stem + '.decode.log'))
        record.update({'decode_exit_code': decode.returncode, 'decode_seconds': decode_seconds,
                       'decode_errors': decode.stderr.decode('utf-8', errors='replace').strip()})
        if decode.returncode or record['decode_errors']:
            raise RuntimeError('完整解码返回错误，详见独立日志')
        if duration <= 0 or record['sample_rate'] <= 0:
            raise ValueError('音频时长或采样率无效')
        if sha256(source) != before:
            raise RuntimeError('源文件在验证过程中改变，不发布转换产物')
        if pending_publish:
            # 兼容性与样曲验证：新增旧生成产物留档及验证后发布，原始 NCM 不参与移动。
            target = output_dir / audio.name
            if target.exists():
                previous_hash = sha256(target)
                backup = output_dir / '.superseded' / f'{target.stem}.{previous_hash[:16]}{target.suffix}'
                backup.parent.mkdir(parents=True, exist_ok=True)
                if not backup.exists():
                    target.replace(backup)
            audio.replace(target)
            audio = target
            record['audio'] = str(audio)
        if source.suffix.lower() == '.ncm':
            cache['entries'][str(source.resolve())] = {'source_sha256': before, 'audio': str(audio.resolve()),
                                                     'audio_sha256': record['audio_sha256'], 'status': 'verified'}
            temporary_manifest = cache_path.with_suffix('.json.tmp')
            save_json(temporary_manifest, cache)
            temporary_manifest.replace(cache_path)
        record['status'] = 'verified'
    except Exception as error:
        record['status'] = 'failed'
        record['error'] = f'{type(error).__name__}: {error}'
    finally:
        # 兼容性与样曲验证：修改最终哈希失败处理，保留明确失败证据而不中断整批记录。
        try:
            record['source_sha256_after'] = sha256(source)
            record['source_unchanged'] = before is not None and before == record['source_sha256_after']
            if not record['source_unchanged']:
                record['status'] = 'failed'
                record.setdefault('error', '源文件哈希发生变化或初次读取失败')
        except Exception as error:
            record.update(status='failed', source_unchanged=False,
                          final_hash_error=f'{type(error).__name__}: {error}')
    return record

'''
text = text[:start] + '# 兼容性与样曲验证：修改缓存与失败处理，以下原处理函数注释保留。\n' + ''.join('# ' + line + '\n' for line in old.splitlines()) + '\n' + new + text[end:]
start = text.index('def make_sample(')
end = text.index('# 兼容性与样曲验证：新增先单首', start)
old = text[start:end]
new = r'''# 兼容性与样曲验证：修改片段生成；验证实际帧数、绑定输入/参数/产物哈希并支持幂等复用。
def make_sample(record: dict, ffmpeg: Path, start: float, duration: float) -> dict:
    if record['status'] != 'verified':
        raise ValueError('仅可从完整解码通过的素材生成测试片段')
    if start < 0 or duration <= 0 or start + duration > record['duration_seconds']:
        raise ValueError('片段范围超出音频时长')
    if sha256(Path(record['audio'])) != record['audio_sha256']:
        raise ValueError('输入音频哈希与完整解码记录不一致')
    sample_dir = ROOT / 'test_outputs' / 'samples'
    sample_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = ROOT / 'reports' / 'sample_manifest.json'
    parameters = f"{record['audio_sha256']}:{start:.9f}:{duration:.9f}:44100:2:pcm_s16le"
    key = hashlib.sha256(parameters.encode()).hexdigest()[:16]
    previous = json.loads(manifest_path.read_text(encoding='utf-8')) if manifest_path.exists() else {}
    # 兼容性与样曲验证：新增真实 WAV 属性读取，清单时长由实际帧数计算。
    def wav_properties(path: Path) -> dict:
        with wave.open(str(path), 'rb') as wav:
            return {'frames': wav.getnframes(), 'sample_rate': wav.getframerate(),
                    'channels': wav.getnchannels(), 'sample_width_bytes': wav.getsampwidth(),
                    'duration_seconds': wav.getnframes() / wav.getframerate()}
    candidate = Path(previous.get('sample', ''))
    matches = (previous.get('source_audio_sha256') == record['audio_sha256']
               and previous.get('start_seconds_in_song') == start
               and previous.get('duration_seconds') == duration
               and candidate.is_file() and candidate.resolve().is_relative_to(sample_dir.resolve())
               and previous.get('sample_sha256') == sha256(candidate))
    if matches:
        actual = wav_properties(candidate)
        matches = (actual['sample_rate'] == 44100 and actual['channels'] == 2
                   and actual['sample_width_bytes'] == 2 and abs(actual['duration_seconds'] - duration) <= 1 / 44100)
        if matches:
            previous.update(actual_wav=actual, extraction_cached=True, requested_duration_seconds=duration)
            save_json(manifest_path, previous)
            return previous
    staging = sample_dir / f'.sample_{key}_{time.time_ns()}.wav'
    # 兼容性与样曲验证：新增输入后定位并解码丢弃前段，失败临时 WAV 不阻止后续重试。
    result, elapsed = run([str(ffmpeg), '-v', 'error', '-nostdin', '-n', '-i', record['audio'], '-ss', str(start),
                           '-t', str(duration), '-map', '0:a:0', '-ac', '2', '-ar', '44100', '-c:a', 'pcm_s16le', str(staging)],
                          ROOT / 'test_outputs' / 'probe' / 'sample_extract.log')
    if result.returncode:
        raise RuntimeError('测试片段提取失败，临时产物保留用于排查且不作为有效样本')
    actual = wav_properties(staging)
    if actual['sample_rate'] != 44100 or actual['channels'] != 2 or actual['sample_width_bytes'] != 2 or abs(actual['duration_seconds'] - duration) > 1 / 44100:
        raise ValueError('WAV 实际属性或帧数与请求不一致')
    output = sample_dir / f'sample_{key}.wav'
    if output.exists() and sha256(output) != sha256(staging):
        output = sample_dir / f'sample_{key}_{time.time_ns()}.wav'
    staging.replace(output)
    manifest = {'source': record['source'], 'audio': record['audio'], 'source_audio_sha256': record['audio_sha256'],
                'sample': str(output), 'sample_sha256': sha256(output), 'start_seconds_in_song': start,
                'requested_duration_seconds': duration, 'duration_seconds': actual['duration_seconds'],
                'sample_rate': 44100, 'channels': 2, 'actual_wav': actual,
                'elapsed_seconds': elapsed, 'extraction_cached': False,
                'purpose': '真实音频兼容性片段，不代表整首或质量验收通过'}
    save_json(manifest_path, manifest)
    return manifest

'''
text = text[:start] + '# 兼容性与样曲验证：修改片段幂等与实测时长，以下原函数注释保留。\n' + ''.join('# ' + line + '\n' for line in old.splitlines()) + '\n' + new + text[end:]
old = '        records.append(record)\n'
new = '''        # 兼容性与样曲验证：新增逐首进度落盘，单首异常不会丢失已完成证据。
        records.append(record)
        save_json(ROOT / 'reports' / 'audio_inventory.in_progress.json', {'records': records, 'complete': False})
'''
text = text.replace(old, '        # 兼容性与样曲验证：修改逐首记录，原追加行注释保留。\n        # records.append(record)\n' + new, 1)
path.write_text(text, encoding='utf-8')
print('cache, failure handling and sample repair saved; original code retained as comments')
