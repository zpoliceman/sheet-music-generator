"""吉他编配规则与统一验收修复：固定已认可音乐材料，另存可读吉他编配。"""
# 吉他编配规则与统一验收修复：新增通用CLI；不执行拍轴、音高或和弦识别，不更新正常入口。
from pathlib import Path
import argparse
from copy import deepcopy
from accompaniment_analysis import extract_features
from score_export import read_json, save_json, sha256
from source_timing_acceptance import require_isolated_output
from guitar_readable_arrangement import revise_guitar_arrangement
from guitar_variable_repeat import build_repeat_plan
from guitar_readability_acceptance import assess_guitar_readability, require_guitar_readability
# 吉他编配规则与统一验收修复：新增旧API遗失顶层标记时仍识别新编配。
from guitar_readability_acceptance import has_guitar_readability_revision

ROOT = Path(__file__).resolve().parents[1]


def protected_baseline(project, project_path):
    # 吉他编配规则与统一验收修复：新增修订稿的可信祖先检查，防止以失败稿自比刷新成通过。
    from guitar_source_bass_acceptance import require_changed_bass_source, source_bass_music_fingerprint
    current, path = project, Path(project_path).resolve()
    seen = set()
    # 吉他编配规则与统一验收修复：修改祖先验证同时检查乐器内部标记。
    # while current.get('guitar_readability_revision'):
    while has_guitar_readability_revision(current):
        if path in seen:
            raise ValueError('修订稿来源循环，必须从已认可原工程重新修订。')
        seen.add(path)
        guard = require_changed_bass_source(current, current.get('guitar_source_bass_acceptance'))
        source = current.get('readability_source', {})
        ancestor_path = source.get('baseline_project', source.get('project'))
        ancestor_sha = source.get('baseline_project_sha256', source.get('project_sha256'))
        if not ancestor_path or not ancestor_sha:
            raise ValueError('修订稿缺少受保护原工程，不能用自身充当音乐验收基线。')
        path = Path(ancestor_path).resolve()
        if not path.is_file() or sha256(path) != ancestor_sha:
            raise ValueError('修订稿原工程已改变或缺失，不能刷新验收。')
        current = read_json(path)
        if guard.get('baseline_input_music_sha256') != source_bass_music_fingerprint(current):
            raise ValueError('修订稿原低音验收与受保护基线不一致。')
    return current, path, sha256(path)


