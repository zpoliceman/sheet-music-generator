"""吉他编配规则闭环修复：原低音独立门槛的差分反例。"""
# 吉他编配规则闭环修复：新增提前根音、标签不变转位丢失、原谱保护及缺原轨未决测试。
from copy import deepcopy
from pathlib import Path
import sys
import unittest
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from guitar_source_bass_acceptance import assess_changed_bass_source, require_changed_bass_source
from guitar_source_bass_acceptance import source_bass_music_fingerprint
from guitar_readability_acceptance import fingerprint, music_payload


def fixture():
    # 吉他编配规则闭环修复：新增节拍清楚的通用合成材料；音高44/48等均为实际发声MIDI。
    harmony = [{'name': 'C', 'root_pc': 0, 'bass_pc': 0, 'start_tick': 0, 'end_tick': 9600,
                'quality': '', 'pitch_classes': [0, 4, 7]}]
    return {'accepted_vocal_project': {'timing': {'knots': [{'quarter': 0., 'seconds': 0.},
                                                          {'quarter': 20., 'seconds': 20.}],
                                                'score_start_quarter': 0.},
                                       'statistics': {'total_ticks': 9600, 'bar_ticks': 1920}},
            'shared_analysis': {'harmony': deepcopy(harmony), 'input_binding': {'sources': {'bass': {'sha256': 'bound-bass'}}}},
            'arrangements': {'guitar': {'readable_harmony': harmony, 'notes': [
                {'id': 'original', 'start_tick': 0, 'end_tick': 480, 'pitch_midi': 48, 'role': 'bass'}]}}}


class BassFeatures:
    # 吉他编配规则闭环修复：新增可控原声观察，记录真的查询秒窗而非调用编配器评分。
    def __init__(self, strongest=0, weak=7):
        self.source = {'sha256': 'bound-bass'}
        self.times = np.arange(0., 20.01, .01)
        self.values = np.full(12, .01)
        self.values[strongest] = 1.
        self.values[weak] = .1
        self.windows = []

    def chroma(self, start, end, low, high):
        self.windows.append((start, end, low, high))
        return self.values.copy()


