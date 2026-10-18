"""人声连续音值与长休止漏音通用修复：独立版本化派生及原来源严格重放，历史版本不升级。"""
from copy import deepcopy
# 工作目录改名兼容：文件仍逐个验证摘要，证据保留原绝对路径名称以便重放历史记录。
from pathlib import Path
from score_export import read_json, save_json, sha256
from vocal_continuity import repair_continuity, POLICY as VOICE_POLICY

# 人声连续音值与长休止漏音通用修复：新增可重建策略，不保存可绕过原音核验的人工工程快照。
POLICY = {'version': 1, 'voice_policy': deepcopy(VOICE_POLICY), 'legacy_reconstruction_preserved': True,
          'original_source_notes_preserved': True, 'new_candidates_require_source_rest_and_audio': True}


# 人声连续音值与长休止漏音通用修复：新增历史派生重建分派，旧连续拍轴版本1完全按原策略复核。
def baseline(original, binding, correction):
    # 原曲拍轴与歌词拍位通用修复：新增独立源层之后的显式人声连续性修复重放，旧来源分派保持。
    if correction.get('base_source_meter_rebuild_correction'):
        from source_meter_project import derive_source_vocal
        return derive_source_vocal(original, binding, correction['base_source_meter_rebuild_correction'])
    if correction.get('base_continuous_correction'):
        from continuous_meter_project import derive_continuous_vocal
        return derive_continuous_vocal(original, binding, correction['base_continuous_correction'])
    from continuous_meter_project import reconstruct_baseline
    return reconstruct_baseline(original, binding, correction)


# 人声连续音值与长休止漏音通用修复：新增声学缓存依赖指纹；修改f0缓存／原轨／保留清单都会拒绝旧结果重放。
def source_dependencies(vocal):
    result = {}
    for label in ('notes', 'lyrics'):
        path = vocal['inputs'][label + '_path']; expected = vocal['inputs'][label + '_sha256']
        if sha256(path) != expected:
            raise ValueError('人声复核的原音段／音素缓存已改变。')
        result[label] = {'path': str(Path(path).absolute()), 'sha256': expected}
    return result


# 人声连续音值与长休止漏音通用修复：新增全字段严格确定性来源复核，恢复音符必须重新通过原f0和实际音频。
def derive_continuity_vocal(original, binding, correction):
    if (correction.get('version') != 1 or correction.get('policy') != POLICY
            or correction.get('source_vocal_project_sha256') != binding['vocal_project_sha256']
            or correction.get('source_fingerprints') != {k: s['sha256'] for k, s in binding['sources'].items()}):
        raise ValueError('连续音值派生策略／源指纹不符。')
    if correction.get('review_path'):
        if (sha256(correction['review_path']) != correction['review_sha256']
                or read_json(correction['review_path']) != correction['review']):
            raise ValueError('连续音值修复的人工保留清单已改变。')
    base = baseline(original, binding, correction)
    # 人声连续音值与长休止漏音通用修复：新增基准／修复后音乐指纹严格重建，伴奏兼容记录不能靠手填SHA伪造。
    from phrase_harmony_plan import vocal_fingerprint
    if vocal_fingerprint(base) != correction['base_vocal_sha256']:
        raise ValueError('连续音值修复的基准音乐指纹不符。')
    if source_dependencies(base) != correction['source_dependencies']:
        raise ValueError('长休止复核来源不一致。')
    updated, audit = repair_continuity(base, binding, correction.get('review'))
    if audit != correction['evidence']:
        raise ValueError('连续音值／漏音不能由原来源确定重建。')
    if vocal_fingerprint(updated) != correction['derived_vocal_sha256']:
        raise ValueError('连续音值修复后的音乐指纹不符。')
    updated['vocal_continuity_correction'] = deepcopy(correction)
    return updated


