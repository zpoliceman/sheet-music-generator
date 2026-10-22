"""Windows窗口的本地任务入口。歌曲和每次修改均独立另存。"""
from __future__ import annotations
import argparse
from contextlib import contextmanager
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import threading
import traceback
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / '.venv-gpu/Scripts/python.exe'
WEB_PYTHON = ROOT / 'HTML/.venv/Scripts/python.exe'
TASKS = ROOT / 'test_outputs/accompaniment_runs/desktop'
STATE = ROOT / 'test_outputs/desktop'
NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
sys.path.insert(0, str(ROOT / 'tools'))
from prepare_audio_input import validate_audio_path
from generation_contracts import (GenerationConflict, check_separation, check_analysis,
                                  check_lyrics, check_melody, check_delivery)


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def read_task(path):
    task = read(path)
    if task.get('status') == 'running' and task.get('active_request'):
        active = Path(task['active_request']).resolve()
        if active.is_relative_to((STATE / 'requests').resolve()):
            try:
                operation = read(active.with_suffix('.status.json'))
                if operation.get('state') in ('failed', 'cancelled', 'needs_review'):
                    task.update(status=operation['state'], error=operation.get('message', ''))
            except (OSError, ValueError):
                pass
    return task


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def task_path(value):
    path = Path(value).resolve(strict=True)
    if not path.is_relative_to(TASKS.resolve()) or path.name != 'task.json':
        raise ValueError('请选择本程序生成的task.json任务文件。')
    return path


def environment():
    env = dict(os.environ)
    env.update(PYTHONIOENCODING='utf-8', PYTHONDONTWRITEBYTECODE='1',
               TORCH_HOME=str(ROOT / '.cache/torch'), HF_HOME=str(ROOT / '.cache/huggingface'))
    ffmpeg = list((ROOT / '.tools/ffmpeg').rglob('ffmpeg.exe'))
    if ffmpeg:
        env['PATH'] = str(ffmpeg[0].parent) + os.pathsep + env.get('PATH', '')
    # 仅为本任务的Git读取允许当前源码及两个已安装外部模型目录。
    env['GIT_CONFIG_COUNT'] = '3'
    for i, path in enumerate((ROOT, ROOT / 'third_party/ROSVOT', ROOT / 'third_party/TIFA')):
        env['GIT_CONFIG_KEY_' + str(i)] = 'safe.directory'
        env['GIT_CONFIG_VALUE_' + str(i)] = path.as_posix()
    return env


class Cancelled(Exception):
    pass


class ReviewNeeded(Exception):
    pass


