"""和弦弹唱与伴奏编配：通用整曲编配入口、编辑重导与原成果保护。"""
# 和弦弹唱与伴奏编配：新增独立CLI，参数选择歌曲，不改既有人声生成路线。
from __future__ import annotations
import argparse
import json
from pathlib import Path
import time
from score_export import read_json, save_json, sha256
from accompaniment_sources import bind_inputs, separate_six_sources
from accompaniment_analysis import analyze, SongClock
# 渴首次吉他编配：修改，统一初次编配及编辑重建的乐器选择；原代码注释保留。
# from accompaniment_arrange import arrange_guitar, arrange_piano, validate_playability
# 渴首次吉他编配：新增按所选乐器执行，保留各乐器原验证。
from accompaniment_arrange import arrange_requested, requested_instruments, validate_playability
from accompaniment_export import export_all, html_page
# 分解和弦优先：新增共享原曲起音支持，不使用上传谱的和弦表作为识别答案。
from accompaniment_texture_policy import add_block_support
# 常用右手伴奏型：新增演唱吉他独立模板，不改变钢琴或共同声学数据。
from guitar_right_hand_patterns import apply_common_patterns, validate_patterns
# 规整分解节奏与延音显示：新增新编配默认规整、旧工程显式升级另存。
# 结构稳定伴奏与人声合播：修改，原代码注释保留。
# from guitar_regular_rhythm import apply_regular_patterns
from guitar_regular_rhythm import apply_regular_patterns
# 结构稳定伴奏与人声合播：新增原曲结构选型和分段夹位。
from guitar_structure_patterns import apply_structured_patterns,POLICY as STRUCTURE_POLICY
from guitar_capo import apply_capo
# 小节划分与拍速层级纠错：新增统一拍层级纠正与严格人声来源核验。
from accompaniment_rebar import correct_accompaniment_grid, validate_vocal_snapshot, compare_sounding_time
from copy import deepcopy
# 相似乐句和弦框架复用：新增共享编配及统一实际和声视图，旧声学分析仍保存。
# 跨歌曲和弦复用与器乐准备：修改，旧导入保留；最终拍点验收使用实际共同编配／固定边界范围。
# from phrase_harmony_arrange import apply_phrase_harmony,validate_phrase_harmony
from phrase_harmony_arrange import apply_phrase_harmony,validate_phrase_harmony,needs_joint_pulse_validation
from phrase_harmony_plan import arrangement_view
# 跨歌曲和弦复用与器乐准备：新增显式源调人声输入的上游来源核验，历史工程继续原路径。
from accompaniment_source_pitch import validate_source_pitch_project
# 吉他编配规则与统一验收修复：新增完整修订身份，旧API丢顶层字段也必须走受保护路线。
from guitar_readability_acceptance import has_guitar_readability_revision

ROOT=Path(__file__).resolve().parents[1]


# 强拍相位与伴奏同步纠错：新增当前交付优先入口，字典序v10不能抢在新v12之前。
def write_collection_index(parent,preferred):
    from urllib.parse import quote
    parent=Path(parent);preferred=Path(preferred)
    # 最小拍轴与词音伴奏修复：修改正常入口放行，原全量枚举保留；新音乐候选needs_review不得被首选或扫描带进谱库。
    # paths=sorted(parent.glob('*/index.html'),key=lambda p:(p!=preferred,p.parent.name))
    from source_timing_acceptance import require_music_publication
    eligible=[]
    for page in parent.glob('*/index.html'):
        project=page.parent/'project.json'
        # 吉他编配规则与统一验收修复：修改，只读整份工程以验证新吉他验收摘要；旧读取保留。
        # acceptance=read_json(project).get('music_acceptance') if project.is_file() else None
        payload=read_json(project) if project.is_file() else {}
        # 两曲简谱吉他确认发布：新增单独范围证明；认可工程不为发布改写，钢琴未决仍保留在原记录中。
        if (page.parent/'publication.json').is_file():
            from scoped_music_publication import require_scoped_publication
            try:
                require_scoped_publication(page.parent,payload)
            except (ValueError,KeyError,OSError):
                if page.resolve()==preferred.resolve():
                    raise ValueError('按乐器范围的发布证明或实际文件未通过，正常入口保持原状。')
                continue
            eligible.append(page)
            continue
        acceptance=payload.get('music_acceptance')
        guitar_check=payload.get('guitar_readability_acceptance')
        # 吉他编配规则与统一验收修复：修改嵌套新编配也必须原声及音乐验收，不允许降级旧谱发布。
        # if guitar_check is not None or payload.get('guitar_readability_revision'):
        if guitar_check is not None or has_guitar_readability_revision(payload):
            from guitar_readability_acceptance import require_guitar_readability
            try:
                require_guitar_readability(payload,guitar_check or {})
                # 吉他编配规则与统一验收修复：新增发布时重读实际文件，避免验收后谱面／音频文件改动仍借旧标记放行。
                from guitar_readability_acceptance import assess_guitar_readability
                plan_path=page.parent/'guitar'/'repeat_plan.json'
                actual_check=assess_guitar_readability(payload,repeat_plan=read_json(plan_path) if plan_path.is_file() else None,
                                                       output_dir=page.parent)
                require_guitar_readability(payload,actual_check)
                if acceptance is None:
                    raise ValueError('新吉他规则通过仍须整曲音乐验收。')
                require_music_publication(acceptance)
            except ValueError:
                if page.resolve()==preferred.resolve():
                    raise ValueError('新吉他实际验收或整曲音乐验收未通过，正常谱库入口保持原状。')
                continue
        if acceptance is not None:
            try:
                require_music_publication(acceptance)
            except ValueError:
                if page.resolve()==preferred.resolve():
                    raise ValueError('该候选音乐验收未通过，正常谱库入口保持原状。')
                continue
        eligible.append(page)
    paths=sorted(eligible,key=lambda p:(p!=preferred,p.parent.name))
    links=['<p><a href="'+quote(p.relative_to(parent).as_posix())+'">'+p.parent.name+'</a></p>' for p in paths]
    (parent/'index.html').write_text(html_page('和弦弹唱与伴奏谱','<h1>和弦弹唱与伴奏谱</h1>'+''.join(links)),encoding='utf-8')


# 和弦弹唱与伴奏编配：新增窄范围输出边界，禁止覆盖原歌曲、音源、配置及冻结快照。
def validate_output_path(output):
    output=Path(output).resolve()
    allowed=(ROOT/'results'/'accompaniment',ROOT/'test_outputs'/'accompaniment_runs')
    if not any(output.is_relative_to(base) and output!=base for base in allowed):
        raise ValueError('编配输出必须位于results/accompaniment或test_outputs/accompaniment_runs的独立子目录。')
    return output


# 渴首次吉他编配：新增多项升级共用的真实器乐输入绑定；已变更和声／节奏不能仍指向早期编辑工程。
def source_revision_input(shared,vocal,arrangements,edited_project,analysis_dir):
    from guitar_instrumental_register import fingerprint
    seed={'shared_analysis':deepcopy(shared),'accepted_vocal_project':deepcopy(vocal),'arrangements':deepcopy(arrangements)}
    # 原曲拍轴与歌词拍位通用修复：修改，旧仅历史工程的来源读取保留；新曲也可绑定当前真实阶段种子。
    # prior=read_json(edited_project)
    # previous={key:prior[key] for key in seed}
    previous={key:read_json(edited_project)[key] for key in seed} if edited_project else None
    if fingerprint(previous)==fingerprint(seed):
        return Path(edited_project).resolve()
    work=Path(analysis_dir).resolve()
    if not work.is_relative_to(ROOT/'test_outputs'/'accompaniment_runs'):
        raise ValueError('器乐骨干修订的阶段来源必须位于项目分析缓存。')
    path=work/('instrumental_backbone_source_'+fingerprint(seed)[:20]+'.json')
    if path.exists():
        if fingerprint(read_json(path))!=fingerprint(seed):
            raise ValueError('不能覆盖器乐骨干修订的真实阶段来源。')
    else:
        save_json(path,seed)
    return path


# 原曲拍轴与歌词拍位通用修复：新增完整钢琴交付检查；纯工作JSON不进入复制优化，现有钢琴清单必须可核验。
def piano_copy_source(project_path):
    path=Path(project_path).resolve();folder=path.parent
    manifest=folder/'manifest.json'
    required=('piano/score.musicxml','piano/accompaniment.mid','piano/preview.wav','piano/score.html')
    if path.name!='project.json' or not manifest.is_file() or not all((folder/name).is_file() for name in required):
        return None
    listed={r['path']:r for r in read_json(manifest).get('files',[])}
    for name in required:
        row=listed.get(name)
        if row is None or sha256(folder/name)!=row['sha256'] or (folder/name).stat().st_size!=row['bytes']:
            raise ValueError('既有钢琴交付清单无效，拒绝复制：'+name)
    return folder


# 原曲拍轴与歌词拍位通用修复：新增未定稿原型的器乐准备；只规划实际器乐，普通声部随后由共同乐句生成。
def prepare_provisional_instrumentals(shared,vocal,guitar):
    # 保音持续按弦与整句八度衔接：新增已统一准备的初始音区不重复降位；来源改变明确拒绝复用。
    initial = guitar.get('initial_phrase_register_preparation')
    if initial:
        from guitar_instrumental_register import fingerprint
        if initial.get('result_notes_sha256') != fingerprint(guitar['notes']):
            raise ValueError('初次整句配音已被修改，不能再次把派生音高当原音重复降八度。')
        return deepcopy(guitar)
    from guitar_instrumental_register import editable_notes,prepare_instrumental_register
    identities=editable_notes(shared,guitar)
    if not identities:return guitar
    subset=deepcopy(guitar);subset['notes']=[n for n in subset['notes'] if n['id'] in identities]
    subset=prepare_instrumental_register(shared,vocal,subset)
    updated={n['id']:n for n in subset['notes']};result=deepcopy(guitar)
    result['notes']=[deepcopy(updated.get(n['id'],n)) for n in guitar['notes']]
    result['instrumental_register_preparations']=deepcopy(subset.get('instrumental_register_preparations',[]))
    result['prototype_preparation_scope']='instrumentals_only_vocal_prototype_not_frozen'
    return result


# 原曲拍轴与歌词拍位通用修复：新增未定稿器乐节奏准备范围；普通伴奏随后由共同和声重建，不能先把原型弦位当作认可音乐锁定。
def regularize_provisional_instrumentals(shared,vocal,arrangements):
    from instrumental_regular_rhythm import regularize_instrumentals,sections_for,in_section
    sections=sections_for(shared);subsets=deepcopy(arrangements);fixed={}
    for instrument,arrangement in subsets.items():
        editable={n['id'] for n in arrangement['notes'] if any(in_section(n,s) for s in sections)}
        fixed[instrument]=[deepcopy(n) for n in arrangement['notes'] if n['id'] not in editable]
        arrangement['notes']=[n for n in arrangement['notes'] if n['id'] in editable]
        arrangement['attack_events']=[e for e in arrangement.get('attack_events',[]) if any(s['start_tick']<=e['start_tick']<s['end_tick'] for s in sections)]
    updated,subsets,report=regularize_instrumentals(shared,vocal,subsets)
    for instrument,arrangement in subsets.items():
        arrangement['notes']=sorted(fixed[instrument]+arrangement['notes'],key=lambda n:(n['start_tick'],n['id']))
        ordinary_events=[deepcopy(e) for e in arrangements[instrument].get('attack_events',[]) if not any(s['start_tick']<=e['start_tick']<s['end_tick'] for s in sections)]
        arrangement['attack_events']=sorted(ordinary_events+arrangement.get('attack_events',[]),key=lambda e:e['start_tick'])
        report['instruments'][instrument]['protected_normal_note_count']=len(fixed[instrument])
    report['preparation_scope']='instrumentals_only_ordinary_prototype_to_be_rebuilt'
    return updated,subsets,report


# 和弦弹唱与伴奏编配：新增既有交付/冻结代码/同源输入全文件指纹前后保护。
def protect_existing(shared,output):
    files=set()
    for base in (ROOT/'results',ROOT/'history-version'):
        if base.exists():
            for path in base.rglob('*'):
                # 分解和弦优先：修改，旧规则排除全部伴奏；新版本同时保护其它已交付伴奏文件。
                # if path.is_file() and not path.is_relative_to(ROOT/'results'/'accompaniment'):
                if path.is_file() and not path.is_relative_to(output) and path!=ROOT/'results'/'accompaniment'/'index.html':
                    files.add(path.resolve())
    binding=shared['input_binding'];files.add(Path(binding['vocal_project']).resolve())
    files.update(Path(x['path']).resolve() for x in binding['sources'].values())
    files.update(Path(x['path']).resolve() for x in binding['references'])
    vocal=read_json(binding['vocal_project'])
    # 跨歌曲和弦复用与器乐准备：新增上游目标调工程保护，另存的源调输入也必须保护原文件。
    pitch_source=vocal.get('accompaniment_source_pitch',{}).get('source_project')
    if pitch_source:files.add(Path(pitch_source).resolve())
    files.update(Path(v).resolve() for k,v in vocal['inputs'].items() if k.endswith('_path'))
    if any(p.is_relative_to(output) for p in files):raise ValueError('编配输出包含受保护输入。')
    return {str(path):sha256(path) for path in sorted(files)}


