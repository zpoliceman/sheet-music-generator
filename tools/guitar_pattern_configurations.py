"""多区间右手配置与网页完整成品：同曲多套命名配置及完整成品定位。"""
# 多区间右手配置与网页完整成品：新增磁盘持久化，绑定真实来源摘要；配置和曲谱版本分别保存。
from copy import deepcopy
from pathlib import Path
from workspace_location import local_path
import re
import time
import uuid

from score_export import read_json, save_json


def editor_workspace(root, explicit=None):
    # 多区间右手配置与网页完整成品：新增记住上次编辑目录，关闭后用原启动器仍能找回配置和全部版本。
    from source_timing_acceptance import require_isolated_output
    root = Path(root).resolve()
    memory = root/'test_outputs/accompaniment_runs/right_hand_editor_session.json'
    selected = explicit
    if selected is None:
        selected = read_json(memory)['workspace'] if memory.is_file() else 'test_outputs/accompaniment_runs/right_hand_editor'
    selected = local_path(selected)
    if not selected.is_absolute(): selected = root/selected
    return require_isolated_output(selected, root)


def remember_workspace(root, workspace):
    # 多区间右手配置与网页完整成品：新增服务成功启动后再记录，保存相对项目路径以便接续。
    root, workspace = Path(root).resolve(), Path(workspace).resolve()
    memory = root/'test_outputs/accompaniment_runs/right_hand_editor_session.json'
    memory.parent.mkdir(parents=True, exist_ok=True)
    save_json(memory, {'version': 1, 'workspace': workspace.relative_to(root).as_posix()})


def full_result(output, version):
    # 多区间右手配置与网页完整成品：新增实际导出文件清单，网页复用完整展开谱、阅读谱与整曲试听。
    prefix = '/saved/'+version+'/'
    full_page = 'guitar/score_full.html' if (output/'guitar/score_full.html').is_file() else 'guitar/score.html'
    return {'url': prefix+'index.html', 'score_url': prefix+full_page,
            'reading_url': prefix+'guitar/score.html', 'audio_url': prefix+'guitar/preview.wav',
            'singing_audio_url': prefix+'guitar/singing_preview.wav', 'version': version}


class ConfigurationStore:
    # 多区间右手配置与网页完整成品：新增受限标识及原子写入，配置名从不作为文件路径。
    def __init__(self, workspace):
        self.folder = Path(workspace)/'configurations'

    def _project_folder(self, project_id):
        if not isinstance(project_id, str) or not re.fullmatch(r'[a-f0-9]{16}', project_id):
            raise ValueError('曲谱标识无效')
        return self.folder/project_id

    def list(self, project_id, source_sha256):
        folder = self._project_folder(project_id)
        result = []
        for path in folder.glob('*.json'):
            row = read_json(path)
            if row.get('project_id') != project_id or row.get('id') != path.stem:
                raise ValueError('保存的配置来源不符')
            result.append({**row, 'compatible': row['source_sha256'] == source_sha256})
        return sorted(result, key=lambda row: (row['updated_at'], row['id']), reverse=True)

    def prepare(self, project_id, source_sha256, configuration):
        # 多区间右手配置与网页完整成品：新增保存前核对；更新已载入配置只改配置文件，历史乐谱不覆盖。
        self._project_folder(project_id)
        configuration = configuration or {}
        name = configuration.get('name', '').strip()
        if not name:
            name = time.strftime('配置 %m-%d %H:%M:%S')
        if len(name) > 80 or any(ord(char) < 32 for char in name):
            raise ValueError('配置名称应为1至80个可见字符')
        identity = configuration.get('id') or uuid.uuid4().hex[:16]
        if not isinstance(identity, str) or not re.fullmatch(r'[a-f0-9]{16}', identity):
            raise ValueError('配置标识无效')
        path = self._project_folder(project_id)/(identity+'.json')
        if configuration.get('id'):
            if not path.is_file():
                raise ValueError('配置不存在，请另存为新配置')
            previous = read_json(path)
            if previous.get('project_id') != project_id or previous.get('source_sha256') != source_sha256:
                raise ValueError('配置对应的原谱已改变，请另存为新配置')
        return {'id': identity, 'name': name, 'project_id': project_id, 'source_sha256': source_sha256}

    def save(self, prepared, plan, result):
        # 多区间右手配置与网页完整成品：新增仅在完整产物通过后保存；失败生成不会改写原配置。
        record = {**deepcopy(prepared), 'version': 1, 'plan': deepcopy(plan), 'result': deepcopy(result),
                  'updated_at': time.strftime('%Y-%m-%d %H:%M:%S')}
        folder = self._project_folder(prepared['project_id'])
        folder.mkdir(parents=True, exist_ok=True)
        path = folder/(prepared['id']+'.json')
        temporary = folder/(prepared['id']+'.'+uuid.uuid4().hex+'.tmp')
        save_json(temporary, record)
        temporary.replace(path)
        return record
