"""源拍轴频段候选通用修复：候选完整门槛、历史严格重放和来源保护反例。"""
# 源拍轴频段候选通用修复：新增任意合成节拍夹具，不含歌曲名、歌词或参考谱答案。
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from source_meter_clock import infer_source_clock, robust_pulse_fit, POLICY, RECOVERY_POLICY
from source_meter_project import derive_source_vocal, prepare_source_vocal, LEGACY_QUALITY_POLICY, QUALITY_POLICY


# 源拍轴频段候选通用修复：新增真实整数脉冲与独立低音相位夹具。
def fixture():
    attacks = [{'seconds': .13 + q * .5, 'strength': 1.2 if q % 4 == 0 else 1.} for q in range(180)]
    onsets = {name: {'source': 'drums', 'attacks': deepcopy(attacks)} for name in ('drums_low', 'drums_full')}
    vocal = {'audio_analysis': {'tempo': {'bpm': 121.}}, 'timing': {'meter': [4, 4]}}
    binding = {'sources': {'drums': {'sha256': 'bound_source'}}}
    bass = {'status': 'independent_downbeat_supported', 'phase_beats': 0,
            'changes': [], 'phase_scores': [40., 0., 3., 0.], 'margin': .9}
    return vocal, binding, onsets, bass


# 源拍轴频段候选通用修复：新增局部相位冲突的可控证据，仍由真实pulse_knots检查拒绝。
def conflict_fit(attacks, candidate):
    phase, period, witnesses = robust_pulse_fit(attacks, candidate)
    if candidate['track'] == 'drums_low':
        for row in witnesses:
            if 24 <= row['quarter'] <= 112:
                row['residual_seconds'] += .20 * period
    return phase, period, witnesses


class CandidateRecoveryTests(unittest.TestCase):
    # 源拍轴频段候选通用修复：新增主频段相位失败后，完整通过原门槛的备选才能被采用。
    def test_valid_full_band_recovers_without_relaxing_thresholds(self):
        vocal, binding, onsets, bass = fixture()
        old_policy = deepcopy(POLICY)
        with patch('source_meter_clock.extract_source_onsets', return_value=(onsets, 'accompaniment')), \
             patch('source_meter_clock.bass_phase_evidence', return_value=bass), \
             patch('source_meter_clock.robust_pulse_fit', side_effect=conflict_fit):
            timing, audit = infer_source_clock(vocal, binding, '.', quality=True)
        self.assertEqual(audit['selected_track'], 'drums_full')
        self.assertEqual(audit['candidate_selection']['rejected_candidates'][0]['track'], 'drums_low')
        self.assertAlmostEqual(timing['steady_tempo_bpm'], 120., places=5)
        self.assertEqual(POLICY, old_policy)
        for key, value in POLICY.items():
            if key != 'version': self.assertEqual(RECOVERY_POLICY[key], value)
        self.assertFalse(audit['source_notation_used']); self.assertFalse(audit['lyric_text_used'])

    # 源拍轴频段候选通用修复：新增历史默认必须保留失败行为，不能暗中改变旧账本。
    def test_legacy_default_does_not_recover_failed_low_band(self):
        vocal, binding, onsets, bass = fixture()
        with patch('source_meter_clock.extract_source_onsets', return_value=(onsets, 'accompaniment')), \
             patch('source_meter_clock.bass_phase_evidence', return_value=bass), \
             patch('source_meter_clock.robust_pulse_fit', side_effect=conflict_fit):
            with self.assertRaisesRegex(ValueError, '局部相位变化'):
                infer_source_clock(vocal, binding, '.')

    # 源拍轴频段候选通用修复：新增备选仍有局部相位冲突时必须停止，不能只通过全局周期。
    def test_all_local_phase_conflicts_are_rejected(self):
        vocal, binding, onsets, bass = fixture()
        def invalid(attacks, candidate):
            return conflict_fit(attacks, {**candidate, 'track': 'drums_low'})
        with patch('source_meter_clock.extract_source_onsets', return_value=(onsets, 'accompaniment')), \
             patch('source_meter_clock.bass_phase_evidence', return_value=bass), \
             patch('source_meter_clock.robust_pulse_fit', side_effect=invalid):
            with self.assertRaisesRegex(ValueError, '所有独立节拍候选'):
                infer_source_clock(vocal, binding, '.', quality=True)

    # 源拍轴频段候选通用修复：新增宽频备选也必须获得独立低音首拍，歌词不能充当证据。
    def test_ambiguous_downbeat_is_not_recovered(self):
        vocal, binding, onsets, bass = fixture()
        bass['status'] = 'ambiguous_downbeat'
        with patch('source_meter_clock.extract_source_onsets', return_value=(onsets, 'accompaniment')), \
             patch('source_meter_clock.bass_phase_evidence', return_value=bass):
            with self.assertRaisesRegex(ValueError, '所有独立节拍候选'):
                infer_source_clock(vocal, binding, '.', quality=True)

    # 源拍轴频段候选通用修复：新增稀疏攻击不能由“备选”标记提升为已确认。
    def test_sparse_evidence_still_stops(self):
        vocal, binding, onsets, bass = fixture()
        for track in onsets.values(): track['attacks'] = track['attacks'][:4]
        with patch('source_meter_clock.extract_source_onsets', return_value=(onsets, 'accompaniment')):
            with self.assertRaisesRegex(ValueError, '证据不足'):
                infer_source_clock(vocal, binding, '.', quality=True)

    # 源拍轴频段候选通用修复：新增主候选通过时旧、新时序必须相同。
    def test_valid_primary_timing_is_unchanged(self):
        vocal, binding, onsets, bass = fixture()
        with patch('source_meter_clock.extract_source_onsets', return_value=(onsets, 'accompaniment')), \
             patch('source_meter_clock.bass_phase_evidence', return_value=bass):
            old, old_audit = infer_source_clock(vocal, binding, '.')
            new, new_audit = infer_source_clock(vocal, binding, '.', quality=True)
        self.assertEqual(old, new)
        self.assertEqual(old_audit['witnesses'], new_audit['witnesses'])
        self.assertEqual(new_audit['selected_track'], 'drums_low')

    # 源拍轴频段候选通用修复：新增已绑定人工拍轴不能被备选选择覆盖。
    def test_reviewed_clock_is_preserved(self):
        vocal = {'timing': {'beat_phase': {'review_id': 'bound_review'}, 'knots': [{'quarter': 0., 'seconds': 2.}]}}
        with patch('source_meter_clock.extract_source_onsets', side_effect=AssertionError('不应重解')):
            timing, audit = infer_source_clock(vocal, {}, '.', quality=True)
        self.assertEqual(timing, vocal['timing'])
        self.assertEqual(audit['status'], 'reviewed_source_clock_retained')

    # 源拍轴频段候选通用修复：新增来源失败不得改选别的音轨绕过。
    def test_source_integrity_error_is_not_bypassed(self):
        vocal, binding, _, _ = fixture()
        with patch('source_meter_clock.extract_source_onsets', side_effect=ValueError('来源SHA改变')):
            with self.assertRaisesRegex(ValueError, '来源SHA改变'):
                infer_source_clock(vocal, binding, '.', quality=True)


