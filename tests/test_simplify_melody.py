"""主旋律简化版：验证短回摆、主音优先、重要转音和字音/休止边界。"""
# 主旋律简化版：新增已知答案的CPU语义测试，不把真实歌曲自动结果当准确性真值。
import copy
from pathlib import Path
import sys
import unittest
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import simplify_melody as sm

# 主旋律简化版：新增手工音符夹具，原秒长与量化时值独立，暴露主音平局问题。
def note(identity, pitch, start, end, raw=0.3, index=0, confidence=0.5):
    return {'id': identity, 'source_note_id': 'raw_' + identity, 'pitch_midi': pitch,
            'start_tick': start, 'end_tick': end, 'start_seconds': start / 960,
            'end_seconds': start / 960 + raw, 'lyric_index': index,
            'confidence': confidence, 'review_flags': [], 'collapsed_to_grace': start == end}

def fixture(notes, chars):
    return {'quantized_notes': notes, 'events': [],
            'lyrics': {'characters': [{'index': i, 'text': text, 'line_index': 0} for i, text in enumerate(chars)]},
            'timing': {'knots': [{'seconds': 0, 'quarter': 0}, {'seconds': 2, 'quarter': 4}],
                       'score_start_quarter': 0},
            'statistics': {'bar_ticks': 1920, 'total_ticks': 1920, 'measure_count': 1},
            'raw_analysis_preservation': {'path': 'synthetic_source', 'sha256': 'fixed'},
            'tempo_events': [{'tick': 0, 'bpm': 120}], 'notation': {'ppq': 480}}

def pitches(notes):
    return [n['pitch_midi'] for n in notes]

class SimplifiedMelodyTests(unittest.TestCase):
    # 主旋律简化版：新增短邻音返回压缩与稳定双音/三段/大跳保留的音乐语义样例。
    def test_short_neighbor_return_collapses_to_main(self):
        before = [note('a', 60, 0, 240, .27), note('b', 62, 240, 360, .08), note('c', 60, 360, 600, .28)]
        after, _ = sm.simplify_group(before, 0)
        self.assertEqual([(n['pitch_midi'], n['start_tick'], n['end_tick']) for n in after], [(60, 0, 600)])

    def test_stable_whole_tone_turn_survives(self):
        after, _ = sm.simplify_group([note('a', 63, 0, 240, .33), note('b', 65, 240, 480, .32)], 0)
        self.assertEqual(pitches(after), [63, 65])

    def test_stable_three_step_contour_survives(self):
        after, _ = sm.simplify_group([note('a', 53, 0, 240, .30), note('b', 55, 240, 600, .44), note('c', 56, 600, 840, .27)], 0)
        self.assertEqual(pitches(after), [53, 55, 56])

    def test_balanced_large_leap_survives(self):
        after, _ = sm.simplify_group([note('a', 62, 0, 240, .2133), note('b', 65, 240, 360, .2133)], 0)
        self.assertEqual(pitches(after), [62, 65])

    def test_raw_long_main_beats_quantized_tie_and_confidence(self):
        after, action = sm.simplify_group([note('short', 56, 0, 120, .088, confidence=.99), note('main', 55, 120, 240, .229, confidence=.1)], 0)
        self.assertEqual(action['main_pitch_midi'], 55)
        self.assertEqual(pitches(after), [55])

    def test_cadence_secondary_is_retained_only_with_enough_duration(self):
        before = [note('main', 60, 0, 720, .9), note('turn', 62, 720, 960, .31)]
        self.assertEqual(pitches(sm.simplify_group(before, 0, False)[0]), [60])
        self.assertEqual(pitches(sm.simplify_group(before, 0, True)[0]), [60, 62])

    # 主旋律简化版：新增不能跨休止或不同汉字合并，确保歌词完整且休止保留。
    def test_no_rest_filling(self):
        after, _ = sm.simplify_group([note('a', 60, 0, 240, .4), note('b', 62, 480, 600, .1)], 0)
        self.assertEqual([(n['start_tick'], n['end_tick']) for n in after], [(0, 240), (480, 600)])
        events = sm.rebuild_events([dict(n, id=str(i)) for i, n in enumerate(after)], 1920, 1920)
        rests = [(e['start_tick'], e['start_tick'] + e['duration_ticks']) for e in events if e['pitch_midi'] is None]
        self.assertIn((240, 480), rests)
        self.assertEqual(sum(e['duration_ticks'] for e in events), 1920)

    def test_same_pitch_at_different_chars_remains_two_lyric_attacks(self):
        original = fixture([note('a', 60, 0, 480, .5, 0), note('b', 60, 480, 960, .5, 1)], ['我', '等'])
        frozen = copy.deepcopy(original)
        result = sm.simplify_project(original)
        self.assertEqual(len(result['quantized_notes']), 2)
        self.assertEqual([e['lyric']['text'] for e in result['events'] if e.get('lyric', {}).get('text')], ['我', '等'])
        self.assertEqual(result['timing'], original['timing'])
        self.assertEqual(result['tempo_events'], original['tempo_events'])
        self.assertEqual(result['raw_analysis_preservation'], original['raw_analysis_preservation'])
        self.assertEqual(original, frozen)

    def test_zero_grace_is_removed_from_actual_layer_and_kept_in_audit(self):
        original = fixture([note('g', 62, 0, 0, .04), note('main', 60, 0, 480, .5)], ['我'])
        result = sm.simplify_project(original)
        self.assertEqual(pitches(result['quantized_notes']), [60])
        self.assertEqual(len(result['simplification']['removed_zero_tick_pieces']), 1)
        self.assertFalse(any(e['grace'] for e in result['events']))

    # 主旋律简化版：新增拒绝不完整歌词、负时值、重叠和已人工校正版的负例。
    def test_reject_missing_positive_lyric(self):
        with self.assertRaises(ValueError):
            sm.simplify_project(fixture([note('a', 60, 0, 480)], ['我', '等']))

    def test_reject_negative_duration(self):
        with self.assertRaises(ValueError):
            sm.simplify_project(fixture([note('a', 60, 480, 0)], ['我']))

    def test_reject_overlap(self):
        with self.assertRaises(ValueError):
            sm.simplify_project(fixture([note('a', 60, 0, 480), note('b', 60, 240, 600)], ['我']))

    def test_reject_corrected_layer(self):
        original = fixture([note('a', 60, 0, 480)], ['我'])
        original['active_notation_layer'] = 'corrected_score'
        with self.assertRaises(ValueError):
            sm.simplify_project(original)

if __name__ == '__main__':
    unittest.main()