# 人声连续音值与长休止漏音通用修复：新增新生成默认与旧工程明确升级接口，伴奏／拍轴不为单字改动。
def correct_vocal_continuity(shared, vocal, arrangements, cache_dir, review_path=None):
    if vocal.get('vocal_continuity_correction'):
        return shared, vocal, arrangements
    binding = shared['input_binding']; dependencies = source_dependencies(vocal)
    review = read_json(review_path) if review_path else None
    updated, audit = repair_continuity(vocal, binding, review)
    # 人声连续音值与长休止漏音通用修复：新增独立修复前后指纹；保持伴奏是显式局部修复契约，不冒称重新选择和声。
    from phrase_harmony_plan import vocal_fingerprint
    correction = {'version': 1, 'policy': deepcopy(POLICY),
                  'source_vocal_project_sha256': binding['vocal_project_sha256'],
                  'source_fingerprints': {k: s['sha256'] for k, s in binding['sources'].items()},
                  'source_dependencies': dependencies,
                  'base_vocal_sha256': vocal_fingerprint(vocal), 'derived_vocal_sha256': vocal_fingerprint(updated),
                  'base_continuous_correction': deepcopy(vocal.get('continuous_meter_correction')),
                  # 原曲拍轴与歌词拍位通用修复：新增可组合的实际最高层来源，旧工程此字段为空。
                  'base_source_meter_rebuild_correction': deepcopy(vocal.get('source_meter_rebuild_correction')),
                  'base_source_meter_correction': deepcopy(vocal.get('source_meter_correction')),
                  'base_performance_correction': deepcopy(vocal.get('performance_clock_correction')),
                  'base_structural_correction': deepcopy(vocal.get('structural_clock_correction')),
                  'base_local_correction': deepcopy(vocal.get('local_clock_correction')),
                  'base_phase_correction': deepcopy(vocal.get('beat_phase_correction')),
                  'base_grid_correction': deepcopy(vocal.get('grid_correction')),
                  'review': deepcopy(review), 'review_path': str(Path(review_path).resolve()) if review_path else None,
                  'review_sha256': sha256(review_path) if review_path else None, 'evidence': audit}
    updated['vocal_continuity_correction'] = correction
    save_json(Path(cache_dir) / 'vocal_continuity_evidence.json', audit)
    # 人声连续音值与长休止漏音通用修复：修改，旧返回保留；局部人声修复明确保持已认可伴奏，且要求旧计划确属修复前工程。
    # return shared, updated, arrangements
    return preserve_accompaniment_plan(shared, vocal, updated), updated, arrangements


# 人声连续音值与长休止漏音通用修复：新增局部修复的伴奏依赖关联，旧和声证据仍保存原指纹，明确重编才计算新计划。
def preserve_accompaniment_plan(shared, base, updated):
    from phrase_harmony_plan import shared_fingerprint, vocal_fingerprint
    result = deepcopy(shared)
    if 'arranged_harmony' not in result:
        return result
    plan = result['phrase_harmony_plan']; correction = updated['vocal_continuity_correction']
    if (plan['source_vocal_sha256'] != vocal_fingerprint(base)
            or plan['source_shared_sha256'] != shared_fingerprint(shared)
            or base['timing'] != updated['timing'] or base['notation'] != updated['notation']):
        raise ValueError('局部人声修复不能沿用其它旋律／拍轴的伴奏计划。')
    plan['vocal_revision_compatibility'] = {'version': 1,
        'action': 'preserve_accepted_accompaniment_after_source_bound_local_vocal_repair',
        'base_vocal_sha256': correction['base_vocal_sha256'], 'derived_vocal_sha256': correction['derived_vocal_sha256'],
        'harmony_reselected': False, 'source_clock_and_key_preserved': True}
    return result


# 人声连续音值与长休止漏音通用修复：新增兼容检查，实际旋律变动或关联字段篡改都会失效；工程加载仍须完整原声重放。
def accompaniment_revision_compatible(plan, vocal):
    from phrase_harmony_plan import vocal_fingerprint
    link = plan.get('vocal_revision_compatibility', {})
    correction = vocal.get('vocal_continuity_correction', {})
    return (link.get('version') == 1 and correction.get('policy') == POLICY
            and link.get('action') == 'preserve_accepted_accompaniment_after_source_bound_local_vocal_repair'
            and link.get('base_vocal_sha256') == correction.get('base_vocal_sha256') == plan.get('source_vocal_sha256')
            and link.get('derived_vocal_sha256') == correction.get('derived_vocal_sha256') == vocal_fingerprint(vocal)
            and correction.get('evidence', {}).get('source_clock_preserved') is True
            and correction.get('evidence', {}).get('existing_source_notes_preserved') is True
            and link.get('harmony_reselected') is False)
