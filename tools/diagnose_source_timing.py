"""最小拍轴与词音伴奏修复：显式隔离的原曲拍轴与首拍验证入口。"""
# 最小拍轴与词音伴奏修复：新增通用CLI；阶段未通过时仅保存原音诊断，不触发全曲切音、和声或编配。
import argparse
from copy import deepcopy
from pathlib import Path
import json
from score_export import read_json, save_json, sha256
from accompaniment_analysis import extract_features
from performance_beat_clock import copy_features
from source_timing_evidence import read_source_model, infer_timing_candidates, source_changes, candidate_phase_scores
from source_timing_decoder import decode_four_beat_candidate
from source_timing_acceptance import assess_clock_candidate, require_isolated_output

ROOT = Path(__file__).resolve().parents[1]


# 最小拍轴与词音伴奏修复：修改显式入口参数，原签名保留；来源听辨只有主动启用才参与新候选，不升级旧工程。
# def diagnose(project_path, work, model_cache=None, features_from=()):
# 自动拍层级与首拍盲测：修改签名并保留原式；自动竞争明确启用，历史重放默认不变。
# def diagnose(project_path, work, model_cache=None, features_from=(), use_source_review=False):
def diagnose(project_path, work, model_cache=None, features_from=(), use_source_review=False, auto_select=False):
    # 最小拍轴与词音伴奏修复：新增原工程SHA保护及新文件边界；诊断结果不覆盖旧缓存或旧曲谱。
    project_path = Path(project_path).resolve()
    before = sha256(project_path)
    work = require_isolated_output(work, ROOT)
    if (work / 'timing_diagnosis.json').exists():
        raise ValueError('本次诊断输出已存在，请另选独立目录，不覆盖已审查候选。')
    project = read_json(project_path)
    vocal, shared = project['accepted_vocal_project'], project['shared_analysis']
    binding = shared['input_binding']
    # 自动拍层级与首拍盲测：新增在读取任何旧拍速／人工表之前分流；只转交白名单原声来源。
    if auto_select:
        if use_source_review:
            raise ValueError('自动盲选不能同时读取人工复核答案')
        from select_source_meter import select_from_sources
        result = select_from_sources(binding, work, model_cache, features_from)
        if sha256(project_path) != before:
            raise ValueError('自动盲选期间原工程改变')
        return result
    cache = work / 'features'
    preferred = list(features_from)
    correction = vocal.get('source_meter_rebuild_correction', {})
    if correction.get('feature_cache'):
        preferred.insert(0, correction['feature_cache'])
    copy_features(binding, cache, preferred)
    names = [name for name in ('accompaniment', 'six_guitar', 'bass') if name in binding['sources']]
    features = {name: extract_features(binding['sources'][name], cache, name) for name in names}
    arrays, provenance = read_source_model(binding['sources']['mix'], work / 'model', model_cache)
    original = infer_timing_candidates(vocal, binding, features, arrays, provenance)
    save_json(work / 'raw_timing_candidates.json', original)
    nominal = original['pulse_audit']['nominal_fine_period_seconds']
    # 最小拍轴与词音伴奏修复：新增来源绑定听辨的通用命令路线，读取实际原音SHA，不以曲名或固定秒数分支。
    if use_source_review:
        from source_timing_reviewed_clock import build_reviewed_clock
        review = read_json(ROOT / 'data/source_timing_reviews.json')['reviews'].get(binding['sources']['mix']['sha256'])
        if review is None:
            raise ValueError('该原混音没有来源绑定的局部拍位听辨，不能移用其它歌曲答案')
        candidate, assessment = build_reviewed_clock(arrays, binding, features, review, provenance)
        save_json(work / 'reviewed_clock.json', candidate)
        save_json(work / 'reviewed_clock_acceptance.json', assessment)
        if sha256(project_path) != before:
            raise ValueError('原工程在隔离拍轴检查期间改变')
        result = {'version': 1, 'status': assessment['status'], 'stage': 'clock_and_downbeat_only',
                  'project': str(project_path), 'project_sha256': before, 'candidate': 'reviewed_clock.json',
                  'acceptance': 'reviewed_clock_acceptance.json', 'model_provenance': provenance,
                  'pitch_chord_or_lyric_mutation_performed': False, 'normal_collection_changed': False,
                  'downstream_revision_started': False, 'music_accepted': False}
        save_json(work / 'timing_diagnosis.json', result)
        return result
    candidates = []
    # 最小拍轴与词音伴奏修复：新增按原混音SHA读取既有人工拍位证据，仅作验收反例，不输入候选解码器。
    metrical_path = ROOT / 'data/metrical_reviews.json'
    registered = read_json(metrical_path).get('reviews', {}).get(binding['sources']['mix']['sha256']) if metrical_path.is_file() else None
    for scale in (.5, 1., 2.):
        print('原曲连续拍序候选：', scale, flush=True)
        decoded = decode_four_beat_candidate(arrays, nominal / scale, vocal['timing']['meter'])
        beats = decoded['beats']
        knots = [{'quarter': float(i + beats[0]['beat'] - 1), 'seconds': row['seconds']} for i, row in enumerate(beats)]
        from score_export import TempoMap
        mapping = TempoMap(knots)
        changes = {name: source_changes(feature, mapping, int(mapping.quarters[0]), int(mapping.quarters[-1])) for name, feature in features.items()}
        windows = []
        for start in range(0, int(binding['duration_seconds']), 16):
            windows.append({'start': start, 'phases': {name: candidate_phase_scores(rows, 1., vocal['timing']['meter'], (start, start + 16)) for name, rows in changes.items()}})
        decoded.update(scale=scale, meter=deepcopy(vocal['timing']['meter']), knots=knots, source_windows=windows,
                       source_mix_sha256=binding['sources']['mix']['sha256'])
        # 最小拍轴与词音伴奏修复：修改只凭缺少人工表单就拒绝的初稿，原式保留；实际原音与已确认点参与验收。
        # assessment = assess_clock_candidate(decoded, binding)
        assessment = assess_clock_candidate(decoded, binding, model_arrays=arrays, historical_meter_review=registered)
        number = len(candidates) + 1
        save_json(work / ('candidate_' + str(number) + '.json'), decoded)
        save_json(work / ('candidate_' + str(number) + '_acceptance.json'), assessment)
        candidates.append({'candidate': 'candidate_' + str(number) + '.json', 'scale': scale,
                           'acceptance': 'candidate_' + str(number) + '_acceptance.json',
                           'status': assessment['status'], 'issues': [row['kind'] for row in assessment['issues']]})
    if sha256(project_path) != before:
        raise ValueError('原工程在诊断期间发生变化，停止。')
    result = {'version': 1, 'status': 'needs_review', 'stage': 'clock_and_downbeat_only',
              'project': str(project_path), 'project_sha256': before,
              'candidates': candidates, 'model_provenance': provenance,
              'pitch_chord_or_lyric_mutation_performed': False, 'normal_collection_changed': False,
              'downstream_revision_started': False}
    save_json(work / 'timing_diagnosis.json', result)
    return result


