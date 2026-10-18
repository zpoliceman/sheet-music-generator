"""跨歌曲和弦复用与器乐准备：相关攻击、弱轨、真拖唱、旧版本与源保护反例。"""
from copy import deepcopy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from score_export import TempoMap
import performance_beat_clock as legacy
import performance_clock_refinement as previous
from performance_clock_evidence import (POLICY, resolve_source_pulses, local_observation_weights,
                                        infer_evidence_clock, derive_evidence_vocal)
from test_performance_clock_refinement import delayed, base_audit


# 跨歌曲和弦复用与器乐准备：新增不同曲名／绝对时刻均无关的独立相关轨攻击候选。
def attack(q, seconds, source='accompaniment', rank=1., family='harmonic_mix'):
    return dict(quarter=q, seconds=seconds, source=source, selection_rank=rank,
                weight=6., family=family, kind='fullband_periodic_pulse')


class CorrelatedAttackTests(unittest.TestCase):
    def test_close_reversed_correlated_tracks_select_one_real_attack(self):
        rows = [attack(6., 10.06), attack(6.25, 10., 'six_guitar', 2.)]
        before = deepcopy(rows)
        chosen, audit = resolve_source_pulses(rows, 1.)
        self.assertEqual(chosen, [rows[1]])
        self.assertEqual(rows, before)
        self.assertFalse(audit['unresolved_phase_conflicts'])
        evidence = audit['correlated_track_near_attack_resolution'][0]
        self.assertEqual(evidence['sources'], ['accompaniment', 'six_guitar'])
        self.assertFalse(evidence['seconds_averaged'])
        self.assertTrue(legacy.deduplicate_source_pulses(rows, 1.)[1]['unresolved_phase_conflicts'])

    def test_two_distinct_attacks_from_same_track_still_fail(self):
        rows = [attack(6., 10.06), attack(6.25, 10.)]
        chosen, audit = resolve_source_pulses(rows, 1.)
        self.assertEqual(chosen, [])
        self.assertTrue(audit['unresolved_phase_conflicts'])

    def test_wide_reversed_attacks_still_fail(self):
        rows = [attack(6., 10.16), attack(6.25, 10., 'six_guitar')]
        self.assertTrue(resolve_source_pulses(rows, 1.)[1]['unresolved_phase_conflicts'])

    def test_legitimate_ordered_close_attacks_are_retained(self):
        rows = [attack(6., 10.), attack(6.25, 10.06, 'six_guitar')]
        chosen, audit = resolve_source_pulses(rows, 1.)
        self.assertEqual(chosen, rows)
        self.assertFalse(audit['correlated_track_near_attack_resolution'])

    def test_independent_bass_does_not_alias_harmonic_attack(self):
        rows = [attack(6., 10.06, 'bass', family='bass'), attack(6.25, 10., 'six_guitar')]
        self.assertEqual(resolve_source_pulses(rows, 1.)[0], rows)

    def test_speed_scaled_alias_decision_is_invariant(self):
        for scale in [.4, 1., 1.8]:
            rows = [attack(6., scale * 10.06), attack(6.25, scale * 10., 'six_guitar', 2.)]
            self.assertEqual(resolve_source_pulses(rows, scale)[0], [rows[1]])

    def test_shared_track_in_candidate_groups_prevents_merge(self):
        rows = [attack(6., 10.06), attack(6., 10.065, 'six_guitar', .5),
                attack(6.25, 10., 'six_guitar', 2.)]
        self.assertTrue(resolve_source_pulses(rows, 1.)[1]['unresolved_phase_conflicts'])

    def test_related_duplicate_windows_do_not_add_weight(self):
        rows = [attack(6., 10.06), attack(6.25, 10., 'six_guitar', 2.)]
        self.assertEqual(resolve_source_pulses(rows, 1.)[0], resolve_source_pulses(rows * 4, 1.)[0])


