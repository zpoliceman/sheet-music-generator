"""跨歌曲和弦复用与器乐准备：任意唱段边界不改变小节强拍与源器乐。"""
# 跨歌曲和弦复用与器乐准备：新增独立边界反例，不用特定曲名、歌词、小节或已生成和弦当答案。
from copy import deepcopy
from pathlib import Path
import sys
import unittest
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
from test_phrase_harmony_plan import known_music, arrangements
from phrase_harmony_plan import build_phrase_harmony
# 跨歌曲和弦复用与器乐准备：修改，旧导入保留；新增最终验收范围反例。
# from phrase_harmony_arrange import apply_phrase_harmony, ordinary, music
from phrase_harmony_arrange import apply_phrase_harmony, ordinary, music, needs_joint_pulse_validation
from guitar_right_hand_patterns import validate_patterns


class CompleteBeatBoundaryTests(unittest.TestCase):
    def test_arbitrary_acoustic_boundary_does_not_offset_harmonic_grid(self):
        for meter in ((4, 4), (3, 4), (6, 8)):
            s, v = known_music(bars=2, meter=meter)
            s['sections'][0]['start_tick'] += 59
            s['sections'][-1]['end_tick'] -= 71
            plan = build_phrase_harmony(s, v); pulse = int(480*4/meter[1])
            self.assertTrue(plan['phrases'])
            self.assertTrue(all(p['start_tick'] % pulse == p['end_tick'] % pulse == 0 for p in plan['phrases']))
            planned = [h for h in plan['arranged_harmony'] if h.get('phrase_id')]
            self.assertTrue(all(h['start_tick'] % pulse == h['end_tick'] % pulse == 0 for h in planned))
            self.assertEqual(plan['arranged_harmony'][0]['start_tick'], s['harmony'][0]['start_tick'])
            self.assertEqual(plan['arranged_harmony'][-1]['end_tick'], s['harmony'][-1]['end_tick'])
            self.assertTrue(all(a['end_tick'] == b['start_tick'] for a,b in zip(plan['arranged_harmony'],plan['arranged_harmony'][1:])))

    def test_partial_beats_remain_source_music_and_actual_chord_entries_are_pulse_basses(self):
        s, v = known_music(bars=2); old = arrangements(s, v)
        s['sections'][0]['start_tick'] = 59; s['sections'][-1]['end_tick'] -= 59
        before = deepcopy((s, v, old))
        new, both, check = apply_phrase_harmony(s, v, old)
        self.assertTrue(check['valid']); self.assertEqual((s, v, old), before)
        for name,a in both.items():
            # 跨歌曲和弦复用与器乐准备：修正契约，首部不完整拍保持，尾部已有合成伴奏归共同框架有意重编。
            # protected = [n for n in old[name]['notes'] if n['start_tick'] < 480 or n['start_tick'] >= s['sections'][-1]['end_tick']//480*480]
            protected = [n for n in old[name]['notes'] if n['start_tick'] < 480]
            self.assertTrue(protected)
            actual = {n['id']:music(n) for n in a['notes']}
            self.assertTrue(all(actual[n['id']] == music(n) for n in protected))
            self.assertTrue(all(n['start_tick'] >= 480 for n in a['notes'] if n.get('phrase_harmony_generated')))
        active = dict(new, harmony=new['arranged_harmony'])
        self.assertTrue(validate_patterns(active, both['guitar'])['valid'])

    def test_short_incomplete_vocal_window_does_not_invent_a_new_chord_cycle(self):
        s, v = known_music(bars=2)
        # 跨歌曲和弦复用与器乐准备：修正短窗反例，以开始与结束均在同一拍内部检验没有新正拍可进入。
        # s['sections'] = [dict(s['sections'][0], start_tick=59, end_tick=300)]
        s['sections'] = [dict(s['sections'][0], start_tick=59, end_tick=300)]
        plan = build_phrase_harmony(s, v)
        self.assertFalse(plan['phrases'])
        self.assertEqual(plan['arranged_harmony'], s['harmony'])

    def test_legacy_plan_keeps_original_partial_beat_protection_semantics(self):
        s, _ = known_music(); n = dict(role='bass', start_tick=240)
        s['phrase_harmony_plan'] = {'phrases': [{'start_tick':480,'end_tick':1920,'action':'shared_progression'}]}
        self.assertTrue(ordinary(s,n))
        s['phrase_harmony_plan']['beat_boundary_version'] = 1
        self.assertFalse(ordinary(s,n))

    # 跨歌曲和弦复用与器乐准备：新增完整拍边界策略不把源短音当新模板，也不更换历史4/4验收语义。
    def test_pulse_validator_scope_matches_new_music_and_frozen_source(self):
        s, v = known_music(); s['phrase_harmony_plan'] = {'phrases':[{'action':'shared_progression'}]}
        self.assertFalse(needs_joint_pulse_validation(s))
        s['phrase_harmony_plan']['beat_boundary_version'] = 1
        self.assertTrue(needs_joint_pulse_validation(s))
        # 跨歌曲和弦复用与器乐准备：移动完整范围断言到本验收选择反例，避免落入后续尾拍测试。
        s['phrase_harmony_plan']['phrases'] = []
        self.assertFalse(needs_joint_pulse_validation(s))
        s['phrase_harmony_plan'] = {'phrases':[{'action':'preserve_source_insufficient_evidence'}]}
        self.assertTrue(needs_joint_pulse_validation(s))

    # 跨歌曲和弦复用与器乐准备：新增末尾借时不冻结旧合成碎片，两乐器正拍低音及最小十六分实音可核对。
    def test_partial_final_vocal_beat_uses_joint_cycle_instead_of_frozen_synthetic_tails(self):
        s, v = known_music(bars=2); old = arrangements(s, v)
        s['sections'][-1]['end_tick'] -= 59
        end = s['sections'][-1]['end_tick']; first = end//480*480
        for a in old.values():
            for n in a['notes']:
                if first <= n['start_tick'] < first+480:
                    n['end_tick'] = min(n['end_tick'], end)
        new, both, check = apply_phrase_harmony(s, v, old)
        self.assertTrue(check['valid'])
        for a in both.values():
            ns = [n for n in a['notes'] if first <= n['start_tick'] < first+480]
            self.assertTrue(ns)
            self.assertTrue(all(n.get('phrase_harmony_generated') for n in ns))
            # 跨歌曲和弦复用与器乐准备：修正音乐断言，低音在和弦／循环入口，不强制已持续和弦的每一拍重拨低音。
            # self.assertTrue(any(n['start_tick'] == first and n['role'] == 'bass' for n in ns))
            group = [n for n in a['notes'] if n.get('phrase_harmony_generated') and n['chord_id'] == ns[0]['chord_id']]
            entry = min(n['start_tick'] for n in group)
            self.assertEqual(entry % 480, 0)
            self.assertTrue(any(n['start_tick'] == entry and n['role'] == 'bass' for n in group))
            self.assertTrue(all(n['start_tick'] % 120 == n['end_tick'] % 120 == 0 for n in ns))
        # 跨歌曲和弦复用与器乐准备：移动验收范围断言至上一个测试，原语句保留。
        # s['phrase_harmony_plan']['phrases'] = []
        # self.assertFalse(needs_joint_pulse_validation(s))
        # s['phrase_harmony_plan'] = {'phrases':[{'action':'preserve_source_insufficient_evidence'}]}
        # self.assertTrue(needs_joint_pulse_validation(s))


if __name__ == '__main__':
    unittest.main()
