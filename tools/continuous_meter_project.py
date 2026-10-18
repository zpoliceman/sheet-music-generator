"""连续源拍序与人声联合重解通用修复：版本化拍序—记谱—共同编配派生，旧版本仍严格重建。"""
from copy import deepcopy
from pathlib import Path
from score_export import read_json, save_json, sha256
from continuous_pulse_sequence import infer_sequence_clock, POLICY as PULSE_POLICY
from continuous_vocal_rhythm import solve_rhythm, POLICY as RHYTHM_POLICY

# 连续源拍序与人声联合重解通用修复：新增明确独立派生层，禁止静默覆盖历史工程或原人声。
POLICY = {'version': 1, 'pulse_policy': deepcopy(PULSE_POLICY), 'rhythm_policy': deepcopy(RHYTHM_POLICY),
          'source_seconds_preserved': True, 'legacy_reconstruction_preserved': True,
          'source_bound_review_constraints': True, 'reference_answers_used': False}


# 连续源拍序与人声联合重解通用修复：新增基准重放分派；不保存可以绕过源核验的手工全工程快照。
def reconstruct_baseline(original, binding, correction):
    if correction.get('base_source_meter_correction'):
        from source_meter_harmony import derive_source_meter_vocal
        return derive_source_meter_vocal(original, binding, correction['base_source_meter_correction'])
    if correction.get('base_performance_correction'):
        from performance_beat_clock import derive_performance_vocal
        return derive_performance_vocal(original, binding, correction['base_performance_correction'])
    from performance_beat_clock import reconstruct_base
    return reconstruct_base(original, binding, correction)


# 连续源拍序与人声联合重解通用修复：新增实际语义/source恒等检查，source音段身份与音高/歌词/原秒不准改变。
def apply_continuous_vocal(base, binding, review=None):
    knots, clock_audit = infer_sequence_clock(base)
    # 连续源拍序与人声联合重解通用修复：修改，旧只传拍轴保留；覆盖/冲突信息也必须传入人声的安全边界。
    # updated, rhythm_audit = solve_rhythm(base, knots, binding, review)
    updated, rhythm_audit = solve_rhythm(base, knots, binding, review, clock_audit=clock_audit)
    fields = ('id', 'source_note_id', 'pitch_midi', 'start_seconds', 'end_seconds', 'lyric_index', 'line_index')
    if [tuple(n.get(k) for k in fields) for n in updated['quantized_notes']] != [tuple(n.get(k) for k in fields) for n in base['quantized_notes']]:
        raise ValueError('连续人声重解改变了原音段身份、源秒或挂词归属。')
    if updated['lyrics']['characters'] != base['lyrics']['characters']:
        raise ValueError('连续人声重解不得静默替换原歌词或音素记录。')
    updated['timing']['continuous_source_meter'] = {'version': 1, 'status': clock_audit['status'],
                                                  'notation_recomputed_after_clock': True}
    return updated, {'clock': clock_audit, 'rhythm': rhythm_audit,
                     'source_identity_preserved': True, 'whole_song_manual_accuracy_claim': False}


# 连续源拍序与人声联合重解通用修复：新增严格来源/策略/人工保留/完整证据重放，旧来源派生不能被手改伪造。
def derive_continuous_vocal(original, binding, correction):
    if (correction.get('version') != 1 or correction.get('policy') != POLICY
            or correction.get('source_vocal_project_sha256') != binding['vocal_project_sha256']
            or correction.get('source_fingerprints') != {k: s['sha256'] for k, s in binding['sources'].items()}):
        raise ValueError('连续拍序派生策略或源指纹不符。')
    if correction.get('review_path'):
        if sha256(correction['review_path']) != correction['review_sha256'] or read_json(correction['review_path']) != correction['review']:
            raise ValueError('人工未决保留清单已改变，需显式重新生成。')
    base = reconstruct_baseline(original, binding, correction)
    updated, audit = apply_continuous_vocal(base, binding, correction.get('review'))
    if audit != correction['evidence']:
        raise ValueError('连续拍序及人声重解无法由来源确定重建。')
    updated['continuous_meter_correction'] = deepcopy(correction)
    return updated


