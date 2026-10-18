"""连续唱段拍轴与原唱同步修复：新增独立原轨时序、弱证据、别名相位与源快照保护回归。"""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import sys
import unittest
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from score_export import PPQ, TempoMap
from performance_beat_clock import (POLICY, apply_performance_clock, changed_regions, fit_pulse,
                                    fit_region, fullband_tracks, infer_performance_clock,
                                    derive_performance_vocal, pulse_observations, vocal_disagreements,
                                    # 连续唱段拍轴与原唱同步修复：修改，旧导入末行保留；加入源器乐/合成种子边界回归。
                                    # vocal_observations)
                                    # 连续唱段拍轴与原唱同步修复：修改，旧导入保留；新增相位别名按源事件去重回归。
                                    # vocal_observations, restore_synthetic_seed_ticks)
                                    vocal_observations, restore_synthetic_seed_ticks, deduplicate_source_pulses)


# 连续唱段拍轴与原唱同步修复：新增任意歌词与独立真实秒时间夹具，绝不把样曲小节/文字答案放进生产策略。
def fixture(offset=0., speed=1., meter=(4, 4), first=0., last=20.):
    quarters = np.arange(first, last, .5)
    notes, characters = [], []
    for i, q in enumerate(quarters):
        actual = 2. + speed * q
        notes.append({'id': str(i), 'source_note_id': str(i), 'pitch_midi': 60 + i % 12,
                      'lyric_index': i, 'line_index': i // 8, 'role': 'main', 'grace': False,
                      'start_seconds': actual + .04 * speed, 'end_seconds': actual + .43 * speed,
                      'start_tick': round(q * PPQ), 'end_tick': round((q + .5) * PPQ),
                      'playback_start_tick': round(q * PPQ), 'playback_end_tick': round((q + .5) * PPQ)})
        characters.append({'index': i, 'text': chr(0x4e20 + i), 'line_index': i // 8,
                           'start_seconds': actual, 'end_seconds': actual + .44 * speed,
                           'phonemes': [{'role': 'nucleus', 'start_seconds': actual + .06 * speed}]})
    knots = [{'quarter': q, 'seconds': 2. + speed * q + offset * np.sin(np.pi * q / last) ** 2}
             for q in np.arange(0, last + .01)]
    return {'timing': {'knots': knots, 'score_start_quarter': 0., 'score_start_seconds': 2.,
                      'steady_tempo_bpm': 60. / speed, 'meter': list(meter)},
            'statistics': {'bar_ticks': round(meter[0] * 4 / meter[1] * PPQ),
                           'total_ticks': round(last * PPQ)}, 'quantized_notes': notes,
            'lyrics': {'characters': characters}, 'events': [], 'decoder': {}}


# 连续唱段拍轴与原唱同步修复：新增独立真实起音链，含真实十六分切分；分轨同族重复不增强权重。
def source_track(speed=1., syncopations=True):
    positions = list(np.arange(0., 20., .5))
    if syncopations:
        positions += [5.25, 6.75, 10.25, 13.75, 15.25]
    return {'attacks': [{'seconds': 2. + speed * q, 'strength': 1., 'track': 'six_piano'}
                        for q in sorted(positions)], 'priority': 1., 'source_sha256': 'independent',
            'rms_floor': .01, 'full_attack_count': len(positions)}


