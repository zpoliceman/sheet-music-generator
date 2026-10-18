"""局部时序与弱证据通用修复：新增通用节奏、倚音、局部误差、边界与独立验收反例。"""
from copy import deepcopy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from test_performance_beat_clock import fixture
from score_export import PPQ, TempoMap
from performance_clock_refinement import (POLICY, vocal_points, local_disagreements, joint_regions,
                                           independent_review, infer_refined_clock, apply_refined_clock, derive_refined_vocal)
from performance_beat_clock import derive_performance_vocal


# 局部时序与弱证据通用修复：新增任意歌词和速度的原秒偏移，变化不写入生产识别答案。
def delayed(first=4., last=7., delay=.12, speed=1., meter=(4, 4)):
    v = fixture(last=16., speed=speed, meter=meter)
    for n, c in zip(v['quantized_notes'], v['lyrics']['characters']):
        if first <= n['start_tick'] / PPQ <= last:
            for side in ['start_seconds', 'end_seconds']:
                n[side] += delay * speed
                c[side] += delay * speed
            for ph in c['phonemes']:
                ph['start_seconds'] += delay * speed
    return v


def base_audit(pulse=()):
    return {'status': 'retained_clock', 'source_pulse_residuals': list(pulse), 'periodic_windows': [],
            'source_event_phase_resolution': {'resolved_aliases': [], 'unresolved_phase_conflicts': []},
            'music_residual_check': {'vocal_expression_or_notation_review': []}}


class LocalPerformanceTests(unittest.TestCase):
    def classify(self, vocal, pulse=()):
        heads, _ = vocal_points(vocal)
        return local_disagreements(vocal, TempoMap(vocal['timing']['knots']), heads, pulse)

    def test_correct_first_half_cannot_hide_delayed_second_half(self):
        v = delayed(first=2., last=3.5)
        v['statistics']['phrase_rhythm'] = {'phrases': [{'first_character_index': 0, 'last_character_index': 15}]}
        triggers, audit = self.classify(v)
        self.assertTrue(any(t['first_quarter'] >= 1.5 for t in triggers))
        self.assertTrue(any(r['median_residual_seconds'] > .1 for r in audit if r['status'] == 'local_coherent_vocal_time_disagreement'))

    def test_single_delayed_word_does_not_move_the_clock(self):
        triggers, _ = self.classify(delayed(first=4., last=4., delay=.5))
        self.assertEqual(triggers, [])

    def test_mixed_earlier_later_words_do_not_move_the_clock(self):
        v = fixture(last=8.)
        for i, (n, c) in enumerate(zip(v['quantized_notes'], v['lyrics']['characters'])):
            delta = .14 if i % 2 else -.14
            n['start_seconds'] += delta
            c['start_seconds'] += delta
        self.assertEqual(self.classify(v)[0], [])

    def test_reliable_accompaniment_protects_true_delayed_singing(self):
        v = delayed()
        pulse = [{'quarter': n['start_tick'] / PPQ, 'weight': 8.} for n in v['quantized_notes']]
        triggers, audit = self.classify(v, pulse)
        self.assertEqual(triggers, [])
        self.assertTrue(any(r['status'] == 'vocal_expression_or_notation_conflict_periodic_pulse_kept' for r in audit))

    def test_weak_pulse_cannot_veto_multiple_reliable_voice_heads(self):
        v = delayed()
        pulse = [{'quarter': n['start_tick'] / PPQ, 'weight': 2.} for n in v['quantized_notes']]
        self.assertTrue(self.classify(v, pulse)[0])

    def test_tempo_scaled_delay_is_detected_across_slow_and_fast_songs(self):
        detected = []
        for speed in [.5, 1., 1.6]:
            triggers, _ = self.classify(delayed(speed=speed))
            detected.append([(r['first_quarter'], r['last_quarter']) for r in triggers])
        self.assertEqual(detected[0], detected[1])
        self.assertEqual(detected[1], detected[2])

    def test_lyrics_and_transposition_do_not_change_clock_decisions(self):
        a = delayed()
        b = deepcopy(a)
        for n in b['quantized_notes']:
            n['pitch_midi'] += 3
        for c in b['lyrics']['characters']:
            c['text'] = 'foreign syllable ' + str(c['index'])
        self.assertEqual(self.classify(a), self.classify(b))

    def test_unreliable_word_alignment_does_not_become_a_timing_witness(self):
        v = fixture(last=8.)
        for n in v['quantized_notes']:
            n['start_seconds'] += .5
        heads, _ = vocal_points(v)
        self.assertTrue(all(not r['reliable'] for r in heads))
        self.assertEqual(self.classify(v)[0], [])

    def test_uncertain_notation_is_reviewed_instead_of_retimed(self):
        v = delayed()
        v['statistics']['phrase_rhythm'] = {'phrases': [{'first_character_index': 0, 'last_character_index': 31, 'needs_review': True}]}
        triggers, audit = self.classify(v)
        self.assertEqual(triggers, [])
        self.assertTrue(any(r['status'] == 'uncertain_notation_keep_clock_for_review' for r in audit))


