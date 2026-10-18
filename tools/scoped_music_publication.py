"""两曲简谱吉他确认发布：把已确认的乐器范围与冻结工程分开记录。"""
# 两曲简谱吉他确认发布：新增按范围发布证明；未发布钢琴不被整体passed顺带放行。
from pathlib import Path
from workspace_location import local_path
from score_export import read_json,sha256
from source_timing_acceptance import require_music_publication

NAME='publication.json'
SCOPE=['vocal','guitar']

# 三曲确认发布与右手选择交接：修改可按明确授权范围显示钢琴，旧简谱／吉他文案保持。
# def published_text(text):
def published_text(text, instruments=None):
    # 两曲简谱吉他确认发布：新增只替换候选状态文字，音乐图形、页面脚本和时间列不动。
    # 三曲确认发布与右手选择交接：新增只支持旧双项或新三项精确范围，不自动扩大授权。
    scope = SCOPE if instruments is None else instruments
    if scope not in (SCOPE, ['vocal','guitar','piano']): raise ValueError('发布文字的乐器范围不受支持')
    confirmed = '本版简谱与吉他已通过用户听辨确认。' if scope == SCOPE else '本版简谱、吉他与钢琴已由用户确认发布。'
    for before,after in (
        ('隔离候选 · ','已确认版本 · '),
        # 三曲确认发布与右手选择交接：修改只替换状态文案，旧表达注释保留。
        # ('本版尚未通过整曲音乐验收。','本版简谱与吉他已通过用户听辨确认。'),
        ('本版尚未通过整曲音乐验收。',confirmed),
        ('本次候选','本版总览')):
        text=text.replace(before,after)
    return text


def publication_scope(manifest):
    # 三曲确认发布与右手选择交接：新增版本化三项发布范围；旧v1仍只认可简谱与吉他。
    scope = SCOPE if manifest.get('version') == 1 else ['vocal','guitar','piano'] if manifest.get('version') == 2 else None
    if scope is None or manifest.get('instruments') != scope: raise ValueError('发布乐器范围不受支持')
    return scope