def main():
    # 最小拍轴与词音伴奏修复：新增窄参数，不把任何歌曲名、歌词或固定秒数写进生产逻辑。
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--model-cache', type=Path)
    parser.add_argument('--features-from', type=Path, action='append', default=[])
    # 最小拍轴与词音伴奏修复：新增主动选用原混音听辨输入的参数；未提供时保留独立快慢候选诊断。
    parser.add_argument('--use-source-review', action='store_true')
    # 自动拍层级与首拍盲测：新增显式通用自动竞争入口；不覆盖旧谱或自动清除音乐未决。
    parser.add_argument('--auto-select', action='store_true')
    # 最小拍轴与词音伴奏修复：修改重复解析参数，原调用保留；统一使用同一个已解析请求。
    # result = diagnose(**{'project_path': parser.parse_args().project, 'work': parser.parse_args().work,
    #                      'model_cache': parser.parse_args().model_cache, 'features_from': parser.parse_args().features_from})
    args = parser.parse_args()
    # 最小拍轴与词音伴奏修复：修改调用以转交显式开关，原四参数式保留。
    # result = diagnose(args.project, args.work, args.model_cache, args.features_from)
    # 自动拍层级与首拍盲测：修改调用并保留旧式，显式传入新参数。
    # result = diagnose(args.project, args.work, args.model_cache, args.features_from, args.use_source_review)
    result = diagnose(args.project, args.work, args.model_cache, args.features_from, args.use_source_review, args.auto_select)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
