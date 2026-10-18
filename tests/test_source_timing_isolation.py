"""最小拍轴与词音伴奏修复：连续拍序、首拍反例与隔离门槛测试。"""
# 最小拍轴与词音伴奏修复：新增真实失效模式的测试，不用“所有文件一致”冒充音乐通过。
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import tempfile
from copy import deepcopy
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from source_timing_evidence import canonical_pulses, candidate_phase_scores
from source_timing_decoder import decode_four_beat_candidate
from source_timing_acceptance import (fingerprint, inspect_timing_review, assess_clock_candidate,
                                      require_clock_passed, require_music_publication, require_isolated_output,
                                      require_unambiguous_new_source)


def fixture():
    # 最小拍轴与词音伴奏修复：新增可验证的合成四拍材料，不读任何歌曲答案。
    logits = np.full(1001, -9.)
    downs = np.full(1001, -10.)
    times = np.arange(0, 20.01, .5)
    for index, second in enumerate(times):
        frame = round(second * 50)
        logits[frame] = 8.
        downs[frame] = 7. if index % 4 == 0 else -8.
    return {'beats': times, 'downbeats': times[::4], 'beat_logits': logits, 'downbeat_logits': downs}


class PulseIsolationTests(unittest.TestCase):
    # 最小拍轴与词音伴奏修复：新增反例，局部听辨不能被动态规划跳过或化成其它拍号。
    def test_reviewed_anchor_cannot_be_skipped_by_the_path(self):
        result = decode_four_beat_candidate(fixture(), .5, phase_anchors=[4.5, 8.5, 12.5])
        for second in (4.5, 8.5, 12.5):
            row = min(result['beats'], key=lambda value: abs(value['seconds'] - second))
            self.assertLess(abs(row['seconds'] - second), .09)
            self.assertEqual(row['beat'], 1)

    def test_ambient_false_pulses_do_not_block_real_initialization(self):
        result = decode_four_beat_candidate(fixture(), .5, unmetered_ranges=[{'start_seconds': 0., 'end_seconds': 4.}])
        self.assertGreaterEqual(result['beats'][0]['seconds'], 4.)
        self.assertLess(result['beats'][0]['seconds'], 5.)

    def test_isolated_extra_downbeat_does_not_create_short_bar(self):
        arrays = fixture()
        arrays['downbeat_logits'][round(7 * 50)] = 8.
        result = decode_four_beat_candidate(arrays, .5, allow_short_bars=True)
        self.assertTrue(all(b['beat'] == a['beat'] % 4 + 1 for a, b in zip(result['beats'], result['beats'][1:])))

    def test_two_beat_transition_can_be_kept_without_speeding_up(self):
        arrays = fixture()
        arrays['downbeat_logits'][:] = -10.
        downs = [0., 2., 4., *np.arange(5., 20.01, 2.)]
        for second in downs:
            arrays['downbeat_logits'][round(second * 50)] = 8.
        arrays['downbeats'] = np.array(downs)
        result = decode_four_beat_candidate(arrays, .5, phase_anchors=[2., 5., 9.], allow_short_bars=True)
        self.assertTrue(any(a['beat'] == 2 and b['beat'] == 1 for a, b in zip(result['beats'], result['beats'][1:])))
        self.assertTrue(all(abs(b['seconds'] - a['seconds'] - .5) < .03 for a, b in zip(result['beats'], result['beats'][1:])))

    def test_actual_short_bar_position_is_used_for_source_phase(self):
        changes = [{'fine_quarter': i, 'bar_phase_quarter': (i - 2) % 4, 'seconds': i,
                    'active': True, 'chroma_change': 1. if (i - 2) % 4 == 0 else .01, 'low_change': 0.}
                   for i in range(30)]
        self.assertEqual(candidate_phase_scores(changes, 1.)[0]['phase_fine_quarters'], 0.)

    def test_half_double_model_switch_does_not_double_continuous_counter(self):
        beats = np.r_[np.arange(0., 10., 1.), np.arange(10., 20., .5)]
        seconds, quarters, audit = canonical_pulses(beats, 120.)
        self.assertAlmostEqual(quarters[-1] - quarters[0], 39.)
        self.assertEqual(audit['interval_conflicts'], [])

    def test_extra_close_peak_is_reported_instead_of_being_forced_to_a_beat(self):
        raw = np.sort(np.r_[np.arange(0., 20., .5), 4.02])
        seconds, quarters, audit = canonical_pulses(raw, 120.)
        self.assertEqual(len(seconds), 40)
        self.assertEqual(audit['excluded_neighbour_peaks'], [4.02])
        self.assertEqual(int(quarters[-1]), 39)

    def test_continuous_decoder_ignores_isolated_offbeat_peak(self):
        arrays = fixture()
        arrays['beat_logits'][round(7.22 * 50)] = 9.
        result = decode_four_beat_candidate(arrays, .5)
        selected = result['beats']
        self.assertTrue(all(abs(row['seconds'] / .5 - round(row['seconds'] / .5)) < .05 for row in selected))
        self.assertTrue(all(b['beat'] == a['beat'] % 4 + 1 for a, b in zip(selected, selected[1:])))
        self.assertLessEqual(selected[0]['seconds'], 1.)
        self.assertGreaterEqual(selected[-1]['seconds'], 19.)

    def test_phase_test_can_distinguish_period_correct_but_bar_shifted(self):
        changes = [{'fine_quarter': q, 'seconds': q * .5, 'active': True,
                    'chroma_change': 1. if q % 4 == 1 else .05, 'low_change': .8 if q % 4 == 1 else .02}
                   for q in range(64)]
        scores = candidate_phase_scores(changes, 1.)
        self.assertEqual(scores[0]['phase_fine_quarters'], 1.)
        self.assertGreater(scores[0]['contrast'], 1.)

    def test_unsupported_meter_and_nonfinite_model_are_not_silently_rewritten(self):
        with self.assertRaisesRegex(ValueError, '拍号保留未决'):
            decode_four_beat_candidate(fixture(), .5, (6, 8))
        arrays = fixture()
        arrays['beat_logits'][100] = np.nan
        with self.assertRaisesRegex(ValueError, '不合法'):
            decode_four_beat_candidate(arrays, .5)