class Operation:
    STAGE_LIMITS = {1: 180, 2: 1200, 3: 1200, 4: 1800, 5: 1800, 6: 600, 7: 1800}

    def __init__(self, request_path):
        self.path = Path(request_path).resolve()
        self.request = read(self.path)
        self.status_path = self.path.with_suffix('.status.json')
        self.cancel_path = self.path.with_suffix('.cancel')
        self.started = self.stage_started = time.monotonic()
        self.stage_timeout = 120
        self.result = {}
        self.state = {'schema_version': 2, 'state': 'running', 'message': '正在准备…', 'percent': 0,
                      'heartbeat_sequence': 0, 'stage_sequence': 0}
        self.lock = threading.RLock()
        self.stopped = threading.Event()
        self.heartbeat = threading.Thread(target=self._heartbeat, name='desktop-status-heartbeat', daemon=True)
        self.heartbeat.start()

    def _publish(self):
        self.state['heartbeat_sequence'] += 1
        self.state.update(heartbeat_utc=time.time(), elapsed_seconds=round(time.monotonic() - self.started, 2),
                          stage_elapsed_seconds=round(time.monotonic() - self.stage_started, 2),
                          stage_timeout_seconds=self.stage_timeout)
        snapshot = dict(self.state)
        snapshot['result'] = dict(self.result)
        write(self.status_path, snapshot)

    def _heartbeat(self):
        while not self.stopped.wait(1):
            try:
                with self.lock:
                    if self.stopped.is_set():
                        return
                    self._publish()
            except Exception as error:
                print('后台状态写入失败：' + str(error), flush=True)

    def update(self, message, percent=None, **extra):
        self.check_cancel()
        with self.lock:
            self.state.update(message=message, **extra)
            if percent is not None:
                self.state.update(percent=percent, stage=message)
                self.state['stage_sequence'] += 1
                self.stage_started = time.monotonic()
                match = re.match(r'([1-7])/7 ', message)
                self.stage_timeout = self.STAGE_LIMITS[int(match[1])] if match else 600 if '导出' in message else 90 if '网页' in message or '页面' in message else 120
            self._publish()

    def finish(self, state, message, **extra):
        if state == 'complete':
            self.check_cancel()
        with self.lock:
            self.stopped.set()
            self.state.update(state=state, message=message, **extra)
            if state != 'complete':
                self.state['percent'] = 0
            self._publish()

    def close(self):
        self.stopped.set()
        self.heartbeat.join(timeout=.5)

    def check_cancel(self):
        if self.cancel_path.exists():
            raise Cancelled('任务已取消；原始文件和已生成的步骤文件保留。')
        if time.monotonic() - self.stage_started > self.stage_timeout:
            raise TimeoutError('当前步骤超过' + str(self.stage_timeout) + '秒的时间上限；任务已停止，已完成的文件保留。')

    def command(self, arguments, log):
        log = Path(log)
        log.parent.mkdir(parents=True, exist_ok=True)
        self.update(self.state['message'], log_path=str(log))
        with log.open('w', encoding='utf-8') as stream:
            child = subprocess.Popen([str(a) for a in arguments], cwd=ROOT, env=environment(),
                                     stdout=stream, stderr=subprocess.STDOUT, creationflags=NO_WINDOW)
            try:
                while child.poll() is None:
                    self.check_cancel()
                    time.sleep(.25)
            except BaseException:
                if child.poll() is None:
                    if os.name == 'nt':
                        try:
                            subprocess.run(['taskkill', '/PID', str(child.pid), '/T', '/F'],
                                           capture_output=True, creationflags=NO_WINDOW, timeout=2)
                        except subprocess.TimeoutExpired:
                            child.kill()
                    else:
                        child.terminate()
                    try:
                        child.wait(timeout=1)
                    except subprocess.TimeoutExpired:
                        pass  # The desktop's native job supervisor also ends descendants.
                raise
        if child.returncode:
            lines = log.read_text(encoding='utf-8', errors='replace').splitlines()
            for line in reversed(lines):
                if not line.startswith('{'):
                    continue
                try:
                    report = json.loads(line)
                except ValueError:
                    continue
                if report.get('status') == 'needs_review':
                    self.result['review_report'] = report
                    labels = {'notation_level_unresolved': '拍速的快慢层级仍无法确定',
                              'insufficient_independent_grouping_support': '各音轨对小节首拍的支持不足',
                              'grouping_conditional_on_unresolved_level': '首拍分组需要先确定拍速层级',
                              'source_window_unresolved': '部分段落的节拍证据不足',
                              'tail_not_observed': '尾段缺少可靠的拍点'}
                    reasons = list(dict.fromkeys(labels.get(row.get('kind'), '部分音乐需要复核') for row in report.get('issues', [])))
                    raise ReviewNeeded('本次未生成完整吉他谱：' + '；'.join(reasons) + '。\n已保留简谱草稿，可点“查看简谱”。\n详细记录：' + str(log))
            detail = next((line for line in reversed(lines) if line.strip()), '程序没有返回具体说明。')
            detail = re.split(r'：\[|: \[', detail, maxsplit=1)[0]
            raise RuntimeError(detail[:500] + '\n详细记录：' + str(log))

    def contract(self, reports, checker, *arguments):
        self.check_cancel()
        record = Path(reports) / 'pipeline_checks.json'
        document = read(record) if record.is_file() else {'version': 1, 'checks': []}
        try:
            result = checker(*arguments, check_cancel=self.check_cancel)
        except GenerationConflict as error:
            document['checks'].append(error.report)
            write(record, document)
            self.result['conflict_report'] = str(record)
            raise
        document['checks'].append(result)
        write(record, document)
        self.check_cancel()
        return result

    def script(self, name, args, log):
        self.command([PYTHON, '-B', '-X', 'utf8', ROOT / 'tools' / name, *args], log)


