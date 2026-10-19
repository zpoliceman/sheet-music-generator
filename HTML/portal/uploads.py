"""校验并保存一套素材，不调用现有制谱或全局缓存入口。"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile

HTML_ROOT = Path(__file__).resolve().parents[1]
AUDIO_LIMIT = 80 * 1024 * 1024
LYRICS_LIMIT = 256 * 1024
BODY_LIMIT = AUDIO_LIMIT + LYRICS_LIMIT + 1024 * 1024

class InvalidUpload(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status

def original_name(upload):
    name = (upload.filename or '').replace('\\', '/').split('/')[-1]
    if not name or len(name) > 220 or any(ord(char) < 32 for char in name):
        raise InvalidUpload('文件名为空、过长或包含无法使用的字符。')
    return name

def find_ffprobe():
    candidates = sorted((HTML_ROOT.parent / '.tools' / 'ffmpeg').glob('*/bin/ffprobe.exe'))
    if candidates:
        return candidates[0]
    executable = shutil.which('ffprobe')
    return Path(executable) if executable else None

def probe_mp3(path):
    tool = find_ffprobe()
    if not tool:
        raise InvalidUpload('网站的音源检查工具尚未就绪，请联系网站主人。', 503)
    command = [str(tool), '-v', 'error', '-protocol_whitelist', 'file,pipe', '-format_whitelist', 'mp3',
               '-show_entries', 'format=duration:stream=codec_type,codec_name', '-of', 'json', str(path)]
    try:
        process = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20,
                                 creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        result = json.loads(process.stdout.decode('utf-8'))
        streams = result.get('streams', [])
        duration = float(result.get('format', {}).get('duration', 0))
        if process.returncode or not any(s.get('codec_type') == 'audio' and s.get('codec_name') == 'mp3' for s in streams) or not 0 < duration <= 300:
            raise ValueError('invalid audio')
        return round(duration, 3)
    except (ValueError, OSError, subprocess.TimeoutExpired):
        raise InvalidUpload('无法读取这份MP3，或歌曲超过5分钟。请检查音源后重新上传。') from None

def decode_lyrics(raw):
    if b'\x00' in raw:
        raise InvalidUpload('歌词不是可读取的文本，请保存为UTF-8格式的TXT。')
    for encoding in ('utf-8-sig', 'gb18030'):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise InvalidUpload('歌词编码无法读取，请保存为UTF-8格式的TXT。')
    if not text.strip() or not any(char.isalpha() for char in text):
        raise InvalidUpload('歌词内容为空或没有可识别的歌词文字。')
    if any(ord(char) < 32 and char not in '\r\n\t' for char in text) or '\ufffd' in text:
        raise InvalidUpload('歌词包含无法识别的字符，请检查TXT文件。')
    return text.replace('\r\n', '\n').replace('\r', '\n'), 'UTF-8' if encoding == 'utf-8-sig' else 'GB18030'

def safe_remove(directory, root):
    directory = directory.resolve()
    root = root.resolve()
    if not directory.is_relative_to(root) or len(directory.relative_to(root).parts) < 2 or not re.fullmatch('[a-f0-9]{32}', directory.name):
        raise RuntimeError('拒绝清理非本次上传目录。')
    if directory.exists():
        shutil.rmtree(directory)

async def save_stream(upload, target, limit):
    count = 0
    hasher = hashlib.sha256()
    with target.open('xb') as output:
        while chunk := await upload.read(256 * 1024):
            count += len(chunk)
            if count > limit:
                raise InvalidUpload('音源不能超过80MB，歌词不能超过256KB。', 413)
            output.write(chunk)
            hasher.update(chunk)
    if count == 0:
        raise InvalidUpload('不能上传空文件。')
    return count, hasher.hexdigest()

async def receive_upload(store, person, form):
    items = list(form.multi_items())
    if len(items) != 2 or set(key for key, _ in items) != {'audio', 'lyrics'} or not all(isinstance(value, UploadFile) for _, value in items):
        raise InvalidUpload('请同时选择一份MP3或NCM音源，以及一份TXT歌词。')
    if store.usage(person['id'])['count'] >= 50:
        raise InvalidUpload('已达到本次试用的50套素材上限，请联系网站主人。', 429)
    audio, lyrics = form['audio'], form['lyrics']
    audio_name, lyrics_name = original_name(audio), original_name(lyrics)
    suffix = Path(audio_name).suffix.lower()
    if suffix not in ('.mp3', '.ncm') or Path(lyrics_name).suffix.lower() != '.txt':
        raise InvalidUpload('音源仅支持MP3或NCM，歌词请选择TXT文件。')
    if (audio.size or 0) > AUDIO_LIMIT or (lyrics.size or 0) > LYRICS_LIMIT:
        raise InvalidUpload('音源不能超过80MB，歌词不能超过256KB。', 413)
    expected_size = (audio.size or 0) + (lyrics.size or 0)
    if shutil.disk_usage(store.root).free < expected_size + 100 * 1024 * 1024:
        raise InvalidUpload('网站可用空间不足，请联系网站主人。', 507)
    identity = uuid.uuid4().hex
    staging = store.upload_root / '.incoming' / identity
    person_root = store.upload_root / person['id']
    final = person_root / identity
    if not staging.resolve().is_relative_to(store.upload_root.resolve()) or not final.resolve().is_relative_to(store.upload_root.resolve()):
        raise RuntimeError('上传目录检查失败。')
    staging.mkdir(exist_ok=False)
    published = False
    try:
        audio_path = staging / ('audio' + suffix)
        audio_size, audio_hash = await save_stream(audio, audio_path, AUDIO_LIMIT)
        lyric_size, lyric_hash = await save_stream(lyrics, staging / 'lyrics.original.txt', LYRICS_LIMIT)
        text, encoding = decode_lyrics((staging / 'lyrics.original.txt').read_bytes())
        (staging / 'lyrics.txt').write_text(text, encoding='utf-8', newline='\n')
        duration = None
        if suffix == '.ncm':
            with audio_path.open('rb') as stream:
                if audio_size < 32 or stream.read(8) != b'CTENFDAM':
                    raise InvalidUpload('这份NCM的文件头不匹配，请检查音源或改用MP3。')
            validation = 'container_header_only'
        else:
            duration = await run_in_threadpool(probe_mp3, audio_path)
            validation = 'mp3_metadata_checked'
        metadata = {'id': identity, 'title': Path(audio_name).stem, 'created': time.time(),
                    'status': 'uploaded', 'status_label': '素材已保存', 'generation_available': False,
                    'audio': {'name': audio_name, 'format': suffix[1:].upper(), 'bytes': audio_size,
                              'sha256': audio_hash, 'duration_seconds': duration, 'validation': validation},
                    'lyrics': {'name': lyrics_name, 'bytes': lyric_size, 'sha256': lyric_hash,
                               'encoding': encoding, 'characters': len(text)},
                    'lyrics_preview': text[:20000]}
        (staging / 'upload.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8')
        person_root.mkdir(exist_ok=True)
        os.replace(staging, final)
        try:
            store.publish(person['id'], metadata)
        except PermissionError as error:
            raise InvalidUpload(str(error), 401) from None
        except ValueError as error:
            raise InvalidUpload(str(error), 429) from None
        published = True
        return metadata
    finally:
        if staging.exists():
            safe_remove(staging, store.upload_root)
        if not published and final.exists():
            safe_remove(final, store.upload_root)
