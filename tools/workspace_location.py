"""工作目录改名兼容：固定曲谱身份，并确认启动器连接的是当前工作区。"""
from pathlib import Path, PureWindowsPath
from functools import lru_cache
import os
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


@lru_cache(maxsize=8)
def historical_roots(root):
    """读取历史根目录；当前工作目录始终由代码所在位置确定。"""
    settings = Path(root)/'data/workspace_paths.json'
    if not settings.is_file():
        return ()
    record = json.loads(settings.read_text(encoding='utf-8-sig'))
    values = record.get('historical_roots')
    if record.get('version') != 1 or not isinstance(values, list) or not all(isinstance(p, str) and PureWindowsPath(p).is_absolute() for p in values):
        raise ValueError('历史路径映射配置无效。')
    return tuple(PureWindowsPath(p) for p in values)


def local_path(value, root=None):
    """在文件读取入口返回实际路径，不修改工程中的原始字符串或摘要。"""
    if not isinstance(value, (str, os.PathLike)):
        return value
    root = Path(root) if root is not None else Path(__file__).resolve().parents[1]
    raw = os.fspath(value)
    if isinstance(raw, bytes):
        return value
    original = Path(value)
    for previous in historical_roots(root):
        try:
            relative = PureWindowsPath(raw).relative_to(previous)
        except ValueError:
            continue
        if '..' in relative.parts:
            raise ValueError('历史路径不能越出当前工程。')
        actual = root.joinpath(*relative.parts)
        if not actual.resolve().is_relative_to(root.resolve()):
            raise ValueError('历史路径指向工程外部，拒绝访问。')
        return actual
    return original
