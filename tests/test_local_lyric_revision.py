"""局部词音归属修订：保护固定拍轴、全伴奏和原音完整持续范围的行为反例。"""
# 局部词音归属修订：新增真正分字／搬空原字／证据过期与局部范围保护测试。
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np
import soundfile as sf
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from local_lyric_revision import apply_local_lyric_review, export_preserved_local_project
from score_export import sha256
from guitar_readability_acceptance import fingerprint, music_payload
from source_timing_revision import rebuild_events
from guitar_variable_repeat import measure_timeline
from test_guitar_readability_acceptance import fixture


class LocalLyricRevisionTests(unittest.TestCase):
    # 局部词音归属修订：新增主入口反例，词音变动不能让摘要失配触发整曲伴奏重编。
    def test_main_entry_preserves_local_project_before_guitar_rearrangement(self):
        from generate_accompaniment import generate
        args = SimpleNamespace(edited_project=Path('local.json'), output=Path('new'))
        with patch('generate_accompaniment.read_json', return_value={'local_lyric_revision': {'version': 1}}), \
             patch('local_lyric_revision.export_preserved_local_project', return_value={'valid': True}) as export, \
             patch('revise_guitar_readability.revise', side_effect=AssertionError('不能重编吉他')):
            self.assertEqual(generate(args), {'valid': True})
            export.assert_called_once_with(args.edited_project, args.output)

    def test_whole_song_rebuild_cannot_be_silently_combined_with_local_reimport(self):
        from generate_accompaniment import generate
        args = SimpleNamespace(edited_project=Path('local.json'), output=Path('new'), rearrange=True)
        with patch('generate_accompaniment.read_json', return_value={'local_lyric_revision': {'version': 1}}):
            with self.assertRaisesRegex(ValueError, '不能同时重建'):
                generate(args)

    def test_changed_local_project_cannot_reuse_old_protection_record(self):
        with patch('source_timing_acceptance.require_isolated_output', return_value=Path(self.directory.name) / 'new'), \
             patch('score_export.read_json', return_value={'local_lyric_revision': {'output_music_sha256': 'stale'},
                    **self.project}):
            with self.assertRaisesRegex(ValueError, '局部词音修订已失效'):
                export_preserved_local_project(Path('local.json'), Path('new'))

    def setUp(self):
        # 局部词音归属修订：新增无曲名的真实短音频身份和合成音段，不依赖旧歌曲答案。
        self.directory = tempfile.TemporaryDirectory()
        root = Path(self.directory.name)
        source = root / 'voice.wav'
        sf.write(source, np.zeros(16000), 16000)
        evidence = root / 'observations.json'
        evidence.write_text('{}', 'utf-8')
        self.project = fixture()
        self.project['shared_analysis']['input_binding'] = {'sources': {'vocals': {'path': str(source), 'sha256': sha256(source)}}}
        voice = self.project['accepted_vocal_project']
        voice['lyrics']['characters'] = [{'index': i, 'text': text, 'line_index': 0, 'start_seconds': i + 1., 'end_seconds': i + 2.}
                                         for i, text in enumerate(('甲', '乙', '丙'))]
        voice['quantized_notes'] = [{'id': identity, 'start_seconds': left, 'end_seconds': right, 'pitch_midi': pitch,
                                    'start_tick': int(left * 480), 'end_tick': int(right * 480), 'lyric_index': owner,
                                    'anchor': True, 'role': 'main', 'grace': False}
                                   for identity, left, right, pitch, owner in (('a', 1., 3., 60, 0), ('b', 3., 4., 62, 1), ('c', 4., 5., 64, 2))]
        rebuild_events(voice, measure_timeline(self.project))
        self.review = {'version': 1, 'input_music_sha256': fingerprint(music_payload(self.project)), 'vocals_sha256': sha256(source),
                       'review_id': 'synthetic', 'evidence_files': [{'path': str(evidence), 'sha256': sha256(evidence)}],
                       'operations': [{'kind': 'split_owner', 'note_id': 'a', 'expected_source_seconds': [1., 3.],
                                       'boundaries_seconds': [2.], 'owners': [0, 1]},
                                      {'kind': 'reassign_owner', 'note_id': 'b', 'expected_source_seconds': [3., 4.], 'owner': 2}]}

    def tearDown(self):
        self.directory.cleanup()

    def test_split_keeps_complete_source_pitch_and_all_accompaniment(self):
        before = deepcopy(self.project)
        revised, audit = apply_local_lyric_review(self.project, self.review)
        voice = revised['accepted_vocal_project']
        self.assertEqual(self.project, before)
        self.assertEqual(revised['arrangements'], before['arrangements'])
        self.assertEqual(voice['timing'], before['accepted_vocal_project']['timing'])
        self.assertEqual([(n['start_seconds'], n['end_seconds'], n['pitch_midi'], n['lyric_index']) for n in voice['quantized_notes']],
                         [(1., 2., 60, 0), (2., 3., 60, 1), (3., 4., 62, 2), (4., 5., 64, 2)])
        self.assertTrue(audit['repeat_groups_identical'])
        # 局部词音归属修订：修改受影响字跨到第二小节时仍需更新其延音归属，原固定小节范围断言保留。
        # self.assertEqual([e for e in voice['events'] if e['measure'] > 1],
        #                  [e for e in before['accepted_vocal_project']['events'] if e['measure'] > 1])
        self.assertEqual([e for e in voice['events'] if e['measure'] not in audit['affected_measures']],
                         [e for e in before['accepted_vocal_project']['events'] if e['measure'] not in audit['affected_measures']])

    def test_old_music_or_source_binding_cannot_be_reused(self):
        changed = deepcopy(self.project)
        changed['arrangements']['guitar']['notes'][0]['fret'] = 1
        with self.assertRaisesRegex(ValueError, '实际音乐不一致'):
            apply_local_lyric_review(changed, self.review)

    def test_evidence_file_change_is_rejected(self):
        Path(self.review['evidence_files'][0]['path']).write_text('changed', 'utf-8')
        with self.assertRaisesRegex(ValueError, '证据文件'):
            apply_local_lyric_review(self.project, self.review)

    def test_cannot_borrow_next_syllable_and_leave_original_empty(self):
        self.review['operations'] = [self.review['operations'][1]]
        with self.assertRaisesRegex(ValueError, '搬空原字'):
            apply_local_lyric_review(self.project, self.review)

    def test_cannot_extend_or_trim_original_note_range(self):
        self.review['operations'][0]['expected_source_seconds'] = [1., 2.9]
        with self.assertRaisesRegex(ValueError, '完整范围'):
            apply_local_lyric_review(self.project, self.review)

    def test_split_outside_note_does_not_move_meter_to_fit(self):
        self.review['operations'][0]['boundaries_seconds'] = [.9]
        with self.assertRaisesRegex(ValueError, '超出原持续范围'):
            apply_local_lyric_review(self.project, self.review)

    def test_no_unrelated_character_window_edit_is_allowed(self):
        self.review['character_windows'] = [{'character_index': 3, 'seconds': [4., 5.]}]
        with self.assertRaisesRegex(ValueError, '身份无效'):
            apply_local_lyric_review(self.project, self.review)

    def test_soft_word_can_be_cued_without_borrowing_following_fixed_pitch(self):
        # 局部词音归属修订：新增明确听辨的轻声词只加字音入口，后字音符保持原音高和完整时值。
        self.project['accepted_vocal_project']['quantized_notes'][0]['end_seconds'] = 2.5
        self.project['accepted_vocal_project']['quantized_notes'][0]['end_tick'] = 1200
        rebuild_events(self.project['accepted_vocal_project'], measure_timeline(self.project))
        self.review['input_music_sha256'] = fingerprint(music_payload(self.project))
        self.review['operations'] = [
            {'kind': 'unpitched_lyric_cue', 'owner': 1, 'seconds': [2.7, 2.9], 'listener_review_id': 'source_bound_listener'},
            self.review['operations'][1]]
        revised, _ = apply_local_lyric_review(self.project, self.review)
        voice = revised['accepted_vocal_project']
        self.assertEqual(len(voice['quantized_notes']), 3)
        self.assertEqual(voice['unpitched_lyric_cues'][0]['character_index'], 1)
        self.assertFalse(voice['unpitched_lyric_cues'][0]['fixed_pitch_assigned'])
        self.assertEqual(voice['lyric_mapping']['unmapped_character_indices'], [])
        self.assertEqual(voice['lyric_mapping']['unpitched_character_indices'], [1])
        self.assertEqual([(n['pitch_midi'], n['start_seconds'], n['end_seconds']) for n in voice['quantized_notes']],
                         [(60, 1., 2.5), (62, 3., 4.), (64, 4., 5.)])

    def test_unpitched_word_needs_explicit_listener_review(self):
        # 局部词音归属修订：新增不能以模型缺音为由擅自把正常字改成轻声不定音高。
        self.review['operations'].insert(0, {'kind': 'unpitched_lyric_cue', 'owner': 1, 'seconds': [2.7, 2.9]})
        with self.assertRaisesRegex(ValueError, '缺少明确局部听辨'):
            apply_local_lyric_review(self.project, self.review)

    def test_falling_syllable_keeps_source_and_does_not_invent_terminal_pitch(self):
        # 两处我局部词音核对：新增短下滑表达的真实保护反例，动作不能改原音高、音段或任何伴奏。
        evidence = Path(self.review['evidence_files'][0]['path'])
        evidence.write_text('{"review_id": "listener-fall"}', 'utf-8')
        self.review['evidence_files'][0]['sha256'] = sha256(evidence)
        self.review['operations'][0]['boundaries_seconds'] = [2.8]
        self.review['operations'][0]['pitch_motions'] = [{'owner': 1, 'kind': 'short_falling_glide', 'listener_review_id': 'listener-fall'}]
        revised, _ = apply_local_lyric_review(self.project, self.review)
        child = next(n for n in revised['accepted_vocal_project']['quantized_notes'] if n['id'] == 'a.local_owner_1')
        self.assertEqual((child['start_seconds'], child['end_seconds'], child['pitch_midi']), (2.8, 3., 60))
        self.assertTrue(child['pitch_motion']['terminal_pitch_unspecified'])
        self.assertNotIn('terminal_pitch_midi', child['pitch_motion'])
        self.assertEqual(revised['arrangements'], self.project['arrangements'])

    def test_falling_motion_cannot_reuse_unbound_listener_id(self):
        # 两处我局部词音核对：新增仅写一个听辨ID而没有绑定证据的假通过必须失败。
        self.review['operations'][0]['pitch_motions'] = [{'owner': 1, 'kind': 'short_falling_glide', 'listener_review_id': 'unbound'}]
        with self.assertRaisesRegex(ValueError, '缺少绑定听辨'):
            apply_local_lyric_review(self.project, self.review)


if __name__ == '__main__':
    # 局部词音归属修订：新增独立测试入口。
    unittest.main()
