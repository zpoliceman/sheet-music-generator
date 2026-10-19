"""从Cloudflare官方GitHub发布下载隧道程序，并核对官方资产摘要。"""
import hashlib
import json
import ssl
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / 'bin'
API = 'https://api.github.com/repos/cloudflare/cloudflared/releases/tags/2026.10.1'

def request(url):
    return urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'sheet-music-upload-portal/0.1', 'Accept': 'application/vnd.github+json' if url == API else 'application/octet-stream'}), timeout=45, context=ssl.create_default_context())

def main():
    BIN.mkdir(exist_ok=True)
    with request(API) as response:
        release = json.load(response)
    asset = next(item for item in release['assets'] if item['name'] == 'cloudflared-windows-amd64.exe')
    expected = asset.get('digest', '')
    if not expected.startswith('sha256:'):
        raise RuntimeError('官方发布未提供SHA256摘要，停止自动运行下载程序。')
    expected = expected.split(':', 1)[1]
    target = BIN / 'cloudflared.exe'
    if not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest() != expected:
        staging = BIN / 'cloudflared.exe.part'
        hasher = hashlib.sha256()
        with request(asset['browser_download_url']) as response, staging.open('wb') as output:
            while chunk := response.read(1024 * 1024):
                output.write(chunk)
                hasher.update(chunk)
        if hasher.hexdigest() != expected:
            raise RuntimeError('下载摘要与官方发布不一致，未启用文件。')
        staging.replace(target)
    record = {'release': release['tag_name'], 'source': asset['browser_download_url'], 'sha256': expected, 'verified': True}
    (BIN / 'cloudflared.release.json').write_text(json.dumps(record, indent=2), encoding='utf-8')
    print(json.dumps(record), flush=True)
if __name__ == '__main__':
    main()
