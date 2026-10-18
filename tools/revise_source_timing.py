"""最小拍轴与词音伴奏修复：已验拍轴上的显式隔离时间修订入口。"""
# 最小拍轴与词音伴奏修复：新增命令，不调用原全曲重建入口、不更新results索引，不含歌曲名称或专用拍点。
import argparse
from copy import deepcopy
from pathlib import Path
from score_export import read_json, save_json, sha256
from accompaniment_analysis import extract_features
from musical_decode import AcousticEvidence
from vocal_continuity import SourceVerifier
from source_timing_revision import build_revision, project_arrangements, POLICY
from source_timing_acceptance import require_isolated_output, fingerprint


def revise(project_path, candidate_path, acceptance_path, binding_path, output):
    # 最小拍轴与词音伴奏修复：新增原文件、分析、原音和已验候选的依赖核对；诊断输入不可当作曲名补丁。
    root = Path(__file__).resolve().parents[1]
    output = require_isolated_output(output, root)
    output.mkdir(parents=True, exist_ok=True)
    project, candidate, assessment, binding = map(read_json, (project_path, candidate_path, acceptance_path, binding_path))
    before = sha256(project_path)
    voice = project['accepted_vocal_project']
    # 最小拍轴与词音伴奏修复：新增旧工程与原混音的直接来源核对，不能把另一混音的已验拍轴套到本工程。
    if (voice['inputs'].get('mix_audio_sha256') != binding['sources']['mix']['sha256']
            or sha256(binding['sources']['mix']['path']) != binding['sources']['mix']['sha256']):
        raise ValueError('原工程和时间修订不是同一原混音')
    if sha256(voice['inputs']['notes_path']) != voice['inputs']['notes_sha256']:
        raise ValueError('祖先原始音高分析已改变')
    analysis = read_json(voice['inputs']['notes_path'])
    acoustic = AcousticEvidence(analysis, verify_audio=False)
    verifier = SourceVerifier(binding, analysis)
    word_reviews = read_json(root / 'data/source_music_word_reviews.json')['reviews'].get(binding['sources']['vocals']['sha256'], [])
    vocal, heads = build_revision(project, candidate, assessment, binding, acoustic, verifier, word_reviews)
    features = {name: extract_features(binding['sources'][name], output.parent / 'features', name)
                for name in ('accompaniment', 'six_guitar') if name in binding['sources']}
    shared, arrangements, accompaniment = project_arrangements(project, vocal, features)
    result = {'schema_version': project['schema_version'], 'artifact_kind': 'isolated_time_revision', 'title': project['title'],
              'accepted_vocal_project': vocal, 'shared_analysis': shared, 'arrangements': arrangements,
              'time_only_revision': {'version': 1, 'policy': POLICY, 'ancestor_project_path': str(Path(project_path).resolve()),
                                     'ancestor_project_sha256': before, 'clock_sha256': fingerprint(candidate)},
              'music_acceptance': {'status': 'needs_review', 'clock_and_downbeat': True,
                                   'lyric_ownership_and_full_duration': not heads['unresolved'],
                                   'accompaniment_original_audio': False, 'confirmed_music_regression': False,
                                   'playability_and_export': False, 'unresolved': deepcopy(heads['unresolved'])}}
    if sha256(project_path) != before:
        raise ValueError('隔离修订期间祖先工程改变，停止')
    save_json(output / 'project.json', result)
    save_json(output / 'timing_revision_audit.json', {'word_heads': heads, 'accompaniment': accompaniment,
                                                   'word_presence_reviews': word_reviews})
    return result


def main():
    # 最小拍轴与词音伴奏修复：新增显式文件参数，通用代码不按曲名选择答案。
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('project', 'candidate', 'acceptance', 'binding', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    result = revise(args.project, args.candidate, args.acceptance, args.binding, args.output)
    print('隔离时间修订完成：', result['music_acceptance'])


if __name__ == '__main__':
    main()
