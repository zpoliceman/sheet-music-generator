"""4/4可选右手与实时谱面试听：未选择时原样另存当前交付，不重新编配或排版。"""
# 4/4可选右手与实时谱面试听：新增窄范围保留入口，仅接受当前正常索引中的工程和无修改请求。
from pathlib import Path
from urllib.parse import unquote
import re
import shutil

from score_export import read_json,save_json,sha256
from source_timing_acceptance import require_isolated_output

ROOT=Path(__file__).resolve().parents[1]


def frozen_delivery_request(args):
    # 4/4可选右手与实时谱面试听：新增任何明确修改／导出要求均退出原样路径，不能吞掉请求。
    if not getattr(args,'edited_project',None):return False
    allowed={'edited_project','output','analysis_dir','report'}
    if any(name not in allowed and value not in (None,False,[],()) for name,value in vars(args).items()):return False
    source=Path(args.edited_project).resolve()
    index=ROOT/'results/accompaniment/index.html'
    if not index.is_file():return False
    text=index.read_text(encoding='utf-8').split('<details>')[0]
    current={(index.parent/unquote(link)).parent.resolve()/'project.json' for link in re.findall(r'href="([^"]+)"',text)}
    return source in current and (source.parent/'guitar/score.html').is_file()


def copy_frozen_delivery(project_path, output):
    # 4/4可选右手与实时谱面试听：新增真正的零修改另存；原曲来源及所有交付文件逐字节核查。
    from revise_guitar_selection import validate_parent,verify_sources
    source=Path(project_path).resolve();output=require_isolated_output(output,ROOT)
    if source.parent==output or source.parent in output.parents:
        raise ValueError('原样副本须另存于原工程以外')
    if output.exists() and any(output.iterdir()):raise ValueError('输出目录已有内容，请另存新版本')
    project=read_json(source);digest=sha256(source)
    parent_check=validate_parent(project,source);bindings=verify_sources(project)
    # 4/4可选右手与实时谱面试听：新增交付身份核查，不能把手改工程与旧谱／旧声音一起静默复制。
    if (source.parent/'publication.json').is_file():
        from scoped_music_publication import require_scoped_publication
        require_scoped_publication(source.parent,project)
    else:
        from guitar_repeat_edition import unchanged_package
        if not unchanged_package(source) and not (project.get('piano_sync_revision') or project.get('bar_boundary_revision')):
            raise ValueError('当前交付工程与原文件凭据不一致，请使用独立编辑工程或明确修订参数导出')
    files={p.relative_to(source.parent).as_posix():sha256(p) for p in source.parent.rglob('*')
           if p.is_file() and p.name!='publication.json'}
    # 4/4可选右手与实时谱面试听：新增复制音乐及读法，不复制只属于原正常目录的发布授权。
    shutil.copytree(source.parent,output,dirs_exist_ok=True,ignore=shutil.ignore_patterns('publication.json'))
    copied={name:sha256(output/name) for name in files}
    if copied!=files or sha256(source)!=digest:raise ValueError('原样副本与当前原工程不一致')
    result={'valid':True,'status':'exact_current_delivery_copy','output':str(output),'music_changed':False,
        'normal_entry_changed':False,'source_project':str(source),'source_project_sha256':digest,
        'files_copied_and_verified':len(files),'parent_acceptance':parent_check,'verified_sources':bindings,
        'new_music_or_reading_generated':False,'new_music_rule_revalidation':False,
        'scope':'unchanged_existing_delivery_only_not_new_music_acceptance','publication_allowed':False}
    save_json(output/'frozen_delivery_copy.json',result)
    # 4/4可选右手与实时谱面试听：新增保留原工程已有历史报告，本次继承证明独立存放。
    if not (output/'revision_report.json').exists():save_json(output/'revision_report.json',result)
    if any(sha256(output/name)!=digest for name,digest in files.items()):
        raise ValueError('原样继承记录改变了旧交付文件')
    return result