def validate_manifest(folder,payload=None):
    # 两曲简谱吉他确认发布：新增真实来源与用户明确授权绑定；不得借声乐／吉他发布证明新增钢琴。
    folder=Path(folder).resolve();manifest=read_json(folder/NAME)
    # 三曲确认发布与右手选择交接：修改旧v1范围不变，新增v2显式三项发布。
    # if manifest.get('version')!=1 or manifest.get('instruments')!=SCOPE:raise ValueError('发布乐器范围不受支持')
    scope=publication_scope(manifest)
    acceptance=manifest.get('music_acceptance',{})
    require_music_publication(acceptance)
    # 三曲确认发布与右手选择交接：修改逐份授权精确比较，不允许钢琴借旧吉他范围放行。
    # if acceptance.get('published_instruments')!=SCOPE:raise ValueError('音乐验收与实际发布范围不一致')
    if acceptance.get('published_instruments')!=scope:raise ValueError('音乐验收与实际发布范围不一致')
    source=local_path(manifest['source_project']);approval_path=local_path(manifest['approval'])
    if not source.is_file() or sha256(source)!=manifest['source_project_sha256']:raise ValueError('认可的来源工程已改变')
    if not approval_path.is_file() or sha256(approval_path)!=manifest['approval_sha256']:raise ValueError('发布听辨授权已改变')
    approval=read_json(approval_path)
    # 三曲确认发布与右手选择交接：修改用户授权必须与此次实际发布范围完全相同。
    # if approval.get('publication_authorized') is not True or approval.get('instruments')!=SCOPE:
    if approval.get('publication_authorized') is not True or approval.get('instruments')!=scope:
        raise ValueError('未取得本乐器范围的明确发布授权')
    bound=[x for x in approval.get('source_candidates',{}).values()
           if local_path(x['project']).resolve()==source.resolve() and x['sha256']==manifest['source_project_sha256']]
    if len(bound)!=1:raise ValueError('用户确认不是该版本的工程')
    if sha256(folder/'project.json')!=sha256(source):raise ValueError('发布时改变了已认可音乐工程')
    original=read_json(source);project=payload if payload is not None else read_json(folder/'project.json')
    if project!=original:raise ValueError('发布载荷与认可工程不同')
    changes={c['id'] for c in project.get('bar_boundary_revision',{}).get('changes',[])}
    if not changes<=set(approval.get('accepted_cards',[])):raise ValueError('仍有未确认的局部小节修改')
    # 三曲确认发布与右手选择交接：修改只在明确三项授权时允许钢琴；v1原拒绝规则保留。
    # if (folder/'piano').exists():raise ValueError('本次范围不能发布新的钢琴文件')
    if 'piano' not in scope and (folder/'piano').exists():raise ValueError('本次范围不能发布新的钢琴文件')
    files=manifest.get('files',{})
    required={'project.json','index.html','vocal/score.html','guitar/score.html','guitar/score_full.html'}
    # 三曲确认发布与右手选择交接：新增三项的实际全部格式要求，不能仅添加钢琴链接或空目录。
    if 'piano' in scope:
        required.update(kind+'/'+name for kind in scope for name in ('score.html','score.musicxml','score.mxl','score.mid','preview.wav'))
    if not required<=set(files):raise ValueError('发布清单缺少必要文件')
    actual={p.relative_to(folder).as_posix() for p in folder.rglob('*') if p.is_file() and p!=folder/NAME}
    if actual!=set(files):raise ValueError('实际文件与发布清单不同')
    for rel,digest in files.items():
        target=(folder/rel).resolve()
        if not target.is_relative_to(folder) or not target.is_file() or sha256(target)!=digest:
            raise ValueError('发布文件缺失或改变：'+rel)
    # 三曲确认发布与右手选择交接：新增v2必须逐文件绑定认可来源，除了总览及状态文案，任何音频／图形／工程内容都不能改变。
    if manifest['version']==2:
        source_files={p.relative_to(source.parent).as_posix():sha256(p) for p in source.parent.rglob('*') if p.is_file()}
        if source_files!=bound[0].get('files') or set(source_files)!=actual:
            raise ValueError('三项发布没有完整绑定认可成品文件')
        for rel,digest in source_files.items():
            target=folder/rel
            if rel=='index.html':continue
            if target.suffix.lower()=='.html':
                if target.read_text(encoding='utf-8')!=published_text((source.parent/rel).read_text(encoding='utf-8'),scope):
                    raise ValueError('发布时改变了谱页图形／脚本：'+rel)
            elif sha256(target)!=digest:
                raise ValueError('发布时改变了认可音乐文件：'+rel)
    return manifest,project

def require_scoped_publication(folder,payload=None):
    # 两曲简谱吉他确认发布：新增在来源和实际产物门槛上使用范围验收，不改原工程或放松旧门槛。
    manifest,project=validate_manifest(folder,payload)
    from revise_guitar_reading import verify_reading_source
    from guitar_readability_acceptance import assess_guitar_readability,require_guitar_readability
    verify_reading_source(project,Path(manifest['source_project']))
    folder=Path(folder);plan=read_json(folder/'guitar/repeat_plan.json')
    actual=assess_guitar_readability(project,repeat_plan=plan,output_dir=folder)
    require_guitar_readability(project,actual)
    # 三曲确认发布与右手选择交接：修改保留旧返回范围，新增钢琴实际MIDI和持续音／手部跨度检查，不调用编配或合成。
    # return {'valid':True,'instruments':SCOPE,'project_sha256':sha256(folder/'project.json'),
    #     'source_verified':True,'actual_guitar_status':actual['status'],
    #     'piano_published':False,'scope':'human_approved_frozen_vocal_guitar_not_all_instruments'}
    scope=publication_scope(manifest);piano_check=None
    if 'piano' in scope:
        from accompaniment_export import validate_midi
        from accompaniment_arrange import validate_playability
        from accompaniment_analysis import SongClock
        voice=project['accepted_vocal_project'];piano=project['arrangements']['piano']
        piano_check={'midi':validate_midi(folder/'piano/score.mid',piano,voice),
                     'playability':validate_playability(piano,SongClock(voice))}
        if not all(item['valid'] for item in piano_check.values()):raise ValueError('钢琴实际产物或可演奏性未通过')
    return {'valid':True,'instruments':scope,'project_sha256':sha256(folder/'project.json'),
        'source_verified':True,'actual_guitar_status':actual['status'],'piano_actual_check':piano_check,
        'piano_published':'piano' in scope,'scope':('human_approved_frozen_vocal_guitar_piano' if 'piano' in scope else 'human_approved_frozen_vocal_guitar_not_all_instruments')}