class PerformancePulseTests(unittest.TestCase):
    def test_high_register_attacks_are_not_filtered_as_nonbass(self):
        attacks = [{'seconds': float(i), 'strength': 1., 'pitches': [{'midi': 84, 'weight': 1.}]}
                   for i in range(10)]
        f = SimpleNamespace(attacks=attacks, rms=np.ones(10), times=np.arange(10))
        with patch('accompaniment_analysis.extract_features', return_value=f):
            tracks = fullband_tracks({'sources': {'six_piano': {'sha256': 'piano'}}}, ROOT)
        self.assertEqual(len(tracks['six_piano']['attacks']), 10)

    def test_locally_inaudible_tail_does_not_become_a_strong_beat(self):
        f = SimpleNamespace(attacks=[{'seconds': 1., 'strength': 1.}, {'seconds': 8., 'strength': 1.}],
                            rms=np.array([1.] * 6 + [.00001] * 4), times=np.arange(10))
        with patch('accompaniment_analysis.extract_features', return_value=f):
            tracks = fullband_tracks({'sources': {'six_piano': {'sha256': 'piano'}}}, ROOT)
        self.assertEqual([a['seconds'] for a in tracks['six_piano']['attacks']], [1.])

    def test_pulses_keep_syncopations_fractional_instead_of_rounding_to_beats(self):
        track = source_track()
        at = [r for r in track['attacks'] if 6 <= r['seconds'] <= 14]
        fit = fit_pulse(at, 8., 10.2, 1., voice=[{'quarter': q, 'seconds': 2. + q, 'weight': 1.}
                                                for q in [5., 6., 7., 8., 9., 10.]])
        self.assertIsNotNone(fit)
        self.assertAlmostEqual(fit['period_seconds'], 1., places=8)
        self.assertAlmostEqual(fit['center_seconds'], 10., places=8)
        sync = next(o for o in fit['observations'] if abs(o['seconds'] - 7.25) < 1e-8)
        self.assertEqual(sync['quarter'], 5.25)

    def test_two_attack_clusters_across_long_silence_cannot_fit_a_clock(self):
        at = [{'seconds': 2. + q, 'strength': 1.} for q in [0., .25, .5, .75, 6., 6.25, 6.5, 6.75]]
        self.assertIsNone(fit_pulse(at, 3., 5., 1.))

    def test_window_end_only_attacks_do_not_extrapolate_into_unsupported_center(self):
        at = [{'seconds': 2. + q, 'strength': 1.} for q in np.arange(5., 8.01, .25)]
        self.assertIsNone(fit_pulse(at, 3., 5., 1.))

    def test_related_source_and_window_duplicates_do_not_inflate_observation_weight(self):
        v = fixture()
        track = source_track()
        # 连续唱段拍轴与原唱同步修复：修改，旧三值接口保留；检查新增的源相位证据接口。
        # single, _, _ = pulse_observations(v, {'six_piano': track})
        # multiple, _, _ = pulse_observations(v, {'six_piano': track, 'other': dict(track, priority=.6),
        single, _, _, _ = pulse_observations(v, {'six_piano': track})
        multiple, _, _, _ = pulse_observations(v, {'six_piano': track, 'other': dict(track, priority=.6),
                                              'accompaniment': dict(track, priority=.8)})
        self.assertEqual(single, multiple)
        self.assertEqual(len({(r['quarter'], r['family']) for r in multiple}), len(multiple))
        self.assertLessEqual(max(r['weight'] for r in multiple), POLICY['pulse_observation_weight'])

    def test_same_audio_attack_with_two_phase_labels_is_counted_once(self):
        rows = [{'quarter': q, 'seconds': seconds, 'family': 'harmonic_mix', 'selection_rank': rank}
                for q, seconds, rank in [(5., 10., .8), (5.25, 10., .6), (5., 10.02, .7), (6., 11., .8)]]
        selected, evidence = deduplicate_source_pulses(rows, 1.)
        self.assertEqual([(r['quarter'], r['seconds']) for r in selected], [(5., 10.), (6., 11.)])
        self.assertEqual(evidence['resolved_aliases'][0]['candidate_quarters'], [5., 5.25])

    def test_nonmonotonic_source_phase_evidence_is_rejected_for_review(self):
        rows = [{'quarter': q, 'seconds': seconds, 'family': 'harmonic_mix', 'selection_rank': 1.}
                for q, seconds in [(5., 10.), (5.25, 9.5), (6., 11.)]]
        selected, evidence = deduplicate_source_pulses(rows, 1.)
        self.assertEqual([r['quarter'] for r in selected], [6.])
        self.assertEqual(len(evidence['unresolved_phase_conflicts']), 1)

    def test_physical_time_scaling_preserves_pulse_quarter_labels(self):
        results = []
        for speed in [1., 1.4]:
            at = [r for r in source_track(speed)['attacks'] if 2. + speed * 4 <= r['seconds'] <= 2. + speed * 12]
            fit = fit_pulse(at, 8., 2. + 8.2 * speed, speed,
                            voice=[{'quarter': q, 'seconds': 2. + q * speed, 'weight': 1.} for q in [5., 6., 7., 8.]])
            self.assertIsNotNone(fit)
            results.append(fit)
        self.assertEqual([o['quarter'] for o in results[0]['observations']], [o['quarter'] for o in results[1]['observations']])
        self.assertAlmostEqual(results[1]['period_seconds'] / results[0]['period_seconds'], 1.4, places=8)


