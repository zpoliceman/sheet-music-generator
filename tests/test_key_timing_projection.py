"""新曲慢拍生成与转调标签同步：覆盖旧坐标越界、短小节和缺词锚点反例。"""
# 新曲慢拍生成与转调标签同步：新增必要的通用元数据保护测试，禁止靠曲名或秒数修复。
from copy import deepcopy
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from key_timing_projection import project_existing_key_segments


class ExistingKeyProjectionTests(unittest.TestCase):
    def fixture(self):
        return {'time_only_revision': {'version': 1}, 'notation': {'key_segments': [
            {'first_character_index': 0, 'start_tick': 0, 'start_measure': 1, 'key': 'C'},
            {'first_character_index': 7, 'start_tick': 999999, 'start_measure': 999, 'key': 'D'}]},
            'timing': {'measure_timeline': [
                {'start_tick': 0, 'number': 1}, {'start_tick': 1920, 'number': 2},
                {'start_tick': 2880, 'number': 3}, {'start_tick': 4800, 'number': 4}]},
            'quantized_notes': [{'id': 'a', 'lyric_index': 0, 'start_tick': 480, 'pitch_midi': 60},
                                {'id': 'b', 'lyric_index': 7, 'start_tick': 2700, 'pitch_midi': 62}]}

    def test_old_label_outside_song_is_replaced_without_changing_music(self):
        original = self.fixture()
        before = deepcopy(original)
        new = project_existing_key_segments(original)
        self.assertEqual(original, before)
        self.assertEqual(new['quantized_notes'], original['quantized_notes'])
        self.assertEqual(new['timing'], original['timing'])
        self.assertEqual(new['notation']['key_segments'][1]['start_tick'], 2880)
        self.assertEqual(new['notation']['key_segments'][1]['start_measure'], 3)
        self.assertTrue(new['notation']['key_segments'][1]['pickup_before_signature'])
        self.assertEqual(new['notation']['key_segments'][1]['key'], 'D')

    def test_exact_short_bar_start_is_not_rounded_to_next_four_beat_bar(self):
        original = self.fixture()
        original['quantized_notes'][1]['start_tick'] = 2880
        new = project_existing_key_segments(original)['notation']['key_segments'][1]
        self.assertEqual(new['start_tick'], 2880)
        self.assertFalse(new['pickup_before_signature'])

    def test_missing_word_owner_stops_instead_of_guessing_from_old_tick(self):
        original = self.fixture()
        original['quantized_notes'].pop()
        with self.assertRaisesRegex(ValueError, '缺少已归属'):
            project_existing_key_segments(original)

    def test_no_existing_segments_is_exact_replay(self):
        original = self.fixture()
        original['notation']['key_segments'] = []
        self.assertEqual(project_existing_key_segments(original), original)


if __name__ == '__main__':
    unittest.main()