def revise(project_path, output, feature_cache=None):
    # 吉他编配规则与统一验收修复：新增来源绑定及非覆盖边界，任何失败只留下新隔离证据。
    project_path = Path(project_path).resolve()
    output = require_isolated_output(output, ROOT)
    if output.exists() and any(output.iterdir()):
        raise ValueError('输出目录已有内容，请使用新的隔离版本，不覆盖现有曲谱。')
    original = read_json(project_path)
    original_sha = sha256(project_path)
    # 吉他编配规则与统一验收修复：新增先拒绝无有效原声验收的修订稿，再解析不可自比的音乐基线。
    baseline, baseline_path, baseline_sha = protected_baseline(original, project_path)
    sources = original['shared_analysis']['input_binding']['sources']
    provenance = {}
    for name, source in sources.items():
        actual = sha256(source['path'])
        if actual != source['sha256']:
            raise ValueError('原曲来源已经改变：' + name)
        provenance[name] = {'path': source['path'], 'sha256': actual}
    cache = Path(feature_cache) if feature_cache else output.parent / 'features'
    features = {name: extract_features(sources[name], cache, name)
                for name in ('mix', 'accompaniment', 'bass', 'six_guitar') if name in sources}
    revised, audit = revise_guitar_arrangement(original, source_features=features)
    output.mkdir(parents=True, exist_ok=True)
    save_json(output / 'arrangement_revision.json', audit)
    # 吉他编配规则与统一验收修复：新增保留既有词音未决；局部规则通过不能升级成整曲音乐通过。
    # 吉他编配规则与统一验收修复：修改保留新编配阶段的失效说明，不能再把祖先认证覆盖到新工程。
    # music = deepcopy(original.get('music_acceptance', {}))
    music = deepcopy(revised.get('music_acceptance', original.get('music_acceptance', {})))
    music.update(status='needs_review', scope='guitar_readability_revision_preserves_approved_clock',
                 publication_allowed=False)
    revised['music_acceptance'] = music
    revised['readability_source'] = {'project': str(project_path), 'project_sha256': original_sha,
                                   # 吉他编配规则与统一验收修复：新增持续绑定首次修订前的可信音乐，不逐次重置基线。
                                   'baseline_project': str(baseline_path), 'baseline_project_sha256': baseline_sha,
                                   'verified_sources': provenance,
                                   'no_pitch_or_harmony_reanalysis': True}
    # 吉他编配规则与统一验收修复：新增实际低音对原轨的独立验收，不能只靠新和弦内部一致放行。
    from guitar_source_bass_acceptance import assess_changed_bass_source, require_changed_bass_source
    # 吉他编配规则与统一验收修复：修改始终相对保护基线复核；旧自比入口保留为注释。
    # bass_check = assess_changed_bass_source(revised, original, features.get('bass'))
    bass_check = assess_changed_bass_source(revised, baseline, features.get('bass'))
    revised['guitar_source_bass_acceptance'] = bass_check
    save_json(output / 'guitar_source_bass_acceptance.json', bass_check)
    save_json(output / 'project.json', revised)
    require_changed_bass_source(revised, bass_check)
    plan = build_repeat_plan(revised)
    # 吉他编配规则与统一验收修复：修改保护校验同样绑定原工程，不把既有改动静默变为基线。
    # preflight = assess_guitar_readability(revised, repeat_plan=plan, baseline_project=original)
    preflight = assess_guitar_readability(revised, repeat_plan=plan, baseline_project=baseline)
    save_json(output / 'guitar_readability_preflight.json', preflight)
    save_json(output / 'project.json', revised)
    require_guitar_readability(revised, preflight, final=False)
    from export_timing_revision import export_revision
    export_revision(output / 'project.json', output, instruments=('guitar',))
    # 吉他编配规则与统一验收修复：修改终检使用原始基线，旧调用保留。
    # final = assess_guitar_readability(revised, repeat_plan=read_json(output / 'guitar/repeat_plan.json'),
    #                                 output_dir=output, baseline_project=original)
    final = assess_guitar_readability(revised, repeat_plan=read_json(output / 'guitar/repeat_plan.json'),
                                    output_dir=output, baseline_project=baseline)
    save_json(output / 'guitar_readability_acceptance.json', final)
    require_guitar_readability(revised, final)
    if sha256(project_path) != original_sha:
        raise ValueError('来源工程在处理期间发生改变，候选不得采用。')
    # 吉他编配规则与统一验收修复：新增处理期间保护基线也必须保持原摘要。
    if sha256(baseline_path) != baseline_sha:
        raise ValueError('受保护原工程在处理期间发生改变，候选不得采用。')
    revised['guitar_readability_acceptance'] = final
    # 吉他编配规则与统一验收修复：新增局部规则的准确结果，整曲音乐和未决词音仍独立保持。
    revised['music_acceptance']['guitar_readability'] = 'actual_arrangement_and_export_passed'
    revised['guitar_score_layout'] = {'mode': 'repeat_folded', 'plan': 'guitar/repeat_plan.json',
                                     'full_score': 'guitar/score_full.html'}
    save_json(output / 'project.json', revised)
    summary = {'output': str(output), 'valid': True, 'normal_entry_changed': False,
               'source_project_unchanged': True, 'music_acceptance': 'needs_review',
               'guitar_readability_acceptance': final}
    save_json(output / 'revision_report.json', summary)
    return summary


def main():
    # 吉他编配规则与统一验收修复：新增独立入口，与主生成入口调用同一实现。
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--feature-cache', type=Path)
    args = parser.parse_args()
    result = revise(args.project, args.output, args.feature_cache)
    print('吉他规则及实际导出验收通过；整曲音乐仍待验收：' + result['output'])


if __name__ == '__main__':
    # 吉他编配规则与统一验收修复：新增直接执行保护。
    main()