class PerformanceVoiceTests(unittest.TestCase):
    def evidence(self, offsets, strong_pulse=False, weak=False):
        v = fixture(last=4.)
        voice = vocal_observations(v)[:4]
        for r, delta in zip(voice, offsets):
            r['seconds'] = TempoMap(v['timing']['knots']).quarters_to_seconds(r['quarter']) + delta
        pulse = [{'quarter': r['quarter'], 'weight': 3.2 if weak else 8.} for r in voice] if strong_pulse else []
        triggers, rows = vocal_disagreements(v, TempoMap(v['timing']['knots']), voice, pulse)
        return triggers, rows

    def test_single_word_outlier_does_not_retime_phrase(self):
        triggers, rows = self.evidence([.5, .03, .02, .01])
        self.assertEqual(triggers, [])
        self.assertEqual(rows[0]['status'], 'within_performance_tolerance')

    def test_coherent_multiple_word_delay_triggers_weak_region_fit(self):
        triggers, rows = self.evidence([.45, .5, .48, .47])
        self.assertEqual(len(triggers), 1)
        self.assertEqual(rows[0]['status'], 'coherent_vocal_time_disagreement')

    def test_true_singing_delay_on_reliable_accompaniment_keeps_pulse_and_requests_review(self):
        triggers, rows = self.evidence([.45, .5, .48, .47], strong_pulse=True)
        self.assertEqual(triggers, [])
        self.assertEqual(rows[0]['status'], 'vocal_expression_or_notation_conflict_periodic_pulse_kept')

    def test_weak_related_residual_track_cannot_veto_voice_witnesses(self):
        triggers, rows = self.evidence([.45, .5, .48, .47], strong_pulse=True, weak=True)
        self.assertEqual(len(triggers), 1)
        self.assertEqual(rows[0]['periodic_pulse_word_count'], 0)

    def test_consonant_compensation_is_bounded_and_source_seconds_unchanged(self):
        v = fixture(last=4.)
        c = v['lyrics']['characters'][0]
        c['phonemes'][0]['start_seconds'] += .5
        before = deepcopy(v)
        row = vocal_observations(v)[0]
        self.assertLessEqual(row['seconds'] - row['raw_seconds'], POLICY['maximum_consonant_compensation_quarters'] + 1e-8)
        self.assertEqual(v, before)