# 和弦弹唱与伴奏编配：新增可编辑编配重导，认可人声快照及实际源指纹不可悄悄替换。
# 旧工程功能自动升级与三曲器乐表现统一：修改加载签名，旧入口保留；只在正式重导出时修复可证明缺失的派生字段。
# def load_edited_project(path,rearrange=False,capo=None):
def load_edited_project(path,rearrange=False,capo=None,repair_missing_features=False,feature_repair_log=None):
    data=read_json(path);shared=data['shared_analysis'];vocal=data['accepted_vocal_project']
    # 原声覆盖与选音归属通用修复：新增保留层加载，先完整重放新旧工程、核验合并实际音乐，再检查实际演奏。
    if shared.get('approved_section_preservation'):
        from approved_music_sections import verified_base
        verified_base(shared,vocal,data['arrangements'],replay=True)
        if rearrange or capo is not None:
            raise ValueError('认可段落工程重编／换夹需用基础工程明确生成，新保留层不能被隐式改写。')
        from accompaniment_arrange import piano_hand_positions
        for instrument,arrangement in data['arrangements'].items():
            if instrument=='piano':arrangement['hand_positions']=piano_hand_positions(arrangement['notes'],SongClock(vocal))
            check=validate_playability(arrangement,SongClock(vocal))
            if not check['valid']:raise ValueError('认可段落合并违反实际演奏约束：'+str(check['errors'][:6]))
        return shared,vocal,data['arrangements']
    binding=shared['input_binding']
    if sha256(binding['vocal_project'])!=binding['vocal_project_sha256']:
        raise ValueError('认可人声来源已改变，需重新绑定。')
    # 跨歌曲和弦复用与器乐准备：新增检查源调输入是否仍可由其上游工程确定重建。
    if not validate_source_pitch_project(read_json(binding['vocal_project'])):
        raise ValueError('源调人声准备的上游来源或派生音乐已改变。')
    # 小节划分与拍速层级纠错：修改，原完全相等核验注释保留；允许确定性时间派生但拒绝音乐改写。
    # if vocal!=read_json(binding['vocal_project']):
    if not validate_vocal_snapshot(vocal,binding):
        raise ValueError('本阶段编辑仅针对伴奏；认可人声快照不能被静默改写。')
    for source in binding['sources'].values():
        if sha256(source['path'])!=source['sha256']:raise ValueError('编辑工程的源音轨指纹不符。')
    if rearrange:
        # 渴首次吉他编配：修改，重新编配保留工程的已选乐器；原代码注释保留。
        # guitar=arrange_guitar(shared,vocal,capo);piano=arrange_piano(shared,vocal)
        # return shared,vocal,{'guitar':guitar,'piano':piano}
        # 渴首次吉他编配：新增按所选乐器执行，保留各乐器原验证。
        # 保音持续按弦与整句八度衔接：修改明确重编同样先整句配音；普通旧工程重导不触发该分支。
        # return shared,vocal,arrange_requested(shared,vocal,capo)
        return shared,vocal,arrange_requested(shared,vocal,capo,phrase_register=True)
    # 和弦弹唱与伴奏编配：修改，钢琴手位是音符派生数据，编辑后重算，原直接返回保留。
    # return shared,vocal,data['arrangements']
    from accompaniment_arrange import piano_hand_positions
    arrangements=data['arrangements']
    # 旧工程功能自动升级与三曲器乐表现统一：新增以原表现来源恢复遗漏字段，现有错误值／改音和篡改仍由严格核验拒绝。
    if repair_missing_features:
        from accompaniment_project_upgrade import repair_missing_expression_fields
        arrangements['guitar'],repairs=repair_missing_expression_fields(shared,vocal,arrangements['guitar'])
        if feature_repair_log is not None:feature_repair_log.extend(repairs)
    # 器乐背景休止与旋律突出：新增加载时实际重放表现层，删音／改力度不能仅凭自填元数据获准。
    if arrangements['guitar'].get('instrumental_expression'):
        from guitar_instrumental_expression import validate_expression
        expression_check=validate_expression(shared,vocal,arrangements['guitar'],replay=True)
        if not expression_check['valid']:raise ValueError('器乐表现来源或派生音乐改变：'+str(expression_check['errors'][:6]))
    # 原曲器乐旋律骨干重提取：新增读取时复演原曲证据，编辑重导不能无验证地接受手填的新旋律。
    if arrangements['guitar'].get('instrumental_source_backbone'):
        from instrumental_source_melody import validate_source_backbone
        check=validate_source_backbone(shared,vocal,arrangements['guitar'],replay=True)
        if not check['valid']:raise ValueError('原曲器乐骨干来源或派生音乐改变：'+str(check['errors'][:6]))
    # 吉他器乐低把位与指型复用：新增来源绑定的确定重放；旧工程未启用时沿用原核验路径。
    if arrangements['guitar'].get('instrumental_register'):
        from guitar_instrumental_register import validate_instrumental_register
        register_check=validate_instrumental_register(shared,vocal,arrangements['guitar'],replay=True)
        if not register_check['valid']:
            raise ValueError('吉他器乐音区／指型来源或派生音乐改变：'+str(register_check['errors'][:6]))
    # 渴首次吉他编配：修改，读取时核对范围并仅重算所选钢琴手位；原代码注释保留。
    # arrangements['piano']['hand_positions']=piano_hand_positions(arrangements['piano']['notes'],SongClock(vocal))
    # 渴首次吉他编配：新增按所选乐器执行，保留各乐器原验证。
    if set(arrangements)!=set(requested_instruments(shared)):
        raise ValueError('编配工程实际乐器与绑定选择不一致。')
    if 'piano' in arrangements:
        arrangements['piano']['hand_positions']=piano_hand_positions(arrangements['piano']['notes'],SongClock(vocal))
    return shared,vocal,arrangements


