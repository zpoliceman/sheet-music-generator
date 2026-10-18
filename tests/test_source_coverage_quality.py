"""原声覆盖与选音归属通用修复：独立声学反例与历史政策保护。"""
# 原声覆盖与选音归属通用修复：新增合成反例，不能用歌曲名、固定歌词或只对照实现的元数据证明修复。
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from musical_decode import AcousticEvidence
from source_vocal_quality import prepare_quality_vocal, repair_owners
from source_accompaniment_quality import refine_attacks, guard_harmony
from accompaniment_analysis import Features, detect_attacks
from instrumental_source_melody import combine_tracks, QUALITY_POLICY, POLICY


def char(index, a, b, flags=()):
    return {'index': index, 'line_index': 0, 'start_seconds': a, 'end_seconds': b,
            'review_flags': list(flags), 'phonemes': [{'role': 'nucleus', 'start_seconds': a + .02,
            'end_seconds': b, 'skipped': False}]}


def note(identity, a, b, pitch, owner):
    return {'id': identity, 'source_note_id': identity, 'start_seconds': a, 'end_seconds': b,
            'pitch_midi': pitch, 'lyric_index': owner, 'line_index': 0, 'grace': False,
            'role': 'main', 'anchor': True}


def analysis(pitches):
    return {'configuration': {'frame_step_seconds': .005}, 'pitch_frames': [
        {'time_seconds': i * .005, 'f0_hz': 440 * 2 ** ((p - 69) / 12) if p else 0.}
        for i, p in enumerate(pitches)]}


