"""局部时序与弱证据通用修复：新增音区近零、弱低音、增益与音高移调的来源质量反例。"""
from pathlib import Path
import sys
import unittest
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from accompaniment_analysis import Features
from harmonic_source_quality import quality_window


# 局部时序与弱证据通用修复：新增可控频带夹具，近零中音残留不能由强低频RMS获得固定和声票。
def track(pitches, rms=.1, gain=1.):
    values = np.zeros((73, 10))
    for midi, energy in pitches.items():
        values[midi - 24] = energy * gain
    return Features(np.arange(10) / 10, values, np.full(10, rms * gain), np.zeros(10), [], {})


class HarmonicQualityTests(unittest.TestCase):
    def evaluate(self, guitar, bass=None, gain=1., shift=0):
        chord = {n + shift: 1. for n in [48, 52, 55, 60]}
        features = {'accompaniment': track(chord, gain=gain), 'other': track(chord, gain=gain), 'six_guitar': guitar}
        if bass is not None:
            features['bass'] = bass
        return quality_window(features, 0., .9, {'accompaniment': .26, 'other': .3, 'six_guitar': .14})

    def test_loud_subbass_and_near_zero_mid_note_cannot_vote_for_a_chord(self):
        _, _, active, mixture, _, _, audit = self.evaluate(track({26: 2., 64: 1e-7}))
        self.assertNotIn('six_guitar', active)
        self.assertFalse(audit['six_guitar']['active'])
        self.assertLess(mixture[4], .4)

    def test_real_guitar_notes_are_retained(self):
        _, _, active, _, _, _, audit = self.evaluate(track({48: .5, 52: .4, 55: .4}))
        self.assertIn('six_guitar', active)
        self.assertTrue(audit['six_guitar']['active'])

    def test_weak_bass_is_not_normalized_into_root_truth(self):
        _, _, _, _, _, bass, audit = self.evaluate(track({48: 1.}), track({30: .001}, rms=.00001))
        self.assertEqual(float(bass.sum()), 0.)
        self.assertFalse(audit['bass']['active'])

    def test_true_bass_is_retained_as_independent_pitch_evidence(self):
        _, _, _, _, _, bass, audit = self.evaluate(track({48: 1.}), track({36: 1.}, rms=.05))
        self.assertAlmostEqual(bass[0], 1.)
        self.assertTrue(audit['bass']['active'])

    def test_joint_gain_scaling_preserves_effective_source_decisions(self):
        results = []
        for gain in [.1, 1., 2.]:
            _, _, active, mixture, _, bass, _ = self.evaluate(track({26: 2., 64: 1e-7}, gain=gain), track({36: 1.}, rms=.05, gain=gain), gain=gain)
            results.append((active, mixture, bass))
        self.assertEqual(results[0][0], results[1][0])
        self.assertEqual(results[1][0], results[2][0])
        np.testing.assert_allclose(results[0][1], results[2][1])
        np.testing.assert_allclose(results[0][2], results[2][2])

    def test_transposition_rotates_chroma_without_changing_source_quality(self):
        a = self.evaluate(track({48: 1., 52: .7, 55: .6}))
        b = self.evaluate(track({50: 1., 54: .7, 57: .6}), shift=2)
        self.assertEqual(a[2], b[2])
        np.testing.assert_allclose(np.roll(a[3], 2), b[3])

    def test_no_effective_pitch_does_not_invent_other_fallback(self):
        f = {'accompaniment': track({26: 1.}), 'other': track({27: 1.})}
        _, _, active, mixture, _, _, _ = quality_window(f, 0., .9, {'accompaniment': .26, 'other': .3})
        self.assertEqual(active, {})
        self.assertEqual(float(mixture.sum()), 0.)


if __name__ == '__main__':
    unittest.main()