# 和弦弹唱与伴奏编配：新增一次完整导出与实测报告，音乐听审未完成时明确为初稿。
def generate(args):
    # 首次生成自动拍轴交接：新增新源缓存参数不得静默作用于旧认可工程，保护修订／重导分支。
    # 尾段原声局部补证：修改旧工程保护范围，来源决定也不能用于覆盖旧认可音乐。
    # if getattr(args,'edited_project',None) and any(getattr(args,name,None) for name in ('source_meter_evidence','source_meter_model_cache')):
    # 首拍与首尾局部补证：修改新词音参数同样不得静默进入旧工程的阅读／重导入口。
    # if getattr(args,'edited_project',None) and any(getattr(args,name,None) for name in ('source_meter_evidence','source_meter_model_cache','first_source_decision')):
    if getattr(args,'edited_project',None) and any(getattr(args,name,None) for name in ('source_meter_evidence','source_meter_model_cache','first_source_decision','first_source_words')):
        raise ValueError('首次原声拍轴参数仅用于全新输入，不能覆盖已有工程')
    # 吉他编配规则与统一验收修复：新增保留已认可拍轴的窄范围入口，在任何旧自动纠拍／重编之前分流。
    edited=read_json(args.edited_project) if getattr(args,'edited_project',None) else {}
    # 4/4可选右手与实时谱面试听：新增明确换型先于旧局部分组／稳定型重导，旧无选择路径顺序保持。
    from guitar_pattern_selection import has_selection
    right_hand_plan=getattr(args,'right_hand_plan',None)
    # 4/4可选右手与实时谱面试听：新增当前交付未请求任何修改时原样另存，保留已认可音符、声音与读法。
    from guitar_pattern_preservation import frozen_delivery_request,copy_frozen_delivery
    if right_hand_plan is None and frozen_delivery_request(args):
        result=copy_frozen_delivery(args.edited_project,args.output)
        if getattr(args,'report',None):save_json(args.report,result)
        return result
    if edited and (right_hand_plan is not None or has_selection(edited)):
        conflicts=('rearrange','bar_boundary_review','meter_unit_decision','stable_vocal_patterns','readable_guitar',
            'refresh_reading','rebuild_source_meter','continuous_meter','correct_beat_phase','vocal_continuity',
            'reextract_instrumental_melody','performance_beat_clock','local_beat_clock','structural_rhythm',
            'phrase_rhythm','common_right_hand','regular_right_hand','capo','rekey','bar_length_factor')
        if any(getattr(args,name,None) for name in conflicts):
            raise ValueError('右手选择须与改拍、换调或其它重编分开另存')
        from revise_guitar_selection import revise_selection
        result=revise_selection(args.edited_project,args.output,right_hand_plan,getattr(args,'readability_feature_cache',None))
        if getattr(args,'report',None):save_json(args.report,result)
        return result
    # 局部两拍过渡听辨修订：新增显式局部小节入口及普通重导继承，优先于重选拍、重编和全曲识别。
    if getattr(args,'bar_boundary_review',None) or (edited.get('bar_boundary_revision') and not getattr(args,'refresh_reading',False)):
        if not edited:raise ValueError('局部小节复核需要已认可完整工程')
        conflicts=('rearrange','meter_unit_decision','stable_vocal_patterns','readable_guitar','refresh_reading',
            'rebuild_source_meter','continuous_meter','correct_beat_phase','vocal_continuity','reextract_instrumental_melody',
            'performance_beat_clock','local_beat_clock','structural_rhythm','phrase_rhythm','common_right_hand','regular_right_hand',
            'structured_accompaniment','approved_section_review','rhythm_review','instrumental_rest_review','capo','rekey','bar_length_factor')
        if any(getattr(args,name,None) for name in conflicts):raise ValueError('局部小节修订不能同时重编、重选拍或改变音乐')
        from reviewed_bar_boundaries import revise,export_reviewed
        result=(revise(args.edited_project,args.bar_boundary_review,args.output) if getattr(args,'bar_boundary_review',None)
                else export_reviewed(args.edited_project,args.output))
        if getattr(args,'report',None):save_json(args.report,result)
        return result
    # 完整乐句与实际时长复用：新增显式纯阅读入口先于全部重编／单位修订分支，禁止顺带改变音乐。
    if getattr(args, 'refresh_reading', False):
        if not edited:
            raise ValueError('阅读重导需要已有完整工程')
        conflicts = ('rearrange', 'meter_unit_decision', 'stable_vocal_patterns', 'readable_guitar',
            'rebuild_source_meter', 'continuous_meter', 'correct_beat_phase', 'vocal_continuity',
            'reextract_instrumental_melody', 'performance_beat_clock', 'local_beat_clock', 'structural_rhythm',
            'phrase_rhythm', 'simplify_instrumental', 'regular_instrumental', 'low_position_instrumental',
            'instrumental_flow', 'instrumental_flow_density', 'instrumental_expression', 'phrase_harmony',
            'common_right_hand', 'regular_right_hand', 'structured_accompaniment', 'approved_section_review',
            'rhythm_review', 'instrumental_rest_review')
        if any(getattr(args, name, False) for name in conflicts) or getattr(args, 'capo', None) is not None or getattr(args, 'bar_length_factor', None) is not None:
            raise ValueError('纯阅读重导不能同时重编、改拍轴、换夹或修改音乐')
        from revise_guitar_reading import revise_reading
        result = revise_reading(args.edited_project, args.output)
        if getattr(args, 'report', None): save_json(args.report, result)
        return result
    # 慢拍单位与两曲最小修订：新增明确单位修订先于旧稳定右手和整曲重建分流，验过的慢拍必须真正进入生成。
    # 慢拍单位与两曲最小修订：修改丢失顶层标记仍由人声来源身份进入相同保护路线，不能降级旧入口。
    # if getattr(args, 'meter_unit_decision', None) or edited.get('meter_unit_revision'):
    if (getattr(args, 'meter_unit_decision', None) or edited.get('meter_unit_revision')
            or edited.get('accepted_vocal_project', {}).get('meter_unit_correction')):
        if not edited:
            raise ValueError('纯单位修订需要已有受保护工程，不能暗中整曲重算')
        if any(getattr(args, name, False) for name in ('rearrange', 'rebuild_source_meter', 'continuous_meter',
                # 慢拍单位与两曲最小修订：新增其它重建／换夹参数不能被静默忽略。
                'correct_beat_phase', 'vocal_continuity', 'reextract_instrumental_melody', 'performance_beat_clock',
                'local_beat_clock', 'structural_rhythm', 'phrase_rhythm', 'capo', 'rekey')):
            raise ValueError('纯单位修订不能同时请求整曲重识别或另一条拍轴重建')
        from revise_meter_unit import revise as revise_unit, export_preserved as export_unit
        if getattr(args, 'meter_unit_decision', None):
            caches = list(getattr(args, 'meter_features_from', []) or [])
            if getattr(args, 'readability_feature_cache', None):
                caches.append(args.readability_feature_cache)
            result = revise_unit(args.edited_project, args.meter_unit_decision, args.output, caches)
        else:
            result = export_unit(args.edited_project, args.output)
        if getattr(args, 'report', None):
            save_json(args.report, result)
        return result
    # 演唱段稳定右手型：新增显式升级及普通重导保护，先于其它升级和整曲重识别入口。
    from revise_guitar_patterns import has_section_patterns
    if getattr(args,'stable_vocal_patterns',False) or has_section_patterns(edited):
        if not edited:raise ValueError('段落稳定右手型需要已有绑定工程，不从头猜拍轴和和弦')
        if any(getattr(args,name,False) for name in ('rearrange','rebuild_source_meter','continuous_meter',
                'correct_beat_phase','reextract_instrumental_melody','vocal_continuity','performance_beat_clock')):
            raise ValueError('段落右手型修订不能同时重建拍轴、人声或整曲音高／和弦')
        from revise_guitar_patterns import revise as revise_patterns
        result=revise_patterns(args.edited_project,args.output,getattr(args,'readability_feature_cache',None))
        if getattr(args,'report',None):save_json(args.report,result)
        return result
    # 钢琴同步已认可词音：新增在旧歌词分流和所有重识别之前保留钢琴同步工程，禁止重编已认可吉他。
    if edited.get('piano_sync_revision'):
        if any(getattr(args,name,False) for name in ('rearrange','rebuild_source_meter','continuous_meter',
                'correct_beat_phase','reextract_instrumental_melody','vocal_continuity','performance_beat_clock')):
            raise ValueError('保护钢琴同步工程时不能同时重建拍轴、音高或伴奏。')
        from piano_preserved_sync import export_preserved_piano_sync
        result=export_preserved_piano_sync(args.edited_project,args.output)
        if getattr(args,'report',None):
            save_json(args.report,result)
        return result
    # 局部词音归属修订：新增局部词音工程先走固定伴奏重导，不能因人声摘要变化重新规划已通过吉他。
    if edited.get('local_lyric_revision'):
        if any(getattr(args,name,False) for name in ('rearrange','rebuild_source_meter','continuous_meter',
                'correct_beat_phase','reextract_instrumental_melody','vocal_continuity','performance_beat_clock')):
            raise ValueError('保护局部词音修订时不能同时重建拍轴、音高或伴奏，请从原工程另立修订。')
        from local_lyric_revision import export_preserved_local_project
        result=export_preserved_local_project(args.edited_project,args.output)
        if getattr(args,'report',None):
            save_json(args.report,result)
        return result
    readable_requested=getattr(args,'readable_guitar',False)
    # 吉他编配规则与统一验收修复：修改恢复丢顶层标记的新修订身份，不能自动转回整曲重分析。
    # readable_inherited=bool(edited.get('guitar_readability_revision'))
    readable_inherited=has_guitar_readability_revision(edited)
    if readable_requested or readable_inherited:
        if not edited:
            raise ValueError('可读吉他修订需要已有工程；不会从头重猜音乐。')
        conflicting=('rearrange','rebuild_source_meter','continuous_meter','correct_beat_phase',
                     'reextract_instrumental_melody','vocal_continuity','performance_beat_clock')
        if any(getattr(args,name,False) for name in conflicting):
            raise ValueError('保留音乐的吉他修订不能同时请求重建拍轴、音高或整曲编配；请分开另存。')
        from revise_guitar_readability import revise
        result=revise(args.edited_project,args.output,getattr(args,'readability_feature_cache',None))
        if getattr(args,'report',None):
            save_json(args.report,result)
        return result
    # 默认入口原曲节拍强制复核：新增旧输入来源检查先于任何快捷分支；无校正的旧谱自动先纠拍再重编。
    from source_meter_entry import prepare_edited_request,require_calibrated_source
    args,source_entry_input=prepare_edited_request(args)
    # 默认入口原曲节拍强制复核：新增已校正旧输入的初始验收依据；后续明确重建用真正新层替换。
    source_entry_ready=source_entry_input
    # 重复乐句折叠与多遍挂词：新增已验收工程的纯排版另存，不重新编配或合成已认可音源。
    from guitar_repeat_edition import notation_only_request, generate_repeat_edition
    if notation_only_request(args):return generate_repeat_edition(args)
    # 旧工程功能自动升级与三曲器乐表现统一：修改排版选择，旧只看CLI保留；已认可反复版普通重导继续保持反复布局。
    # fold_repeats_enabled=getattr(args,'fold_repeats',False) or not args.edited_project or args.rearrange
    # 原曲拍轴与歌词拍位通用修复：新增显式旧工程重建与新音乐范围；旧工程普通重导不自动改人声。
    source_rebuild_requested=getattr(args,'rebuild_source_meter',False)
    # 原曲拍轴与歌词拍位通用修复：新增旧拍轴版本的明确复现边界，不能将两个互相覆盖的时序策略混成一次隐式导出。
    legacy_clock_requested=any(getattr(args,name,False) for name in (
        'correct_beat_phase','phrase_rhythm','local_beat_clock','structural_rhythm','performance_beat_clock','continuous_meter'))
    if source_rebuild_requested and legacy_clock_requested:
        raise ValueError('独立源拍轴重建与历史拍轴校正请分别另存执行，不能在同一任务互相覆盖。')
    fresh_music=not args.edited_project or args.rearrange or source_rebuild_requested
    source_meter_enabled=False
    inherited_layout=read_json(args.edited_project).get('guitar_score_layout',{}).get('mode') if args.edited_project else None
    # 原曲拍轴与歌词拍位通用修复：修改，旧默认条件保留；明确重建也执行完整阅读与编配功能。
    # fold_repeats_enabled=getattr(args,'fold_repeats',False) or inherited_layout=='repeat_folded' or not args.edited_project or args.rearrange
    fold_repeats_enabled=getattr(args,'fold_repeats',False) or inherited_layout=='repeat_folded' or fresh_music
    feature_load_repairs=[]
    # 吉他器乐低把位与指型复用：新增新编配默认采用、历史工程明确另存升级，普通编辑不重复降八度。
    # 原曲器乐旋律骨干重提取：修改，新骨干也需重新联合规划低把位，不能沿用已失效的旧旋律指型。
    # low_instrumental_enabled=getattr(args,'low_position_instrumental',False) or not args.edited_project or args.rearrange
    # 原曲拍轴与歌词拍位通用修复：修改，旧条件保留；明确源重建视作未定稿新音乐。
    # low_instrumental_enabled=getattr(args,'low_position_instrumental',False) or getattr(args,'reextract_instrumental_melody',False) or not args.edited_project or args.rearrange
    low_instrumental_enabled=getattr(args,'low_position_instrumental',False) or getattr(args,'reextract_instrumental_melody',False) or fresh_music
    # 器乐低弦分解填充：新增历史工程显式升级，新编配默认启用；普通重导不重复添加填音。
    # 器乐填充密度随主体伴奏：修改，旧触发保留；新歌默认跟随正文密度，旧工程明确另存升级。
    # flow_enabled=getattr(args,'instrumental_flow',False) or not args.edited_project or args.rearrange
    # 原曲拍轴与歌词拍位通用修复：修改，旧条件保留；新音乐使用同曲主体密度。
    # density_enabled=getattr(args,'instrumental_flow_density',False) or not args.edited_project or args.rearrange
    # 器乐合理分句与十二品硬限制：修改，旧触发保留；明确重排八度后重做低弦填充／表现，避免复用旧高把位填音。
    # density_enabled=getattr(args,'instrumental_flow_density',False) or fresh_music
    density_enabled=getattr(args,'instrumental_flow_density',False) or fresh_music or getattr(args,'low_position_instrumental',False)
    flow_enabled=getattr(args,'instrumental_flow',False) or density_enabled
    # 器乐背景休止与旋律突出：新增新编配默认突出器乐，历史工程需明确升级；不将某曲休止时间写入默认算法。
    # 器乐填充密度随主体伴奏：修改，旧触发保留；重填充后重新绑定背景／力度，不能丢失上一版已认可的表现。
    # expression_enabled=getattr(args,'instrumental_expression',False) or bool(getattr(args,'instrumental_rest_review',None)) or not args.edited_project or args.rearrange
    expression_enabled=getattr(args,'instrumental_expression',False) or bool(getattr(args,'instrumental_rest_review',None)) or density_enabled
    # 器乐声部恢复与规整节奏：新增互斥校验，旧单线简化与新完整声部规整不能同时启用。
    if getattr(args,'simplify_instrumental',False) and getattr(args,'regular_instrumental',False):
        raise ValueError('器乐主线简化与完整声部规整请选择一种。')
    output=validate_output_path(args.output);started=time.perf_counter()
    # 和弦弹唱与伴奏编配：新增执行前验证全部写入边界，编辑重导必须另存。
    if args.report and not Path(args.report).resolve().is_relative_to(ROOT/'reports'/'accompaniment'):
        raise ValueError('报告需位于reports/accompaniment。')
    if args.edited_project and Path(args.edited_project).resolve().is_relative_to(output):
        raise ValueError('编辑重导请另存到新的伴奏目录，保留输入工程。')
    if args.edited_project:
        # 渴首次吉他编配：修改，已有工程重导不得悄悄丢弃另一乐器；原代码注释保留。
        # shared,vocal,arrangements=load_edited_project(args.edited_project,args.rearrange,args.capo)
        # 渴首次吉他编配：新增按所选乐器执行，保留各乐器原验证。
        # 旧工程功能自动升级与三曲器乐表现统一：修改正式加载，旧调用保留；恢复可来源重建的缺失派生属性。
        # shared,vocal,arrangements=load_edited_project(args.edited_project,args.rearrange,args.capo)
        # 原曲拍轴与歌词拍位通用修复：修改，旧先重编原型保留；明确源重建先读取已验收输入，再确定新拍轴。
        # shared,vocal,arrangements=load_edited_project(args.edited_project,args.rearrange,args.capo,
        shared,vocal,arrangements=load_edited_project(args.edited_project,args.rearrange and not source_rebuild_requested,args.capo,
            repair_missing_features=True,feature_repair_log=feature_load_repairs)
        # 默认入口原曲节拍强制复核：新增已采用独立源层的重编继续同一新策略，避免隐式退回历史拍轴拼接。
        source_meter_enabled=bool(vocal.get('source_meter_rebuild_correction')) and fresh_music
        if getattr(args,'guitar_only',False) and requested_instruments(shared)!=('guitar',):
            raise ValueError('已有双乐器工程请保留原范围；仅吉他新编配应从人声绑定或共享分析输入生成。')
        # 原曲拍轴与歌词拍位通用修复：新增旧工程显式重建，完全确定共同人声时序之后才创建伴奏原型。
        if source_rebuild_requested:
            from source_meter_project import rebuild_source_project
            print('先独立校准原曲连续拍轴／首拍与有声歌词，再编配两乐器',flush=True)
            # 原曲拍轴与歌词拍位通用修复：新增已有初始夹位偏好继承；未明确指定新夹位时保持输入工程的演奏配置。
            initial_capo=args.capo if args.capo is not None else arrangements.get('guitar',{}).get('configuration',{}).get('capo_fret')
            shared,vocal=rebuild_source_project(shared,vocal,Path(args.analysis_dir)/'features')
            # 默认入口原曲节拍强制复核：新增复核失败不得继续使用旧人声或旧原型，重新编配前检查真实新层。
            source_entry_ready=require_calibrated_source(vocal,shared['input_binding'])
            # 原曲拍轴与歌词拍位通用修复：修改，旧重新自动选夹保留；已有输入沿用明确的初始配置。
            # arrangements=arrange_requested(shared,vocal,args.capo)
            # 保音持续按弦与整句八度衔接：修改显式新源重建先整体规划，旧初次配音调用保留。
            # arrangements=arrange_requested(shared,vocal,initial_capo)
            arrangements=arrange_requested(shared,vocal,initial_capo,phrase_register=True)
            source_meter_enabled=True
        # 首拍与首尾局部补证：删除误置于旧工程分支的接线并保留原行；实际消费移到下方首次分支，旧工程入口在函数开头已明确拒绝该参数。
        # if getattr(args,'first_source_words',None):
        #     from first_generation_words import use_words
        #     vocal=use_words(vocal,binding,args.first_source_words)
    else:
        work=Path(args.analysis_dir).resolve()
        if not work.is_relative_to(ROOT/'test_outputs'/'accompaniment_runs'):
            raise ValueError('分析缓存需位于test_outputs/accompaniment_runs。')
        work.mkdir(parents=True,exist_ok=True)
        if args.shared_analysis:
            # 渴首次吉他编配：修改，缓存共享分析可在新输出中明确选择仅吉他；原代码注释保留。
            # shared=read_json(args.shared_analysis);binding=shared['input_binding']
            # 渴首次吉他编配：新增按所选乐器执行，保留各乐器原验证。
            shared=read_json(args.shared_analysis);binding=shared['input_binding']
            if getattr(args,'guitar_only',False):binding['requested_instruments']=['guitar']
        else:
            if args.binding:binding=read_json(args.binding)
            else:
                if not args.vocal_project or not args.demucs_report:raise ValueError('需要输入绑定或人声工程与分轨报告。')
                binding=bind_inputs(args.vocal_project,args.demucs_report,args.reference)
            # 渴首次吉他编配：修改，分轨仍完整保留，演奏乐器范围在分析前绑定；原代码注释保留。
            # if args.six_sources and not all('six_'+name in binding['sources'] for name in ('guitar','piano','other')):
            # 渴首次吉他编配：新增按所选乐器执行，保留各乐器原验证。
            if getattr(args,'guitar_only',False):binding['requested_instruments']=['guitar']
            if args.six_sources and not all('six_'+name in binding['sources'] for name in ('guitar','piano','other')):
                separated=separate_six_sources(binding,work,full=True)
                for name in ('guitar','piano','other'):binding['sources']['six_'+name]=separated['full_outputs'][name]
                save_json(work/'input_binding.json',binding)
            # 原曲拍轴与歌词拍位通用修复：修改，旧先分析错误拍窗保留；共享和声在独立人声准备后计算。
            # vocal=read_json(binding['vocal_project']);shared=analyze(binding,vocal,work/'features')
            # save_json(work/'shared_analysis.json',shared)
            shared=None
        vocal=read_json(binding['vocal_project'])
        if sha256(binding['vocal_project'])!=binding['vocal_project_sha256']:raise ValueError('共享分析的人声工程已改变。')
        # 跨歌曲和弦复用与器乐准备：新增源调反算检查，禁止合播与和声落入两个音高域。
        if not validate_source_pitch_project(vocal):raise ValueError('源调人声输入与原目标调工程不一致。')
        for source in binding['sources'].values():
            if sha256(source['path'])!=source['sha256']:raise ValueError('共享分析的音轨已改变。')
        # 原曲拍轴与歌词拍位通用修复：新增新曲默认前置校准；来源绑定的人工作曲拍位继续走既有精确保护路线。
        from beat_phase_alignment import phase_review
        # 原曲拍轴与歌词拍位通用修复：修改，旧自动条件保留；显式旧策略仍可复现，新曲无旧策略时默认前置。
        # if source_rebuild_requested or not phase_review(vocal['audio_analysis'],vocal['timing']):
        if source_rebuild_requested or (not legacy_clock_requested and not phase_review(vocal['audio_analysis'],vocal['timing'])):
            from source_meter_project import prepare_source_vocal
            # 首次生成自动拍轴交接：修改新曲阶段说明为真实执行范围，首次路线只换算已有词音时间。
            # print('先从原轨确认连续拍序／小节首拍，并重解有声字头',flush=True)
            print('先自动核对原曲拍单位／局部分组／覆盖，仅投影已有词音' if not args.edited_project
                  else '先从原轨确认连续拍序／小节首拍，并重解有声字头',flush=True)
            # 原声覆盖与选音归属通用修复：修改，默认新编配先补查原声漏音及相邻字归属；旧重导不触发。
            # vocal,source_meter_evidence=prepare_source_vocal(vocal,binding,work/'features')
            # 首次生成自动拍轴交接：修改新输入实际接收匿名原声决定；旧工程修订继续原路线。
            # vocal,source_meter_evidence=prepare_source_vocal(vocal,binding,work/'features',quality=True)
            vocal,source_meter_evidence=prepare_source_vocal(vocal,binding,work/'features',quality=True,
                first_generation=not bool(args.edited_project), evidence=getattr(args,'source_meter_evidence',None),
                feature_caches=getattr(args,'meter_features_from',()) or (),
                # 尾段原声局部补证：修改增加冻结且来源重放通过的首次决定参数，不触发全曲重选拍。
                # model_cache=getattr(args,'source_meter_model_cache',None))
                model_cache=getattr(args,'source_meter_model_cache',None),
                decision_path=getattr(args,'first_source_decision',None))
            source_meter_enabled=True
        # 默认入口原曲节拍强制复核：新增源校正必须在和声窗及初次伴奏原型生成之前通过完整复核。
        # 首拍与首尾局部补证：新增首次分支在已验拍轴之后、和声／编配之前实际加载指定字音补证，不能只接受参数却沿用旧词位。
        # 歌词自动加载与伴随声部音区保护：修改正常首次入口自动读取共享分析的必需修正清单；旧显式参数仍受相同来源校验。
        # if getattr(args,'first_source_words',None):
        from first_generation_analysis_bundle import resolve_words
        first_words_path=resolve_words(getattr(args,'shared_analysis',None),getattr(args,'first_source_words',None))
        # 歌词自动加载与伴随声部音区保护：新增相同分析包自动取认可伴随声部；没有声明不猜测历史曲谱。
        from first_generation_analysis_bundle import resolve_companion
        companion_reference=resolve_companion(getattr(args,'shared_analysis',None))
        if first_words_path is not None:
            from first_generation_words import use_words
            # 歌词自动加载与伴随声部音区保护：修改消费已解析的自动／显式文件，仍检查最终实际采用的准确SHA。
            # vocal=use_words(vocal,binding,args.first_source_words)
            # if vocal.get('first_source_word_correction',{}).get('artifact_sha256')!=sha256(args.first_source_words):
            vocal=use_words(vocal,binding,first_words_path)
            if vocal.get('first_source_word_correction',{}).get('artifact_sha256')!=sha256(first_words_path):
                raise ValueError('首次局部字音没有实际进入当前人声，拒绝继续编配')
            print('已加载并重放指定局部词音，原拍轴与音高保持',flush=True)
        source_entry_ready=require_calibrated_source(vocal,shared['input_binding'] if shared is not None else binding)
        # 尾段原声局部补证：修改首次中断恢复沿用同源同轴的共享分析，不因已有来源层而整曲重算和弦。
        # if shared is None or source_meter_enabled:
        if shared is not None and source_meter_enabled and vocal.get('first_source_meter_correction'):
            if (shared['input_binding']!=binding or shared['timing']!=vocal['timing']
                    or shared['statistics']!=vocal['statistics']):
                raise ValueError('首次恢复的共享分析来源或拍轴不同，不能借缓存跳过校验')
            from first_generation_tail import verified_tail_observation,constrain_terminal_events
            observation=verified_tail_observation(vocal,binding)
            melody,tail_audit=constrain_terminal_events(shared['instrumental_melody'],observation)
            shared=deepcopy(shared)
            shared['instrumental_melody']=melody
            if tail_audit is not None:shared['terminal_decay_constraint']=tail_audit
            # 尾段原声局部补证：新增缓存恢复同步已有转调的纯时间坐标，原调性、和弦实音及所有窗口不重算。
            shared['notation']['key_segments']=deepcopy(vocal['notation'].get('key_segments',[]))
            # 尾段原声局部补证：新增恢复时仅刷新织体的实际短小节分箱，沿用同一声学缓存；音高／和弦解码和原窗口不再计算。
            if vocal.get('first_source_meter_correction',{}).get('version')==2:
                from accompaniment_analysis import extract_features,measure_textures
                from source_accompaniment_quality import refine_attacks,sustained_attack
                tracks={role:extract_features(binding['sources'][role],work/'features',role)
                        for role in ('six_guitar','six_piano','other') if role in binding['sources']}
                for track in tracks.values():refine_attacks(track)
                clock=SongClock(vocal)
                shared['measure_textures']=measure_textures(tracks,clock,vocal,shared['sections'])
                for texture in shared['measure_textures']:
                    if texture['kind']=='sustain' and not texture['attacks']:
                        held=sustained_attack(texture,tracks,clock)
                        if held is not None:texture['sustained_observation']=held
        elif shared is None or source_meter_enabled:
            # 原声覆盖与选音归属通用修复：修改，新源质量重建启用独立伴奏覆盖检查。
            # shared=analyze(binding,vocal,work/'features',harmonic_quality=2 if source_meter_enabled else 1)
            shared=analyze(binding,vocal,work/'features',harmonic_quality=3 if source_meter_enabled else 1)
        save_json(work/'shared_analysis.json',shared)
        # 尾段原声局部补证：新增所有首次来源的器乐／织体共同约束，弱起音恢复不得在已证实尾响内重新发明攻击。
        if vocal.get('first_source_meter_correction'):
            from first_generation_tail import verified_tail_observation,constrain_shared_tail
            shared=constrain_shared_tail(shared,verified_tail_observation(vocal,binding))
            save_json(work/'shared_analysis.json',shared)
        # 歌词自动加载与伴随声部音区保护：新增随本次真实共享缓存保存必需字音声明，下一次普通首次生成自动加载，不能丢修正后悄悄退回旧词位。
        if vocal.get('first_source_meter_correction'):
            from first_generation_analysis_bundle import save_bundle
            bundle_words=first_words_path
            if bundle_words is not None and read_json(bundle_words).get('artifact_kind') != 'verified_first_generation_word_cache':
                from first_generation_word_cache import register_cache
                bundle_words=register_cache(bundle_words,work/'first_source_meter/accepted_vocal_project.json',binding,
                                            work/'reusable_word_supplement.json')
            # 歌词自动加载与伴随声部音区保护：修改输出分析缓存完整保留两类必需输入，并同步新增清单声明元数据。
            # save_bundle(work/'shared_analysis.json',bundle_words)
            save_bundle(work/'shared_analysis.json',bundle_words,companion_reference)
            shared=read_json(work/'shared_analysis.json')
        # 分解和弦优先：新增复用多轨攻击缓存的柱式例外核查，原和声及原织体kind保留。
        print('核查柱式例外的原曲起音证据',flush=True)
        shared=add_block_support(shared,vocal,work/'features')
        # 默认入口原曲节拍强制复核：新增新曲也须在首次乐器编配前通过来源检查，不能只凭prepare函数自报成功。
        # 默认入口原曲节拍强制复核：修改，原后置检查保留为注释；已移至共享和声分析之前。
        # source_entry_ready=require_calibrated_source(vocal,shared['input_binding'])
        # 渴首次吉他编配：修改，初次编配仅实例化所选乐器；原代码注释保留。
        # print('编配吉他与钢琴',flush=True)
        # arrangements={'guitar':arrange_guitar(shared,vocal,args.capo),'piano':arrange_piano(shared,vocal)}
        # 渴首次吉他编配：新增按所选乐器执行，保留各乐器原验证。
        print('编配吉他' if requested_instruments(shared)==('guitar',) else '编配吉他与钢琴',flush=True)
        # 保音持续按弦与整句八度衔接：修改全新音乐显式启用整句规划，旧工程重导不触发。
        # arrangements=arrange_requested(shared,vocal,args.capo)
        # 歌词自动加载与伴随声部音区保护：修改真实首次编配入口消费同源参考，仍执行完整旋律、低音、和声与指法求解。
        # arrangements=arrange_requested(shared,vocal,args.capo,phrase_register=True)
        arrangements=arrange_requested(shared,vocal,args.capo,phrase_register=True,companion_reference=companion_reference)
    # 常用右手伴奏型：新增新编配默认启用；编辑重导仅显式请求时套型，保护手工编辑。
    # 强拍相位与伴奏同步纠错：新增已授权的相位纠错先重建人声/和声，再选型，禁止复用错拍的右手循环。
    # 乐句节奏与音值分组：修改，原条件与调用注释保留；新增完整乐句升级同样重建共享分析。
    # if getattr(args,'correct_beat_phase',False):
    #     from beat_phase_alignment import correct_phase_project
    #     shared,vocal,arrangements=correct_phase_project(shared,vocal,arrangements,Path(args.analysis_dir)/'features')
    # 原曲拍轴与歌词拍位通用修复：新增新编配的明确配音版本；已认可旧工程普通重导不触发。
    if source_meter_enabled:
        arrangements['guitar']['configuration']['instrumental_register_voicing_version']=2
        # 原曲拍轴与歌词拍位通用修复：新增填充运动版本，只有未定稿源重建启用，旧缓存保持原重放。
        arrangements['guitar']['configuration']['instrumental_flow_motion_version']=2
    if getattr(args,'correct_beat_phase',False) or getattr(args,'phrase_rhythm',False):
        from beat_phase_alignment import correct_phase_project
        shared,vocal,arrangements=correct_phase_project(shared,vocal,arrangements,Path(args.analysis_dir)/'features',
                                                      phrase_rhythm=getattr(args,'phrase_rhythm',False))
    # 局部拍轴与原唱同步纠错：新增新编配默认局部拍轴，旧工程仅明确升级时重算，保存人工编辑与历史重建。
    # 通用段落强拍与乐句节奏修复：修改，保留原触发；明确结构升级也需要可靠的局部源拍轴。
    # local_clock_enabled=getattr(args,'local_beat_clock',False) or not args.edited_project or args.rearrange
    # 连续唱段拍轴与原唱同步修复：修改，原触发条件注释保留；新生成启用，历史工程须显式升级。
    # structural_enabled=getattr(args,'structural_rhythm',False) or not args.edited_project or args.rearrange
    # 原曲拍轴与歌词拍位通用修复：修改，旧自动后置拼接条件保留；已经独立重建的时序不再自动套旧原型校正。
    # performance_enabled=getattr(args,'performance_beat_clock',False) or not args.edited_project or args.rearrange
    performance_enabled=getattr(args,'performance_beat_clock',False) or (fresh_music and not source_meter_enabled)
    structural_enabled=getattr(args,'structural_rhythm',False) or performance_enabled
    local_clock_enabled=getattr(args,'local_beat_clock',False) or structural_enabled
    if local_clock_enabled:
        # 局部拍轴与原唱同步纠错：新增先确认拍层级和已有源锚点，避免用倍速脉冲拟合错误拍数。
        shared,vocal,arrangements=correct_accompaniment_grid(shared,vocal,arrangements,
                                      Path(args.analysis_dir)/'features',getattr(args,'bar_length_factor',None))
        from beat_phase_alignment import phase_review,correct_phase_project
        if not vocal.get('beat_phase_correction') and phase_review(vocal['audio_analysis'],vocal['timing']):
            shared,vocal,arrangements=correct_phase_project(shared,vocal,arrangements,Path(args.analysis_dir)/'features',phrase_rhythm=True)
        from local_beat_clock import correct_local_project
        print('校准原曲局部拍轴与跨句人声节奏',flush=True)
        shared,vocal,arrangements=correct_local_project(shared,vocal,arrangements,Path(args.analysis_dir)/'features')
    # 通用段落强拍与乐句节奏修复：新增通用结构升级；历史普通编辑重导保持原版本策略。
    if structural_enabled:
        from structure_beat_clock import correct_structural_project
        print('联合校准段落首拍、相似旋律与真实连音',flush=True)
        shared,vocal,arrangements=correct_structural_project(shared,vocal,arrangements,Path(args.analysis_dir)/'features')
    # 连续唱段拍轴与原唱同步修复：新增最后校准物理拍秒，保留已经认可的谱面和原唱，再重算共有分析。
    if performance_enabled:
        # 局部时序与弱证据通用修复：修改，旧v1调用完整注释保留；新生成及明确升级采用版本2，普通历史编辑不变。
        # from performance_beat_clock import correct_performance_project
        # print('校准连续唱段的原伴奏脉冲与原唱时序',flush=True)
        # shared,vocal,arrangements=correct_performance_project(shared,vocal,arrangements,Path(args.analysis_dir)/'features')
        # 跨歌曲和弦复用与器乐准备：修改，旧版本2入口保留；新生成／显式升级采用版本3，历史普通重导仍保持原策略。
        # from performance_clock_refinement import correct_refined_project
        # print('联合校准局部演唱时序、倚音与弱证据边界',flush=True)
        # shared,vocal,arrangements=correct_refined_project(shared,vocal,arrangements,Path(args.analysis_dir)/'features')
        from performance_clock_evidence import correct_evidence_project
        print('联合校准相关分轨攻击身份、局部原唱与弱证据边界',flush=True)
        shared,vocal,arrangements=correct_evidence_project(shared,vocal,arrangements,Path(args.analysis_dir)/'features')
        source_clock_check=shared['performance_beat_clock']['music_residual_check']
        if not source_clock_check['valid']:
            raise ValueError('连续拍轴仍有源时序分歧，停止交付并保留诊断：'+str(source_clock_check))
    # 跨曲低音与强拍复用通用修复：新增新生成/明确重编的独立低音首拍确认；普通历史编辑保持原音乐。
    # 连续源拍序与人声联合重解通用修复：修改，旧触发保留；显式连续重解也先确认同源绝对首拍，新编配默认启用。
    # if not args.edited_project or args.rearrange:
    # 原曲拍轴与歌词拍位通用修复：修改，旧自动后置版本保留；显式历史校正仍可复现，新的独立源层不再拼接旧原型。
    # continuous_enabled=getattr(args,'continuous_meter',False) or not args.edited_project or args.rearrange
    # if not args.edited_project or args.rearrange or continuous_enabled:
    continuous_enabled=getattr(args,'continuous_meter',False) or (fresh_music and not source_meter_enabled)
    if (fresh_music and not source_meter_enabled) or continuous_enabled:
        from source_meter_harmony import correct_source_meter_project
        print('核查跨乐器低音、小节首拍和开放指型性质音', flush=True)
        shared,vocal,arrangements=correct_source_meter_project(shared,vocal,arrangements,Path(args.analysis_dir)/'features')
    # 连续源拍序与人声联合重解通用修复：新增在确认整体首拍之后、共同和弦之前重建连续拍序与人声，不给播放器加偏移。
    if continuous_enabled:
        from continuous_meter_project import correct_continuous_project
        print('联合重建原伴奏连续拍序、小节首拍及人声音值／歌词',flush=True)
        shared,vocal,arrangements=correct_continuous_project(shared,vocal,arrangements,Path(args.analysis_dir)/'features',
                                                           getattr(args,'rhythm_review',None))
    # 人声连续音值与长休止漏音通用修复：新增初次生成／明确升级的局部声学复核；普通历史重导不静默改音。
    # 原曲拍轴与歌词拍位通用修复：修改，旧自动层保留；源f0已参与新层时不再隐式叠加旧人声派生。
    # if getattr(args,'vocal_continuity',False) or not args.edited_project or args.rearrange:
    if getattr(args,'vocal_continuity',False) or (fresh_music and not source_meter_enabled):
        from vocal_continuity_project import correct_vocal_continuity
        print('复核长休止内部稳定人声，修复连续字尾及字内音值',flush=True)
        shared,vocal,arrangements=correct_vocal_continuity(shared,vocal,arrangements,Path(args.analysis_dir)/'features',
                                                        getattr(args,'rhythm_review',None))
    # 规整分解节奏与延音显示：修改，原触发条件保留；增加用户明确要求的规整升级选项。
    # if args.common_right_hand or not args.edited_project or args.rearrange:
    # 结构稳定伴奏与人声合播：修改，原代码注释保留。
    # if args.common_right_hand or getattr(args,'regular_right_hand',False) or not args.edited_project or args.rearrange:
    # 结构稳定伴奏与人声合播：新增已授权的一体升级，旧显式规整参数继续可用。
    # 强拍相位与伴奏同步纠错：修改，原升级条件保留；纠错重建的伴奏必须在正确拍轴上完整重新选型。
    # structured=getattr(args,'structured_accompaniment',False) or not args.edited_project or args.rearrange
    # 乐句节奏与音值分组：修改，旧升级条件注释保留；节奏升级完成后重新选择普通伴奏型。
    # structured=getattr(args,'structured_accompaniment',False) or getattr(args,'correct_beat_phase',False) or not args.edited_project or args.rearrange
    # 局部拍轴与原唱同步纠错：修改，原升级条件注释保留；局部拍轴纠正后必须重新选择普通伴奏的共同拍点。
    # structured=getattr(args,'structured_accompaniment',False) or getattr(args,'correct_beat_phase',False) or getattr(args,'phrase_rhythm',False) or not args.edited_project or args.rearrange
    # 连续源拍序与人声联合重解通用修复：修改，旧触发保留；连续升级也必须重建转调夹位和指型，不能清掉缓存后跳过实际处理。
    # structured=getattr(args,'structured_accompaniment',False) or getattr(args,'correct_beat_phase',False) or getattr(args,'phrase_rhythm',False) or local_clock_enabled
    # 原曲拍轴与歌词拍位通用修复：修改，旧结构条件保留；独立源重建使用规整共同编配。
    # structured=getattr(args,'structured_accompaniment',False) or getattr(args,'correct_beat_phase',False) or getattr(args,'phrase_rhythm',False) or local_clock_enabled or continuous_enabled
    structured=getattr(args,'structured_accompaniment',False) or getattr(args,'correct_beat_phase',False) or getattr(args,'phrase_rhythm',False) or local_clock_enabled or continuous_enabled or source_meter_enabled
    # 跨歌曲和弦复用与器乐准备：新增一次联合规划；新编配不先按旧逐小节和弦造一套即将废弃的模板音。
    # 原曲拍轴与歌词拍位通用修复：修改，旧条件保留；新拍轴必须重算共同和声和两套实际伴奏。
    # joint_harmony_enabled=getattr(args,'phrase_harmony',False) or not args.edited_project or args.rearrange
    joint_harmony_enabled=getattr(args,'phrase_harmony',False) or fresh_music
    # 跨歌曲和弦复用与器乐准备：新增先整理获授权器乐时序，再冻结完整指型；旧顺序会过早拒绝可准备的换把。
    instrumental_rhythm_check=None
    early_instrumental=(structured and not getattr(args,'simplify_instrumental',False) and
                         # 原曲拍轴与歌词拍位通用修复：修改，旧条件保留；源重建的器乐也需先规整。
                         # (getattr(args,'regular_instrumental',False) or not args.edited_project or args.rearrange))
                         (getattr(args,'regular_instrumental',False) or fresh_music))
    if early_instrumental:
        from instrumental_regular_rhythm import regularize_instrumentals
        print('先整理器乐持续音与规整换把准备，再选择唱段模板',flush=True)
        # 跨歌曲和弦复用与器乐准备：新增先应用实际夹位，不能用未换算的品数判断持续音覆盖。
        apply_capo(shared,vocal,arrangements['guitar'])
        # 吉他器乐低把位与指型复用：新增在器乐节奏／固定音高时序检查前联合准备低把位候选。
        if low_instrumental_enabled:
            from guitar_instrumental_register import prepare_instrumental_register
            # 原曲拍轴与歌词拍位通用修复：修改，旧全曲冻结保留；新音乐先只准备器乐，真正旧认可唱段仍按原保护。
            # arrangements['guitar']=prepare_instrumental_register(shared,vocal,arrangements['guitar'])
            arrangements['guitar']=prepare_provisional_instrumentals(shared,vocal,arrangements['guitar']) if fresh_music and joint_harmony_enabled else prepare_instrumental_register(shared,vocal,arrangements['guitar'])
        # 原曲拍轴与歌词拍位通用修复：修改，旧全曲器乐准备保留；新编配不因尚未认可的普通原型换弦触发保护失败。
        # shared,arrangements,instrumental_rhythm_check=regularize_instrumentals(shared,vocal,arrangements)
        shared,arrangements,instrumental_rhythm_check=regularize_provisional_instrumentals(shared,vocal,arrangements) if fresh_music and joint_harmony_enabled else regularize_instrumentals(shared,vocal,arrangements)
    if structured:
        from guitar_exact_positions import refinger_exact_positions
        guitar=arrangements['guitar']
        guitar['configuration']['structure_policy']=dict(STRUCTURE_POLICY)
        apply_capo(shared,vocal,guitar)
        # 原曲拍轴与歌词拍位通用修复：修改，旧原型全曲锁位保留；共同乐句未生成前不固定普通候选弦位。
        # refinger_exact_positions(shared,vocal,guitar)
        if not (fresh_music and joint_harmony_enabled):refinger_exact_positions(shared,vocal,guitar)
        # 跨歌曲和弦复用与器乐准备：修改，旧局部模板保留给独立节奏升级；联合和声由后续共同视图一次生成并验收实音。
        # apply_structured_patterns(shared,vocal,guitar,Path(args.analysis_dir)/'features')
        if not joint_harmony_enabled:
            apply_structured_patterns(shared,vocal,guitar,Path(args.analysis_dir)/'features')
        guitar['configuration']['enable_vocal_playback']=True
        # 跨歌曲和弦复用与器乐准备：修改，旧中间态校验保留；联合编配在最终实际和声视图中完整验收。
        # pattern_check=validate_patterns(shared,guitar)
        # if pattern_check and not pattern_check['valid']:
        #     raise ValueError('新版右手模板语义校验失败：'+str(pattern_check['errors'][:8]))
        if not joint_harmony_enabled:
            pattern_check=validate_patterns(shared,guitar)
            if pattern_check and not pattern_check['valid']:
                raise ValueError('新版右手模板语义校验失败：'+str(pattern_check['errors'][:8]))
    # 跨歌曲和弦复用与器乐准备：修改，旧条件保留；多个明确升级选项同时出现时仍只生成一次新模板。
    # elif args.common_right_hand or getattr(args,'regular_right_hand',False):
    elif (args.common_right_hand or getattr(args,'regular_right_hand',False)) and not joint_harmony_enabled:
        from guitar_exact_positions import refinger_exact_positions
        refinger_exact_positions(shared,vocal,arrangements['guitar'])
        # 规整分解节奏与延音显示：修改，原只套常用型保留；默认套型与规整拍格合并执行。
        # apply_common_patterns(shared,vocal,arrangements['guitar'])
        apply_regular_patterns(shared,vocal,arrangements['guitar'])
        pattern_check=validate_patterns(shared,arrangements['guitar'])
        if pattern_check and not pattern_check['valid']:
            raise ValueError('右手模板语义校验失败：'+str(pattern_check['errors'][:8]))
    # 小节划分与拍速层级纠错：新增默认读取源SHA的拍层级复核，也提供人工明确的小节长度比例。
    before_vocal=deepcopy(vocal);before_arrangements=deepcopy(arrangements)
    shared,vocal,arrangements=correct_accompaniment_grid(shared,vocal,arrangements,
                         Path(args.analysis_dir)/'features',getattr(args,'bar_length_factor',None))
    rebar_check=compare_sounding_time(before_vocal,before_arrangements,vocal,arrangements)
    if not rebar_check['valid']:raise ValueError('小节重记谱改变实际音乐：'+str(rebar_check['errors'][:8]))
    # 器乐主旋律简化与规整节奏：新增独立编配层，重记谱之后简化器乐；旧普通编辑重导不改变音乐。
    instrumental_check=None
    # 器乐声部恢复与规整节奏：修改，保留v18默认单线触发；旧简化仅显式选择，新编配保留完整声部。
    # if getattr(args,'simplify_instrumental',False) or not args.edited_project or args.rearrange:
    # 跨歌曲和弦复用与器乐准备：修改，保留旧初始化；前置准备结果必须保留，不能重置后重复整理。
    # instrumental_rhythm_check=None
    if getattr(args,'simplify_instrumental',False):
        from instrumental_backbone import simplify_instrumentals
        print('提取前奏/间奏/尾奏主旋律，减少内声部与碎音',flush=True)
        shared,arrangements,instrumental_check=simplify_instrumentals(shared,vocal,arrangements,Path(args.analysis_dir)/'features')
    # 原曲拍轴与歌词拍位通用修复：修改，旧条件保留；源重建也整理器乐时值。
    # elif getattr(args,'regular_instrumental',False) or not args.edited_project or args.rearrange:
    elif getattr(args,'regular_instrumental',False) or fresh_music:
        # 器乐声部恢复与规整节奏：新增独立器乐编配层，沿用旋律/低音/和声，仅重新整理器乐节奏。
        from instrumental_regular_rhythm import regularize_instrumentals
        print('保留器乐旋律、低音和和声，整理规整十六分以上的节奏',flush=True)
        # 跨歌曲和弦复用与器乐准备：修改，保留旧无条件调用；普通历史升级仍走后置路径，新生成只准备一次。
        # shared,arrangements,instrumental_rhythm_check=regularize_instrumentals(shared,vocal,arrangements)
        if instrumental_rhythm_check is None:
            shared,arrangements,instrumental_rhythm_check=regularize_instrumentals(shared,vocal,arrangements)
    # 相似乐句和弦框架复用：新增明确另存升级；新分析/重编默认采用，普通编辑保留人工音乐。
    phrase_harmony_check=None
    # 跨歌曲和弦复用与器乐准备：修改，原重复条件保留；共同使用前面声明的联合规划入口。
    # if getattr(args,'phrase_harmony',False) or not args.edited_project or args.rearrange:
    if joint_harmony_enabled:
        print('联合相似乐句选择稳定和弦进行，两乐器重编实际伴奏',flush=True)
        # 跨曲低音与强拍复用通用修复：新增可回放的编配前诊断快照，边界实音失败必须可逐音追查。
        if vocal.get('source_meter_correction'):
            save_json(Path(args.analysis_dir)/'before_phrase_project.json',
                      {'shared_analysis':shared,'accepted_vocal_project':vocal,'arrangements':arrangements})
        shared,arrangements,phrase_harmony_check=apply_phrase_harmony(shared,vocal,arrangements,Path(args.analysis_dir)/'features')
    # 吉他器乐低把位与指型复用：新增最终拍轴／夹位上的吉他独立规划，认可人声及钢琴不参与重编。
    instrumental_register_check=None
    preserve_piano_from=None
    # 原曲器乐旋律骨干重提取：新增历史工程明确另存的吉他独立修订，源谱旋律改变但认可人声和钢琴不重编。
    source_backbone_check=None
    # 原曲拍轴与歌词拍位通用修复：修改，旧历史开关入口保留；独立源重建沿用通用多音骨干，阶段种子来源真实另存。
    # if getattr(args,'reextract_instrumental_melody',False):
    #     if not args.edited_project or args.rearrange:raise ValueError('历史器乐骨干修订需提供--edited-project，并保留认可正常唱段。')
    if getattr(args,'reextract_instrumental_melody',False) or source_meter_enabled:
        if not source_meter_enabled and (not args.edited_project or args.rearrange):raise ValueError('历史器乐骨干修订需提供--edited-project，并保留认可正常唱段。')
        from instrumental_source_melody import reextract_guitar
        print('从原曲多音证据重新提取器乐骨干，保留吉他低音／和声及认可钢琴',flush=True)
        # 渴首次吉他编配：修改，旧绑定早期编辑工程在组合和弦／节奏升级后失真，原式保留。
        # arrangements['guitar']=reextract_guitar(shared,vocal,arrangements['guitar'],args.edited_project,Path(args.analysis_dir)/'features')
        # 渴首次吉他编配：新增实际重提取前完整来源；纯骨干升级继续沿用真实旧工程，不改旧账本保护。
        backbone_source=source_revision_input(shared,vocal,arrangements,args.edited_project,args.analysis_dir)
        arrangements['guitar']=reextract_guitar(shared,vocal,arrangements['guitar'],backbone_source,Path(args.analysis_dir)/'features')
    if low_instrumental_enabled:
        from guitar_instrumental_register import arrange_instrumental_register,bind_register_source
        # 器乐合理分句与十二品硬限制：新增明确低品升级先恢复真实原音输入；默认旧重导仍按历史来源保护。
        register_upgrade_check = None
        if getattr(args,'low_position_instrumental',False):
            from instrumental_register_upgrade import prepare_register_upgrade
            arrangements['guitar'], register_upgrade_check = prepare_register_upgrade(shared,vocal,arrangements['guitar'])
        if not arrangements['guitar'].get('instrumental_register'):
            arrangements['guitar']['configuration']['instrumental_register_strategy_version'] = 2
            arrangements['guitar']['configuration']['instrumental_register_voicing_version'] = 2
            arrangements['guitar']['configuration']['instrumental_flow_motion_version'] = 2
        work=Path(args.analysis_dir).resolve()
        if not work.is_relative_to(ROOT/'test_outputs'/'accompaniment_runs'):
            raise ValueError('器乐低把位来源缓存需位于test_outputs/accompaniment_runs。')
        # 吉他器乐低把位与指型复用：修改，旧固定缓存名可能覆盖历史绑定；改为内容寻址的只增来源。
        # seed_path=work/'instrumental_register_source.json'
        seed={'shared_analysis':deepcopy(shared),'accepted_vocal_project':deepcopy(vocal),'arrangements':deepcopy(arrangements)}
        from guitar_instrumental_register import fingerprint
        seed_path=work/('instrumental_register_source_'+fingerprint(seed)[:20]+'.json')
        existing_register=bool(arrangements['guitar'].get('instrumental_register'))
        if not existing_register:
            # 吉他器乐低把位与指型复用：修改，旧Python字典比较会误判JSON弦号键的类型；比较规范内容指纹。
            # if seed_path.exists() and read_json(seed_path)!=seed:
            if seed_path.exists() and fingerprint(read_json(seed_path))!=fingerprint(seed):
                raise ValueError('不能覆盖已绑定的器乐来源缓存。')
            if not seed_path.exists():save_json(seed_path,seed)
        print('联合规划吉他器乐音区、基础手型及持续按指，保留全部声部',flush=True)
        arrangements['guitar'],instrumental_register_check=arrange_instrumental_register(shared,vocal,arrangements['guitar'])
        # 器乐合理分句与十二品硬限制：新增实际来源恢复记录，不把既有已降旋律当作新的原音重复降位。
        if register_upgrade_check:
            instrumental_register_check['upgrade_source'] = register_upgrade_check
        # 吉他器乐低把位与指型复用：修改，旧无条件重绑定保留；幂等重导保持第一次的真实来源。
        # bind_register_source(arrangements['guitar'],seed_path,shared,vocal)
        if arrangements['guitar'].get('instrumental_register') and not existing_register:
            bind_register_source(arrangements['guitar'],seed_path,shared,vocal)
        if args.edited_project:
            accepted=read_json(args.edited_project)
            # 吉他器乐低把位与指型复用：新增纯吉他升级使用旧钢琴交付的原字节；有其它明确音乐升级时走正常导出。
            # 渴首次吉他编配：修改，仅双乐器工程复制既有钢琴字节；旧条件保留。
            # if accepted['accepted_vocal_project']==vocal and accepted['shared_analysis']==shared and accepted['arrangements']['piano']==arrangements['piano']:
            if 'piano' in arrangements and 'piano' in accepted['arrangements'] and accepted['accepted_vocal_project']==vocal and accepted['shared_analysis']==shared and accepted['arrangements']['piano']==arrangements['piano']:
                # 原曲拍轴与歌词拍位通用修复：修改，旧直接复制目录保留；先核验钢琴交付包，工作种子走完整导出。
                # preserve_piano_from=Path(args.edited_project).resolve().parent
                preserve_piano_from=piano_copy_source(args.edited_project)
            # 吉他器乐低把位与指型复用：修改，旧无条件覆盖上游保留；已有策略重导不更换原来源。
            # arrangements['guitar']['instrumental_register']['upstream_project']=str(Path(args.edited_project).resolve())
            # arrangements['guitar']['instrumental_register']['upstream_project_sha256']=sha256(args.edited_project)
            if arrangements['guitar'].get('instrumental_register') and not existing_register:
                info=arrangements['guitar']['instrumental_register']
                info['upstream_project']=str(Path(args.edited_project).resolve())
                info['upstream_project_sha256']=sha256(args.edited_project)
                info['upstream_exact_notes']=accepted['arrangements']['guitar']['notes']==seed['arrangements']['guitar']['notes']
    # 器乐低弦分解填充：新增固定实际旋律／手位之后的联合填充，正常唱段与钢琴不参与重编。
    # 器乐填充密度随主体伴奏：新增自动继承同源人工休止复核，新的明确参数仍优先。
    # 器乐合理分句与十二品硬限制：修改，旧继承方式保留；恢复原音后仍保护用户已有休止复核。
    # inherited_rest_review=arrangements['guitar'].get('instrumental_expression',{}).get('review_path') if density_enabled else None
    inherited_rest_review=(arrangements['guitar'].get('instrumental_expression',{}).get('review_path') or
        arrangements['guitar'].get('instrumental_register_upgrade_source',{}).get('inherited_rest_review')) if density_enabled else None
    flow_check=None
    if flow_enabled:
        from guitar_instrumental_flow import apply_flow,validate_flow
        from guitar_instrumental_register import fingerprint
        work=Path(args.analysis_dir).resolve()
        if not work.is_relative_to(ROOT/'test_outputs'/'accompaniment_runs'):
            raise ValueError('低弦填充来源缓存需位于test_outputs/accompaniment_runs。')
        seed={'shared_analysis':deepcopy(shared),'accepted_vocal_project':deepcopy(vocal),'arrangements':deepcopy(arrangements)}
        seed_path=work/('instrumental_flow_source_'+fingerprint(seed)[:20]+'.json')
        if args.edited_project and not args.rearrange and read_json(args.edited_project)['arrangements']['guitar']==arrangements['guitar']:
            seed_path=Path(args.edited_project).resolve()
        elif not seed_path.exists():save_json(seed_path,seed)
        elif fingerprint(read_json(seed_path))!=fingerprint(seed):raise ValueError('不能覆盖低弦织体的真实输入。')
        print('固定器乐骨干，按原曲活动／真实休止联合填充4／5／6弦分解',flush=True)
        # 器乐填充密度随主体伴奏：修改，旧调用保留；版本2按实际正文密度重填充，原强拍／休止／指型约束保持。
        # arrangements['guitar'],_=apply_flow(shared,vocal,arrangements['guitar'],seed_path,work/'features')
        arrangements['guitar'],_=apply_flow(shared,vocal,arrangements['guitar'],seed_path,work/'features',follow_density=density_enabled)
        flow_check=validate_flow(shared,vocal,arrangements['guitar'],replay=True)
        if not flow_check['valid']:raise ValueError('器乐连续织体验收失败：'+str(flow_check['errors'][:8]))
        if args.edited_project:
            accepted=read_json(args.edited_project)
            # 渴首次吉他编配：修改，仅双乐器工程复制既有钢琴字节；旧条件保留。
            # if accepted['accepted_vocal_project']==vocal and accepted['shared_analysis']==shared and accepted['arrangements']['piano']==arrangements['piano']:
            if 'piano' in arrangements and 'piano' in accepted['arrangements'] and accepted['accepted_vocal_project']==vocal and accepted['shared_analysis']==shared and accepted['arrangements']['piano']==arrangements['piano']:
                # 原曲拍轴与歌词拍位通用修复：修改，旧直接复制目录保留；只有完整清单有效才复制钢琴。
                # preserve_piano_from=Path(args.edited_project).resolve().parent
                preserve_piano_from=piano_copy_source(args.edited_project)
    # 器乐背景休止与旋律突出：新增在全部编配完成后独立处理休止与力度，保持已认可人声／时轴／正常唱段。
    expression_check=None
    if expression_enabled:
        from guitar_instrumental_expression import apply_expression,validate_expression
        from guitar_instrumental_register import fingerprint
        work=Path(args.analysis_dir).resolve()
        if not work.is_relative_to(ROOT/'test_outputs'/'accompaniment_runs'):
            raise ValueError('器乐表现来源缓存必须位于项目分析目录。')
        seed={'shared_analysis':deepcopy(shared),'accepted_vocal_project':deepcopy(vocal),'arrangements':deepcopy(arrangements)}
        if args.edited_project and fingerprint(read_json(args.edited_project)['arrangements']['guitar'])==fingerprint(arrangements['guitar']):
            expression_source=Path(args.edited_project).resolve()
        else:
            expression_source=work/('instrumental_expression_source_'+fingerprint(seed)[:20]+'.json')
            if expression_source.exists() and fingerprint(read_json(expression_source))!=fingerprint(seed):
                raise ValueError('不能覆盖器乐表现层真实输入。')
            if not expression_source.exists():save_json(expression_source,seed)
        # 器乐背景休止与旋律突出：修改，旧仅复核窗口调用保留；每首新编配／明确升级均自动筛选原音频背景。
        # print('应用已复核器乐休止、旋律黑点重音和弱化低弦填充',flush=True)
        # arrangements['guitar'],_=apply_expression(shared,vocal,arrangements['guitar'],expression_source,
        #     getattr(args,'instrumental_rest_review',None))
        print('自动筛选杂乱背景，突出器乐主旋律并弱化低弦填充',flush=True)
        arrangements['guitar'],_=apply_expression(shared,vocal,arrangements['guitar'],expression_source,
            # 器乐填充密度随主体伴奏：修改，旧仅CLI复核参数保留；密度升级仍继承用户原复核范围。
            # getattr(args,'instrumental_rest_review',None),clarity_dir=work/'instrumental_clarity')
            getattr(args,'instrumental_rest_review',None) or inherited_rest_review,clarity_dir=work/'instrumental_clarity')
        expression_check=validate_expression(shared,vocal,arrangements['guitar'],replay=True)
        if not expression_check['valid']:raise ValueError('器乐表现核验失败：'+str(expression_check['errors'][:6]))
        # 器乐背景休止与旋律突出：新增纯吉他表现升级继续保留已有钢琴的原始交付字节。
        if args.edited_project and 'piano' in arrangements:
            accepted=read_json(args.edited_project)
            if accepted['accepted_vocal_project']==vocal and accepted['shared_analysis']==shared and accepted['arrangements'].get('piano')==arrangements['piano']:
                # 原曲拍轴与歌词拍位通用修复：修改，旧直接复制目录保留；只有完整清单有效才复制钢琴。
                # preserve_piano_from=Path(args.edited_project).resolve().parent
                preserve_piano_from=piano_copy_source(args.edited_project)
    # 旧工程功能自动升级与三曲器乐表现统一：新增所有正常重导出的通用能力检查；缺少器乐重音时最小升级，不重筛背景／节奏。
    from accompaniment_project_upgrade import ensure_project_features,delivery_capabilities
    # 旧工程功能自动升级与三曲器乐表现统一：删除局部重复导入，原行保留；使用模块级deepcopy避免前段局部变量未初始化。
    # from copy import deepcopy
    feature_work=Path(args.analysis_dir).resolve()
    if not feature_work.is_relative_to(ROOT/'test_outputs'/'accompaniment_runs'):
        raise ValueError('旧工程功能升级缓存需位于test_outputs/accompaniment_runs。')
    arrangements,feature_upgrade=ensure_project_features(shared,vocal,arrangements,args.edited_project,feature_work)
    feature_upgrade['restored_missing_fields']=feature_load_repairs
    # 原声覆盖与选音归属通用修复：新增显式来源复核保留入口；通用修复先完整生成，再保护用户认可的段落。
    if getattr(args,'approved_section_review',None):
        from approved_music_sections import preserve_sections
        shared,vocal,arrangements=preserve_sections(shared,vocal,arrangements,args.approved_section_review,feature_work)
    if feature_upgrade['changed'] and args.edited_project and 'piano' in arrangements:
        accepted=read_json(args.edited_project)
        if accepted['accepted_vocal_project']==vocal and accepted['shared_analysis']==shared and accepted['arrangements'].get('piano')==arrangements['piano']:
            # 原曲拍轴与歌词拍位通用修复：修改，旧直接复制目录保留；缺少钢琴交付的工作种子完整导出。
            # preserve_piano_from=Path(args.edited_project).resolve().parent
            preserve_piano_from=piano_copy_source(args.edited_project)
    # 原曲器乐旋律骨干重提取：新增实际源证据与修订范围验收，导出前失败便不交付新谱。
    if arrangements['guitar'].get('instrumental_source_backbone'):
        from instrumental_source_melody import validate_source_backbone
        source_backbone_check=validate_source_backbone(shared,vocal,arrangements['guitar'],replay=True)
        if not source_backbone_check['valid']:raise ValueError('器乐原曲骨干修订核验失败：'+str(source_backbone_check['errors'][:8]))
    # 器乐合理分句与十二品硬限制：新增最终实际音符硬检查，后续填充和谱面派生也不得越过12品。
    instrumental_fret_limit = None
    if arrangements['guitar'].get('instrumental_register',{}).get('version') == 2:
        from guitar_instrumental_register import require_instrumental_fret_limit
        instrumental_fret_limit = require_instrumental_fret_limit(shared,arrangements['guitar'])
    for name,arrangement in arrangements.items():
        validation=validate_playability(arrangement,SongClock(vocal))
        if not validation['valid']:raise ValueError(name+'编辑/编配违反演奏约束：'+str(validation['errors'][:8]))
    # 原声覆盖与选音归属通用修复：新增最终源覆盖门槛，避免后级模板或可弹性修复再次删成整小节休止。
    from source_accompaniment_quality import validate_source_coverage
    source_coverage_check=validate_source_coverage(shared,vocal,arrangements)
    if not source_coverage_check['valid']:raise ValueError('原声覆盖检查未通过：'+str(source_coverage_check['errors'][:8]))
    # 尾段原声局部补证：新增首次来源v2统一末阶段，先执行既有稳定右手／长段读法再导三套谱；旧工程和历史导出流程保持。
    if fresh_music and not args.edited_project and vocal.get('first_source_meter_correction',{}).get('version')==2:
        from first_generation_delivery import finish_first_delivery
        print('首次交付先验稳定右手与长段复用，再导出简谱及所选乐器',flush=True)
        # 尾段原声局部补证：修改新末阶段同样保存CLI要求的报告，不能只有返回码而没有实际交付证据。
        # return finish_first_delivery(shared,vocal,arrangements,Path(args.analysis_dir),output)
        # 4/4可选右手与实时谱面试听：修改首次末阶段传递同一选择，未传保持旧调用及行为。
        # result=finish_first_delivery(shared,vocal,arrangements,Path(args.analysis_dir),output)
        if right_hand_plan is None:
            result=finish_first_delivery(shared,vocal,arrangements,Path(args.analysis_dir),output)
        else:
            result=finish_first_delivery(shared,vocal,arrangements,Path(args.analysis_dir),output,right_hand_plan=right_hand_plan)
        if args.report:save_json(args.report,result)
        return result
    # 4/4可选右手与实时谱面试听：新增其它已校准首次路线也接同一最终选择，不允许计划被普通导出忽略。
    if right_hand_plan is not None:
        staged=source_revision_input(shared,vocal,arrangements,None,Path(args.analysis_dir))
        from revise_guitar_selection import revise_selection
        result=revise_selection(staged,output,right_hand_plan,getattr(args,'readability_feature_cache',None))
        if args.report:save_json(args.report,result)
        return result
    protected=protect_existing(shared,output)
    if args.edited_project:protected[str(Path(args.edited_project).resolve())]=sha256(args.edited_project)
    print('导出谱面/试听并独立读回',flush=True)
    # 吉他器乐低把位与指型复用：修改，原两套全部重渲染保留；纯吉他升级可原字节保留钢琴部分。
    # result=export_all(output,shared,vocal,arrangements)
    # 重复乐句折叠与多遍挂词：修改正式导出，旧调用保留；新编配默认输出反复阅读页，旧工程需明确另存。
    # result=export_all(output,shared,vocal,arrangements,preserve_piano_from=preserve_piano_from)
    # 旧工程功能自动升级与三曲器乐表现统一：修改导出调用，旧入口保留；原人声完全相同时复用原唱交付字节。
    # result=export_all(output,shared,vocal,arrangements,preserve_piano_from=preserve_piano_from,fold_repeats=fold_repeats_enabled)
    preserve_vocals_from=None
    if args.edited_project:
        accepted=read_json(args.edited_project);source_folder=Path(args.edited_project).resolve().parent
        if accepted['accepted_vocal_project']==vocal and (source_folder/'audio/vocals_aligned.wav').is_file():preserve_vocals_from=source_folder
    result=export_all(output,shared,vocal,arrangements,preserve_piano_from=preserve_piano_from,
        fold_repeats=fold_repeats_enabled,preserve_vocals_from=preserve_vocals_from)
    # 旧工程功能自动升级与三曲器乐表现统一：新增能力清单与迁移记录到顶层，原音符账本格式保持。
    result['project_feature_upgrade']=feature_upgrade
    # 原声覆盖与选音归属通用修复：新增实际源覆盖验收结果，和文件／指法校验分开登记。
    result['source_coverage_quality']=source_coverage_check
    # 默认入口原曲节拍强制复核：新增交付报告记录检查依据及是否自动纠拍，不把校正层重放说成全新识别已认证。
    result['source_meter_entry_check']={'input':source_entry_input,
        'ready':source_entry_ready if fresh_music else source_entry_input,
        'automatic_rebuild':bool((source_entry_input or {}).get('automatic_rebuild_requested'))}
    feature_project=read_json(output/'project.json')
    # 器乐合理分句与十二品硬限制：新增读回真实导出工程的第二道硬检查，绘图或导出派生不能重新带入高品。
    if instrumental_fret_limit is not None:
        instrumental_fret_limit = require_instrumental_fret_limit(feature_project['shared_analysis'],
            feature_project['arrangements']['guitar'])
    feature_project['feature_capabilities']=delivery_capabilities(feature_upgrade,result.get('guitar_repeat_layout'))
    feature_project['last_feature_upgrade']=feature_upgrade
    save_json(output/'project.json',feature_project)
    if instrumental_register_check is not None:
        result['instrumental_register']=instrumental_register_check
    # 原曲器乐旋律骨干重提取：新增交付报告，源音符重解与只改八度的验收分别记录。
    if source_backbone_check is not None:result['instrumental_source_backbone']=source_backbone_check
    # 器乐低弦分解填充：新增最终交付报告，新增编配和原曲骨干验证分别记录。
    if flow_check is not None:result['instrumental_flow']=flow_check
    # 器乐背景休止与旋律突出：新增交付中明确休止、重音及弱填充的实际数量，与音高识别结论区分。
    if expression_check is not None:result['instrumental_expression']=expression_check
    # 相似乐句和弦框架复用：新增导出后保护及实音复核，指型派生也不能修改已认可器乐。
    if shared.get('phrase_harmony_plan',{}).get('phrases'):
        phrase_harmony_check=validate_phrase_harmony(shared,vocal,arrangements)
        if not phrase_harmony_check['valid']:raise ValueError('共同和弦导出后实音校验失败：'+str(phrase_harmony_check['errors'][:8]))
    if phrase_harmony_check is not None:result['phrase_harmony']=phrase_harmony_check
    # 器乐主旋律简化与规整节奏：新增有意简化的实音审计，不能将器乐改写误称为全部音乐未变。
    if instrumental_check is not None:
        result['instrumental_simplification']=instrumental_check
    # 器乐声部恢复与规整节奏：新增实音密度/低音保持/时序整理审计，明确器乐音源与谱面一同更新。
    if instrumental_rhythm_check is not None:
        result['instrumental_rhythm']=instrumental_rhythm_check
    # 小节划分与拍速层级纠错：新增导出后的实音时间证明，旧版的源工程仍受SHA保护。
    result['metrical_grid']={'correction':vocal.get('grid_correction'), 'sounding_time':rebar_check}
    # 连续唱段拍轴与原唱同步修复：新增源音乐绝对残差验收，与文件编码/同启校验分开记录。
    if vocal.get('performance_clock_correction'):
        result['performance_beat_clock']=deepcopy(vocal['performance_clock_correction']['clock_evidence']['music_residual_check'])
    # 强拍相位与伴奏同步纠错：新增真实拍点校验，不能以简谱/TAB同刻中心相等代替音乐时序正确。
    # 强拍相位与伴奏同步纠错：修改，原只核人声保留；再验证实际低音循环与和弦开始。
    # from beat_phase_alignment import validate_reviewed_beats
    # 强拍相位与伴奏同步纠错：修改，原仅吉他核验保留；钢琴实际换和弦起音也必须同步。
    # from beat_phase_alignment import validate_reviewed_beats,validate_beat_synchrony
    from beat_phase_alignment import validate_reviewed_beats,validate_beat_synchrony,validate_piano_beats
    result['reviewed_vocal_beats']=validate_reviewed_beats(vocal)
    # 相似乐句和弦框架复用：修改，原分析拍点入口保留；实际编配拍点必须核查派生共同进行。
    # result['beat_synchrony']=validate_beat_synchrony(shared,vocal,arrangements['guitar'])
    performed_shared=arrangement_view(shared,vocal)
    result['beat_synchrony']=validate_beat_synchrony(performed_shared,vocal,arrangements['guitar'])
    # 相似乐句和弦框架复用：新增在拒绝交付前选择正确拍号验证；四分拍旧验证不用于复合拍降级。
    # 跨歌曲和弦复用与器乐准备：修改，旧选择保留；固定短边界采用逐音保护验收，新音仍必须在正拍先弹低音。
    # phrase_pulse_upgrade=bool(shared.get('phrase_harmony_plan',{}).get('phrases')) and (
    #     shared['timing']['meter'] != [4,4] or any(p['action'].startswith('preserve_source') for p in shared['phrase_harmony_plan']['phrases']))
    phrase_pulse_upgrade=needs_joint_pulse_validation(shared)
    if phrase_pulse_upgrade:
        joint_beats=validate_phrase_harmony(shared,vocal,arrangements)
        result['beat_synchrony']={**joint_beats,'scope':'new_accompaniment_at_actual_meter_pulses_and_frozen_source'}
    if result['beat_synchrony'] and not result['beat_synchrony']['valid']:
        raise ValueError('伴奏强拍实音校验失败：'+str(result['beat_synchrony']['errors'][:8]))
    # 相似乐句和弦框架复用：修改，原钢琴分析入口保留；双手伴奏与吉他共用实际和声。
    # result['piano_beat_synchrony']=validate_piano_beats(shared,arrangements['piano'])
    # 渴首次吉他编配：修改，钢琴强拍核验仅用于实际交付钢琴，吉他强拍核验保持；原代码注释保留。
    # result['piano_beat_synchrony']=validate_piano_beats(performed_shared,arrangements['piano'])
    # # 相似乐句和弦框架复用：新增其它拍号/缺证据保留范围的独立入口，旧验证器只定义四分正拍。
    # # 相似乐句和弦框架复用：修改，旧过晚的双乐器选择保留；吉他已在失败判断之前选好验证器。
    # # if shared.get('phrase_harmony_plan',{}).get('phrases') and (
    # #         shared['timing']['meter'] != [4,4] or any(p['action'].startswith('preserve_source') for p in shared['phrase_harmony_plan']['phrases'])):
    # #     joint_beats=validate_phrase_harmony(shared,vocal,arrangements)
    # #     result['beat_synchrony']={**joint_beats,'scope':'new_accompaniment_at_actual_meter_pulses_and_frozen_source'}
    # if phrase_pulse_upgrade:
    #     result['piano_beat_synchrony']={**joint_beats,'scope':'new_accompaniment_at_actual_meter_pulses_and_frozen_source'}
    # if result['piano_beat_synchrony'] and not result['piano_beat_synchrony']['valid']:
    #     raise ValueError('钢琴强拍实音校验失败：'+str(result['piano_beat_synchrony']['errors'][:8]))
    # 渴首次吉他编配：新增按所选乐器执行，保留各乐器原验证。
    if 'piano' in arrangements:
        result['piano_beat_synchrony']=validate_piano_beats(performed_shared,arrangements['piano'])
        # 相似乐句和弦框架复用：新增其它拍号/缺证据保留范围的独立入口，旧验证器只定义四分正拍。
        # 相似乐句和弦框架复用：修改，旧过晚的双乐器选择保留；吉他已在失败判断之前选好验证器。
        # if shared.get('phrase_harmony_plan',{}).get('phrases') and (
        #         shared['timing']['meter'] != [4,4] or any(p['action'].startswith('preserve_source') for p in shared['phrase_harmony_plan']['phrases'])):
        #     joint_beats=validate_phrase_harmony(shared,vocal,arrangements)
        #     result['beat_synchrony']={**joint_beats,'scope':'new_accompaniment_at_actual_meter_pulses_and_frozen_source'}
        if phrase_pulse_upgrade:
            result['piano_beat_synchrony']={**joint_beats,'scope':'new_accompaniment_at_actual_meter_pulses_and_frozen_source'}
        if result['piano_beat_synchrony'] and not result['piano_beat_synchrony']['valid']:
            raise ValueError('钢琴强拍实音校验失败：'+str(result['piano_beat_synchrony']['errors'][:8]))
    # 强拍相位与伴奏同步纠错：新增修正后独立人声谱交付，和弦谱和独立简谱使用相同量化工程。
    # 局部拍轴与原唱同步纠错：修改，原已复核样曲条件保留；其它具有可靠局部拍轴的歌曲同样交付独立人声谱。
    # if vocal.get('beat_phase_correction'):
    # 连续源拍序与人声联合重解通用修复：修改，原交付条件保留；独立新人声谱也必须用最后的共同拍轴。
    # if vocal.get('beat_phase_correction') or vocal.get('local_clock_correction'):
    # 人声连续音值与长休止漏音通用修复：修改，旧交付条件注释保留；仅局部声学升级也交付对应独立人声谱／MIDI。
    # if vocal.get('beat_phase_correction') or vocal.get('local_clock_correction') or vocal.get('continuous_meter_correction'):
    # 原曲拍轴与歌词拍位通用修复：修改，旧只有部分校正分支才导简谱的条件保留；独立源层和显式简谱请求均正式导出。
    # if vocal.get('beat_phase_correction') or vocal.get('local_clock_correction') or vocal.get('continuous_meter_correction') or vocal.get('vocal_continuity_correction'):
    if vocal.get('beat_phase_correction') or vocal.get('local_clock_correction') or vocal.get('continuous_meter_correction') or vocal.get('vocal_continuity_correction') or vocal.get('source_meter_rebuild_correction') or getattr(args,'export_vocal',False):
        from beat_phase_alignment import export_phase_vocal
        # 器乐背景休止与旋律突出：修改，旧直接输出包含背景误识别的参考人声保留；认可快照不改，只按复核显示参考休止。
        # result['vocal_delivery']=export_phase_vocal(output,vocal)
        from guitar_instrumental_expression import reference_vocal
        result['vocal_delivery']=export_phase_vocal(output,reference_vocal(vocal,arrangements['guitar']))
    after={path:sha256(path) for path in protected};changed=[path for path,digest in protected.items() if after[path]!=digest]
    if changed:raise ValueError('受保护原成果改变：'+str(changed[:5]))
    # 器乐合理分句与十二品硬限制：新增最终而非中间配音的低品统计进入正式交付报告。
    if instrumental_fret_limit is not None:
        result['instrumental_fret_limit'] = instrumental_fret_limit
    result['preservation']={'checked_file_count':len(protected),'all_sha256_unchanged':True,'files':protected}
    result['elapsed_seconds']=time.perf_counter()-started
    save_json(output/'validation.json',result)
    save_json(output/'manifest.json',{'schema_version':1,'files':[{'path':str(p.relative_to(output)).replace('\\','/'),
                      'sha256':sha256(p),'bytes':p.stat().st_size} for p in sorted(output.rglob('*')) if p.is_file() and p.name!='manifest.json']})
    if args.report:
        report=Path(args.report).resolve()
        if not report.is_relative_to(ROOT/'reports'/'accompaniment'):raise ValueError('报告需位于reports/accompaniment。')
        save_json(report,result)
    parent=output.parent
    if parent==ROOT/'results'/'accompaniment':
        # 强拍相位与伴奏同步纠错：修改，原字典序索引保留；当前新版在前，其余历史链接保留。
        # links=[]
        # for path in sorted(parent.glob('*/index.html')):
        #     from urllib.parse import quote
        #     links.append('<p><a href="'+quote(path.relative_to(parent).as_posix())+'">'+path.parent.name+'</a></p>')
        # (parent/'index.html').write_text(html_page('和弦弹唱与伴奏谱','<h1>和弦弹唱与伴奏谱</h1>'+''.join(links)),encoding='utf-8')
        write_collection_index(parent,output/'index.html')
    # 渴首次吉他编配：修改，结果统计准确列出所选乐器；原代码注释保留。
    # print(json.dumps({'output':str(output),'status':result['status'],'seconds':result['elapsed_seconds'],
    #                   'protected_files':len(protected),'guitar_notes':len(arrangements['guitar']['notes']),
    #                   'piano_notes':len(arrangements['piano']['notes'])},ensure_ascii=False),flush=True)
    # 渴首次吉他编配：新增按所选乐器执行，保留各乐器原验证。
    print(json.dumps({'output':str(output),'status':result['status'],'seconds':result['elapsed_seconds'],
        'protected_files':len(protected),'instruments':list(arrangements),
        **{name+'_notes':len(arr['notes']) for name,arr in arrangements.items()}},ensure_ascii=False),flush=True)
    return result


