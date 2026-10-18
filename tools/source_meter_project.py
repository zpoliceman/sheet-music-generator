"""原曲拍轴与歌词拍位通用修复：独立源拍轴和字音派生的严格来源重放。"""
# 原曲拍轴与歌词拍位通用修复：新增独立顶层版本；历史各拍轴／人声策略保持原复核入口。
from copy import deepcopy
from pathlib import Path
from score_export import read_json, save_json, sha256
from source_meter_clock import infer_source_clock, POLICY as CLOCK_POLICY
from source_vocal_rebuild import rebuild_source_vocal, source_dependencies, POLICY as VOICE_POLICY

POLICY = {'version': 1, 'clock_policy': deepcopy(CLOCK_POLICY), 'voice_policy': deepcopy(VOICE_POLICY),
          'arrangement_after_final_vocal_clock': True, 'old_project_default_preserved': True,
          'source_audio_and_f0_unchanged': True, 'song_names_lyrics_or_fixed_answers_used': False}

# 原声覆盖与选音归属通用修复：新增质量层版本，旧v1严格重放，新的默认生成补查未记谱的真实发声。
from source_vocal_quality import prepare_quality_vocal, POLICY as VOCAL_QUALITY_POLICY
# 源拍轴频段候选通用修复：修改最新质量策略，原v2定义注释保留；v2仍完整重放，v3使用经验证的候选拍轴。
# QUALITY_POLICY = {**deepcopy(POLICY), 'version': 2, 'source_vocal_quality': deepcopy(VOCAL_QUALITY_POLICY)}
LEGACY_QUALITY_POLICY = {**deepcopy(POLICY), 'version': 2, 'source_vocal_quality': deepcopy(VOCAL_QUALITY_POLICY)}
from source_meter_clock import RECOVERY_POLICY
# 字音唯一挂词音保护通用修复：修改未交付的v3策略，原定义保留；旧v2原声政策不变。
# QUALITY_POLICY = {**deepcopy(LEGACY_QUALITY_POLICY), 'version': 3, 'clock_policy': deepcopy(RECOVERY_POLICY)}
from source_vocal_quality import COVERAGE_POLICY
QUALITY_POLICY = {**deepcopy(LEGACY_QUALITY_POLICY), 'version': 3, 'clock_policy': deepcopy(RECOVERY_POLICY),
                  'source_vocal_quality': deepcopy(COVERAGE_POLICY)}


# 原曲拍轴与歌词拍位通用修复：新增被新层替代的顶层标记清理；完整旧派生保存在base账本，避免旧算法误认新结果。
def clear_superseded_layers(vocal):
    for key in ('grid_correction', 'beat_phase_correction', 'local_clock_correction', 'structural_clock_correction',
                'performance_clock_correction', 'source_meter_correction', 'continuous_meter_correction', 'vocal_continuity_correction'):
        vocal.pop(key, None)
    return vocal


# 原曲拍轴与歌词拍位通用修复：新增已有派生的确定性重建分派，按已有最高层而不是存手工可改的全工程快照。
def baseline(original, binding, correction):
    if correction.get('base_vocal_continuity_correction'):
        from vocal_continuity_project import derive_continuity_vocal
        return derive_continuity_vocal(original, binding, correction['base_vocal_continuity_correction'])
    if correction.get('base_continuous_correction'):
        from continuous_meter_project import derive_continuous_vocal
        return derive_continuous_vocal(original, binding, correction['base_continuous_correction'])
    from continuous_meter_project import reconstruct_baseline
    return reconstruct_baseline(original, binding, correction)


# 原曲拍轴与歌词拍位通用修复：新增源缓存依赖登记，拍轴攻击／低音证据被改动时拒绝旧工程复核。
def cache_dependencies(cache):
    cache = Path(cache)
    paths = list(cache.glob('source_onsets_v1_*')) + list(cache.glob('v1_*'))
    return {str(p.resolve()): sha256(p) for p in sorted(paths) if p.suffix in ('.json', '.npz')}