@contextmanager
def generation_lock():
    STATE.mkdir(parents=True, exist_ok=True)
    with (STATE / 'generation.lock').open('a+b') as stream:
        stream.seek(0)
        if not stream.read(1):
            stream.write(b'0')
            stream.flush()
        stream.seek(0)
        if os.name == 'nt':
            import msvcrt
            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as error:
                raise ValueError('已有歌曲正在生成。请等该任务结束，避免两首歌同时占用显卡。') from error
        try:
            yield
        finally:
            if os.name == 'nt':
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)


def lyrics_text(path):
    return decode_lyrics(path.read_bytes())


def decode_lyrics(data):
    codecs = ('utf-16',) if data.startswith((b'\xff\xfe', b'\xfe\xff')) else ('utf-8-sig', 'gb18030')
    for codec in codecs:
        try:
            text = data.decode(codec).strip()
            if not text or '\x00' in text:
                raise ValueError('歌词文件为空，或不是可读的TXT文本。')
            return text.replace('\r\n', '\n').replace('\r', '\n') + '\n'
        except UnicodeDecodeError:
            continue
    raise ValueError('歌词编码无法读取，请另存为UTF-8文本后重新选择。')


def generate(op):
    audio = Path(op.request.get('audio', '')).resolve()
    lyrics = Path(op.request.get('lyrics', '')).resolve()
    validate_audio_path(audio)
    if not lyrics.is_file() or lyrics.suffix.lower() != '.txt':
        raise ValueError('请选择存在的TXT歌词文件。')
    if audio.stat().st_size > 500 * 1024 * 1024:
        raise ValueError('音源超过500MB，请选择单首歌曲。')
    lyric_bytes = lyrics.read_bytes()
    text = decode_lyrics(lyric_bytes)
    input_hashes = {'audio': sha(audio), 'lyrics': hashlib.sha256(lyric_bytes).hexdigest()}
    op.check_cancel()
    for required in (PYTHON, WEB_PYTHON, ROOT / 'third_party/ROSVOT/checkpoints/rosvot/model.pt',
                     ROOT / '.cache/tifa/model/TIFA-1.0-ST/model.pt'):
        if not required.is_file():
            raise ValueError('缺少程序环境或模型：' + str(required) + '。请先按README配置。')
    with generation_lock():
        identity = datetime.now().strftime('%Y%m%d_%H%M%S') + '_' + uuid.uuid4().hex[:8]
        folder = TASKS / identity
        folder.mkdir(parents=True, exist_ok=False)
        original = folder / 'inputs' / audio.name
        original.parent.mkdir()
        shutil.copy2(audio, original)
        reference_text = original.parent / 'lyrics.txt'
        reference_text.write_text(text, encoding='utf-8')
        task = {'schema_version': 1, 'id': identity, 'title': audio.stem, 'status': 'running',
                'created': datetime.now().isoformat(timespec='seconds'), 'active_request': str(op.path),
                'inputs': {'audio': str(audio), 'audio_sha256': input_hashes['audio'],
                           'lyrics': str(lyrics), 'lyrics_sha256': input_hashes['lyrics']}, 'folder': str(folder)}
        path = folder / 'task.json'
        write(path, task)
        op.result.update(task_path=str(path), title=task['title'])
        try:
            reports = folder / 'reports'
            reports.mkdir()
            if sha(original) != input_hashes['audio'] or sha(audio) != input_hashes['audio'] or sha(lyrics) != input_hashes['lyrics']:
                raise ValueError('输入文件在读取或复制期间发生变化，请使用稳定的音源和歌词重新生成。')
            op.check_cancel()
            op.update('1/7 识别音源格式并完成预处理', 3)
            audio_workspace = folder / 'audio'
            op.script('prepare_audio_input.py', ['--input', original, '--output', audio_workspace,
                      '--expected-sha256', input_hashes['audio']], reports / '01_audio_preparation.log')
            prepared = read(audio_workspace / 'preparation.json')
            inventory = read(audio_workspace / 'validation.json')
            write(reports / 'audio_validation.json', inventory)
            if prepared['status'] != 'verified' or inventory['status'] != 'verified':
                raise ValueError(prepared.get('error', inventory.get('error', '音源预处理未完成。')))
            mixed = Path(prepared['processing_audio']['path'])
            if sha(mixed) != prepared['processing_audio']['sha256']:
                raise ValueError('预处理音源与报告摘要不同，不能继续分轨。')
            task['audio_preparation'] = {'path': str(audio_workspace / 'preparation.json'),
                                         'sha256': sha(audio_workspace / 'preparation.json')}
            task['processing_audio'] = {'path': str(mixed), 'sha256': sha(mixed)}
            write(path, task)
            demucs = reports / 'demucs.json'
            op.update('2/7 分离原唱和伴奏', 10)
            op.script('check_environment.py', ['--audio', mixed, '--report', demucs, '--output-dir', folder / 'separated'], reports / '02_separation.log')
            op.contract(reports, check_separation, demucs, mixed)
            summary = folder / 'transcription/summary.json'
            op.update('3/7 识别原唱旋律', 28)
            op.script('rosvot_smoke.py', ['--input', folder / 'separated/vocals.wav', '--output-dir', summary.parent], reports / '03_transcription.log')
            analysis = folder / 'refined/analysis.json'
            op.script('refine_transcription.py', ['--input', summary.parent / 'analysis.json', '--output-dir', analysis.parent, '--no-plots'], reports / '03_refinement.log')
            op.contract(reports, check_analysis, analysis, folder / 'separated/vocals.wav')
            aligned = folder / 'lyrics'
            op.update('4/7 读取歌词，定位演唱句子', 40)
            op.script('lyrics_transcribe.py', ['--source-summary', summary, '--output-dir', aligned, '--lyrics-file', reference_text, '--report-dir', reports], reports / '04_lyrics.log')
            reference = aligned / 'lyrics_reference.json'
            language = read(reference)['asr_language']
            anchor = aligned / 'asr_anchor'
            op.script('lyrics_transcribe.py', ['--source-summary', summary, '--output-dir', anchor, '--model', 'medium', '--language', language, '--report-dir', reports / 'anchor'], reports / '04_anchor.log')
            op.contract(reports, check_lyrics, reference, analysis, anchor / 'asr_raw.json')
            op.update('5/7 将歌词逐字对齐原唱', 53)
            op.script('lyrics_align_phrases.py', ['--reference', reference, '--asr-anchor', anchor / 'asr_raw.json', '--analysis', analysis, '--output-dir', aligned, '--report-dir', reports], reports / '05_alignment.log')
            phonemes = aligned / 'characters_phonemes.json'
            op.script('phoneme_evidence.py', ['--characters', aligned / 'characters.json', '--alignment-report', aligned / 'alignment_report.json', '--output', phonemes, '--reference-file', reference], reports / '05_phonemes.log')
            op.contract(reports, check_lyrics, phonemes, analysis, anchor / 'asr_raw.json')
            finish_generation(op, path, task, folder, reports, analysis, phonemes, mixed, demucs)
        except BaseException as error:
            task.update(status='generated' if Path(task.get('project_path') or '').is_file() else 'cancelled' if isinstance(error, Cancelled) else 'needs_review' if isinstance(error, ReviewNeeded) else 'failed', error=str(error))
            write(path, task)
            raise


