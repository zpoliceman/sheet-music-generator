"""钢琴低音与内声部音区：跨歌曲快速分解、移调及真实旋律保护的回归。"""
import copy, unittest
from unittest.mock import patch
from test_accompaniment import fixture
from accompaniment_analysis import SongClock
from accompaniment_arrange import arrange_piano, performance_groups, piano_hand_positions, validate_playability


# 渴首次吉他编配：新增自拟快分解夹具，刻意包含高内声后立刻回低音，不使用样曲时间或答案。
def fast_groups(shift=0, melody=False):
    shared, vocal = fixture(); shared['instrumental_melody'] = []
    vocal['timing']['knots'] = [{'seconds':0, 'quarter':0}, {'seconds':60 / 166, 'quarter':1}]
    original = performance_groups(shared)[0]
    chord = shared['harmony'][0]
    chord.update(root_pc=shift % 12, bass_pc=shift % 12, quality='maj9',
                 pitch_classes=[(pc + shift) % 12 for pc in (0, 4, 7, 11, 2)])
    groups = []
    for tick, duration, pitch, bass in ((0, 240, 64, True), (240, 240, 55, False),
        (480, 120, 59, False), (600, 240, 62, True)):
        row = {**copy.deepcopy(original), 'tick':tick, 'duration_ticks':duration,
            'kind':'arpeggio', 'melody':None, 'target_midi':pitch + shift,
            'arpeggio_pitch_class':(pitch + shift) % 12, 'bass_anchor':bass}
        if melody and not tick:
            row['melody'] = {'id':'independent_solo', 'pitch_midi':76 + shift, 'duration_ticks':480}
        groups.append(row)
    return shared, vocal, groups


class PianoBassRegisterTests(unittest.TestCase):
    # 渴首次吉他编配：新增真正失败的快速内声／根音往返，修正音区后仍使用原96半音每秒硬约束。
    def test_fast_inner_voice_return_to_bass_is_playable(self):
        shared, vocal, groups = fast_groups()
        with patch('accompaniment_arrange.performance_groups', return_value=groups):
            piano = arrange_piano(shared, vocal)
        self.assertTrue(validate_playability(piano, SongClock(vocal))['valid'])
        basses = [n for n in piano['notes'] if n['role'] == 'bass']
        self.assertEqual([(n['start_tick'], n['pitch_midi']) for n in basses], [(0, 36), (600, 36)])
        inner = [n for n in piano['notes'] if n['role'] == 'harmony' and n['hand'] == 'left']
        self.assertEqual([(n['start_tick'], n['pitch_midi'] % 12) for n in inner], [(240, 7), (480, 11)])
        self.assertTrue(all(36 <= n['pitch_midi'] <= 48 for n in inner))

    def test_transposed_chords_keep_bass_and_pitch_class(self):
        for shift in (-3, -2, 0, 1, 2, 5):
            shared, vocal, groups = fast_groups(shift)
            with patch('accompaniment_arrange.performance_groups', return_value=groups):
                piano = arrange_piano(shared, vocal)
            self.assertTrue(validate_playability(piano, SongClock(vocal))['valid'])
            self.assertTrue(all(n['pitch_midi'] % 12 in shared['harmony'][0]['pitch_classes'] for n in piano['notes']))
            self.assertEqual({n['pitch_midi'] % 12 for n in piano['notes'] if n['role'] == 'bass'}, {shift % 12})

    def test_solo_melody_and_input_evidence_unchanged(self):
        shared, vocal, groups = fast_groups(melody=True); before = copy.deepcopy((shared, vocal, groups))
        with patch('accompaniment_arrange.performance_groups', return_value=groups):
            piano = arrange_piano(shared, vocal)
        self.assertEqual((shared, vocal, groups), before)
        melody = [n for n in piano['notes'] if n['role'] == 'instrumental_melody']
        self.assertEqual([(n['start_tick'], n['end_tick'], n['pitch_midi']) for n in melody], [(0, 480, 76)])

    def test_impossible_fixed_keyboard_jump_still_rejected(self):
        _, vocal, _ = fast_groups()
        fixed = [{'id':'a', 'pitch_midi':36, 'hand':'left', 'start_tick':0, 'end_tick':120},
                 {'id':'b', 'pitch_midi':96, 'hand':'left', 'start_tick':120, 'end_tick':240}]
        with self.assertRaises(ValueError):
            piano_hand_positions(fixed, SongClock(vocal))


if __name__ == '__main__':
    unittest.main()
