"""最小拍轴与词音伴奏修复：拍轴、首拍与正常交付的分别验收。"""
# 最小拍轴与词音伴奏修复：新增证据门槛；模型分数、文件一致或旧来源重放均不能替代音乐通过。
from copy import deepcopy
from pathlib import Path
import hashlib
import json
import math
import numpy as np
from score_export import TempoMap, read_json, sha256

POLICY = {'version': 1, 'phase_anchor_tolerance_seconds': .09,
          # 最小拍轴与词音伴奏修复：修改不必要的固定人工复核间隔；逐段原声证据决定缺口，不要求用户每48秒确认。
          # 'maximum_review_anchor_gap_seconds': 48.,
          'review_gap_checked_by_source_windows': True,
          'minimum_phase_contrast': .03, 'phase_counterfactual_margin': .015,
          'maximum_unobserved_active_head_seconds': 4.,
          'requires_notation_level_and_downbeat_separately': True,
          'needs_review_enters_normal_collection': False}


def fingerprint(value):
    # 最小拍轴与词音伴奏修复：新增规范指纹，审查输入不能脱离实际候选／原混音而复用。
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()


def inspect_timing_review(review, candidate, binding):
    # 最小拍轴与词音伴奏修复：新增来源／候选／拍层级／首拍锚点的实际核对；孤立的approved字段不足以放行。
    issues = []
    if review is None:
        return {'valid': False, 'issues': ['notation_level_and_downbeat_review_missing'], 'anchors_checked': 0}
    if (review.get('version') != 1 or review.get('mix_sha256') != binding['sources']['mix']['sha256']
            or review.get('candidate_sha256') != fingerprint(candidate)):
        issues.append('review_source_or_candidate_mismatch')
    if (review.get('notation_level_confirmed') is not True or not review.get('review_id')
            or not review.get('reviewer') or not review.get('basis')):
        issues.append('notation_level_review_incomplete')
    anchors = review.get('downbeat_anchors', [])
    if len(anchors) < 2:
        issues.append('independent_downbeat_anchors_insufficient')
    mapping = TempoMap(candidate['knots'])
    meter = candidate.get('meter', [4, 4])
    bar = meter[0] * 4 / meter[1]
    for row in anchors:
        second, quarter = row.get('seconds'), row.get('quarter')
        if (not isinstance(second, (int, float)) or not isinstance(quarter, (int, float))
                or not row.get('basis') or abs(quarter / bar - round(quarter / bar)) > 1e-7):
            issues.append('downbeat_anchor_not_explicit_bar_start')
            continue
        if abs(mapping.quarters_to_seconds(quarter) - second) > POLICY['phase_anchor_tolerance_seconds']:
            issues.append('actual_clock_does_not_match_reviewed_downbeat')
    confirmed = sorted(row['seconds'] for row in anchors if isinstance(row.get('seconds'), (int, float)))
    # 最小拍轴与词音伴奏修复：删除固定间隔的人工流程，原检查保留；实际源相位窗口仍在下方独立验收。
    # if confirmed and any(b - a > POLICY['maximum_review_anchor_gap_seconds'] for a, b in zip(confirmed, confirmed[1:])):
    #     issues.append('review_has_long_unchecked_phase_gap')
    return {'valid': not issues, 'issues': sorted(set(issues)), 'anchors_checked': len(anchors),
            'review_id': review.get('review_id')}