class SourceVocalQualityTests(unittest.TestCase):
    def prepare(self, pitches, existing, characters, check=None):
        # 原声覆盖与选音归属通用修复：修改，独立运行也使用经验证的项目内测试目录，系统Temp在本沙箱不可写。
        # with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(__file__).resolve().parents[1] / 'test_outputs/accompaniment_runs/tests'
        workspace.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=workspace) as tmp:
            path = Path(tmp) / 'analysis.json'; path.write_text(json.dumps(analysis(pitches)), encoding='utf-8')
            base = {'quantized_notes': existing, 'lyrics': {'characters': characters}, 'inputs': {'notes_path': str(path)}}
            before = deepcopy(base); source_before = path.read_bytes()
            check = check or {'independent_source_audio_checked': True, 'yin_agreement': .98,
                              'vocal_dbfs': -28., 'foreground_ratio_db': 8.}
            result, audit = prepare_quality_vocal(base, {}, {'steady_tempo_bpm': 120}, verifier=lambda core: check)
            self.assertEqual(base, before); self.assertEqual(path.read_bytes(), source_before)
            return result, audit

    def test_missing_first_note_recovers_without_owned_predecessor(self):
        result, audit = self.prepare([0] * 20 + [58] * 36 + [63] * 50,
            [note('later', .28, .53, 63, 0)], [char(0, .1, .53)])
        restored = [n for n in result['quantized_notes'] if n.get('recovery_provenance')]
        self.assertEqual(len(restored), 1); self.assertEqual(restored[0]['pitch_midi'], 58)
        self.assertAlmostEqual(restored[0]['start_seconds'], .1)

    def test_missing_long_tail_recovers_full_vibrato_before_stable_platform(self):
        pitches = [63] * 40 + [60 + .75 * np.sin(i / 8) for i in range(60)] + [60] * 120
        result, audit = self.prepare(pitches, [note('head', 0., .2, 63, 0)], [char(0, 0., 1.1)])
        restored = [n for n in result['quantized_notes'] if n.get('recovery_provenance')]
        self.assertEqual(len(restored), 1); self.assertAlmostEqual(restored[0]['start_seconds'], .2)
        self.assertGreater(restored[0]['end_seconds'], 1.09)

    def test_stable_backing_bleed_rejected(self):
        result, audit = self.prepare([60] * 100, [], [char(0, 0., .5)],
            {'independent_source_audio_checked': True, 'yin_agreement': 1., 'vocal_dbfs': -32., 'foreground_ratio_db': -20.})
        self.assertEqual(audit['recovered_note_count'], 0)

    def test_independent_pitch_disagreement_rejected(self):
        result, audit = self.prepare([60] * 100, [], [char(0, 0., .5)],
            {'independent_source_audio_checked': True, 'yin_agreement': .4, 'vocal_dbfs': -20., 'foreground_ratio_db': 8.})
        self.assertEqual(audit['recovered_note_count'], 0)

    def test_true_silence_not_recovered(self):
        result, audit = self.prepare([0] * 100, [], [char(0, 0., .5)])
        self.assertEqual(audit['coverage_checks'], [])

    def test_missing_two_stable_semitones_remain_distinct(self):
        result, audit = self.prepare([59] * 60 + [60] * 60, [], [char(0, 0., .6)])
        self.assertEqual([n['pitch_midi'] for n in result['quantized_notes']], [59, 60])

    def test_same_pitch_continuation_extends_without_new_midi_attack(self):
        result, audit = self.prepare([60] * 160, [note('held', 0., .3, 60, 0)], [char(0, 0., .8)])
        self.assertEqual(len(result['quantized_notes']), 1)
        self.assertEqual(result['quantized_notes'][0]['id'], 'held')
        self.assertAlmostEqual(result['quantized_notes'][0]['end_seconds'], .8)

    def test_missing_alignment_line_not_forced(self):
        result, audit = self.prepare([60] * 100, [], [char(0, 0., .5, ['asr_missing_line'])])
        self.assertEqual(audit['recovered_note_count'], 0)

    def test_adjacent_slide_stays_with_previous_syllable(self):
        notes = [note('slide', .2, .4, 67, 1), note('long', .4, .8, 67, 2)]
        output, audit = repair_owners(notes, [char(0, 0., .4), char(1, .4, .8), char(2, .8, 1.)],
                                      .5, AcousticEvidence(analysis([67] * 200), False))
        self.assertEqual([n['lyric_index'] for n in output], [0, 1])
        self.assertEqual([n['pitch_midi'] for n in output], [67, 67])
        self.assertEqual(notes[0]['lyric_index'], 1)

    def test_short_voiced_prefix_partition_preserves_full_interval(self):
        output, audit = repair_owners([note('joined', .93, 1.13, 63, 1)],
            [char(0, .7, 1.), char(1, 1., 1.4)], .5, AcousticEvidence(analysis([63] * 300), False))
        self.assertEqual([n['lyric_index'] for n in output], [0, 1])
        self.assertEqual([(n['start_seconds'], n['end_seconds']) for n in output], [(.93, 1.), (1., 1.13)])

    def test_implausibly_short_word_window_cannot_steal_real_note(self):
        existing = [note('long', .73, 1.20, 63, 0)]
        output, audit = repair_owners(existing, [char(0, .717, .777), char(1, .777, 1.58)],
                                      .5, AcousticEvidence(analysis([63] * 400), False))
        self.assertEqual(output, existing)


class AccompanimentCoverageTests(unittest.TestCase):
    def feature(self, activations):
        times = np.arange(activations.shape[1]) * .02
        rms = np.full(len(times), .04)
        attacks, flux = detect_attacks(times, activations, rms)
        return Features(times, activations, rms, flux, attacks, {'sha256': 'fixture'})

    def test_quiet_attacks_not_masked_by_distant_loud_onset(self):
        values = np.zeros((73, 1500)); values[24, 50:60] = 50.
        values[24, 800:810] = .03; values[28, 825:835] = .03
        feature = self.feature(values); before = deepcopy(feature.attacks)
        self.assertFalse(any(15.9 < a['seconds'] < 17.0 for a in before))
        refine_attacks(feature)
        self.assertTrue(any(15.9 < a['seconds'] < 17.0 for a in feature.attacks))

    def test_constant_sustain_does_not_create_multiple_attacks(self):
        values = np.zeros((73, 400)); values[24] = .04
        feature = self.feature(values); refine_attacks(feature)
        self.assertEqual(feature.attacks, [])

    def test_true_silence_has_no_attacks(self):
        feature = self.feature(np.zeros((73, 400))); refine_attacks(feature)
        self.assertEqual(feature.attacks, [])


