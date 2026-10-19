"""只启动HTML内的素材网站，不加载音乐模型。"""
import argparse
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent

def main():
    parser = argparse.ArgumentParser(description='启动统一素材网页')
    parser.add_argument('--port', type=int, default=8768)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error('端口必须介于1024和65535之间。')
    temporary = ROOT / 'runtime' / 'app' / 'tmp'
    temporary.mkdir(parents=True, exist_ok=True)
    os.environ['TMP'] = str(temporary)
    os.environ['TEMP'] = str(temporary)
    import uvicorn
    uvicorn.run('portal.app:create_app', factory=True, host='127.0.0.1', port=args.port,
                proxy_headers=True, forwarded_allow_ips='127.0.0.1', access_log=False,
                limit_concurrency=24, timeout_keep_alive=10)

if __name__ == '__main__':
    main()
