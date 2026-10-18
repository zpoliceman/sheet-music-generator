"""极美通用双乐器制谱：相邻和弦的左手内声、固定低音与持续按键反例。"""
# 极美通用双乐器制谱：新增跨调合成输入，测试不使用歌曲时间、小节或旋律答案。
import copy
import unittest
from accompaniment_analysis import SongClock
# 极美通用双乐器制谱：修改，原导入保留；新增双手规划和正式编配入口反例。
# from accompaniment_arrange import plan_piano_left_inner_register, piano_hand_positions, validate_playability
from accompaniment_arrange import plan_piano_left_inner_register, plan_piano_inner_register, piano_hand_positions, validate_playability, arrange_piano, performance_groups
from unittest.mock import patch
from test_accompaniment import fixture


def crossing_notes(shift=0):
    _, vocal = fixture()
    vocal['timing']['knots'] = [{'seconds': 0, 'quarter': 0}, {'seconds': 60 / 152, 'quarter': 1}]
    notes = [
        {'id': 'held_bass', 'hand': 'left', 'role': 'bass', 'pitch_midi': 46 + shift,
         'start_tick': 0, 'end_tick': 240},
        {'id': 'first_inner', 'hand': 'left', 'role': 'harmony', 'pitch_midi': 53 + shift,
         'start_tick': 240, 'end_tick': 480},
        {'id': 'last_inner', 'hand': 'left', 'role': 'harmony', 'pitch_midi': 58 + shift,
         'start_tick': 480, 'end_tick': 600},
        {'id': 'next_bass', 'hand': 'left', 'role': 'bass', 'pitch_midi': 36 + shift,
         'start_tick': 600, 'end_tick': 1080},
        {'id': 'next_inner', 'hand': 'left', 'role': 'harmony', 'pitch_midi': 43 + shift,
         'start_tick': 600, 'end_tick': 840},
        {'id': 'solo', 'hand': 'right', 'role': 'instrumental_melody', 'pitch_midi': 76 + shift,
         'start_tick': 480, 'end_tick': 1080},
    ]
    return notes, SongClock(vocal)


class PianoHarmonicTransitionTests(unittest.TestCase):
    # 极美通用双乐器制谱：新增真实高旋律之后的右手快速回内声，保护旋律音高和持续时长。
    def test_right_inner_octaves_can_follow_fixed_high_solo(self):
        notes, clock = crossing_notes()
        values = [
            {**notes[-1], 'id': 'high_solo', 'pitch_midi': 97, 'start_tick': 0, 'end_tick': 120},
            {**notes[-1], 'id': 'inner', 'role': 'harmony', 'pitch_midi': 60, 'start_tick': 120, 'end_tick': 360},
        ]
        with self.assertRaises(ValueError):
            piano_hand_positions(values, clock)
        result, changes = plan_piano_inner_register(values, clock, 'right')
        self.assertEqual(result[0], values[0])
        self.assertEqual(result[1]['pitch_midi'] % 12, 0)
        self.assertTrue(changes)
        piano_hand_positions(result, clock)

    def test_formal_arranger_uses_fallback_without_changing_melody(self):
        shared, vocal = fixture()
        vocal['timing']['knots'] = [{'seconds': 0, 'quarter': 0}, {'seconds': 60 / 152, 'quarter': 1}]
        proto = performance_groups(shared)[0]
        groups = [
            {**proto, 'tick': 0, 'duration_ticks': 120, 'kind': 'arpeggio', 'bass_anchor': True,
             'melody': {'id': 'high_solo', 'pitch_midi': 97, 'duration_ticks': 120}},
            {**proto, 'tick': 120, 'duration_ticks': 240, 'kind': 'arpeggio', 'bass_anchor': False,
             'melody': None, 'target_midi': 60, 'arpeggio_pitch_class': 0},
        ]
        before = copy.deepcopy((shared, vocal, groups))
        with patch('accompaniment_arrange.performance_groups', return_value=groups):
            piano = arrange_piano(shared, vocal)
        self.assertTrue(validate_playability(piano, SongClock(vocal))['valid'])
        solo = next(n for n in piano['notes'] if n['role'] == 'instrumental_melody')
        self.assertEqual((solo['pitch_midi'], solo['start_tick'], solo['end_tick']), (97, 0, 120))
        self.assertEqual((shared, vocal, groups), before)

    def test_fixed_previous_register_really_fails(self):
        notes, clock = crossing_notes()
        with self.assertRaises(ValueError):
            piano_hand_positions(notes, clock)

    def test_transposed_transitions_keep_fixed_voices_and_all_attacks(self):
        for shift in (-5, -3, 0, 1):
            with self.subTest(shift=shift):
                notes, clock = crossing_notes(shift)
                before = copy.deepcopy(notes)
                fixed, changes = plan_piano_left_inner_register(notes, clock)
                self.assertEqual(notes, before)
                self.assertTrue(changes)
                for old, new in zip(notes, fixed):
                    if old['hand'] == 'left' and old['role'] == 'harmony':
                        self.assertEqual(old['pitch_midi'] % 12, new['pitch_midi'] % 12)
                        self.assertEqual({k: v for k, v in old.items() if k != 'pitch_midi'},
                                         {k: v for k, v in new.items() if k != 'pitch_midi'})
                    else:
                        self.assertEqual(old, new)
                arrangement = {'instrument': 'piano', 'notes': fixed,
                    'hand_positions': piano_hand_positions(fixed, clock),
                    'configuration': {'maximum_hand_position_semitones_per_second': 96}}
                self.assertTrue(validate_playability(arrangement, clock)['valid'])

    def test_impossible_fixed_bass_jump_still_fails(self):
        notes, clock = crossing_notes()
        fixed = [notes[0], {**notes[3], 'pitch_midi': 84, 'start_tick': 120, 'end_tick': 240}]
        fixed[0] = {**fixed[0], 'end_tick': 120}
        with self.assertRaises(ValueError):
            plan_piano_left_inner_register(fixed, clock)

    def test_held_keys_cannot_be_reassigned_mid_note(self):
        notes, clock = crossing_notes()
        notes[0]['end_tick'] = 840
        before = copy.deepcopy(notes)
        fixed, _ = plan_piano_left_inner_register(notes, clock)
        self.assertEqual(fixed[0], before[0])
        piano_hand_positions(fixed, clock)

    def test_same_key_overlap_is_not_accepted(self):
        notes, clock = crossing_notes()
        repeated = [notes[0], {**notes[0], 'id': 'second_bass', 'start_tick': 120}]
        with self.assertRaises(ValueError):
            plan_piano_left_inner_register(repeated, clock)


if __name__ == '__main__':
    unittest.main()
