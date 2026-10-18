"""自动拍层级与首拍盲测：快慢互换、相位冲突、缺证和输入泄漏反例。"""
# 自动拍层级与首拍盲测：新增可听节律对应的合成事件；不含真实曲名、歌词、人工选项或秒数答案。
from copy import deepcopy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from source_meter_selection import (POLICY, compare_candidates, period_candidates,
                                    validate_evidence, select_meter, fingerprint)


def fixture(quarter=1., duration=128.):
    # 自动拍层级与首拍盲测：新增主拍和细分都响的合成原声，只有完整四拍组头特别明确。
    times = np.arange(round(duration * 50) + 1) / 50.
    beat = np.full(len(times), -10.)
    down = np.full(len(times), -10.)
    native = np.arange(0., duration + .001, .5)
    beat[np.rint(native * 50).astype(int)] = 9.
    first = np.arange(0., duration + .001, quarter * 4)
    down[np.rint(first * 50).astype(int)] = 9.
    raw = {'beats': native, 'downbeats': first, 'beat_logits': beat, 'downbeat_logits': down}
    novelty = np.zeros(len(times))
    novelty[np.rint(np.arange(0., duration + .001, quarter) * 50).astype(int)] = .04
    novelty[np.rint(first * 50).astype(int)] = .8
    tracks = []
    for role in ('accompaniment', 'bass'):
        prefix = 't' + str(len(tracks))
        tracks.append({'role': role, 'source_sha256': 'b' * 64, 'prefix': prefix})
        raw.update({prefix + '_times': times, prefix + '_novelty': novelty.copy(),
                    prefix + '_rms': np.ones(len(times)), prefix + '_onset_low': novelty.copy(),
                    prefix + '_onset_high': np.zeros(len(times)), prefix + '_phrase': np.zeros(len(times))})
    meta = {'version': 1, 'duration_seconds': duration, 'mix_sha256': 'a' * 64,
            'model_archive_sha256': 'c' * 64, 'tracks': tracks, 'array_sha256': 'd' * 64, 'raw_only': True}
    candidates = [{'beats': [{'seconds': float(t), 'beat': i % 4 + 1}
                            for i, t in enumerate(np.arange(0., duration + .001, p))]}
                  for p in (.5, 1.)]
    return meta, raw, candidates