# 和弦弹唱与伴奏编配：新增命令参数，与既有run_score独立，支持直接复用缓存和编辑重导。
def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vocal-project',type=Path);parser.add_argument('--demucs-report',type=Path)
    parser.add_argument('--reference',type=Path,action='append',default=[]);parser.add_argument('--binding',type=Path)
    # 渴首次吉他编配：修改，新增明确的仅吉他命令入口，默认双乐器兼容；原代码注释保留。
    # parser.add_argument('--shared-analysis',type=Path);parser.add_argument('--six-sources',action='store_true')
    # 渴首次吉他编配：新增按所选乐器执行，保留各乐器原验证。
    parser.add_argument('--shared-analysis',type=Path);parser.add_argument('--six-sources',action='store_true')
    parser.add_argument('--guitar-only',action='store_true',help='新编配仅生成吉他谱与原唱合播；仍保留完整分轨分析及吉他演奏／时序核验。')
    parser.add_argument('--analysis-dir',type=Path,default=ROOT/'test_outputs'/'accompaniment_runs'/'current')
    parser.add_argument('--capo',type=int,choices=range(0,8));parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--report',type=Path);parser.add_argument('--edited-project',type=Path);parser.add_argument('--rearrange',action='store_true')
    # 吉他编配规则与统一验收修复：新增主入口专用编配阶段，固定拍轴／原和声／钢琴，真实共用验收后仅隔离另存。
    parser.add_argument('--readable-guitar',action='store_true',help='固定已有拍轴、人声和原和声材料，规整吉他和弦／十六分／长段复用；只另存隔离候选及试听。')
    # 演唱段稳定右手型：新增明确演唱伴奏范围，不与器乐、原和声或正常入口混在一起。
    parser.add_argument('--stable-vocal-patterns',action='store_true',help='在已认可拍轴与和弦上，整段使用简单固定右手型；保护人声／钢琴／器乐并隔离另存。')
    # 4/4可选右手与实时谱面试听：新增显式版本化选择计划，已有工程与首次末阶段共用。
    parser.add_argument('--right-hand-plan',type=Path,help='4/4右手型、时值与演唱段选择JSON；按原拍轴另存新谱及试听。')
    parser.add_argument('--readability-feature-cache',type=Path,help='可读吉他修订所用来源SHA绑定的原声特征缓存。')
    # 慢拍单位与两曲最小修订：新增通用单位决定和只读缓存参数，不使用歌名或固定秒数选择路径。
    parser.add_argument('--meter-unit-decision', type=Path, help='来源可重放的慢／快拍决定；保留旧词音、音高、和弦与秒坐标，局部整理后另存。')
    parser.add_argument('--meter-features-from', type=Path, action='append', default=[], help='只读原声缓存；缺失时停止，不整曲重分析。')
    # 首次生成自动拍轴交接：新增只接原始声学／节拍缓存的复用参数，不接收裸BPM或人工passed。
    parser.add_argument('--source-meter-evidence', type=Path, help='首次生成使用的来源绑定匿名原声包；每次重放判断，不包含人工答案。')
    parser.add_argument('--source-meter-model-cache', type=Path, help='首次生成只读原始混音节拍模型缓存，仍重新比较候选。')
    # 尾段原声局部补证：新增严格绑定且可重放的首次决定输入，不能借它覆盖已有曲谱。
    parser.add_argument('--first-source-decision', type=Path, help='首次输入沿用已验证拍轴决定及局部补证；必须由原音／缓存重放通过，不接受裸BPM或自填通过。')
    # 首拍与首尾局部补证：新增显式局部词音输入，不能直接接受整曲改写人声。
    parser.add_argument('--first-source-words',type=Path,help='已验首次拍轴之后的局部Tifa词音补证，沿原音高和完整音值重放。')
    # 重复乐句折叠与多遍挂词：新增跨曲通用反复阅读版入口，不强迫旧工程的普通重导改排版。
    parser.add_argument('--fold-repeats',action='store_true',help='将伴奏逐音等价的重复乐句折叠，各遍简谱／歌词上下排列；保留完整展开谱、原曲顺序MIDI和原唱合播，并另存。')
    # 完整乐句与实际时长复用：新增冻结全部音乐的吉他阅读刷新参数，候选、显示与验收仍调用通用程序。
    parser.add_argument('--refresh-reading',action='store_true',help='保持已有全部音乐与试听，只按完整乐句和实际时长刷新吉他阅读谱；另存隔离版本。')
    # 局部两拍过渡听辨修订：新增来源绑定的局部听辨文件参数，禁止以歌名或固定秒数内置补丁。
    parser.add_argument('--bar-boundary-review',type=Path,help='按绑定原音的听辨记录局部重排2／4拍小节；保持全部音乐和试听，另存简谱及吉他谱。')
    # 常用右手伴奏型：新增可将既有编配另存为常用右手型，普通编辑默认保留已有音序。
    parser.add_argument('--common-right-hand',action='store_true')
    # 规整分解节奏与延音显示：新增既有工程规整右手节奏的显式另存入口。
    # 结构稳定伴奏与人声合播：修改，原代码注释保留。
    # parser.add_argument('--regular-right-hand',action='store_true')
    parser.add_argument('--regular-right-hand',action='store_true')
    # 结构稳定伴奏与人声合播：新增旧工程显式升级，默认保留人工音乐编辑。
    parser.add_argument('--structured-accompaniment',action='store_true')
    # 强拍相位与伴奏同步纠错：新增旧工程显式另存纠错，普通编辑重导仍保留人工时序。
    parser.add_argument('--correct-beat-phase',action='store_true')
    # 乐句节奏与音值分组：新增旧工程显式升级入口，普通人工编辑重导仍保持原音乐。
    parser.add_argument('--phrase-rhythm',action='store_true',help='从绑定原音段重新推断乐句节奏、规范音值并另存。')
    # 局部拍轴与原唱同步纠错：新增旧工程的明确升级开关，新编配默认按原曲多轨校准。
    parser.add_argument('--local-beat-clock',action='store_true',help='从同源多轨重建局部拍轴，联合歌词节奏后另存；原唱保持原时间。')
    # 通用段落强拍与乐句节奏修复：新增旧工程明确升级开关；新编配默认采用同源音乐结构候选。
    parser.add_argument('--structural-rhythm',action='store_true',help='用相似旋律校验段落拍数，联合短音组/三连音并另存新版。')
    # 连续唱段拍轴与原唱同步修复：新增历史工程明确升级参数；普通编辑重导继续保护人工音乐。
    parser.add_argument('--performance-beat-clock',action='store_true',help='保留谱面，联合原曲完整频段脉冲与原唱校准连续拍秒，重编伴奏另存。')
    # 连续源拍序与人声联合重解通用修复：新增历史明确升级与源绑定未决保留，新生成默认连续联合策略。
    parser.add_argument('--continuous-meter',action='store_true',help='从原伴奏连续攻击联合判断拍序与首拍，再重新求解人声音值／挂字，另存共同编配。')
    # 原曲拍轴与歌词拍位通用修复：新增旧工程明确源重建和独立简谱请求；新曲默认前置源校准，普通旧工程重导保持。
    parser.add_argument('--rebuild-source-meter',action='store_true',help='从原轨独立重建拍速／小节首拍和有声歌词，再重新编配；现有版本保持，新输出另存。')
    parser.add_argument('--export-vocal',action='store_true',help='正式输出与两套伴奏同一工程的独立人声简谱／MIDI／XML，不要求先执行校正分支。')
    # 原声覆盖与选音归属通用修复：新增通用用户认可段落保留参数，复核JSON绑定原工程SHA，不接受歌曲专用规则。
    parser.add_argument('--approved-section-review',type=Path,help='同源／同拍轴原工程的用户认可段落清单；保留音符、力度、弦品和持续音，完整验证后另存。')
    parser.add_argument('--rhythm-review',type=Path,help='来源绑定的人工未决记谱保留清单；不能拿参考谱答案代替源推断。')
    # 人声连续音值与长休止漏音通用修复：新增旧工程明确升级，默认不改变原拍轴／伴奏，恢复音符需独立原声证据。
    parser.add_argument('--vocal-continuity',action='store_true',help='复核源休止里的可靠连续人声及相邻字音值，保留拍轴并另存新版。')
    # 器乐主旋律简化与规整节奏：新增已有工程的显式另存开关；新编配默认突出器乐旋律主线。
    parser.add_argument('--simplify-instrumental',action='store_true',help='从同源多轨提取器乐主线，简化前奏/间奏/尾奏，演唱段与拍轴保持并另存。')
    # 器乐声部恢复与规整节奏：新增旧工程另存完整声部规整入口；新生成默认该策略，单线选项仍可显式复现。
    parser.add_argument('--regular-instrumental',action='store_true',help='保留前奏/间奏/尾奏旋律、低音和必要和声，减少附点/切分，最小十六分并另存。')
    # 吉他器乐低把位与指型复用：新增历史工程明确升级参数，正常唱段／人声／钢琴保持。
    # 器乐合理分句与十二品硬限制：修改，旧帮助保留；明确升级恢复源音、合理分句、12品失败即停止。
    # parser.add_argument('--low-position-instrumental',action='store_true',help='以自然旋律动机联合选吉他器乐八度、低品弦位和连续按指，保留全部声部并另存。')
    parser.add_argument('--low-position-instrumental',action='store_true',help='从真实器乐来源按合理乐句统一选八度，优先0–4品、硬限制12品，重做填充／试听并另存；失败不放宽。')
    # 原曲器乐旋律骨干重提取：新增跨歌曲历史工程的显式升级入口，默认普通重导仍保留人工编辑。
    parser.add_argument('--reextract-instrumental-melody',action='store_true',help='从原曲分轨多音证据重提取吉他器乐骨干，保留低音／和声、人声、正常唱段和钢琴，并另存。')
    # 器乐低弦分解填充：新增明确升级入口，固定正确骨干、保护真实休止并另存吉他连续织体。
    parser.add_argument('--instrumental-flow',action='store_true',help='固定器乐主线，依据原伴奏活动与真实休止，用4／5／6弦规整分解填充空拍；人声、唱段和钢琴保持。')
    # 器乐填充密度随主体伴奏：新增历史工程显式另存的通用升级入口，密度从同曲正常伴奏判断。
    parser.add_argument('--instrumental-flow-density',action='store_true',help='前奏／间奏／尾奏低弦填充跟随稳定主歌／副歌的四分、八分或十六分密度，保持器乐骨干、背景休止和原唱。')
    # 器乐背景休止与旋律突出：新增历史工程显式表现升级及源SHA绑定的人工休止复核入口。
    parser.add_argument('--instrumental-expression',action='store_true',help='器乐主旋律加黑点重音并增强力度，低弦填充稍弱；历史工程另存，正常唱段保持。')
    parser.add_argument('--instrumental-rest-review',type=Path,help='与原曲SHA绑定的背景／休止复核JSON；不采用固定歌曲名或默认前20秒。')
    # 相似乐句和弦框架复用：新增已有工程明确升级，正常重导不擅自覆盖人工伴奏。
    parser.add_argument('--phrase-harmony',action='store_true',help='从音乐骨干与多轨证据规划相似乐句共同和弦，保护人声和器乐，两乐器另存新实音。')
    # 小节划分与拍速层级纠错：新增通用重记谱入口；2表示原小节长度两倍，保持4/4与真实播放速度。
    parser.add_argument('--bar-length-factor',type=float,choices=(.5,1.,2.),
                        help='按人工复核修正小节时长比例；默认采用同源SHA的已确认层级，未知曲不自动减半。')
    # 首次生成自动拍轴交接：修改命令行未决为带证据路径的结构化返回，仍返回非零且不导出伴奏。
    # generate(parser.parse_args())
    args=parser.parse_args()
    from first_generation_source import UnresolvedFirstSource
    try:
        generate(args)
    except UnresolvedFirstSource as error:
        result={'status':'needs_review','stage':'first_generation_source_clock',
                'decision_path':error.decision_path,'issues':error.decision['issues'],
                'normal_publication_allowed':False,'accompaniment_generated':False}
        if getattr(args,'report',None):save_json(args.report,result)
        print(json.dumps(result,ensure_ascii=False),flush=True)
        raise SystemExit(2)


if __name__=='__main__':main()
