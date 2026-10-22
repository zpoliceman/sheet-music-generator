"""4/4可选右手与实时谱面试听：绑定父工程、隔离另存及完整产物验收入口。"""
# 4/4可选右手与实时谱面试听：新增实际修改入口，与局部预览复用统一编译器。
from copy import deepcopy
from pathlib import Path
from workspace_location import local_path
import argparse
import shutil

from score_export import read_json, save_json, sha256
from source_timing_acceptance import require_isolated_output
from guitar_pattern_selection import (compile_selection, assess_selection, require_selection,
    has_selection, legacy_source, fingerprint, POLICY)

ROOT = Path(__file__).resolve().parents[1]


def validate_parent(project, path):
    if project.get('automatic_draft'):
        from draft_music_review import verify_draft
        verify_draft(project,path)
    # 4/4可选右手与实时谱面试听：新增旧拍轴／小节／来源仍按原规则重放，已选型版本先核真实选择。
    # 4/4可选右手与实时谱面试听：新增已有发布凭据时核对实际交付，防止手改原工程被当作认可基线。
    if (Path(path).parent/'publication.json').is_file():
        from scoped_music_publication import require_scoped_publication
        require_scoped_publication(Path(path).parent,project)
    if has_selection(project):
        require_selection(project)
        from guitar_source_bass_acceptance import require_changed_bass_source
        require_changed_bass_source(project, project.get('guitar_source_bass_acceptance'))
        return {'valid': True, 'status': 'verified_selected_parent'}
    from revise_guitar_patterns import has_section_patterns
    if has_section_patterns(project) and not any(project.get(key) for key in
            ('bar_boundary_revision','piano_sync_revision','local_lyric_revision')):
        # 4/4可选右手与实时谱面试听：新增即使原拍轴可重放，旧稳定右手及其实际低音摘要失效也不能用作新型基线。
        from guitar_section_patterns import assess_section_patterns
        from guitar_source_bass_acceptance import require_changed_bass_source
        check=assess_section_patterns(project)
        if not check['valid']:raise ValueError('原稳定右手工程已改变：'+str(check.get('errors',[])))
        require_changed_bass_source(project,project.get('guitar_source_bass_acceptance'))
    if project.get('piano_sync_revision'):
        # 4/4可选右手与实时谱面试听：新增沿已认可钢琴同步及局部词音的最高层验证，避免回到更旧的词音祖先。
        from piano_preserved_sync import check_sync_project
        original, _ = check_sync_project(project)
        validate_parent(original, Path(project['piano_sync_revision']['source_project']))
        return {'valid': True, 'status': 'verified_piano_sync_and_approved_lyrics'}
    if project.get('local_lyric_revision'):
        # 4/4可选右手与实时谱面试听：新增复用局部词音入口的完整材料及祖先保护，当前词音保持逐字段不变。
        from local_lyric_revision import fingerprint as lyric_fingerprint, music_payload
        from guitar_source_bass_acceptance import require_changed_bass_source
        audit = project['local_lyric_revision']
        ancestor = Path(audit.get('source_project', '__missing_lyric_source__'))
        if audit.get('output_music_sha256') != lyric_fingerprint(music_payload(project)) or not local_path(ancestor).is_file() or sha256(ancestor) != audit.get('source_project_sha256'):
            raise ValueError('已认可局部词音的实际内容或父工程改变')
        original = read_json(ancestor)
        if (project['arrangements'] != original['arrangements'] or project['shared_analysis'] != original['shared_analysis']
                or project['accepted_vocal_project']['timing'] != original['accepted_vocal_project']['timing']):
            raise ValueError('已认可局部词音的伴奏／拍轴保护失效')
        require_changed_bass_source(project, project.get('guitar_source_bass_acceptance'))
        return {'valid': True, 'status': 'verified_approved_local_lyrics'}
    from revise_guitar_reading import verify_reading_source
    return verify_reading_source(project, path)


def verify_sources(project):
    # 4/4可选右手与实时谱面试听：新增所有来源实际摘要核查；不重识别人声、拍轴或和弦。
    result = {}
    for role, source in project['shared_analysis']['input_binding']['sources'].items():
        digest = sha256(source['path'])
        if digest != source['sha256']:
            raise ValueError('原曲来源已改变：' + role)
        result[role] = {'path': source['path'], 'sha256': digest}
    return result


def bind_selection(revised, source, source_sha, bindings):
    # 4/4可选右手与实时谱面试听：新增不可自比的直接父工程绑定；旧音乐认证完整保存在来源账本。
    revised['right_hand_selection_source'] = {'project': str(source), 'project_sha256': source_sha,
        'verified_sources': bindings, 'no_pitch_or_harmony_reanalysis': True}
    revised['readability_source'] = {'project': str(source), 'project_sha256': source_sha,
        'baseline_project': str(source), 'baseline_project_sha256': source_sha,
        'verified_sources': bindings, 'no_pitch_or_harmony_reanalysis': True}