# 最小拍轴与词音伴奏修复：修改验收接口，原签名保留；原声证据充分可自动通过，有歧义才请求额外听辨。
# def assess_clock_candidate(candidate, binding, review=None):
def assess_clock_candidate(candidate, binding, review=None, model_arrays=None, historical_meter_review=None):
    # 最小拍轴与词音伴奏修复：新增逐段反相位挑战；允许悬而未决的草稿保存，不允许推进音乐修订。
    issues = []
    mapping = TempoMap(candidate['knots'])
    source = binding['sources']['mix']
    first, last = mapping.seconds[0], mapping.seconds[-1]
    if first > POLICY['maximum_unobserved_active_head_seconds']:
        issues.append({'kind': 'head_not_observed', 'seconds': [0., first]})
    if binding['duration_seconds'] - last > 4.:
        issues.append({'kind': 'tail_not_observed', 'seconds': [last, binding['duration_seconds']]})
    conflicts = []
    unsupported = []
    for window in candidate.get('source_windows', []):
        rows = window.get('phases', {})
        primary = rows.get('accompaniment', [])
        if not primary:
            unsupported.append(window['start'])
            continue
        best = primary[0]
        current = next((r for r in primary if abs(r['phase_fine_quarters']) < 1e-7), None)
        if current is None or best['count'] < 2 or best['contrast'] < POLICY['minimum_phase_contrast']:
            unsupported.append(window['start'])
        elif (best['phase_fine_quarters'] != 0
              and best['contrast'] - current['contrast'] >= POLICY['phase_counterfactual_margin']):
            conflicts.append({'start_seconds': window['start'], 'best_phase_quarters': best['phase_fine_quarters'],
                              'margin': best['contrast'] - current['contrast']})
    if conflicts:
        issues.append({'kind': 'original_source_supports_other_group_start', 'windows': conflicts})
    if not candidate.get('source_windows'):
        issues.append({'kind': 'independent_source_phase_windows_missing'})
    review_check = inspect_timing_review(review, candidate, binding)
    # 最小拍轴与词音伴奏修复：修改无条件要求人工输入的初稿；直接复算原始模型拍点是否保持单一拍层级，并核对各段反相位差。
    unit_check = {'valid': False, 'basis': 'missing_original_model_and_source_grouping_evidence'}
    if model_arrays is not None:
        native = np.asarray(model_arrays['beats'], dtype=float)
        native = native[(native >= mapping.seconds[0]) & (native <= mapping.seconds[-1])]
        increments = np.diff([mapping.seconds_to_quarters(float(second)) for second in native])
        fraction = float(np.mean(abs(increments - 1.) < .15)) if len(increments) else 0.
        unique_windows = []
        for window in candidate.get('source_windows', []):
            options = window.get('phases', {}).get('accompaniment', [])
            if len(options) > 1 and options[0]['count'] >= 2:
                unique_windows.append(options[0]['phase_fine_quarters'] == 0 and options[0]['contrast'] - options[1]['contrast'] > .03)
        stable = bool(unique_windows) and sum(unique_windows) / len(unique_windows) >= .90
        unit_check = {'valid': fraction >= .90 and stable, 'native_one_beat_fraction': fraction,
                      'source_grouping_unique_fraction': float(np.mean(unique_windows)) if unique_windows else 0.,
                      'basis': 'raw_mix_model_unit_plus_independent_original_source_phase_counterfactual'}
    if historical_meter_review is not None:
        phase = historical_meter_review.get('beat_phase', {})
        target = phase.get('quarter_bpm')
        actual = float(np.median(60 / (np.diff(mapping.seconds) / np.diff(mapping.quarters))))
        anchor = phase.get('anchor_seconds')
        if target is not None and anchor is not None:
            quarter = mapping.seconds_to_quarters(anchor)
            bar = candidate.get('meter', [4, 4])[0] * 4 / candidate.get('meter', [4, 4])[1]
            nearest = round(quarter / bar) * bar
            compatible = abs(actual / target - 1) < .04 and abs(mapping.quarters_to_seconds(nearest) - anchor) <= POLICY['phase_anchor_tolerance_seconds']
            unit_check.update(valid=bool(compatible), registered_review_id=historical_meter_review.get('review_id'),
                              registered_anchor_seconds=anchor, registered_quarter_bpm=target)
            if not compatible:
                issues.append({'kind': 'candidate_conflicts_with_registered_music_review'})
    if not review_check['valid'] and not unit_check['valid']:
        issues.append({'kind': 'notation_level_or_downbeat_not_reviewed', 'details': review_check['issues']})
    if unsupported:
        # 最小拍轴与词音伴奏修复：新增缺证窗口登记；持续音未必有首拍变化，不按“没有换和弦”直接判音乐错。
        issues.append({'kind': 'phase_windows_need_context_review', 'starts_seconds': unsupported})
    valid = not issues
    return {'version': 1, 'policy': deepcopy(POLICY), 'status': 'passed' if valid else 'needs_review',
            'valid': valid, 'mix_sha256': source['sha256'], 'candidate_sha256': fingerprint(candidate),
            'review_check': review_check, 'original_audio_unit_check': unit_check, 'issues': issues,
            'pitch_or_chord_recognition_changed': False,
            'downstream_timing_revision_allowed': valid, 'normal_publication_allowed': False}


def require_clock_passed(assessment):
    # 最小拍轴与词音伴奏修复：新增阶段硬门槛；没有通过拍轴／首拍验收，不能先改词音或伴奏。
    if (assessment.get('status') != 'passed' or assessment.get('valid') is not True
            or assessment.get('downstream_timing_revision_allowed') is not True or assessment.get('issues')):
        raise ValueError('拍轴和小节首拍尚未通过音乐验收：仅保存诊断，不推进歌词或伴奏修订。')


def require_isolated_output(output, root):
    # 最小拍轴与词音伴奏修复：新增独立路径门槛；此工具不会自动改正常谱库，即便候选已通过也先保存隔离版。
    path, base = Path(output).resolve(), (Path(root) / 'test_outputs/accompaniment_runs').resolve()
    if not path.is_relative_to(base) or path == base:
        raise ValueError('最小时间修订必须先输出到test_outputs/accompaniment_runs的独立目录。')
    return path


def require_music_publication(acceptance):
    # 最小拍轴与词音伴奏修复：新增正常入口条件，旧export_allowed/not_critical或仅结构通过都不足以发布。
    required = ('clock_and_downbeat', 'lyric_ownership_and_full_duration', 'accompaniment_original_audio',
                'confirmed_music_regression', 'playability_and_export')
    if (acceptance.get('status') != 'passed' or acceptance.get('unresolved')
            or any(acceptance.get(key) is not True for key in required)):
        raise ValueError('音乐验收未通过，禁止替换正常曲谱入口。')
    return True


def require_unambiguous_new_source(vocal, binding):
    # 最小拍轴与词音伴奏修复：新增默认新输入的未决检查；明确未解的倍半拍不能再被旧周期拟合偷偷清成通过。
    tempo = vocal.get('audio_analysis', {}).get('tempo', {})
    if tempo.get('half_double_time_ambiguity_unresolved') is not True:
        return
    from source_meter_entry import inspect_source_meter
    check = inspect_source_meter(vocal, binding)
    # 慢拍单位与两曲最小修订：修改通过名单，只增加经过完整来源重放的单位决定，普通旧派生仍不能清除未决。
    # if check['status'] != 'source_bound_human_review_retained':
    # 首次生成自动拍轴交接：修改来源通过名单，仅增加真实重放的新自动决定，守卫仍不可直接清空。
    # if check['status'] not in ('source_bound_human_review_retained', 'source_verified_meter_unit_projection_retained'):
    if check['status'] not in ('source_bound_human_review_retained', 'source_verified_meter_unit_projection_retained',
                              'source_verified_first_generation_clock_retained'):
        raise ValueError('原曲快慢拍层级明确未解，不能自动清除确认标记；请先用diagnose_source_timing.py隔离验证拍轴和小节首拍。')