class SourceMeterSelectionTests(unittest.TestCase):
    # 自动拍层级与首拍盲测：新增慢拍正确时原生模型细拍不能自动优先。
    def test_slow_group_wins_even_when_native_beats_are_double(self):
        meta, raw, candidates = fixture(1.)
        result = compare_candidates(meta, raw, candidates)
        self.assertEqual(result['status'], 'selected')
        self.assertAlmostEqual(result['notation_level']['bpm'], 60.)
        self.assertFalse(result['downstream_timing_revision_allowed'])
        self.assertFalse(result['full_clock_music_accepted'])

    # 自动拍层级与首拍盲测：新增方向相反的真快拍，禁止总选慢候选。
    def test_fast_group_wins_when_alternate_slow_bars_would_be_omitted(self):
        meta, raw, candidates = fixture(.5)
        result = compare_candidates(meta, raw, candidates)
        self.assertEqual(result['status'], 'selected')
        self.assertAlmostEqual(result['notation_level']['bpm'], 120.)

    # 自动拍层级与首拍盲测：新增候选交换顺序仍应选同一音乐，防止A标签／索引偏好。
    def test_candidate_order_does_not_change_choice(self):
        for quarter in (.5, 1.):
            meta, raw, candidates = fixture(quarter)
            a = compare_candidates(meta, raw, candidates)
            b = compare_candidates(meta, raw, candidates[::-1])
            self.assertEqual(a['notation_level'], b['notation_level'])

    # 自动拍层级与首拍盲测：新增快慢都缺乏首拍证据时拒判。
    def test_no_model_grouping_is_not_invented_from_harmonic_peaks(self):
        meta, raw, candidates = fixture()
        raw['downbeat_logits'][:] = -10.
        result = compare_candidates(meta, raw, candidates)
        self.assertEqual(result['status'], 'needs_review')
        self.assertIsNone(result['notation_level']['bpm'])

    # 自动拍层级与首拍盲测：新增仅模型很自信仍不够，必须有原伴奏上下文。
    def test_model_confidence_without_original_instruments_is_insufficient(self):
        meta, raw, candidates = fixture()
        for track in meta['tracks']:
            raw[track['prefix'] + '_novelty'][:] = 0.
        result = compare_candidates(meta, raw, candidates)
        self.assertIn('original_harmonic_context_insufficient', result['notation_level']['issues'])
        self.assertFalse(result['normal_publication_allowed'])

    # 自动拍层级与首拍盲测：新增高平均分反例；四分之一弱拍是解码器硬补时，也必须拒绝自动选择。
    def test_high_average_cannot_hide_unsupported_individual_pulses(self):
        meta, raw, candidates = fixture(.5)
        weak = np.arange(.5, meta['duration_seconds'], 2.)
        raw['beat_logits'][np.rint(weak * 50).astype(int)] = -9.
        result = compare_candidates(meta, raw, candidates)
        self.assertGreater(result['ranked_candidates'][0]['phases'][0]['model']['beat_probability'], .65)
        self.assertEqual(result['status'], 'needs_review')
        self.assertIn('decoded_pulses_include_unsupported_events', result['notation_level']['issues'])

    # 自动拍层级与首拍盲测：新增原声只支持第三拍时，不准用一个高模型分强行洗成第1拍。
    def test_instrument_phase_conflict_is_kept_unresolved(self):
        meta, raw, candidates = fixture()
        for track in meta['tracks']:
            key = track['prefix'] + '_novelty'
            raw[key] = np.roll(raw[key], 100)
        result = compare_candidates(meta, raw, candidates)
        self.assertEqual(result['status'], 'needs_review')

    # 自动拍层级与首拍盲测：新增前后半曲首拍相反，全局平均不能掩盖局部错位。
    def test_half_song_phase_change_requires_review(self):
        meta, raw, candidates = fixture()
        split = round(len(raw['downbeat_logits']) / 2)
        raw['downbeat_logits'][split:] = np.roll(raw['downbeat_logits'][split:], 100)
        for track in meta['tracks']:
            key = track['prefix'] + '_novelty'
            raw[key][split:] = np.roll(raw[key][split:], 100)
        result = compare_candidates(meta, raw, candidates)
        self.assertEqual(result['bar_first_beat']['status'], 'needs_review')
        self.assertTrue(result['unresolved_windows'])

    # 自动拍层级与首拍盲测：新增只在片尾有证据时不追认整首。
    def test_short_or_single_region_evidence_does_not_certify_whole_song(self):
        meta, raw, candidates = fixture(duration=40.)
        result = compare_candidates(meta, raw, candidates)
        self.assertIn('too_few_independent_time_windows', result['notation_level']['issues'])

    # 自动拍层级与首拍盲测：新增人工表单、标题和旧拍轴不能塞入匿名证据。
    def test_human_answers_and_old_score_fields_are_rejected(self):
        for field in ('human_choice', 'review', 'timing', 'title', 'expected_bpm'):
            meta, raw, _ = fixture()
            meta[field] = 'forbidden'
            with self.assertRaisesRegex(ValueError, '人工答案或旧谱'):
                validate_evidence(meta, raw)

    # 自动拍层级与首拍盲测：新增数组中藏答案同样被拒绝。
    def test_extra_arrays_are_not_silently_accepted(self):
        meta, raw, _ = fixture()
        raw['accepted_clock'] = np.array([1.])
        with self.assertRaisesRegex(ValueError, '数组字段'):
            validate_evidence(meta, raw)

    # 自动拍层级与首拍盲测：新增NaN、坏帧和逆序不参与排名。
    def test_nonfinite_and_reversed_raw_times_are_rejected(self):
        meta, raw, _ = fixture()
        raw['beat_logits'][5] = np.nan
        with self.assertRaises(ValueError):
            validate_evidence(meta, raw)
        meta, raw, _ = fixture()
        raw['t0_times'] = raw['t0_times'][::-1]
        with self.assertRaises(ValueError):
            validate_evidence(meta, raw)

    # 自动拍层级与首拍盲测：新增只有一个候选不能被称为胜出。
    def test_single_candidate_cannot_certify_a_level(self):
        meta, raw, candidates = fixture()
        with self.assertRaisesRegex(ValueError, '独立快慢候选不足'):
            compare_candidates(meta, raw, candidates[:1])

    # 自动拍层级与首拍盲测：新增直接公开入口确实解码全部原声候选，且不修改输入。
    def test_public_entry_decodes_all_raw_candidates_without_mutation(self):
        meta, raw, candidates = fixture()
        before = {key: value.copy() for key, value in raw.items()}
        with patch('source_meter_selection.decode_four_beat_candidate', side_effect=candidates) as decoder, \
             patch('source_meter_selection.period_candidates', return_value=[.5, 1.]):
            result = select_meter(meta, raw)
        self.assertEqual(decoder.call_count, 2)
        self.assertEqual(result['status'], 'selected')
        for key in before:
            np.testing.assert_array_equal(before[key], raw[key])
        self.assertEqual(result['proposed_clock']['beats'][0]['beat'], 1)

    # 自动拍层级与首拍盲测：新增纯原始脉冲候选与冻结策略的可重现性。
    def test_period_proposals_use_raw_arrays_and_policy_fingerprint_is_stable(self):
        _, raw, _ = fixture()
        values = period_candidates(raw)
        self.assertIn(.5, values)
        self.assertIn(1., values)
        self.assertEqual(fingerprint(POLICY), fingerprint(deepcopy(POLICY)))


# 自动拍层级与首拍盲测：新增标准测试入口。
if __name__ == '__main__':
    unittest.main()