# 连续源拍序与人声联合重解通用修复：新增整曲共同重编入口；器乐继续按真实源秒迁移，合成普通循环随后共同生成。
def correct_continuous_project(shared, vocal, arrangements, cache_dir, review_path=None):
    if vocal.get('continuous_meter_correction'):
        return shared, vocal, arrangements
    from accompaniment_analysis import analyze
    # 渴首次吉他编配：修改，重建阶段继承绑定的乐器范围；原代码注释保留。
    # from accompaniment_arrange import arrange_guitar, arrange_piano
    # 渴首次吉他编配：新增按所选乐器执行，保留各乐器原验证。
    from accompaniment_arrange import arrange_requested
    from accompaniment_texture_policy import add_block_support
    from performance_beat_clock import copy_features
    from beat_phase_alignment import seed_existing_music, align_piano_bass
    from local_beat_clock import reusable_guitar_configuration
    from source_meter_harmony import regrid_observed_entries
    binding = shared['input_binding']; cache = Path(cache_dir).resolve()
    copy_features(binding, cache, [vocal.get('performance_clock_correction', {}).get('feature_cache')])
    review = read_json(review_path) if review_path else None
    updated, audit = apply_continuous_vocal(vocal, binding, review)
    correction = {'version': 1, 'policy': deepcopy(POLICY),
                  'source_vocal_project_sha256': binding['vocal_project_sha256'],
                  'source_fingerprints': {k: s['sha256'] for k, s in binding['sources'].items()},
                  'base_source_meter_correction': deepcopy(vocal.get('source_meter_correction')),
                  'base_performance_correction': deepcopy(vocal.get('performance_clock_correction')),
                  'base_structural_correction': deepcopy(vocal.get('structural_clock_correction')),
                  'base_local_correction': deepcopy(vocal.get('local_clock_correction')),
                  'base_phase_correction': deepcopy(vocal.get('beat_phase_correction')),
                  'base_grid_correction': deepcopy(vocal.get('grid_correction')),
                  'review': deepcopy(review), 'review_path': str(Path(review_path).resolve()) if review_path else None,
                  'review_sha256': sha256(review_path) if review_path else None,
                  'feature_cache': str(cache), 'evidence': audit}
    updated['continuous_meter_correction'] = correction
    save_json(cache.parent / 'continuous_meter_evidence.json', audit)
    fresh_shared = add_block_support(analyze(binding, updated, cache, harmonic_quality=2), updated, cache)
    for field in ('arrangement_policy', 'musical_structure', 'melodic_motif_matches', 'performance_beat_clock', 'source_meter_phase'):
        if field in shared:
            fresh_shared[field] = deepcopy(shared[field])
    fresh_shared['continuous_source_meter'] = deepcopy(audit)
    # 渴首次吉他编配：修改，避免未请求乐器阻塞所选乐器；原代码注释保留。
    # fresh = {'guitar': arrange_guitar(fresh_shared, updated, arrangements['guitar']['configuration']['capo_fret']),
    #          'piano': arrange_piano(fresh_shared, updated)}
    # 渴首次吉他编配：新增按所选乐器执行，保留各乐器原验证。
    fresh = arrange_requested(fresh_shared, updated, arrangements['guitar']['configuration']['capo_fret'])
    fresh = seed_existing_music(shared, vocal, arrangements, fresh_shared, updated, fresh, source_time_sections=True)
    # 连续源拍序与人声联合重解通用修复：新增来源归类，旧人声自动循环越出新唱段时不能被锁成真实间奏。
    from continuous_accompaniment_seed import prepare_continuous_seeds
    fresh = prepare_continuous_seeds(arrangements, fresh)
    regrid_observed_entries(fresh_shared, updated, fresh)
    fresh['guitar']['configuration'].update(reusable_guitar_configuration(arrangements['guitar']['configuration']))
    fresh['guitar']['configuration']['beat_synchronous_patterns'] = True
    # 渴首次吉他编配：修改，仅对已选择钢琴校准钢琴低音；原代码注释保留。
    # align_piano_bass(fresh_shared, updated, fresh['piano'])
    # 渴首次吉他编配：新增按所选乐器执行，保留各乐器原验证。
    if 'piano' in fresh:
        align_piano_bass(fresh_shared, updated, fresh['piano'])
    return fresh_shared, updated, fresh
