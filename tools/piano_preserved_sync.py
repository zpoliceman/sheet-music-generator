"""钢琴同步已认可词音：同步导出钢琴，逐文件保持已认可简谱、吉他和原唱数据。"""
# 钢琴同步已认可词音：新增通用受保护重导；不会调用原曲识别或全曲重新编配。
from pathlib import Path
from workspace_location import local_path
import shutil
from copy import deepcopy

from score_export import read_json, save_json, sha256
from source_timing_acceptance import require_isolated_output
from piano_harmony_readability import assess_piano_labels, fingerprint, source_payload


def protected_files(source):
    # 钢琴同步已认可词音：新增三个目录的实际文件清单，复制后要求逐字节相同且无额外文件。
    source = local_path(source)
    return {str(p.relative_to(source)): sha256(p) for folder in ('guitar', 'vocal', 'audio')
            for p in (source / folder).rglob('*') if p.is_file()}


def make_sync_record(project, source_path):
    # 钢琴同步已认可词音：新增明确来源工程和实际钢琴摘要，防止再次重导误入歌词旧入口或整曲分析。
    source_path = Path(source_path).resolve()
    return {'version': 1, 'source_project': str(source_path), 'source_project_sha256': sha256(source_path),
            'source_music_sha256': fingerprint(source_payload(project)),
            'protected_file_sha256': protected_files(source_path.parent),
            'music_scope': 'piano_sync_with_preserved_approved_voice_and_guitar', 'whole_song_reanalysis': False}


def check_sync_project(project):
    # 钢琴同步已认可词音：新增实际局部差异白名单；只允许有原声证据的生成低音省略与派生和声标记。
    audit = project.get('piano_sync_revision', {})
    source_path = Path(audit.get('source_project', ''))
    if not local_path(source_path).is_file() or sha256(source_path) != audit.get('source_project_sha256'):
        raise ValueError('钢琴同步认可原工程已改变或缺失。')
    original = read_json(source_path)
    if any(project[key] != original[key] for key in ('accepted_vocal_project', 'shared_analysis')):
        raise ValueError('钢琴同步改变了已认可拍轴、歌词或共享分析。')
    if project['arrangements']['guitar'] != original['arrangements']['guitar']:
        raise ValueError('钢琴同步不能重写吉他编配。')
    if audit.get('source_music_sha256') != fingerprint(source_payload(project)):
        raise ValueError('钢琴同步实际内容已失效。')
    labels = assess_piano_labels(project)
    if not labels['valid']:
        raise ValueError('钢琴同步和声标记已失效：' + str(labels['errors']))
    old = deepcopy(original['arrangements']['piano'])
    actual = deepcopy(project['arrangements']['piano'])
    revision = actual.pop('piano_label_revision')
    actual.pop('readable_harmony')
    removed = {row['note']['id']: row for row in revision['removed_generated_bass_notes']}
    known = {n['id']: n for n in old['notes']}
    source_sha = project['shared_analysis']['input_binding']['sources']['bass']['sha256']
    for identity, row in removed.items():
        if (known.get(identity) != row['note'] or not row['note'].get('phrase_harmony_generated')
                or row['note'].get('source_melody_id') or row['note'].get('role') != 'bass'
                or row['source_sha256'] != source_sha or len(row['windows']) != 2):
            raise ValueError('钢琴同步删除了未授权的实际音符。')
    old['notes'] = [n for n in old['notes'] if n['id'] not in removed]
    for event in old.get('attack_events', []):
        if any(identity in removed for identity in event.get('note_ids', [])):
            event['note_ids'] = [identity for identity in event['note_ids'] if identity not in removed]
    if actual != old:
        raise ValueError('钢琴同步存在未记录的音高、时值、踏板或左右手改写。')
    if audit.get('protected_file_sha256') != protected_files(source_path.parent):
        raise ValueError('钢琴同步原吉他／简谱／原唱文件已改变。')
    return original, labels


def export_preserved_piano_sync(project_path, output):
    # 钢琴同步已认可词音：新增只在新隔离目录写钢琴，正常入口另由音乐验收后更新。
    from export_timing_revision import export_revision
    from guitar_readability_acceptance import assess_guitar_readability, require_guitar_readability
    from guitar_variable_repeat import build_repeat_plan
    root = Path(__file__).resolve().parents[1]
    output = require_isolated_output(output, root)
    if output.exists() and any(output.iterdir()):
        raise ValueError('钢琴同步必须另存新的隔离目录。')
    project = read_json(project_path)
    original, labels = check_sync_project(project)
    output.mkdir(parents=True, exist_ok=True)
    save_json(output / 'project.json', project)
    checks = export_revision(output / 'project.json', output, instruments=('piano',))
    # 钢琴同步已认可词音：新增当前双手实际持音、手跨度、同键与换位速度检查；旧通过字段不能替代本次验收。
    from accompaniment_arrange import validate_playability
    from accompaniment_analysis import SongClock
    physical = validate_playability(project['arrangements']['piano'], SongClock(project['accepted_vocal_project']))
    if not physical['valid']:
        raise ValueError('同步钢琴实际可演奏性失败：' + str(physical['errors']))
    save_json(output / 'piano_playability.json', physical)
    source = local_path(project['piano_sync_revision']['source_project']).parent
    for folder in ('guitar', 'vocal', 'audio'):
        shutil.copytree(source / folder, output / folder, dirs_exist_ok=True)
    observed = protected_files(output)
    if observed != project['piano_sync_revision']['protected_file_sha256']:
        raise ValueError('钢琴同步导出未保持吉他／简谱／原唱实际文件。')
    guitar = assess_guitar_readability(project, build_repeat_plan(project), output_dir=output)
    require_guitar_readability(project, guitar)
    save_json(output / 'guitar_readability_acceptance.json', guitar)
    save_json(output / 'piano_label_acceptance.json', labels)
    save_json(output / 'piano_sync_revision.json', project['piano_sync_revision'])
    validation = read_json(output / 'export_validation.json')
    validation.update(protected_instruments=['guitar', 'vocal'], protected_files_identical=True,
                      piano_music_status=project.get('piano_music_acceptance', {}).get('status', 'needs_review'))
    save_json(output / 'export_validation.json', validation)
    # 钢琴同步已认可词音：新增候选总入口补齐保留声部，吉他页面本身不修改。
    from accompaniment_export import html_page
    import html
    title = html.escape(project['accepted_vocal_project']['title'])
    (output / 'index.html').write_text(html_page(title + ' · 钢琴同步候选',
        '<h1>' + title + ' · 钢琴同步候选</h1><p>钢琴音乐验收待完成，现行吉他与简谱文件保持。</p>'
        '<p><a href="vocal/score.html">人声简谱</a> · <a href="guitar/score.html">已认可吉他谱</a> · '
        '<a href="piano/score.html">同步钢琴谱与原唱试听</a></p>'), 'utf-8')
    return {'valid': True, 'output': str(output), 'notes': len(project['arrangements']['piano']['notes']),
            'protected_files_identical': True, 'normal_entry_changed': False,
            'piano_music_status': validation['piano_music_status']}
