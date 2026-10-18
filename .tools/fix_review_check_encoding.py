# 歌词对齐与真实制谱：修复验证子进程编码，原调用行注释保留。
from pathlib import Path
p=Path('.tools/validate_review_bundle.py')
s=p.read_text(encoding='utf-8-sig')
s=s.replace('import subprocess\n','import subprocess\n# 歌词对齐与真实制谱：新增对子进程UTF-8编码的显式控制。\nimport os\n')
lines=s.splitlines()
for i,line in enumerate(lines):
    if line.startswith('result = subprocess.run('):
        lines[i]='# 歌词对齐与真实制谱：原调用注释保留，修复Windows默认CP936与验证器UTF-8解码不一致。\n# '+line+'\n'+line[:-1]+',env=dict(os.environ,PYTHONIOENCODING="utf-8"))'
        break
else: raise ValueError('expected subprocess invocation missing')
p.write_text('\n'.join(lines)+'\n',encoding='utf-8-sig')
