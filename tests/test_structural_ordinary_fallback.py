"""渴首次吉他编配：新增歌词换行、句尾音素重叠与源音段连续性的独立反例。"""
from copy import deepcopy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from score_export import TempoMap
import phrase_rhythm_structure as structure
from phrase_rhythm_local import solve_words as legacy_solve


# 渴首次吉他编配：新增自拟连续转音与下一行衬词，音素末界晚于实际下一字发声，音乐仍连续不重叠。
def overlapping_phoneme_fixture():
    intervals = [(0.2, .675), (.675, 1.65), (1.65, 2.55), (2.55, 3.52), (3.52, 4.60), (4.60, 7.58), (7.58, 11.6)]
    words = [0, 0, 1, 2, 2, 2, 3]
    chars = [{'index': i, 'text': chr(0x4e00+i), 'line_index': int(i==3), 'phrase_job_id': int(i==3),
        'start_seconds': a, 'end_seconds': b,
        'phonemes': [{'role': 'nucleus', 'start_seconds': a, 'end_seconds': b}]}
        for i, (a, b) in enumerate(((.666, 1.608), (1.608, 2.496), (2.496, 8.588), (7.295, 11.6)))]
    pieces = [{'id': str(i), 'source_note_id': str(i), 'pitch_midi': pitch,
        'start_seconds': a, 'end_seconds': b, 'lyric_index': words[i], 'line_index': int(words[i]==3),
        'role': 'main' if i in (0, 2, 5, 6) else 'turn', 'grace': False}
        for i, ((a, b), pitch) in enumerate(zip(intervals, (64, 67, 62, 64, 67, 64, 65)))]
    mapping = TempoMap([{'seconds': 0, 'quarter': 0}, {'seconds': 12, 'quarter': 12}])
    timing = {'score_start_quarter': 0, 'steady_tempo_bpm': 60, 'meter': [4, 4]}
    return pieces, chars, mapping, timing


class StructuralFallbackTests(unittest.TestCase):
    # 渴首次吉他编配：新增无新结构证据时不能先枚举本来不会采用的失败候选；所有源音及已合法的拍序保留。
    def test_ordinary_phrase_preserves_joint_legacy_path_despite_overlapping_phoneme_tail(self):
        pieces, chars, mapping, timing = overlapping_phoneme_fixture()
        legacy, _ = legacy_solve(pieces, chars, mapping, timing, 12.)
        words = structure.word_models(pieces, chars, mapping, timing)
        phrases = structure.music_phrases(words)
        self.assertEqual([len(p) for p in phrases], [3, 1])
        self.assertFalse(any(structure.short_groups(p, 1.) or structure.tuplet_candidates(p, 1.) for p in phrases))
        # 渴首次吉他编配：新增先证明旧提前枚举确实无候选，断言修复不是靠放宽时序约束。
        maximum = int((phrases[1][0]['start']+.5)*480)
        baselines = {n['id']: n for n in legacy}
        with self.assertRaisesRegex(ValueError, '节奏候选为空'):
            structure.phrase_options(phrases[0], maximum, 1., 1920,
                baseline=[baselines[w['notes'][0]['id']]['start_tick'] for w in phrases[0]])
        before = deepcopy(pieces)
        with patch('phrase_rhythm_structure.phrase_options', side_effect=AssertionError('普通句不应先枚举结构候选')):
            actual, audit = structure.solve_words(pieces, chars, mapping, timing, 12.)
        music = lambda ns: [(n['id'], n['pitch_midi'], n['start_tick'], n['end_tick'], n['start_seconds'], n['end_seconds']) for n in ns]
        self.assertEqual(music(actual), music(legacy)); self.assertEqual(pieces, before)
        self.assertTrue(all(p['baseline_retained_without_new_structure_evidence'] for p in audit['phrases']))
        self.assertEqual(len(actual), len(pieces))
        ordered = sorted(actual, key=lambda n:n['start_tick'])
        self.assertTrue(all(a['end_tick']<=b['start_tick'] for a,b in zip(ordered, ordered[1:])))


if __name__ == '__main__':
    unittest.main(verbosity=2)