# 原曲拍轴与歌词拍位通用修复：新增从原文件、源音轨和算法政策完整重放，拒绝只修改结果音符／拍位的伪派生。
def derive_source_vocal(original, binding, correction):
    # 原声覆盖与选音归属通用修复：修改，仅接受明确版本政策，历史源派生仍用原算法。
    # if (correction.get('version') != 1 or correction.get('policy') != POLICY
    # 源拍轴频段候选通用修复：修改策略分派，原仅v1／v2保留；历史拍轴不会被备选策略重算。
    # policy = QUALITY_POLICY if correction.get('version') == 2 else POLICY
    # if (correction.get('version') not in (1, 2) or correction.get('policy') != policy
    policy = {1: POLICY, 2: LEGACY_QUALITY_POLICY, 3: QUALITY_POLICY}.get(correction.get('version'))
    if (correction.get('version') not in (1, 2, 3) or correction.get('policy') != policy
            or correction.get('source_vocal_project_sha256') != binding['vocal_project_sha256']
            or correction.get('source_fingerprints') != {name: source['sha256'] for name, source in binding['sources'].items()}):
        raise ValueError('独立源拍轴派生的版本／策略／来源不符。')
    for path, expected in correction['cache_dependencies'].items():
        if sha256(path) != expected:
            raise ValueError('独立源拍轴的原攻击／低音缓存已改变。')
    base = baseline(original, binding, correction)
    if source_dependencies(base) != correction['source_dependencies']:
        raise ValueError('独立源字音的原音段／音素来源不符。')
    # 源拍轴频段候选通用修复：修改重放调用，原调用保留；只有v3启用新候选验证。
    # timing, clock_audit = infer_source_clock(base, binding, correction['feature_cache'])
    timing, clock_audit = infer_source_clock(base, binding, correction['feature_cache'], quality=True) if correction['version'] == 3 else infer_source_clock(base, binding, correction['feature_cache'])
    # 原声覆盖与选音归属通用修复：新增原声质量层完整重放；结果音不能只靠自填账本通过。
    # 源拍轴频段候选通用修复：修改新质量层覆盖范围，原v2条件保留；v3沿用相同原声覆盖重放。
    # if correction['version'] == 2:
    if correction['version'] in (2, 3):
        # 字音唯一挂词音保护通用修复：修改v3重放，原调用保留；旧v2完整保留原策略。
        # base, quality_audit = prepare_quality_vocal(base, binding, timing)
        base, quality_audit = prepare_quality_vocal(base, binding, timing, protect_coverage=True) if correction['version'] == 3 else prepare_quality_vocal(base, binding, timing)
        if quality_audit != correction.get('source_quality_evidence'):
            raise ValueError('源覆盖或字音归属不能由原轨确定重建。')
    updated, voice_audit = rebuild_source_vocal(base, timing)
    if clock_audit != correction['clock_evidence'] or voice_audit != correction['vocal_evidence']:
        raise ValueError('独立源拍轴／字音不能由原来源确定重建。')
    # 原曲拍轴与歌词拍位通用修复：修改，旧叠挂标记保留；旧基准仍在correction账本内严格重建。
    # updated['source_meter_rebuild_correction'] = deepcopy(correction)
    clear_superseded_layers(updated)['source_meter_rebuild_correction'] = deepcopy(correction)
    return updated