class PerformanceClockTests(unittest.TestCase):
    def test_synthetic_seed_keeps_score_tick_while_instrumental_note_keeps_source_second_mapping(self):
        old = fixture(last=12.)
        new = deepcopy(old)
        new['timing']['knots'][8]['seconds'] += .5
        source = [{'id': 'synth', 'role': 'bass', 'start_tick': 8 * PPQ, 'end_tick': 9 * PPQ},
                  {'id': 'melody', 'role': 'instrumental_melody', 'source_melody_id': 'recorded',
                   'start_tick': 8 * PPQ, 'end_tick': 9 * PPQ}]
        shared = {'sections': [{'kind': 'vocal', 'start_seconds': 0., 'end_seconds': 30.}],
                  'statistics': {'bar_ticks': 1920},
                  'harmony': [{'id': 'chord', 'name': 'C', 'start_tick': 0, 'end_tick': 12 * PPQ}]}
        fresh = {'guitar': {'notes': [dict(n, start_tick=8 * PPQ - 120, end_tick=9 * PPQ - 120) for n in source],
                            'attack_events': [], 'beat_phase_seed': {}}}
        result = restore_synthetic_seed_ticks(shared, old, {'guitar': {'notes': source, 'attack_events': []}},
                                              shared, new, fresh)
        by_id = {n['id']: n for n in result['guitar']['notes']}
        self.assertEqual(by_id['synth']['start_tick'], 8 * PPQ)
        self.assertEqual(by_id['melody']['start_tick'], 8 * PPQ - 120)
        self.assertEqual(by_id['melody']['source_melody_id'], 'recorded')

    def test_positive_tempo_solver_preserves_both_endpoints(self):
        mapping = TempoMap([{'quarter': q, 'seconds': float(q)} for q in range(13)])
        obs = [{'quarter': q, 'seconds': q + .5, 'weight': 1.5} for q in [5., 5.25, 5.5, 6.]]
        points, evidence = fit_region(mapping, 0., {'first_quarter': 2., 'last_quarter': 10.}, obs, 1.)
        self.assertEqual(points[0], {'quarter': 2., 'seconds': 2.})
        self.assertEqual(points[-1], {'quarter': 10., 'seconds': 10.})
        self.assertTrue(all(a['seconds'] < b['seconds'] for a, b in zip(points, points[1:])))
        fitted = TempoMap(points)
        self.assertLess(abs(fitted.quarters_to_seconds(5.5) - 6.), .1)
        self.assertEqual(evidence['status'], 'source_performance_time_refitted')

    def test_fixed_clock_without_evidence_is_retained(self):
        v = fixture()
        with patch('performance_beat_clock.fullband_tracks', return_value={}):
            knots, audit = infer_performance_clock(v, {'sources': {}}, ROOT)
        self.assertEqual(knots, v['timing']['knots'])
        self.assertEqual(audit['status'], 'retained_clock')

    def test_periodic_source_corrects_old_clock_without_changing_notation_or_raw_audio(self):
        v = fixture(offset=.3)
        before = deepcopy(v)
        with patch('performance_beat_clock.fullband_tracks', return_value={'six_piano': source_track()}):
            knots, audit = infer_performance_clock(v, {'sources': {}}, ROOT)
        fixed = TempoMap(knots)
        for q in [7., 8., 9., 10., 11., 12.]:
            self.assertLess(abs(fixed.quarters_to_seconds(q) - (2. + q)), .05)
        self.assertEqual(v, before)
        derived = apply_performance_clock(v, knots, audit)
        ignored = {'quantized_start_seconds', 'quantized_end_seconds', 'start_error_seconds', 'end_error_seconds'}
        for a, b in zip(v['quantized_notes'], derived['quantized_notes']):
            self.assertEqual(a, {k: value for k, value in b.items() if k not in ignored})
        self.assertEqual(v['lyrics'], derived['lyrics'])
        self.assertEqual(v['events'], derived['events'])
        self.assertTrue(audit['music_residual_check']['valid'])

    def test_compound_meter_uses_same_quarter_mapping_without_changing_big_beat_structure(self):
        v = fixture(offset=.3, meter=(6, 8))
        with patch('performance_beat_clock.fullband_tracks', return_value={'six_piano': source_track()}):
            knots, audit = infer_performance_clock(v, {'sources': {}}, ROOT)
        out = apply_performance_clock(v, knots, audit)
        self.assertEqual(out['timing']['meter'], [6, 8])
        self.assertEqual(out['statistics']['bar_ticks'], 1440)
        self.assertEqual([n['start_tick'] for n in out['quantized_notes']], [n['start_tick'] for n in v['quantized_notes']])

    def test_long_instrumental_gap_is_not_included_in_voice_refit(self):
        a, b = fixture(first=0., last=4.), fixture(first=12., last=16.)
        # 连续唱段拍轴与原唱同步修复：修改，旧重复字编号夹具保留；第二唱段使用真实独立源身份。
        # a['quantized_notes'] += b['quantized_notes']  # 旧夹具错误：两段共享了同一字编号。
        for n in b['quantized_notes']:
            n.update(id='second_' + n['id'], source_note_id='second_' + n['source_note_id'],
                     lyric_index=n['lyric_index'] + len(a['quantized_notes']))
        a['quantized_notes'] += b['quantized_notes']
        a['statistics']['total_ticks'] = 16 * PPQ
        regions = changed_regions(a, [{'first_quarter': 1., 'last_quarter': 2., 'reason': 'vocal'},
                                      {'first_quarter': 13., 'last_quarter': 14., 'reason': 'vocal'}])
        self.assertEqual([(r['first_quarter'], r['last_quarter']) for r in regions], [(0., 4), (12., 16)])

    def test_nonmonotonic_time_map_is_rejected(self):
        v = fixture(last=4.)
        with self.assertRaisesRegex(ValueError, '严格单调'):
            apply_performance_clock(v, [{'quarter': 0., 'seconds': 1.}, {'quarter': 1., 'seconds': .9}], {'status': 'bad'})

    def test_policy_or_source_fingerprint_change_cannot_bypass_reconstruction(self):
        binding = {'vocal_project_sha256': 'vocal', 'sources': {'mix': {'sha256': 'original'}}}
        correction = {'version': 1, 'policy': deepcopy(POLICY), 'source_vocal_project_sha256': 'vocal',
                      'source_fingerprints': {'mix': 'other'}}
        with self.assertRaisesRegex(ValueError, '指纹'):
            derive_performance_vocal({}, binding, correction)
        correction['source_fingerprints']['mix'] = 'original'
        correction['policy']['retain_notation_ticks'] = False
        with self.assertRaisesRegex(ValueError, '策略'):
            derive_performance_vocal({}, binding, correction)


if __name__ == '__main__':
    unittest.main()
