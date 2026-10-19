"""启动本轮网页与免费分享进程；只停止PID、创建时间和命令均匹配的进程。"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
import psutil

ROOT = Path(__file__).resolve().parent
RUNTIME = ROOT / 'runtime'
STATE = RUNTIME / 'service.json'
LOGS = RUNTIME / 'logs'
APP_ROOT = RUNTIME / 'app'
APP_ID = 'sheet_music_upload_portal'

class LaunchError(RuntimeError):
    pass

def read_json(path):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}

def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.new')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)

def fetch(url, timeout=4):
    request = urllib.request.Request(url, headers={'User-Agent': 'sheet-music-upload-portal/0.1', 'Cache-Control': 'no-cache'})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)

def health(port):
    try:
        result = fetch(f'http://127.0.0.1:{port}/api/health', 2)
        return result.get('application') == APP_ID and result.get('instance') == hashlib.sha256(str(ROOT.resolve()).casefold().encode()).hexdigest()[:16]
    except (OSError, ValueError):
        return False

def occupied(port):
    with socket.socket() as connection:
        connection.settimeout(1)
        return connection.connect_ex(('127.0.0.1', port)) == 0

def managed_process(record, kind):
    if not record or record.get('kind') != kind:
        return None
    try:
        process = psutil.Process(record['pid'])
        if abs(process.create_time() - record['created']) > 0.1:
            return None
        expected = ROOT / 'server.py' if kind == 'server' else ROOT / 'bin' / 'cloudflared.exe'
        arguments = process.cmdline()
        if not any(Path(part).resolve() == expected.resolve() for part in arguments if part and not part.startswith('--')):
            return None
        return process if process.is_running() else None
    except (psutil.Error, KeyError, OSError, ValueError):
        return None

def spawn(command, kind):
    LOGS.mkdir(parents=True, exist_ok=True)
    output_path = LOGS / (kind + '.stdout.log')
    error_path = LOGS / (kind + '.stderr.log')
    offsets = {str(path): path.stat().st_size if path.exists() else 0 for path in (output_path, error_path)}
    options = {'cwd': str(ROOT), 'stdin': subprocess.DEVNULL, 'close_fds': True,
               'env': {**os.environ, 'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONIOENCODING': 'utf-8'}}
    options['env']['TMP'] = str(APP_ROOT / 'tmp')
    options['env']['TEMP'] = str(APP_ROOT / 'tmp')
    (APP_ROOT / 'tmp').mkdir(parents=True, exist_ok=True)
    if os.name == 'nt':
        options['creationflags'] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        options['start_new_session'] = True
    with output_path.open('ab') as output, error_path.open('ab') as error:
        options.update(stdout=output, stderr=error)
        try:
            flags = options.get('creationflags', 0)
            process = subprocess.Popen(command, **{**options, 'creationflags': flags | subprocess.CREATE_BREAKAWAY_FROM_JOB}) if os.name == 'nt' else subprocess.Popen(command, **options)
        except OSError as failure:
            if os.name != 'nt' or failure.winerror != 5:
                raise
            process = subprocess.Popen(command, **options)
    return {'kind': kind, 'pid': process.pid, 'created': psutil.Process(process.pid).create_time(), 'log_offsets': offsets}

def log_tail(record):
    chunks = []
    for name, offset in record.get('log_offsets', {}).items():
        path = Path(name)
        if path.is_file() and path.resolve().is_relative_to(LOGS.resolve()):
            with path.open('rb') as stream:
                stream.seek(offset)
                chunks.append(stream.read().decode('utf-8', errors='replace'))
    return '\n'.join(chunks)

def stop_owned(record, kind):
    process = managed_process(record, kind)
    if process:
        expected = (ROOT / 'server.py' if kind == 'server' else ROOT / 'bin' / 'cloudflared.exe').resolve()
        owned = []
        for child in process.children(recursive=True):
            try:
                if any(Path(part).resolve() == expected for part in child.cmdline() if part and not part.startswith('--')):
                    owned.append(child)
            except (psutil.Error, OSError, ValueError):
                continue
        for target in reversed(owned + [process]):
            try:
                target.terminate()
                target.wait(timeout=8)
            except psutil.TimeoutExpired:
                target.kill()
                target.wait(timeout=4)
            except psutil.NoSuchProcess:
                pass
        return True
    return False

def ensure_server(port, state):
    if health(port):
        state['port'] = port
        return
    if occupied(port):
        raise LaunchError(f'本机{port}端口被其他程序占用，未停止该程序。')
    python = ROOT / '.venv' / 'Scripts' / ('pythonw.exe' if os.name == 'nt' else 'python')
    if not python.is_file():
        raise LaunchError('缺少HTML内独立环境，请先运行准备环境.ps1。')
    print('正在启动本机统一网页…', flush=True)
    state['server'] = spawn([str(python), '-B', '-X', 'utf8', str(ROOT / 'server.py'), '--port', str(port)], 'server')
    state['port'] = port
    write_json(STATE, state)
    deadline = time.monotonic() + 35
    while time.monotonic() < deadline:
        if health(port):
            return
        if not managed_process(state['server'], 'server'):
            raise LaunchError('网页进程退出，请查看HTML/runtime/logs中的server日志。')
        time.sleep(0.5)
    raise LaunchError('网页尚未就绪，请查看HTML/runtime/logs中的server日志。')

def publish_share(url):
    write_json(APP_ROOT / 'sharing.json', {'url': url, 'checked': time.time(), 'provider': 'cloudflare_quick_tunnel'})
    invitation = RUNTIME / '朋友试用邀请.txt'
    if invitation.is_file():
        note = invitation.read_text(encoding='utf-8')
        note = re.sub(r'(?m)^网址：.*$', '网址：' + url, note)
        invitation.write_text(note, encoding='utf-8')

def ensure_share(port, state):
    record = state.get('tunnel')
    if managed_process(record, 'tunnel'):
        url = state.get('public_url', '')
        try:
            if url and fetch(url + '/api/health', 8).get('application') == APP_ID:
                publish_share(url)
                return url
        except (OSError, ValueError):
            pass
        stop_owned(record, 'tunnel')
    binary = ROOT / 'bin' / 'cloudflared.exe'
    release = read_json(ROOT / 'bin' / 'cloudflared.release.json')
    if not binary.is_file() or not release.get('verified') or hashlib.sha256(binary.read_bytes()).hexdigest() != release.get('sha256'):
        raise LaunchError('免费分享工具缺失或摘要不匹配，请运行scripts/download_share.py。')
    print('正在申请免费分享网址并检查外网响应…', flush=True)
    record = spawn([str(binary), 'tunnel', '--no-autoupdate', '--url', f'http://127.0.0.1:{port}',
                    '--protocol', 'http2', '--edge-ip-version', '4', '--metrics', '127.0.0.1:0'], 'tunnel')
    state['tunnel'] = record
    write_json(STATE, state)
    url = ''
    deadline = time.monotonic() + 110
    next_probe = 0
    while time.monotonic() < deadline:
        if not managed_process(record, 'tunnel'):
            raise LaunchError('分享进程退出，请查看tunnel日志；本机网页仍可使用。')
        for candidate in re.findall(r'https://[a-z0-9-]+\.trycloudflare\.com', log_tail(record)):
            if urlsplit_hostname(candidate) != 'api.trycloudflare.com':
                url = candidate
        if url and time.monotonic() >= next_probe:
            next_probe = time.monotonic() + 3
            try:
                if fetch(url + '/api/health', 6).get('application') == APP_ID:
                    state['public_url'] = url
                    write_json(STATE, state)
                    publish_share(url)
                    return url
            except (OSError, ValueError):
                pass
        time.sleep(1)
    state['public_url'] = url
    write_json(STATE, state)
    raise LaunchError('分享进程仍在连接，尚未取得可验证的外网响应。本机网页可用，请查看tunnel日志后重试。')

def urlsplit_hostname(url):
    from urllib.parse import urlsplit
    return urlsplit(url).hostname

def main():
    parser = argparse.ArgumentParser(description='启动或停止统一网页及免费分享')
    parser.add_argument('--share', action='store_true')
    parser.add_argument('--open', action='store_true')
    parser.add_argument('--stop', action='store_true')
    parser.add_argument('--port', type=int, default=8768)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error('端口必须介于1024和65535之间。')
    RUNTIME.mkdir(exist_ok=True)
    state = read_json(STATE)
    if args.stop:
        stopped = [kind for key, kind in (('tunnel', 'tunnel'), ('server', 'server')) if stop_owned(state.get(key), kind)]
        write_json(APP_ROOT / 'sharing.json', {})
        write_json(STATE, {})
        print('已停止本轮启动器管理的进程：' + ('、'.join(stopped) if stopped else '没有仍在运行的对应进程。'))
        return 0
    try:
        ensure_server(args.port, state)
        local = f'http://127.0.0.1:{args.port}/'
        print('本机网页：' + local, flush=True)
        if args.share:
            url = ensure_share(args.port, state)
            print('朋友访问网址：' + url, flush=True)
        print('管理员访问码：HTML/runtime/app/管理员访问码.txt', flush=True)
        if args.open:
            webbrowser.open(local)
        return 0
    except (LaunchError, OSError, ValueError) as error:
        print(str(error), file=sys.stderr, flush=True)
        if args.open and health(args.port):
            webbrowser.open(f'http://127.0.0.1:{args.port}/')
        return 1

if __name__ == '__main__':
    raise SystemExit(main())