class WeakPulseAndVersionTests(unittest.TestCase):
    def test_only_weak_pulses_inside_confirmed_local_window_change_weight(self):
        pulse = [attack(1., 1.), attack(3., 3.), attack(4., 4.)]
        pulse[0]['weight'] = pulse[1]['weight'] = 4.8
        region = dict(first_quarter=2., last_quarter=6.)
        before = deepcopy(pulse)
        weighted, audit = local_observation_weights(region, pulse, [{'weight': 1.5}] * 3, [])
        # 跨歌曲和弦复用与器乐准备：修正测试取样，联合列表末尾还有保留的人声观察，这里只比较脉冲。
        # self.assertEqual([p['weight'] for p in weighted], [4.8, .72, 6.])
        self.assertEqual([p['weight'] for p in weighted[:len(pulse)]], [4.8, .72, 6.])
        self.assertEqual(pulse, before)
        # 跨歌曲和弦复用与器乐准备：修正脉冲秒比较范围，联合字首仍在列表中。
        # self.assertEqual([p['seconds'] for p in weighted], [p['seconds'] for p in pulse])
        self.assertEqual([p['seconds'] for p in weighted[:len(pulse)]], [p['seconds'] for p in pulse])
        self.assertFalse(audit['strong_pulse_weights_changed'])

    def test_insufficient_vocal_witnesses_leave_weights_unchanged(self):
        pulse = [dict(attack(3., 3.), weight=4.8)]
        weighted, _ = local_observation_weights(dict(first_quarter=2., last_quarter=6.), pulse, [], [])
        self.assertEqual(weighted, pulse)

    def test_coherent_voice_is_not_overpowered_by_weak_track(self):
        v = delayed(first=2., last=3.5, delay=.20)
        pulse = [dict(attack(q, 2. + q), weight=4.8) for q in [2., 2.5, 3., 3.5]]
        pulse += [attack(1., 3.), attack(5., 7.)]
        before = deepcopy(v)
        with patch('performance_clock_refinement.legacy.infer_performance_clock',
                   return_value=(v['timing']['knots'], base_audit(pulse))):
            old_knots, old_audit = previous.infer_refined_clock(v, {}, ROOT)
            knots, audit = infer_evidence_clock(v, {}, ROOT)
        self.assertTrue(old_audit['independent_local_review']['unresolved'])
        self.assertFalse(audit['independent_local_review']['unresolved'])
        self.assertTrue(audit['music_residual_check']['valid'])
        self.assertEqual(v, before)
        self.assertTrue(any(r['observation_weight_resolution']['weak_pulses'] for r in audit['regions']))
        self.assertEqual(audit['policy']['independent_review_quarters'], previous.POLICY['independent_review_quarters'])
        self.assertTrue(all(a['seconds'] < b['seconds'] for a, b in zip(knots, knots[1:])))

    def test_strong_pulses_keep_real_vocal_expression(self):
        v = delayed(first=2., last=3.5, delay=.20)
        pulse = [attack(n['start_tick'] / 480, 2. + n['start_tick'] / 480) for n in v['quantized_notes']]
        with patch('performance_clock_refinement.legacy.infer_performance_clock',
                   return_value=(v['timing']['knots'], base_audit(pulse))):
            knots, audit = infer_evidence_clock(v, {}, ROOT)
        self.assertEqual(knots, v['timing']['knots'])
        self.assertTrue(audit['music_residual_check']['vocal_expression_or_notation_review'])

    def test_version_three_dispatch_keeps_older_policies(self):
        with patch('performance_clock_evidence.derive_evidence_vocal', return_value={'version': 3}) as derive:
            self.assertEqual(legacy.derive_performance_vocal({}, {}, {'version': 3}), {'version': 3})
            derive.assert_called_once()
        self.assertEqual((legacy.POLICY['version'], previous.POLICY['version']), (1, 2))
        self.assertEqual(previous.POLICY['independent_review_quarters'], POLICY['independent_review_quarters'])

    def test_policy_or_source_tampering_is_rejected(self):
        binding = {'vocal_project_sha256': 'v', 'sources': {'mix': {'sha256': 'a'}}}
        correction = {'version': 3, 'policy': deepcopy(POLICY), 'source_vocal_project_sha256': 'v',
                      'source_fingerprints': {'mix': 'bad'}}
        with self.assertRaisesRegex(ValueError, '指纹'):
            derive_evidence_vocal({}, binding, correction)
        correction['source_fingerprints']['mix'] = 'a'
        correction['policy']['weak_pulse_local_weight_fraction'] = 1.
        with self.assertRaisesRegex(ValueError, '策略'):
            derive_evidence_vocal({}, binding, correction)


if __name__ == '__main__':
    unittest.main()