class ProjectVersionRecoveryTests(unittest.TestCase):
    # 源拍轴频段候选通用修复：新增旧质量层与新质量层的幂等保护，不修改已认可音乐。
    def test_existing_quality_versions_are_retained(self):
        for version in (2, 3):
            vocal = {'source_meter_rebuild_correction': {'version': version}, 'quantized_notes': ['approved']}
            with patch('source_meter_project.infer_source_clock', side_effect=AssertionError('不应重算')):
                result, _ = prepare_source_vocal(vocal, {}, '.', quality=True)
            self.assertIs(result, vocal)

    # 源拍轴频段候选通用修复：新增历史v2严格原策略重放，v3才能使用候选恢复。
    def test_replay_dispatches_exact_policy_version(self):
        binding = {'vocal_project_sha256': 'vocal', 'sources': {'drums': {'sha256': 'drums'}}}
        for version, policy in ((2, LEGACY_QUALITY_POLICY), (3, QUALITY_POLICY)):
            correction = {'version': version, 'policy': deepcopy(policy), 'source_vocal_project_sha256': 'vocal',
                'source_fingerprints': {'drums': 'drums'}, 'cache_dependencies': {}, 'source_dependencies': {},
                'feature_cache': '.', 'clock_evidence': {'clock': 1}, 'vocal_evidence': {'voice': 1},
                'source_quality_evidence': {'quality': 1}}
            with patch('source_meter_project.baseline', return_value={'base': True}), \
                 patch('source_meter_project.source_dependencies', return_value={}), \
                 patch('source_meter_project.infer_source_clock', return_value=({'timing': 1}, {'clock': 1})) as clock, \
                 patch('source_meter_project.prepare_quality_vocal', return_value=({'prepared': True}, {'quality': 1})), \
                 patch('source_meter_project.rebuild_source_vocal', return_value=({'quantized_notes': ['checked']}, {'voice': 1})):
                result = derive_source_vocal({}, binding, correction)
            self.assertEqual(result['quantized_notes'], ['checked'])
            self.assertEqual(clock.call_args.kwargs, {'quality': True} if version == 3 else {})

    # 源拍轴频段候选通用修复：新增不可将v3政策伪装成旧v2账本绕过重放。
    def test_policy_mismatch_is_rejected(self):
        binding = {'vocal_project_sha256': 'vocal', 'sources': {}}
        correction = {'version': 2, 'policy': deepcopy(QUALITY_POLICY), 'source_vocal_project_sha256': 'vocal', 'source_fingerprints': {}}
        with self.assertRaisesRegex(ValueError, '版本／策略／来源不符'):
            derive_source_vocal({}, binding, correction)


# 源拍轴频段候选通用修复：新增标准测试入口。
if __name__ == '__main__': unittest.main()