class GraceAndBoundaryTests(unittest.TestCase):
    def test_grace_entry_and_main_use_different_actual_playback_coordinates(self):
        v = fixture(last=8.)
        main = v['quantized_notes'][4]
        grace = deepcopy(main)
        grace.update(id='g', source_note_id='g', grace=True, role='grace', pitch_midi=62,
                     end_tick=main['start_tick'], start_seconds=4., end_seconds=4.2,
                     playback_end_tick=main['start_tick'] + 96)
        main.update(start_seconds=4.2, playback_start_tick=main['start_tick'] + 96)
        v['quantized_notes'].append(grace)
        before = deepcopy(v)
        heads, inside = vocal_points(v)
        head = next(h for h in heads if h['character_index'] == 4)
        inner = next(h for h in inside if h['character_index'] == 4)
        self.assertEqual((head['quarter'], head['seconds'], head['includes_grace']), (2., 4., True))
        self.assertEqual((inner['quarter'], inner['seconds']), (2.2, 4.2))
        self.assertEqual(inner['nominal_quarter'], 2.)
        self.assertEqual(v, before)

    def test_boundaries_seek_actual_pulses_beyond_old_integer_cutoff(self):
        v = fixture(last=16.)
        trigger = {'first_quarter': 7., 'last_quarter': 9., 'reason': 'local', 'character_indices': [14, 15, 16, 17, 18]}
        regions = joint_regions(v, TempoMap(v['timing']['knots']), [trigger], [{'quarter': 4.5, 'weight': 8.}, {'quarter': 12., 'weight': 8.}])
        self.assertEqual([(r['first_quarter'], r['last_quarter']) for r in regions], [(4.5, 12.)])
        self.assertEqual(regions[0]['left_boundary_kind'], 'periodic_source_anchor')
        self.assertFalse(regions[0]['unverified_integer_boundary_fixed'])

    def test_joint_weak_windows_leave_no_two_beat_hole(self):
        v = fixture(last=16.)
        triggers = [{'first_quarter': a, 'last_quarter': b, 'reason': 'local', 'character_indices': [round(a * 2)]} for a, b in [(6., 7.), (9., 10.)]]
        regions = joint_regions(v, TempoMap(v['timing']['knots']), triggers, [{'quarter': 4., 'weight': 8.}, {'quarter': 12., 'weight': 8.}])
        self.assertEqual(len(regions), 1)
        self.assertEqual((regions[0]['first_quarter'], regions[0]['last_quarter']), (4., 12.))

    def test_absent_pulse_boundary_is_an_explicit_outer_prior(self):
        v = fixture(last=16.)
        triggers = [{'first_quarter': 6., 'last_quarter': 8., 'reason': 'local', 'character_indices': [12, 13, 14]}]
        r = joint_regions(v, TempoMap(v['timing']['knots']), triggers, [])[0]
        self.assertEqual((r['first_quarter'], r['last_quarter']), (0., 16.))
        self.assertEqual(r['left_boundary_kind'], 'outer_singing_span_prior')
        self.assertEqual(r['right_boundary_kind'], 'outer_singing_span_prior')

    def test_instrumental_gap_is_not_crossed_by_joint_regions(self):
        a, b = fixture(first=0., last=4.), fixture(first=12., last=16.)
        shift = len(a['lyrics']['characters'])
        for n in b['quantized_notes']:
            n['lyric_index'] += shift
        for c in b['lyrics']['characters']:
            c['index'] += shift
        a['quantized_notes'].extend(b['quantized_notes'])
        a['lyrics']['characters'].extend(b['lyrics']['characters'])
        a['statistics']['total_ticks'] = 16 * PPQ
        triggers = [{'first_quarter': q, 'last_quarter': q + 1., 'reason': 'local', 'character_indices': []} for q in [1., 13.]]
        regions = joint_regions(a, TempoMap(a['timing']['knots']), triggers, [])
        self.assertEqual([(r['first_quarter'], r['last_quarter']) for r in regions], [(0., 4.), (12., 16.)])