def finish_generation(op, path, task, folder, reports, analysis, phonemes, mixed, demucs):
    vocal = folder / 'melody'
    op.update('6/7 生成带歌词的简谱', 67)
    op.script('musical_decode.py', ['--notes', analysis, '--lyrics', phonemes, '--audio', mixed, '--output-dir', vocal, '--report', reports / 'score_export.json', '--audio-report', reports / 'audio_analysis.json', '--title', task['title'], '--subdivision', '4'], reports / '06_melody.log')
    op.contract(reports, check_melody, vocal / 'project.json', analysis, phonemes, mixed)
    task['melody_preview'] = op.result['melody_preview'] = str(vocal / 'jianpu.html')
    write(path, task)
    op.update('7/7 分析和弦，生成吉他伴奏及完整试听', 78)
    delivery = folder / 'score'
    op.script('generate_accompaniment.py', ['--vocal-project', vocal / 'project.json', '--demucs-report', demucs, '--analysis-dir', folder / 'arrangement', '--output', delivery, '--guitar-only', '--export-vocal', '--defer-vocal-prototype', '--review-draft'], reports / '07_accompaniment.log')
    project = delivery / 'project.json'
    if not project.is_file() or not (delivery / 'guitar/repeat_plan.json').is_file():
        raise ValueError('生成程序没有产出完整吉他工程，不能报告为成功。')
    task['candidate_project_path'] = str(project)
    write(path, task)
    op.contract(reports, check_delivery, delivery)
    complete_generation(op, path, task, project)