class ReviewAndPublicationTests(unittest.TestCase):
    def setUp(self):
        self.binding = {'sources': {'mix': {'sha256': 'mix-fingerprint'}}, 'duration_seconds': 20.}
        self.candidate = {'meter': [4, 4], 'knots': [{'quarter': 0., 'seconds': 0.}, {'quarter': 40., 'seconds': 20.}],
                          'source_windows': [{'start': 0, 'phases': {'accompaniment': [
                              {'phase_fine_quarters': 0., 'contrast': .4, 'count': 10},
                              {'phase_fine_quarters': 1., 'contrast': .02, 'count': 10}]}}]}
        self.review = {'version': 1, 'mix_sha256': 'mix-fingerprint', 'candidate_sha256': fingerprint(self.candidate),
                       'notation_level_confirmed': True, 'review_id': 'synthetic-reference', 'reviewer': 'test-fixture',
                       'basis': 'known synthetic sound pattern', 'downbeat_anchors': [
                           {'quarter': 0, 'seconds': 0., 'basis': 'known first attack'},
                           {'quarter': 32, 'seconds': 16., 'basis': 'known later first attack'}]}

    def test_isolated_approved_flag_cannot_bypass_real_clock_anchors(self):
        bad = {'approved': True, 'valid': True, 'status': 'passed'}
        result = inspect_timing_review(bad, self.candidate, self.binding)
        self.assertFalse(result['valid'])

    def test_same_period_shifted_one_beat_is_not_certified(self):
        candidate = deepcopy(self.candidate)
        for knot in candidate['knots']:
            knot['seconds'] += .5
        review = deepcopy(self.review)
        review['candidate_sha256'] = fingerprint(candidate)
        result = inspect_timing_review(review, candidate, self.binding)
        self.assertIn('actual_clock_does_not_match_reviewed_downbeat', result['issues'])

    def test_missing_local_source_cannot_be_hidden_by_whole_song_flag(self):
        candidate = deepcopy(self.candidate)
        candidate['source_windows'] = []
        review = deepcopy(self.review)
        review['candidate_sha256'] = fingerprint(candidate)
        assessment = assess_clock_candidate(candidate, self.binding, review)
        self.assertFalse(assessment['valid'])
        with self.assertRaisesRegex(ValueError, '不推进'):
            require_clock_passed(assessment)

    def test_unsupported_prefix_cannot_be_called_full_song_pass(self):
        candidate = deepcopy(self.candidate)
        candidate['knots'][0]['seconds'] = 10.
        review = deepcopy(self.review)
        review['candidate_sha256'] = fingerprint(candidate)
        result = assess_clock_candidate(candidate, self.binding, review)
        self.assertIn('head_not_observed', [row['kind'] for row in result['issues']])

    def test_clock_pass_does_not_imply_full_music_publication(self):
        assessment = assess_clock_candidate(self.candidate, self.binding, self.review)
        self.assertTrue(assessment['valid'])
        require_clock_passed(assessment)
        with self.assertRaisesRegex(ValueError, '禁止替换'):
            require_music_publication(assessment)

    def test_sufficient_original_source_evidence_does_not_force_user_confirmation(self):
        assessment = assess_clock_candidate(self.candidate, self.binding, model_arrays=fixture())
        self.assertTrue(assessment['valid'])
        self.assertFalse(assessment['review_check']['valid'])
        self.assertTrue(assessment['original_audio_unit_check']['valid'])

    def test_native_model_unit_switch_cannot_be_called_a_unique_notation_level(self):
        arrays = fixture()
        arrays['beats'] = np.r_[np.arange(0., 10., 1.), np.arange(10., 20., .5)]
        assessment = assess_clock_candidate(self.candidate, self.binding, model_arrays=arrays)
        self.assertFalse(assessment['valid'])

    def test_known_reviewed_slow_meter_cannot_be_overruled_by_model_fast_unit(self):
        known = {'review_id': 'prior-review', 'beat_phase': {'quarter_bpm': 60., 'anchor_seconds': 0.}}
        assessment = assess_clock_candidate(self.candidate, self.binding, model_arrays=fixture(), historical_meter_review=known)
        self.assertFalse(assessment['valid'])
        self.assertIn('candidate_conflicts_with_registered_music_review', [row['kind'] for row in assessment['issues']])

    def test_needs_review_with_export_allowed_still_cannot_publish(self):
        with self.assertRaises(ValueError):
            require_music_publication({'status': 'needs_review', 'export_allowed': True, 'critical': False})

    def test_current_normal_collection_cannot_be_used_as_work_output(self):
        root = Path(__file__).resolve().parents[1]
        with self.assertRaises(ValueError):
            require_isolated_output(root / 'results/accompaniment/new', root)

    def test_raw_half_double_ambiguity_does_not_get_cleared_by_old_fit(self):
        vocal = {'audio_analysis': {'tempo': {'half_double_time_ambiguity_unresolved': True}}}
        with patch('source_meter_entry.inspect_source_meter', return_value={'status': 'source_bound_correction_retained'}):
            with self.assertRaisesRegex(ValueError, '不能自动清除'):
                require_unambiguous_new_source(vocal, {})
        with patch('source_meter_entry.inspect_source_meter', return_value={'status': 'source_bound_human_review_retained'}):
            require_unambiguous_new_source(vocal, {})

    def test_actual_source_prepare_stops_before_voice_or_chord_redecode(self):
        from source_meter_project import prepare_source_vocal
        vocal = {'audio_analysis': {'tempo': {'half_double_time_ambiguity_unresolved': True}}}
        with patch('source_meter_entry.inspect_source_meter', return_value={'status': 'unverified_clock_requires_source_rebuild'}), \
             patch('source_meter_project.infer_source_clock', side_effect=AssertionError('不得先算错误拍轴')), \
             patch('source_meter_project.prepare_quality_vocal', side_effect=AssertionError('不得先重切音符')):
            with self.assertRaisesRegex(ValueError, '不能自动清除'):
                prepare_source_vocal(vocal, {}, 'unused', quality=True)

    def test_actual_normal_index_rejects_review_needed_and_keeps_existing_bytes(self):
        import json
        from generate_accompaniment import write_collection_index
        with tempfile.TemporaryDirectory() as folder:
            parent = Path(folder)
            page = parent / 'candidate/index.html'
            page.parent.mkdir()
            page.write_text('candidate', 'utf-8')
            (page.parent / 'project.json').write_text(json.dumps({'music_acceptance': {'status': 'needs_review', 'export_allowed': True}}), 'utf-8')
            (parent / 'index.html').write_text('original-entry', 'utf-8')
            with self.assertRaisesRegex(ValueError, '入口保持原状'):
                write_collection_index(parent, page)
            self.assertEqual((parent / 'index.html').read_text('utf-8'), 'original-entry')

    def test_unreviewed_nonpreferred_candidate_is_not_swept_into_collection(self):
        import json
        from generate_accompaniment import write_collection_index
        with tempfile.TemporaryDirectory() as folder:
            parent = Path(folder)
            for name in ('stable', 'unreviewed'):
                path = parent / name / 'index.html'
                path.parent.mkdir()
                path.write_text(name, 'utf-8')
            (parent / 'unreviewed/project.json').write_text(json.dumps({'music_acceptance': {'status': 'needs_review'}}), 'utf-8')
            write_collection_index(parent, parent / 'stable/index.html')
            result = (parent / 'index.html').read_text('utf-8')
            self.assertIn('stable', result)
            self.assertNotIn('unreviewed', result)


if __name__ == '__main__':
    unittest.main()