class IndependentAndVersionTests(unittest.TestCase):
    def test_independent_half_bar_check_finds_partial_phrase_residual(self):
        v = delayed(first=2., last=3.5)
        heads, _ = vocal_points(v)
        check = independent_review(v, TempoMap(v['timing']['knots']), heads, [])
        self.assertTrue(check['unresolved'])

    def test_sparse_source_coverage_is_explicit_not_accuracy_claim(self):
        v = fixture(first=4., last=5.)
        heads, _ = vocal_points(v)
        check = independent_review(v, TempoMap(v['timing']['knots']), heads, [])
        self.assertTrue(check['uncovered'])

    def test_actual_refinement_reduces_delay_and_keeps_source_and_notation(self):
        v = delayed()
        before = deepcopy(v)
        pulse = [{'quarter': q, 'seconds': 2. + q, 'weight': 8.} for q in [3., 8.]]
        with patch('performance_clock_refinement.legacy.infer_performance_clock', return_value=(v['timing']['knots'], base_audit(pulse))):
            knots, audit = infer_refined_clock(v, {'sources': {}}, ROOT)
        out = apply_refined_clock(v, knots, audit)
        self.assertEqual(v, before)
        self.assertTrue(audit['music_residual_check']['valid'])
        for r in audit['vocal_residuals']:
            if 4. <= r['quarter'] <= 7.:
                self.assertLess(abs(r['after_residual_seconds']), .03)
        ignored = {'quantized_start_seconds', 'quantized_end_seconds', 'start_error_seconds', 'end_error_seconds'}
        self.assertEqual(v['quantized_notes'], [{k: x for k, x in n.items() if k not in ignored} for n in out['quantized_notes']])
        self.assertEqual(v['lyrics'], out['lyrics'])
        self.assertEqual(out['timing']['performance_beat_clock']['version'], 2)
        self.assertTrue(all(a['seconds'] < b['seconds'] for a, b in zip(knots, knots[1:])))

    def test_compound_meter_retains_big_beat_and_source_ticks(self):
        v = delayed(meter=(6, 8))
        with patch('performance_clock_refinement.legacy.infer_performance_clock', return_value=(v['timing']['knots'], base_audit())):
            knots, audit = infer_refined_clock(v, {'sources': {}}, ROOT)
        out = apply_refined_clock(v, knots, audit)
        self.assertEqual(out['timing']['meter'], [6, 8])
        self.assertEqual(out['statistics']['bar_ticks'], 1440)
        self.assertEqual([n['start_tick'] for n in v['quantized_notes']], [n['start_tick'] for n in out['quantized_notes']])

    def test_version_two_dispatch_does_not_replace_version_one_policy(self):
        with patch('performance_clock_refinement.derive_refined_vocal', return_value={'version': 2}) as derive:
            self.assertEqual(derive_performance_vocal({}, {}, {'version': 2}), {'version': 2})
            derive.assert_called_once()

    def test_refined_fingerprint_or_policy_tampering_is_rejected(self):
        binding = {'vocal_project_sha256': 'v', 'sources': {'mix': {'sha256': 'a'}}}
        correction = {'version': 2, 'policy': deepcopy(POLICY), 'source_vocal_project_sha256': 'v', 'source_fingerprints': {'mix': 'bad'}}
        with self.assertRaisesRegex(ValueError, '指纹'):
            derive_refined_vocal({}, binding, correction)


if __name__ == '__main__':
    unittest.main()
