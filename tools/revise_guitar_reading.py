"""完整乐句与实际时长复用：复制已核验完整音乐，仅刷新吉他阅读谱。"""
# 完整乐句与实际时长复用：新增公开冻结重导入口，禁止调用音高、节拍、和弦或编配器。
from copy import deepcopy
from pathlib import Path
import shutil

from score_export import read_json, save_json, sha256
from source_timing_acceptance import require_isolated_output

ROOT = Path(__file__).resolve().parents[1]


def verify_reading_source(project, source):
    # 局部两拍过渡听辨修订：新增已复核小节层的来源重放，不能复制旧分组或绕过原音乐保护。
    if project.get('bar_boundary_revision'):
        from reviewed_bar_boundaries import verify_revision
        return verify_revision(project)
    # 完整乐句与实际时长复用：新增区分最高层时间修订和旧拍轴派生；冻结重导不能拿旧层否定后续已确认词音。
    voice = project['accepted_vocal_project']; binding = project['shared_analysis']['input_binding']
    # 首次生成自动拍轴交接：新增新源冻结重导先重放自身决定，不用旧人工时间修订祖先替它验收。
    if voice.get('first_source_meter_correction'):
        # 尾段原声局部补证：新增冻结重导仍检查实际尾响无假新音，不只重放人声拍轴标记。
        if voice['first_source_meter_correction'].get('version')==2:
            from first_generation_tail import require_terminal_arrangements
            require_terminal_arrangements(project['shared_analysis'],voice,project['arrangements'])
        from source_meter_entry import require_calibrated_source
        return require_calibrated_source(voice, binding)
    if voice.get('meter_unit_correction'):
        from meter_unit_entry import verify_projected_shared
        verify_projected_shared(project)
    elif voice.get('time_only_revision'):
        from revise_guitar_readability import protected_baseline
        from guitar_source_bass_acceptance import require_changed_bass_source
        # 完整乐句与实际时长复用：新增沿可信祖先和完整音乐摘要核验，孤立time_only标记不能绕过检查。
        require_changed_bass_source(project, project.get('guitar_source_bass_acceptance'))
        protected_baseline(project, source)
        origin = project.get('readability_source', {})
        ancestor = Path(origin.get('project', ''))
        if not ancestor.is_file() or sha256(ancestor) != origin.get('project_sha256'):
            raise ValueError('冻结阅读的词音来源已改变或缺失')
        base = read_json(ancestor)
        if (base['accepted_vocal_project'] != voice or
                base['shared_analysis']['input_binding'] != binding):
            raise ValueError('冻结阅读的最高层词音与受保护来源不一致')
        for role, row in binding['sources'].items():
            if sha256(row['path']) != row['sha256']:
                raise ValueError('冻结阅读的原音来源已改变：' + role)
        return {'status': 'verified_frozen_time_revision', 'source_project': str(ancestor),
                'scope': 'unchanged_confirmed_material_not_new_clock_or_music_acceptance'}
    from source_meter_entry import require_calibrated_source
    return require_calibrated_source(voice, binding)


def revise_reading(project_path, output):
    # 完整乐句与实际时长复用：新增原来源验证与新目录限制，候选不能覆盖原曲谱。
    source = Path(project_path).resolve(); directory = source.parent
    output = require_isolated_output(output, ROOT)
    if output == directory or directory in output.parents:
        raise ValueError('阅读副本必须放在原工程之外，避免递归复制或覆盖')
    if output.exists() and any(output.iterdir()):
        raise ValueError('阅读谱必须另存空的新版本目录')
    project = read_json(source); before = deepcopy(project)
    # 完整乐句与实际时长复用：修改按最高层来源核验，原仅旧派生重放代码注释保留。
    # voice = project['accepted_vocal_project']; binding = project['shared_analysis']['input_binding']
    # if voice.get('meter_unit_correction'):
    #     from meter_unit_entry import verify_projected_shared
    #     verify_projected_shared(project)
    # from accompaniment_rebar import validate_vocal_snapshot
    # if not validate_vocal_snapshot(voice, binding):
    #     raise ValueError('原人声／拍轴来源不能重放，停止阅读修订')
    # from source_meter_entry import require_calibrated_source
    # require_calibrated_source(voice, binding)
    source_check = verify_reading_source(project, source)
    from guitar_variable_repeat import build_repeat_plan, validate_repeat_plan
    from guitar_readability_acceptance import assess_guitar_readability
    plan = build_repeat_plan(project)
    route = validate_repeat_plan(plan, project)
    initial = assess_guitar_readability(project, plan)
    if not route['valid'] or not initial['valid']:
        raise ValueError('阅读预验收失败：' + str(route['errors'] + initial['errors']))
    page = directory / 'guitar/score_full.html'
    if not page.is_file(): page = directory / 'guitar/score.html'
    if not page.is_file(): raise ValueError('缺少原完整谱面，不能暗中重新生成音乐')
    # 完整乐句与实际时长复用：新增原声音／钢琴／简谱及原工程逐文件复制，所有非阅读内容保持字节一致。
    shutil.copytree(directory, output, dirs_exist_ok=True)
    shutil.copy2(page, output / 'guitar/score.html')
    # 局部两拍过渡听辨修订：新增副表在冻结阅读重导中同步当前小节号，含弱起显示号；不改变音乐文件。
    if project.get('bar_boundary_revision'):
        from reviewed_bar_boundaries import refresh_pattern_guides
        refresh_pattern_guides(project,output/'guitar')
    from export_timing_revision import write_variable_repeat_score
    printed = write_variable_repeat_score(project, output / 'guitar')
    plan = read_json(output / 'guitar/repeat_plan.json')
    actual = assess_guitar_readability(project, plan, output_dir=output)
    if project != before or sha256(output / source.name) != sha256(source):
        raise ValueError('只读阅读流程改变了受保护工程')
    protected = []
    for old in directory.rglob('*'):
        if not old.is_file(): continue
        relative = old.relative_to(directory)
        # 完整乐句与实际时长复用：新增只有吉他阅读HTML／SVG／路线报告可以改变，XML／MXL／MIDI／音频全部冻结。
        reading = (relative.parts[0] == 'guitar' and
                   (old.suffix in ('.html', '.svg') or old.name in ('repeat_plan.json', 'repeat_validation.json')))
        if reading: continue
        copied = output / relative
        if not copied.is_file() or sha256(old) != sha256(copied):
            raise ValueError('受保护音乐或钢琴／简谱文件改变：' + str(relative))
        protected.append(str(relative))
    save_json(output / 'guitar/phrase_reading_acceptance.json', actual)
    if not actual['valid']: raise ValueError('实际阅读产物未通过：' + str(actual['errors']))
    result = {'version': 1, 'source_project': str(source), 'source_project_sha256': sha256(source),
        # 完整乐句与实际时长复用：新增最高层冻结来源证据，不把该证据称为整曲音乐认证。
        'source_check': source_check,
        'output': str(output), 'scope': 'guitar_reading_only_all_existing_music_preserved',
        'protected_files': protected, 'complete_project_unchanged': True,
        'reading_acceptance': actual['status'], 'printed_repeat': printed,
        'normal_entry_updated': False, 'inherited_music_acceptance': project.get('music_acceptance', {})}
    save_json(output / 'reading_revision.json', result)
    return result