def complete_generation(op, path, task, project):
    for key in ('audio', 'lyrics'):
        source = Path(task['inputs'][key])
        if sha(source) != task['inputs'][key + '_sha256']:
            raise ValueError('处理期间输入文件发生变化，请使用稳定的原文件重试。')
    task.update(status='generated', project_path=str(project), music_review='automatic_draft_requires_listening')
    task.pop('error', None)
    write(path, task)
    op.result.update(project_path=str(project), versions=versions(path))
    op.update('曲谱已生成，正在打开手型编辑页面', 92)
    op.result['editor_url'] = start_editor(path, op)
    if op.request.get('auto_export'):
        export(op, path, project)


def resume(op):
    """Reuse verified model results and write every new score/log into a new attempt."""
    path = task_path(op.request['task_path'])
    task = read_task(path)
    if Path(task.get('project_path', '')).is_file():
        raise ValueError('这个任务已有完整曲谱，请打开预览或直接导出。')
    folder = path.parent
    if Path(task['folder']).resolve() != folder:
        raise ValueError('任务目录记录与实际位置不一致。')
    with generation_lock():
        op.result.update(task_path=str(path), title=task['title'])
        op.update('正在核对已有音源、旋律和歌词对齐结果…', 3)
        for key in ('audio', 'lyrics'):
            source = Path(task['inputs'][key])
            if not source.is_file() or sha(source) != task['inputs'][key + '_sha256']:
                raise ValueError('原' + ('音源' if key == 'audio' else '歌词') + '已移动或修改，请重新选择文件生成新任务。')
        reports = folder / 'reports'
        analysis = folder / 'refined/analysis.json'
        phonemes = folder / 'lyrics/characters_phonemes.json'
        demucs = reports / 'demucs.json'
        inventory_path = reports / 'audio_validation.json'
        if not all(p.is_file() for p in (analysis, phonemes, demucs, inventory_path)):
            raise ValueError('这个任务还没有完成旋律识别和歌词对齐，请用“一键生成曲谱”重新处理。')
        inventory = read(inventory_path)
        decoded = Path(inventory['audio'])
        if inventory.get('status') != 'verified' or inventory.get('source_sha256_after') != task['inputs']['audio_sha256'] or not decoded.is_file() or sha(decoded) != inventory.get('audio_sha256'):
            raise ValueError('已解码音源与原任务不一致，请重新生成。')
        processing = task.get('processing_audio', {'path': str(decoded), 'sha256': inventory['audio_sha256']})
        mixed = Path(processing['path']).resolve()
        if not mixed.is_file() or sha(mixed) != processing['sha256']:
            raise ValueError('实际处理音源已改变，请重新生成。')
        notes, lyrics = read(analysis), read(phonemes)
        source = Path(notes['source']['path'])
        if notes['source'] != lyrics['source'] or not source.is_file() or sha(source) != notes['source']['sha256']:
            raise ValueError('旋律与歌词对齐结果不属于同一个人声音源，请重新生成。')
        separation = read(demucs)['checks']['demucs_short_inference']
        if Path(separation['input']).resolve() != mixed.resolve() or not all(Path(p).is_file() for p in separation['outputs'].values()):
            raise ValueError('已有分轨文件不完整或不属于本次音源，请重新生成。')
        reference = folder / 'inputs/lyrics.txt'
        if not reference.is_file() or reference.read_text(encoding='utf-8').split() != lyrics_text(Path(task['inputs']['lyrics'])).split():
            raise ValueError('已保存歌词与当前TXT不一致，请重新生成。')
        candidate_value = task.get('candidate_project_path')
        if not candidate_value:
            candidate_value = str(Path(task.get('current_attempt', folder)) / 'score/project.json')
        candidate = Path(candidate_value).resolve()
        if not candidate.is_relative_to(folder):
            raise ValueError('未完成曲谱候选位于任务目录之外，拒绝继续。')
        attempt = folder / 'attempts' / (datetime.now().strftime('%Y%m%d_%H%M%S') + '_' + uuid.uuid4().hex[:8])
        attempt.mkdir(parents=True, exist_ok=False)
        new_reports = attempt / 'reports'
        write(new_reports / 'task_before_resume.json', task)
        write(new_reports / 'reused_analysis.json', {str(p): sha(p) for p in (analysis, phonemes, demucs, inventory_path, mixed, source, reference)})
        task.update(status='running', current_attempt=str(attempt), active_request=str(op.path))
        write(path, task)
        try:
            op.contract(new_reports, check_separation, demucs, mixed)
            op.contract(new_reports, check_analysis, analysis, source)
            op.contract(new_reports, check_lyrics, phonemes, analysis)
            if candidate.is_file():
                try:
                    final_check = check_delivery(candidate.parent, check_cancel=op.check_cancel)
                    bound = read(candidate)['shared_analysis']['input_binding']
                    check_melody(bound['vocal_project'], analysis, phonemes, mixed, check_cancel=op.check_cancel)
                except (Cancelled, TimeoutError):
                    raise
                except (GenerationConflict, FileNotFoundError, ValueError, KeyError) as incomplete:
                    write(new_reports / 'candidate_not_reused.json', {'candidate': str(candidate), 'reason': str(incomplete),
                          'old_candidate_unchanged': True, 'next_action': 'generate_new_attempt'})
                else:
                    write(new_reports / 'reused_delivery.json', {'candidate': str(candidate), 'sha256': sha(candidate),
                          'actual_files_check': final_check, 'old_candidate_unchanged': True})
                    op.result['reused_complete_delivery'] = True
                    op.update('完整草稿已核对，恢复预览和导出，无需重复识别', 90)
                    complete_generation(op, path, task, candidate)
                    return
            op.update('前5步已完成，复用已有旋律和歌词对齐结果', 60)
            finish_generation(op, path, task, attempt, new_reports, analysis, phonemes, mixed, demucs)
        except BaseException as error:
            task.update(status='generated' if Path(task.get('project_path') or '').is_file() else 'cancelled' if isinstance(error, Cancelled) else 'needs_review' if isinstance(error, ReviewNeeded) else 'failed', error=str(error))
            write(path, task)
            raise


