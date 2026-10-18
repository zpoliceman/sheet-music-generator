"""慢拍单位与两曲最小修订：真快拍、两小节和声、安静尾段及来源隔离反例。"""
# 慢拍单位与两曲最小修订：新增音乐意义明确的独立合成源，不使用任何真实曲目或人工答案。
from pathlib import Path
from copy import deepcopy
import sys
import unittest
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from source_meter_hierarchy import compare_ordered_candidates
from source_meter_sequence import VECTOR_KEYS, ordered_vectors, validate_ordered_evidence


def fixture(period=.5, duration=160., extra_model_groups=False, silent_tail=0.):
    # 慢拍单位与两曲最小修订：新增跨两小节换和声但鼓保持四拍的反例，防止最慢／最长循环必胜。
    times = np.arange(int(duration * 50) + 1) / 50
    native = np.arange(0., duration + 1e-6, period)
    first = native[::4]
    bp, dp = np.full(len(times), -10.), np.full(len(times), -10.)
    bp[np.rint(native * 50).astype(int)] = 9.
    dp[np.rint((native[::2] if extra_model_groups else first) * 50).astype(int)] = 9.
    arrays = {'beats': native, 'downbeats': first, 'beat_logits': bp, 'downbeat_logits': dp}
    tracks = []
    for role in ('bass', 'accompaniment', 'drums'):
        prefix = 't' + str(len(tracks))
        tracks.append({'role': role, 'source_sha256': str(len(tracks)) * 64, 'prefix': prefix})
        values = {key: np.zeros(len(times)) for key in ('novelty', 'onset_low', 'onset_high', 'phrase') + VECTOR_KEYS}
        values['rms'] = np.ones(len(times))
        values['times'] = times
        if role == 'drums':
            values['onset_low'][np.rint(native * 50).astype(int)] = 2.
            values['onset_high'][np.rint(native[1::2] * 50).astype(int)] = 2.
        else:
            # 慢拍单位与两曲最小修订：新增完整两小节循环；第1／3拍可换低音，同一和弦并非只响一拍。
            pitch = (np.floor(times / (period * 8)).astype(int) * 5) % 12
            for i in range(12):
                values['pitch_class_' + str(i)] = (pitch == i).astype(float)
            values['register_0'][:] = 1.
            values['novelty'][np.rint(first[::2] * 50).astype(int)] = .8
            values['onset_low'][np.rint(native * 50).astype(int)] = 1.
        if silent_tail:
            tail = times > duration - silent_tail
            for key in values:
                if key != 'times':
                    values[key][tail] = 0.
        arrays.update({prefix + '_' + key: value for key, value in values.items()})
    if silent_tail:
        bp[times > duration - silent_tail] = -10.
        dp[times > duration - silent_tail] = -10.
    meta = {'version': 2, 'duration_seconds': duration, 'mix_sha256': 'a' * 64,
            'model_archive_sha256': 'b' * 64, 'tracks': tracks, 'array_sha256': 'c' * 64, 'raw_only': True}
    decoded = [{'beats': [{'seconds': float(t), 'beat': i % 4 + 1}
                for i, t in enumerate(np.arange(0., duration + .001, value))]} for value in (period / 2, period, period * 2)]
    return meta, arrays, decoded


class OrderedMeterTests(unittest.TestCase):
    # 慢拍单位与两曲最小修订：新增真快拍不能被跨两小节和弦循环合并。
    def test_two_bar_harmony_does_not_override_quarter_drum_pulse(self):
        meta, arrays, decoded = fixture(.5)
        result = compare_ordered_candidates(meta, arrays, decoded)
        self.assertEqual(result['notation_level']['status'], 'selected')
        self.assertAlmostEqual(result['notation_level']['bpm'], 120.)

    # 慢拍单位与两曲最小修订：新增第三拍也被模型标强时，不把慢四拍自动判成漏小节。
    def test_secondary_model_groups_do_not_force_double_time(self):
        meta, arrays, decoded = fixture(1., extra_model_groups=True)
        result = compare_ordered_candidates(meta, arrays, decoded)
        self.assertEqual(result['notation_level']['status'], 'selected')
        self.assertAlmostEqual(result['notation_level']['bpm'], 60.)

    # 慢拍单位与两曲最小修订：新增反例顺序不改变音乐结论，绝不能按索引或最慢选择。
    def test_candidate_order_is_irrelevant(self):
        meta, arrays, decoded = fixture(.6)
        left = compare_ordered_candidates(meta, arrays, decoded)
        right = compare_ordered_candidates(meta, arrays, list(reversed(decoded)))
        self.assertEqual(left['notation_level'], right['notation_level'])

    # 慢拍单位与两曲最小修订：新增安静尾段保留覆盖未决，不以最低模型概率否认主体单位。
    def test_silent_tail_cannot_veto_unit_or_certify_full_coverage(self):
        meta, arrays, decoded = fixture(.5, silent_tail=32.)
        result = compare_ordered_candidates(meta, arrays, decoded)
        self.assertEqual(result['notation_level']['status'], 'selected')
        self.assertEqual(result['coverage']['status'], 'needs_review')
        self.assertFalse(result['downstream_timing_revision_allowed'])

    # 慢拍单位与两曲最小修订：新增缺少原声独立支持时不能只信高模型概率。
    def test_empty_source_does_not_certify_model(self):
        meta, arrays, decoded = fixture()
        for track in meta['tracks']:
            for key in ('novelty', 'onset_low', 'onset_high', 'rms') + VECTOR_KEYS:
                arrays[track['prefix'] + '_' + key][:] = 0.
        result = compare_ordered_candidates(meta, arrays, decoded)
        self.assertEqual(result['notation_level']['status'], 'needs_review')

    # 慢拍单位与两曲最小修订：新增首拍局部旋转只使相位未决，不能自动修改真实拍序。
    def test_phase_conflict_does_not_create_spliced_clock(self):
        meta, arrays, decoded = fixture(.5)
        split = len(arrays['downbeat_logits']) // 2
        arrays['downbeat_logits'][split:] = np.roll(arrays['downbeat_logits'][split:], 50)
        before = deepcopy(decoded)
        result = compare_ordered_candidates(meta, arrays, decoded)
        self.assertEqual(result['bar_first_beat']['status'], 'needs_review')
        self.assertEqual(decoded, before)

    # 慢拍单位与两曲最小修订：新增白名单无法塞入人工答案或旧拍轴。
    def test_ordered_pack_rejects_answers_and_wrong_shapes(self):
        meta, arrays, _ = fixture()
        with self.assertRaises(ValueError):
            validate_ordered_evidence({**meta, 'answer': 'slow'}, arrays)
        arrays['t0_pitch_class_0'] = np.zeros(3)
        with self.assertRaises(ValueError):
            validate_ordered_evidence(meta, arrays)

    # 慢拍单位与两曲最小修订：新增全静音／浮点负零不能变成非法能量，也不修改输入缓存。
    def test_vector_preparation_keeps_cache_and_silence(self):
        times = np.arange(100) / 50.
        activations = np.zeros((73, 100)); activations[30, 3:9] = 1.
        before = activations.copy()
        result = ordered_vectors(times, activations)
        self.assertTrue(all(np.min(v) >= 0 for v in result.values()))
        np.testing.assert_array_equal(activations, before)


if __name__ == '__main__':
    unittest.main()
