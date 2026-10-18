"""网页连接恢复与独立启动：启动本机编辑服务，确认网页可用后打开浏览器。"""
# 网页连接恢复与独立启动：新增独立进程启动器，关闭启动窗口不会同时关闭曲谱服务。
from pathlib import Path
import argparse
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser

from workspace_location import same_workspace


ROOT = Path(__file__).resolve().parents[1]
APPLICATION = 'guitar_right_hand_editor'


class LaunchError(RuntimeError):
    # 网页连接恢复与独立启动：新增可直接展示给用户的启动错误。
    pass


def health_ready(port):
    # 网页连接恢复与独立启动：只核对本机编辑器的健康接口，绕过系统代理。
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(f'http://127.0.0.1:{port}/api/health', timeout=1) as response:
            # 工作目录改名兼容：读取服务实际目录，避免错误复用另一个工程的编辑器。
            return same_workspace(json.loads(response.read(4096)), ROOT)
    except (OSError, ValueError, AttributeError, urllib.error.URLError):
        return False


def port_occupied(port):
    # 网页连接恢复与独立启动：新增其它程序占端口的检查，不终止任何已有进程。
    try:
        with socket.create_connection(('127.0.0.1', port), timeout=0.5):
            return True
    except OSError:
        return False


def spawn_server(port, logs):
    # 网页连接恢复与独立启动：新增独立日志，服务仍由原入口找回上次编辑目录。
    logs = Path(logs)
    logs.mkdir(parents=True, exist_ok=True)
    executable = Path(sys.executable)
    options = {'cwd': str(ROOT), 'stdin': subprocess.DEVNULL, 'close_fds': True}
    if os.name == 'nt':
        executable = executable.with_name('pythonw.exe')
        if not executable.is_file():
            raise LaunchError(f'找不到后台运行程序：{executable}')
        options['creationflags'] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        # 网页连接恢复与独立启动：优先脱离启动工具的进程组；系统不允许时使用普通独立进程。
        breakaway = subprocess.CREATE_BREAKAWAY_FROM_JOB
    else:
        options['start_new_session'] = True
        breakaway = 0
    command = [str(executable), '-B', '-X', 'utf8', str(ROOT/'tools/guitar_pattern_preview.py'), '--port', str(port)]
    with (logs/'server.stdout.log').open('ab') as output, (logs/'server.stderr.log').open('ab') as error:
        offset = error.tell()
        options.update(stdout=output, stderr=error)
        try:
            process = subprocess.Popen(command, **{**options, 'creationflags': options['creationflags'] | breakaway}) if breakaway else subprocess.Popen(command, **options)
        except OSError as exc:
            if not breakaway or exc.winerror != 5:
                raise
            process = subprocess.Popen(command, **options)
    return process, offset


def launch_service(port=8766, timeout=30, logs=None):
    # 网页连接恢复与独立启动：新增先复用、再启动、最后等待真实健康响应的顺序。
    if not 1 <= port <= 65535 or timeout <= 0:
        raise LaunchError('端口必须介于1和65535之间，等待时间必须大于0。')
    url = f'http://127.0.0.1:{port}/'
    if health_ready(port):
        return {'url': url, 'started': False}
    if port_occupied(port):
        # 网页连接恢复与独立启动：再次核对并发启动的编辑器，避免误报刚就绪的服务。
        if health_ready(port):
            return {'url': url, 'started': False}
        raise LaunchError(f'本机{port}端口已被其它程序占用，右手编辑器尚未就绪。请查看该端口的程序。')
    logs = Path(logs) if logs is not None else ROOT/'test_outputs/accompaniment_runs/right_hand_editor_service'
    process, offset = spawn_server(port, logs)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if health_ready(port):
            return {'url': url, 'started': True, 'pid': process.pid, 'logs': str(logs)}
        if process.poll() is not None:
            # 网页连接恢复与独立启动：新增本次失败日志摘要，不把往次错误误报为本次原因。
            error_path = logs/'server.stderr.log'
            with error_path.open('rb') as error:
                error.seek(max(offset, error_path.stat().st_size - 4000))
                details = error.read().decode('utf-8', errors='replace').strip()
            raise LaunchError(f'右手编辑服务启动后退出，网页尚不可用。错误日志：{error_path}' + (f'\n{details}' if details else ''))
        time.sleep(0.2)
    raise LaunchError(f'右手编辑服务在{timeout:g}秒内未就绪。请查看{logs}中的日志，再重新运行启动器。')


def main(argv=None):
    # 网页连接恢复与独立启动：新增命令行入口，健康检查失败时不打开无法访问的网页。
    parser = argparse.ArgumentParser(description='启动并打开本机右手编辑器')
    parser.add_argument('--port', type=int, default=8766)
    parser.add_argument('--timeout', type=float, default=30)
    parser.add_argument('--no-open', action='store_true', help='检查或启动服务，但不另开浏览器')
    args = parser.parse_args(argv)
    try:
        result = launch_service(args.port, args.timeout)
    except (LaunchError, OSError) as exc:
        print(f'右手编辑器未能打开：{exc}', file=sys.stderr)
        return 1
    print(('右手编辑服务已启动：' if result['started'] else '右手编辑服务正在运行：') + result['url'])
    if not args.no_open:
        webbrowser.open(result['url'])
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