class HighPartialTests(unittest.TestCase):
    def tracks(self, independent=False):
        times = np.arange(40) * .05
        spectral = np.zeros((40, 88)); spectral[:, 63 - 21] = 1.; spectral[:, 97 - 21] = .55
        notes = spectral.copy(); onsets = spectral * .5
        if independent:
            onsets[:, 97 - 21] = .95; onsets[:, 63 - 21] = .1
        return [{'source': 'other', 'times': times, 'note': notes, 'onset': onsets, 'spectral': spectral}], times

    def test_seventh_partial_is_filtered_before_register_selection(self):
        tracks, times = self.tracks()
        old, _, _, _ = combine_tracks(tracks, times)
        new, _, _, _ = combine_tracks(tracks, times, QUALITY_POLICY)
        self.assertLess(new[:, 97 - 21].mean(), old[:, 97 - 21].mean() * .25)
        self.assertEqual(POLICY['harmonic_parent_intervals'], [12, 19, 24, 28, 31])

    def test_independent_high_lead_onset_is_retained(self):
        tracks, times = self.tracks(True)
        old, _, _, _ = combine_tracks(tracks, times)
        new, _, _, _ = combine_tracks(tracks, times, QUALITY_POLICY)
        np.testing.assert_allclose(new[:, 97 - 21], old[:, 97 - 21])


class StrongBassTests(unittest.TestCase):
    def fixture(self, strong=True):
        key = {'tonic_pc': 0}
        def chord(identity, a, b, root, quality, pcs):
            return {'id': identity, 'start_tick': a, 'end_tick': b, 'root_pc': root,
                    'bass_pc': root, 'quality': quality, 'pitch_classes': pcs, 'name': identity, 'key': key}
        source = [chord('Cm', 0, 480, 0, 'minor', [0, 3, 7]), chord('Ab', 480, 960, 8, 'major', [8, 0, 3])]
        proposed = [chord('Abmaj7', 0, 960, 8, 'maj7', [8, 0, 3, 7])]
        windows = [{'start_tick': h['start_tick'], 'end_tick': h['end_tick'],
                    'bass_chroma': [1. if i == h['bass_pc'] else 0. for i in range(12)],
                    'harmonic_source_quality': {'low_register': {'independent_bass_active': strong}}} for h in source]
        vocal = {'timing': {'knots': [{'seconds': 0., 'quarter': 0.}, {'seconds': 1., 'quarter': 2.}],
                  'score_start_quarter': 0., 'meter': [4, 4]}, 'statistics': {'total_ticks': 960, 'bar_ticks': 1920}}
        return {'harmony': source, 'harmony_windows': windows}, vocal, proposed

    def test_chord_member_bass_still_blocks_premature_root_change(self):
        shared, vocal, proposed = self.fixture()
        result, audit = guard_harmony(shared, vocal, proposed)
        self.assertEqual([(r['start_tick'], r['end_tick'], r['bass_pc']) for r in result], [(0, 480, 0), (480, 960, 8)])
        self.assertEqual(audit[0]['retained'], 'Cm')

    def test_weak_or_correlated_bass_cannot_force_chord(self):
        shared, vocal, proposed = self.fixture(False)
        result, audit = guard_harmony(shared, vocal, proposed)
        self.assertEqual(audit, []); self.assertTrue(all(h['bass_pc'] == 8 for h in result))


if __name__ == '__main__':
    unittest.main()
