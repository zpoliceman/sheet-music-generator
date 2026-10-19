"""为新工作目录创建空白复核配置；已有文件原样保留。"""
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]


def initialize(root=ROOT):
    root = Path(root)
    destination = root / 'data'
    destination.mkdir(parents=True, exist_ok=True)
    result = {}
    for source in sorted((root / 'config').glob('*.example.json')):
        target = destination / source.name.replace('.example.json', '.json')
        value = json.loads(source.read_text(encoding='utf-8-sig'))
        if value.get('schema_version') != 1 or not isinstance(value.get('reviews'), dict):
            raise ValueError('配置示例格式错误：' + source.name)
        try:
            with target.open('x', encoding='utf-8') as stream:
                json.dump(value, stream, ensure_ascii=False, indent=2)
                stream.write('\n')
            result[target.name] = '已创建空白配置'
        except FileExistsError:
            result[target.name] = '已有配置，保持原样'
    return result


if __name__ == '__main__':
    print(json.dumps(initialize(), ensure_ascii=False, indent=2))