def versions(path):
    task = read_task(task_path(path))
    result = []
    default = Path(task.get('project_path', ''))
    if default.is_file():
        result.append({'name': '默认右手手型', 'path': str(default)})
    for config in sorted((Path(task['folder']) / 'editor/saved').glob('*/configuration.json'), reverse=True):
        if (config.parent / 'project.json').is_file():
            entry = read(config)
            result.append({'name': entry.get('name', '已保存手型') + ' · ' + config.parent.name, 'path': str(config.parent / 'project.json')})
    return result


def start_editor(path, op):
    path = task_path(path)
    task = read_task(path)
    folder = Path(task['folder'])
    server_file = folder / 'editor/server.json'
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    if server_file.is_file():
        server = read(server_file)
        try:
            with opener.open(server['url'] + 'api/health', timeout=1) as response:
                health = json.load(response)
            if health.get('application') == 'guitar_right_hand_editor' and Path(health.get('workspace', '')).resolve() == (folder / 'editor').resolve():
                return server['url']
        except (OSError, ValueError):
            pass
    editor = folder / 'editor'
    editor.mkdir(exist_ok=True)
    before = server_file.stat().st_mtime_ns if server_file.exists() else None
    with (editor / 'server.log').open('a', encoding='utf-8') as stream:
        child = subprocess.Popen([str(PYTHON), '-B', '-X', 'utf8', str(ROOT / 'tools/guitar_pattern_preview.py'), '--project', task['project_path'], '--workspace', str(editor), '--port', '0'], cwd=ROOT, env=environment(), stdout=stream, stderr=subprocess.STDOUT, creationflags=NO_WINDOW)
    for _ in range(240):
        op.check_cancel()
        if child.poll() is not None:
            raise ValueError('右手网页启动未完成，请查看：' + str(editor / 'server.log'))
        if server_file.is_file() and server_file.stat().st_mtime_ns != before:
            server = read(server_file)
            write(editor / 'process.json', {'pid': child.pid, 'url': server['url'], 'task': str(path)})
            return server['url']
        time.sleep(.25)
    child.terminate()
    raise ValueError('右手网页启动超过一分钟，请查看server.log。')