# 原曲拍轴与歌词拍位通用修复：新增编配之前的人声准备入口；已经校正的本层幂等，人工源拍位原样保留。
# 原声覆盖与选音归属通用修复：修改入口，旧显式调用保持原政策，生产默认传入quality=True。
# def prepare_source_vocal(vocal, binding, cache):
# 首次生成自动拍轴交接：修改增加显式新源参数，旧调用默认沿用原政策。
# def prepare_source_vocal(vocal, binding, cache, quality=False):
# 尾段原声局部补证：修改参数只供首次新输入传递可重放决定，原调用与旧认可工程分支保持。
# def prepare_source_vocal(vocal, binding, cache, quality=False, first_generation=False,
#                          evidence=None, feature_caches=(), model_cache=None):
def prepare_source_vocal(vocal, binding, cache, quality=False, first_generation=False,
                         evidence=None, feature_caches=(), model_cache=None, decision_path=None):
    # 首次生成自动拍轴交接：新增已有新来源层保持，普通重导只验重放，不重新选拍。
    if vocal.get('first_source_meter_correction'):
        from source_meter_entry import require_calibrated_source
        return vocal, require_calibrated_source(vocal, binding)
    # 慢拍单位与两曲最小修订：新增明确单位修订优先保持；真实复核后直接传递，不重算原152等旧提示或有声字头。
    if vocal.get('meter_unit_correction'):
        from source_meter_entry import require_calibrated_source
        return vocal, require_calibrated_source(vocal, binding)
    # 原声覆盖与选音归属通用修复：修改，旧层普通重导保持；明确启用质量检查时必须升级旧v1，不能因“已校拍轴”跳过漏音。
    # if vocal.get('source_meter_rebuild_correction'):
    #     return vocal, {'status': 'existing_independent_source_vocal_retained'}
    existing = vocal.get('source_meter_rebuild_correction')
    if existing:
        # 源拍轴频段候选通用修复：修改既有质量层幂等，原v2判断保留；普通旧重导保留已认可音乐。
        # if not quality or existing.get('version') == 2:
        if not quality or existing.get('version') in (2, 3):
            return vocal, {'status': 'existing_independent_source_vocal_retained'}
        original = read_json(binding['vocal_project'])
        if vocal != derive_source_vocal(original, binding, existing):
            raise ValueError('旧源拍轴人声已改写，不能丢弃现有改动后声称质量升级。')
        vocal = baseline(original, binding, existing)
    # 源拍轴频段候选通用修复：修改默认新质量准备，原调用保留；无质量开关仍用旧拍轴策略。
    # timing, clock_audit = infer_source_clock(vocal, binding, cache)
    # 最小拍轴与词音伴奏修复：修改新质量输入的前置门槛，原调用保留；历史已有v1/v2/v3重放／普通重导分支不变。
    # timing, clock_audit = infer_source_clock(vocal, binding, cache, quality=True) if quality else infer_source_clock(vocal, binding, cache)
    # 首次生成自动拍轴交接：新增首次新歌先运行匿名选择／局部分组／覆盖，成功后直接投影，不进旧重建。
    if first_generation and quality:
        from first_generation_source import prepare_first_source
        # 尾段原声局部补证：修改首次准备传递严格来源决定，旧六参数调用保留为注释。
        # return prepare_first_source(vocal, binding, cache, evidence, feature_caches, model_cache)
        return prepare_first_source(vocal, binding, cache, evidence, feature_caches, model_cache, decision_path)
    if quality:
        from source_timing_acceptance import require_unambiguous_new_source
        require_unambiguous_new_source(vocal, binding)
    timing, clock_audit = infer_source_clock(vocal, binding, cache, quality=True) if quality else infer_source_clock(vocal, binding, cache)
    if clock_audit['status'] == 'reviewed_source_clock_retained':
        return vocal, clock_audit
    # 原声覆盖与选音归属通用修复：修改，原直接重解保留；先检查未覆盖发声与字音归属再量化。
    # updated, voice_audit = rebuild_source_vocal(vocal, timing)
    # correction = {'version': 1, 'policy': deepcopy(POLICY),
    # 字音唯一挂词音保护通用修复：修改最新生成的原声准备，原调用保留；没有quality开关仍沿用旧v1。
    # prepared, quality_audit = prepare_quality_vocal(vocal, binding, timing) if quality else (vocal, None)
    prepared, quality_audit = prepare_quality_vocal(vocal, binding, timing, protect_coverage=True) if quality else (vocal, None)
    updated, voice_audit = rebuild_source_vocal(prepared, timing)
    # 源拍轴频段候选通用修复：修改新派生版本号，原v2编号保留；原v1/v2账本政策均不覆盖。
    # correction = {'version': 2 if quality else 1, 'policy': deepcopy(QUALITY_POLICY if quality else POLICY),
    correction = {'version': 3 if quality else 1, 'policy': deepcopy(QUALITY_POLICY if quality else POLICY),
        'source_vocal_project_sha256': binding['vocal_project_sha256'],
        'source_fingerprints': {name: source['sha256'] for name, source in binding['sources'].items()},
        'source_dependencies': source_dependencies(vocal), 'feature_cache': str(Path(cache).resolve()),
        'cache_dependencies': cache_dependencies(cache), 'clock_evidence': clock_audit, 'vocal_evidence': voice_audit,
        'base_vocal_continuity_correction': deepcopy(vocal.get('vocal_continuity_correction')),
        'base_continuous_correction': deepcopy(vocal.get('continuous_meter_correction')),
        'base_source_meter_correction': deepcopy(vocal.get('source_meter_correction')),
        'base_performance_correction': deepcopy(vocal.get('performance_clock_correction')),
        'base_structural_correction': deepcopy(vocal.get('structural_clock_correction')),
        'base_local_correction': deepcopy(vocal.get('local_clock_correction')),
        'base_phase_correction': deepcopy(vocal.get('beat_phase_correction')),
        'base_grid_correction': deepcopy(vocal.get('grid_correction'))}
    # 原声覆盖与选音归属通用修复：新增独立源质量证据，只用于新层重建，不改变旧缓存。
    if quality:
        correction['source_quality_evidence'] = quality_audit
    # 原曲拍轴与歌词拍位通用修复：修改，旧叠挂标记保留；新版输出仅保留实际最高层标记。
    # updated['source_meter_rebuild_correction'] = correction
    clear_superseded_layers(updated)['source_meter_rebuild_correction'] = correction
    save_json(Path(cache).parent / 'source_meter_rebuild_evidence.json', {'clock': clock_audit, 'vocal': voice_audit})
    save_json(Path(cache).parent / 'source_meter_rebuilt_vocal.json', updated)
    return updated, {'clock': clock_audit, 'vocal': voice_audit}


# 原曲拍轴与歌词拍位通用修复：新增明确重建的共同编配入口，尚未认可的原型不作为已确认音乐冻结或跨时钟拼接。
def rebuild_source_project(shared, vocal, cache):
    from accompaniment_analysis import analyze
    from accompaniment_texture_policy import add_block_support
    # 原声覆盖与选音归属通用修复：修改，明确重建使用新的源质量层。
    # updated, evidence = prepare_source_vocal(vocal, shared['input_binding'], cache)
    updated, evidence = prepare_source_vocal(vocal, shared['input_binding'], cache, quality=True)
    # 默认入口原曲节拍强制复核：新增拍轴／字音准备后必须核验来源，证据不足不得先生成错误拍窗的共有和声。
    from source_meter_entry import require_calibrated_source
    require_calibrated_source(updated,shared['input_binding'])
    # 原声覆盖与选音归属通用修复：修改，新的共享分析启用源覆盖政策，v1／v2分析保留原路径。
    # fresh = add_block_support(analyze(shared['input_binding'], updated, cache, harmonic_quality=2), updated, cache)
    fresh = add_block_support(analyze(shared['input_binding'], updated, cache, harmonic_quality=3), updated, cache)
    fresh['independent_source_meter'] = deepcopy(evidence)
    return fresh, updated
