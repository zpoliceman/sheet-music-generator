"""乐句钢琴持续配音通用修复：重配换和弦时的八度内声搜索与固定音保护。"""
# 乐句钢琴持续配音通用修复：新增任意时间轴／音高的单手持续冲突反例。
from copy import deepcopy
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from accompaniment_analysis import SongClock
from phrase_harmony_arrange import phrase_piano_positions
from accompaniment_arrange import piano_hand_positions


# 乐句钢琴持续配音通用修复：新增简单物理秒钟及右手音夹具。
def clock():
    # 乐句钢琴持续配音通用修复：修改不完整时间轴夹具，原式保留；补齐实际SongClock要求的统计。
    # return SongClock({'timing': {'knots': [{'quarter': 0., 'seconds': 0.}, {'quarter': 1., 'seconds': .5}],
    #                             'score_start_quarter': 0., 'meter': [4, 4]}})
    return SongClock({'timing': {'knots': [{'quarter': 0., 'seconds': 0.}, {'quarter': 1., 'seconds': .5}],
                                'score_start_quarter': 0., 'meter': [4, 4]},
                      'statistics': {'bar_ticks': 1920, 'total_ticks': 1920}})


# 乐句钢琴持续配音通用修复：新增实际音符参数，固定音使用与新音相同的完整对象格式。
def note(identity, tick, end, pitch, role='harmony'):
    return {'id': identity, 'hand': 'right', 'start_tick': tick, 'end_tick': end, 'pitch_midi': pitch, 'role': role, 'finger': 3}


class PhrasePianoRegisterTests(unittest.TestCase):
    # 乐句钢琴持续配音通用修复：新增前奏固定内声跨唱段首拍，新低音必须选可按到的同音级八度。
    def test_generated_bass_can_move_octave_at_fixed_instrumental_boundary(self):
        held = note('held', 0, 360, 58); held['hand'] = 'left'
        bass = note('new_bass', 240, 720, 39, 'bass'); bass['hand'] = 'left'
        piano = {'notes': [deepcopy(held), bass], 'adjustments': []}
        phrase_piano_positions(piano, clock(), [held])
        self.assertEqual(piano['notes'][0], held)
        self.assertEqual(piano['notes'][1]['pitch_midi'], 51)
        self.assertEqual(piano['adjustments'][0]['type'], 'compact_piano_generated_bass_for_phrase_transition')

    # 乐句钢琴持续配音通用修复：新增重配后持续音冲突，必须保留固定内声并移新内声八度。
    def test_new_inner_voice_moves_while_fixed_harmony_is_locked(self):
        fixed = [note('fixed', 0, 960, 60)]
        original = fixed + [note('new', 240, 720, 79)]
        piano = {'notes': deepcopy(original), 'adjustments': []}
        with self.assertRaisesRegex(ValueError, '单手八度'):
            piano_hand_positions(piano['notes'], clock())
        positions = phrase_piano_positions(piano, clock(), fixed)
        self.assertEqual(piano['notes'][0], fixed[0])
        self.assertEqual(piano['notes'][1]['pitch_midi'], 67)
        self.assertEqual([(n['start_tick'], n['end_tick']) for n in piano['notes']], [(0, 960), (240, 720)])
        self.assertEqual(positions, piano_hand_positions(piano['notes'], clock()))

    # 乐句钢琴持续配音通用修复：新增可行原配音完全保持，不为新规则无故移八度。
    def test_feasible_music_remains_exactly_unchanged(self):
        piano = {'notes': [note('a', 0, 960, 67), note('b', 240, 720, 72)], 'adjustments': []}
        before = deepcopy(piano)
        phrase_piano_positions(piano, clock(), [])
        self.assertEqual(piano, before)

    # 乐句钢琴持续配音通用修复：新增两个固定和声冲突必须停下，不能通过修改保护音解围。
    def test_impossible_fixed_harmony_is_rejected(self):
        fixed = [note('a', 0, 960, 60), note('b', 240, 720, 79)]
        piano = {'notes': deepcopy(fixed), 'adjustments': []}
        with self.assertRaisesRegex(ValueError, '无合法路径'):
            phrase_piano_positions(piano, clock(), fixed)
        self.assertEqual(piano['notes'], fixed)

    # 乐句钢琴持续配音通用修复：新增低音／旋律角色不可用新内声八度修复擅自改变。
    def test_fixed_melody_with_conflicting_new_melody_still_stops(self):
        fixed = [note('melody', 0, 960, 60, 'instrumental_melody')]
        piano = {'notes': fixed + [note('other', 240, 720, 79, 'instrumental_melody')], 'adjustments': []}
        before = deepcopy(piano)
        with self.assertRaisesRegex(ValueError, '无合法路径'):
            phrase_piano_positions(piano, clock(), fixed)
        self.assertEqual(piano, before)


# 乐句钢琴持续配音通用修复：新增标准测试入口。
if __name__ == '__main__': unittest.main()