def export(op, path, project=None):
    task = read(task_path(path))
    kind = op.request.get('format', 'both')
    if kind not in ('both', 'pdf', 'jpg'):
        raise ValueError('导出格式必须是PDF、JPG或两者。')
    allowed = versions(path)
    project = Path(project or op.request.get('project_path', task.get('project_path', ''))).resolve()
    if project not in [Path(item['path']).resolve() for item in allowed]:
        raise ValueError('请选择默认谱或已在网页保存完成的手型版本后导出。')
    destination = Path(op.request.get('destination', '')).expanduser()
    if not str(op.request.get('destination', '')).strip():
        raise ValueError('请先选择曲谱保存文件夹。')
    destination.mkdir(parents=True, exist_ok=True)
    if not destination.is_dir():
        raise ValueError('保存位置不是文件夹。')
    op.update('正在排版并导出PDF和逐页JPG', 95)
    scratch = ROOT / 'HTML/runtime/desktop_exports' / uuid.uuid4().hex
    scratch.mkdir(parents=True)
    log = scratch / 'export.log'
    op.command([WEB_PYTHON, '-B', '-X', 'utf8', ROOT / 'desktop/print_score.py', '--source', project, '--output', scratch / 'files'], log)
    verified = read(scratch / 'files/desktop_export.json')
    if not verified.get('passed'):
        raise ValueError('导出文件检查未通过，请查看：' + str(log))
    title = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', task['title']).strip(' .')[:80] or '曲谱'
    target = destination / (title + '_' + datetime.now().strftime('%Y%m%d_%H%M%S') + '_' + uuid.uuid4().hex[:4])
    target.mkdir(exist_ok=False)

    for item in verified['files']:
        if kind != 'both' and item['kind'] != kind:
            continue
        relative = Path(item['path'])
        source = scratch / 'files' / relative
        output = target / relative
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, output)
        if sha(output) != item['sha256']:
            raise ValueError('保存文件校验失败：' + str(output))
    write(target / '曲谱信息.json', {'title': task['title'], 'source_project': str(project), 'task_path': str(path), 'format': kind, 'created': datetime.now().isoformat(), 'music_review': task.get('music_review')})
    task['last_export'] = str(target)
    write(path, task)
    op.result.update(export_folder=str(target), project_path=str(project), task_path=str(path), title=task['title'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request', type=Path, required=True)
    args = parser.parse_args()
    op = Operation(args.request)
    try:
        op.update('正在准备任务…', 0)
        action = op.request.get('action')
        if action == 'generate':
            generate(op)
        elif action == 'resume':
            resume(op)
        elif action == 'open':
            path = task_path(op.request['task_path'])
            op.result.update(task_path=str(path), title=read(path)['title'], versions=versions(path))
            op.result['editor_url'] = start_editor(path, op)
        elif action == 'export':
            export(op, task_path(op.request['task_path']))
        else:
            raise ValueError('未知操作。')
        op.finish('complete', '已完成', percent=100)
        return 0
    except BaseException as error:
        state = 'cancelled' if isinstance(error, Cancelled) else 'needs_review' if isinstance(error, ReviewNeeded) else 'failed'
        stage = op.state.get('stage', '')
        message = str(error) or '任务进程没有返回具体说明，请查看详细记录。'
        detail = message.splitlines()[0]
        detail = re.sub(r'^(?:ValueError|RuntimeError|OSError|GenerationConflict|RhythmConflict|CapoConflict):\s*', '', detail)
        if '乐句末音无可用完整节奏候选' in detail or '乐句节奏候选冲突' in detail:
            detail = '部分歌词与音符的节奏边界无法确定，已完成的识别结果保留。'
        prefix = '已取消' if state == 'cancelled' else '需要校对' if state == 'needs_review' else '已停止'
        op.finish(state, message, summary=prefix + '：' + (stage + '。' if stage else '') + detail)
        op.path.with_suffix('.failure.txt').write_text(traceback.format_exc(), encoding='utf-8')
        return 1
    finally:
        op.close()


if __name__ == '__main__':
    raise SystemExit(main())
