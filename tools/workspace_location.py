"""工作目录改名兼容：固定曲谱身份，并确认启动器连接的是当前工作区。"""
from pathlib import Path
import hashlib
import json


def project_identity(path, root):
    # 工作目录改名兼容：身份根只作为编号种子，不作为磁盘访问路径；目录迁移不丢失原配置。
    root = Path(root).resolve()
    relative = Path(path).resolve().relative_to(root)
    settings = root/'data/workspace_identity.json'
    seed = root
    if settings.is_file():
        record = json.loads(settings.read_text(encoding='utf-8-sig'))
        if record.get('version') != 1 or not isinstance(record.get('identity_root'), str):
            raise ValueError('工作区身份记录无效，请保留原data/workspace_identity.json。')
        seed = Path(record['identity_root'])
    return hashlib.sha256(str(seed/relative).encode('utf-8')).hexdigest()[:16]


def same_workspace(health, root):
    # 工作目录改名兼容：不能仅凭应用名称复用其它工程副本的服务。
    if not isinstance(health, dict) or health.get('application') != 'guitar_right_hand_editor':
        return False
    value = health.get('workspace_root')
    return isinstance(value, str) and bool(value) and Path(value).resolve() == Path(root).resolve()