def revise_selection(project_path, output, plan=None, feature_cache=None):
    # 4/4可选右手与实时谱面试听：新增仅允许空隔离目录，普通重导不改变已保存型。
    source = local_path(project_path).resolve()
    output = require_isolated_output(output, ROOT)
    if output == source.parent or source.parent in output.parents:
        raise ValueError('右手新版本须在原工程目录以外另存')
    if output.exists() and any(output.iterdir()):
        raise ValueError('输出目录已有内容，请另存新版本')
    original = read_json(source)
    source_sha = sha256(source)
    parent_check = validate_parent(original, source)
    bindings = verify_sources(original)
    if isinstance(plan, (str, Path)):
        plan = read_json(plan)
    if plan is None and has_selection(original):
        revised = deepcopy(original)
        audit = {'status': 'exact_selected_music_reexport', 'music_changed': False,
                 'arranged_measures': original['right_hand_selection']['arranged_measures']}
    else:
        revised, audit = compile_selection(original, plan)
        if not audit['music_changed']:
            return {'valid': True, 'output': str(source.parent), 'music_changed': False,
                    'status': 'unchanged_no_selection', 'normal_entry_changed': False}
        bind_selection(revised, source, source_sha, bindings)
    # 4/4可选右手与实时谱面试听：新增实际绘图先于材料摘要，避免布局派生使验收过期。
    from revise_guitar_register import prepare_reading_layout
    layout = prepare_reading_layout(revised)
    selection_check = require_selection(revised)
    from accompaniment_analysis import extract_features
    from guitar_source_bass_acceptance import assess_changed_bass_source, require_changed_bass_source
    bass_source = original['shared_analysis']['input_binding']['sources'].get('bass')
    bass_feature = extract_features(bass_source, Path(feature_cache) if feature_cache else output.parent/'features', 'bass') if bass_source else None
    # 4/4可选右手与实时谱面试听：新增普通重导沿原父基线复核，不拿当前选型工程自己证明低音正确。
    from guitar_pattern_selection import source_project
    baseline = source_project(revised)
    bass_check = assess_changed_bass_source(revised, baseline, bass_feature)
    revised['guitar_source_bass_acceptance'] = bass_check
    output.mkdir(parents=True, exist_ok=True)
    save_json(output/'selection_revision.json', audit)
    save_json(output/'selection_acceptance.json', selection_check)
    save_json(output/'parent_acceptance.json', parent_check)
    save_json(output/'reading_layout.json', layout)
    save_json(output/'guitar_source_bass_acceptance.json', bass_check)
    save_json(output/'project.json', revised)
    require_changed_bass_source(revised, bass_check)
    from guitar_variable_repeat import build_repeat_plan
    from guitar_readability_acceptance import assess_guitar_readability, require_guitar_readability
    repeat = build_repeat_plan(revised)
    preflight = assess_guitar_readability(revised, repeat_plan=repeat, baseline_project=baseline)
    save_json(output/'guitar_readability_preflight.json', preflight)
    require_guitar_readability(revised, preflight, final=False)
    from export_timing_revision import export_revision
    checks = export_revision(output/'project.json', output, instruments=('guitar',))
    # 4/4可选右手与实时谱面试听：新增其它已交付乐器原文件复制，音乐与音频不重编。
    for name in ('piano', 'vocal'):
        folder = source.parent/name
        if folder.is_dir() and not (output/name).exists():
            shutil.copytree(folder, output/name)
    if sha256(source) != source_sha:
        raise ValueError('处理期间原工程改变，候选不得采用')
    require_selection(revised)
    from guitar_pattern_selection_ui import saved_index
    saved_index(revised, output, source)
    if original.get('automatic_draft'):
        from draft_music_review import stamp_draft,annotate_delivery
        delivered=read_json(output/'project.json')
        stamp_draft(delivered)
        save_json(output/'project.json',delivered)
        annotate_delivery(output)
    result = {'valid': True, 'output': str(output), 'music_changed': audit['music_changed'],
        'music_status': 'needs_review', 'normal_entry_changed': False, 'policy': POLICY,
        'selection': selection_check, 'section_patterns': selection_check, 'artifacts': checks,
        'source_project': str(source), 'source_project_sha256': source_sha,
        'plan_sha256': fingerprint(revised['right_hand_selection']['plan'])}
    save_json(output/'revision_report.json', result)
    return result


def main():
    # 4/4可选右手与实时谱面试听：新增命令行入口，供脚本及首次交付复用。
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--right-hand-plan', type=Path)
    parser.add_argument('--feature-cache', type=Path)
    args = parser.parse_args()
    print(revise_selection(args.project, args.output, args.right_hand_plan, args.feature_cache)['output'])


if __name__ == '__main__':
    # 4/4可选右手与实时谱面试听：新增直接执行保护。
    main()