class GuitarSourceBassAcceptanceTests(unittest.TestCase):
    # 慢拍单位与两曲最小修订：新增旧v2只可原样重放，不能为改动后的新单位材料担保。
    def test_legacy_v2_requires_unchanged_music_and_no_unit_revision(self):
        from guitar_source_bass_acceptance import LEGACY_POLICY
        before = fixture()
        old = assess_changed_bass_source(before, deepcopy(before))
        old.update(version=2, policy=deepcopy(LEGACY_POLICY))
        require_changed_bass_source(before, old)
        changed = deepcopy(before)
        changed['arrangements']['guitar']['notes'][0]['end_tick'] += 120
        with self.assertRaises(ValueError):
            require_changed_bass_source(changed, old)
        before['meter_unit_revision'] = {'version': 1}
        with self.assertRaises(ValueError):
            require_changed_bass_source(before, old)

    # 慢拍单位与两曲最小修订：新增差分反例，保护既有和声音不能掩盖真正新增的长前沿或长尾。
    def test_retained_harmony_note_only_new_front_is_assessed(self):
        before = fixture()
        before['arrangements']['guitar']['notes'][0]['end_tick'] = 480
        before['arrangements']['guitar']['notes'].append(
            {'id': 'retained_fill', 'start_tick': 480, 'end_tick': 528,
             'pitch_midi': 43, 'string': 6, 'fret': 3, 'role': 'harmony'})
        after = deepcopy(before)
        after['arrangements']['guitar']['notes'][1]['start_tick'] = 432
        result = assess_changed_bass_source(after, before, BassFeatures())
        self.assertTrue(result['valid'], result)
        self.assertTrue(result['changed_intervals'])
        self.assertTrue(all(r['duration_seconds'] <= .1 + 1e-8 for r in result['changed_intervals']))
        after['arrangements']['guitar']['notes'][1]['start_tick'] = 300
        self.assertFalse(assess_changed_bass_source(after, before, BassFeatures())['valid'])

    def test_same_attack_extended_tail_is_not_exempted(self):
        before = fixture()
        before['arrangements']['guitar']['notes'][0].update(pitch_midi=43, end_tick=48)
        after = deepcopy(before)
        after['arrangements']['guitar']['notes'][0]['end_tick'] = 480
        result = assess_changed_bass_source(after, before, BassFeatures())
        self.assertFalse(result['valid'])
        self.assertTrue(any(r['ticks'] == [48, 480] for r in result['changed_intervals']))

    def test_original_note_cannot_exempt_two_new_notes(self):
        before = fixture()
        before['arrangements']['guitar']['notes'][0]['pitch_midi'] = 43
        after = deepcopy(before)
        after['arrangements']['guitar']['notes'].append(deepcopy(after['arrangements']['guitar']['notes'][0]))
        self.assertFalse(assess_changed_bass_source(after, before, BassFeatures())['valid'])

    def changed(self):
        # 吉他编配规则闭环修复：新增强原C仍在时先换G低音的合成错例。
        before = fixture()
        after = deepcopy(before)
        note = after['arrangements']['guitar']['notes'][0]
        note.update(pitch_midi=43, id='new')
        after['arrangements']['guitar']['readable_harmony'][0].update(name='G', root_pc=7, bass_pc=7)
        return before, after

    def test_early_root_is_rejected_against_original_bass(self):
        before, after = self.changed()
        feature = BassFeatures()
        result = assess_changed_bass_source(after, before, feature)
        self.assertFalse(result['valid'])
        self.assertTrue(result['conflict_interval_count'])
        self.assertIn((0., 1., 24, 59), feature.windows)
        with self.assertRaisesRegex(ValueError, '未通过'):
            require_changed_bass_source(after, result)

    def test_unchanged_old_music_is_not_rejected_for_old_source_disagreement(self):
        before, after = self.changed()
        result = assess_changed_bass_source(after, deepcopy(after), BassFeatures())
        self.assertTrue(result['valid'])
        self.assertFalse(result['applicable'])
        self.assertEqual(result['changed_bass_attacks'], 0)
        require_changed_bass_source(after, result)

    def test_changed_actual_inversion_is_checked_when_harmony_label_does_not_change(self):
        before = fixture()
        before['arrangements']['guitar']['notes'][0]['pitch_midi'] = 45
        after = deepcopy(before)
        after['arrangements']['guitar']['notes'][0].update(id='new', pitch_midi=48)
        result = assess_changed_bass_source(after, before, BassFeatures(strongest=9, weak=0))
        self.assertFalse(result['valid'])
        self.assertTrue(any(r.get('reference_kind') == 'old_actual_sounding_bass'
                            and r['substantial_new_source_conflict_clue'] for r in result['changed_intervals']))

    def test_missing_bass_track_is_unresolved_for_real_pitch_change(self):
        before, after = self.changed()
        before['shared_analysis']['input_binding']['sources'].pop('bass')
        after['shared_analysis']['input_binding']['sources'].pop('bass')
        result = assess_changed_bass_source(after, before)
        self.assertFalse(result['valid'])
        self.assertEqual(result['status'], 'needs_review')
        self.assertTrue(result['unresolved'])

    def test_missing_features_and_wrong_source_sha_are_unresolved(self):
        before, after = self.changed()
        result = assess_changed_bass_source(after, before)
        self.assertFalse(result['valid'])
        feature = BassFeatures()
        feature.source['sha256'] = 'another-recording'
        wrong = assess_changed_bass_source(after, before, feature)
        self.assertFalse(wrong['valid'])
        self.assertTrue(any(r['reason'] == 'bass_feature_source_sha_mismatch' for r in wrong['unresolved']))

    def test_short_passing_bass_does_not_trigger_sustained_conflict_threshold(self):
        before, after = self.changed()
        after['arrangements']['guitar']['notes'][0]['end_tick'] = 48
        result = assess_changed_bass_source(after, before, BassFeatures())
        self.assertTrue(result['valid'], result)
        self.assertFalse(result['applicable'])

    def test_whole_song_not_only_first_phrase_is_observed(self):
        before, after = self.changed()
        for project in (before, after):
            project['arrangements']['guitar']['notes'][0].update(start_tick=8640, end_tick=9120)
        feature = BassFeatures()
        result = assess_changed_bass_source(after, before, feature)
        self.assertFalse(result['valid'])
        self.assertIn((18., 19., 24, 59), feature.windows)

    def test_current_music_and_bound_source_are_required_for_reusing_pass(self):
        before = fixture()
        result = assess_changed_bass_source(before, deepcopy(before))
        self.assertEqual(result['input_music_sha256'], fingerprint(music_payload(before)))
        self.assertEqual(source_bass_music_fingerprint(before), result['input_music_sha256'])
        changed = deepcopy(before)
        changed['arrangements']['guitar']['notes'][0]['pitch_midi'] = 43
        with self.assertRaisesRegex(ValueError, '已失效'):
            require_changed_bass_source(changed, result)
        changed = deepcopy(before)
        changed['shared_analysis']['input_binding']['sources']['bass']['sha256'] = 'new-source'
        with self.assertRaisesRegex(ValueError, 'SHA'):
            require_changed_bass_source(changed, result)
        # 吉他编配规则闭环修复：新增同文件不同秒偏移也必须失效，不能仅靠文件SHA放行。
        changed = deepcopy(before)
        changed['shared_analysis']['input_binding']['sources']['bass']['offset_seconds'] = .5
        with self.assertRaisesRegex(ValueError, '秒偏移'):
            require_changed_bass_source(changed, result)

    def test_new_note_supported_by_original_bass_is_allowed(self):
        before, after = self.changed()
        result = assess_changed_bass_source(after, before, BassFeatures(strongest=7, weak=0))
        self.assertTrue(result['valid'], result)
        self.assertTrue(result['source_features_used'])
        require_changed_bass_source(after, result)

    def test_later_root_support_cannot_hide_wrong_attack_onset(self):
        # 吉他编配规则闭环修复：新增首端仍是旧低音、后半拍才转根的反例，均值好看不等于能提前拨弦。
        before, after = self.changed()
        class DelayedRoot(BassFeatures):
            def chroma(self, start, end, low, high):
                self.windows.append((start, end, low, high))
                values = np.full(12, .01)
                values[0], values[7] = (1., .1) if end <= .25 else (.2, 1.)
                return values
        result = assess_changed_bass_source(after, before, DelayedRoot())
        self.assertFalse(result['valid'])
        self.assertTrue(any(r.get('observation_window_kind') == 'actual_attack_onset'
                            and r['substantial_new_source_conflict_clue'] for r in result['changed_intervals']))
        self.assertTrue(any(r.get('observation_window_kind') == 'whole_actual_overlap'
                            and not r['substantial_new_source_conflict_clue'] for r in result['changed_intervals']))

    def test_renaming_same_low_note_cannot_bypass_source_guard(self):
        # 吉他编配规则闭环修复：新增同一实际错音只改role的直接反例，低音身份以真实指型和音区复核。
        before = fixture()
        before['arrangements']['guitar']['notes'][0].update(pitch_midi=45, string=6, fret=2)
        after = deepcopy(before)
        guitar = after['arrangements']['guitar']
        guitar['configuration'] = {'capo_fret': 3}
        guitar['fingering_diagrams'] = [{'start_tick': 0, 'end_tick': 480,
                                       'frets': {'4': 0, '3': 2, '2': 1, '1': 2}}]
        guitar['notes'][0].update(id='new', pitch_midi=53, string=4, fret=0)
        feature = BassFeatures(strongest=9, weak=5)
        self.assertFalse(assess_changed_bass_source(after, before, feature)['valid'])
        guitar['notes'][0]['role'] = 'harmony'
        result = assess_changed_bass_source(after, before, feature)
        self.assertFalse(result['valid'])
        self.assertIn('new', result['bass_identity']['physically_inferred_bass_ids'])

    def test_actual_move_to_high_string_upper_voice_is_not_renamed_bass(self):
        # 吉他编配规则闭环修复：新增旧低音时点真正改为高三弦上声部，不能把任意分解音误判成根低音。
        before = fixture()
        before['arrangements']['guitar']['notes'][0].update(pitch_midi=45, string=6, fret=2)
        after = deepcopy(before)
        guitar = after['arrangements']['guitar']
        guitar['configuration'] = {'capo_fret': 3}
        guitar['fingering_diagrams'] = [{'start_tick': 0, 'end_tick': 480,
                                       'frets': {'4': 0, '3': 2, '2': 1, '1': 2}}]
        guitar['notes'][0].update(id='new-upper', pitch_midi=63, string=2, fret=1, role='harmony')
        result = assess_changed_bass_source(after, before, BassFeatures(strongest=9, weak=3))
        self.assertTrue(result['valid'], result)
        self.assertFalse(result['applicable'])
        self.assertIn('new-upper', result['bass_identity']['verified_upper_voice_ids'])

    def test_role_only_old_policy_pass_is_stale(self):
        # 吉他编配规则闭环修复：新增策略升级反例，旧验收摘要即使音符一致也不能直接放行。
        before = fixture()
        result = assess_changed_bass_source(before, deepcopy(before))
        result['version'] = 1
        with self.assertRaisesRegex(ValueError, '规则'):
            require_changed_bass_source(before, result)

    def test_existing_instrumental_upper_note_shift_is_not_a_new_bass(self):
        # 吉他编配规则闭环修复：新增无图式器乐高弦时移，原活动低音上方五度的真实高声部保持独立。
        before = fixture()
        guitar = before['arrangements']['guitar']
        guitar['configuration'] = {'capo_fret': 3}
        guitar['notes'][0].update(pitch_midi=58, string=3, fret=0)
        guitar['notes'].append({'id': 'upper', 'start_tick': 30, 'end_tick': 150,
                                'pitch_midi': 65, 'string': 2, 'fret': 3, 'role': 'harmony'})
        after = deepcopy(before)
        after['arrangements']['guitar']['notes'][1].update(start_tick=120, end_tick=240)
        result = assess_changed_bass_source(after, before, BassFeatures(strongest=10, weak=5))
        self.assertTrue(result['valid'], result)
        self.assertIn('upper', result['bass_identity']['verified_upper_voice_ids'])


if __name__ == '__main__':
    # 吉他编配规则闭环修复：新增独立运行入口。
    unittest.main()
