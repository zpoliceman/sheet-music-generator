"""钢琴同步已认可词音：音符保护、真实碰撞证据与主入口防重编反例。"""
# 钢琴同步已认可词音：新增无曲名合成材料，验证误把分解音当新和弦及无证据删音的风险。
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import sys
import unittest
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from piano_harmony_readability import revise_piano_labels, assess_piano_labels
from test_guitar_readability_acceptance import fixture


def example():
    # 钢琴同步已认可词音：新增一个有短标签、实音可在原C和弦中连续演奏的合成小节。
    project = fixture()
    first = deepcopy(project['shared_analysis']['harmony'][0])
    first['end_tick'] = 240
    middle = {**deepcopy(first), 'id': 'g', 'name': 'G', 'root_pc': 7, 'bass_pc': 7,
              'pitch_classes': [7, 11, 2], 'start_tick': 240, 'end_tick': 360}
    last = {**deepcopy(first), 'id': 'c2', 'start_tick': 360, 'end_tick': 7680}
    project['shared_analysis'].update(harmony=[first, middle, last],
        input_binding={'sources': {'bass': {'sha256': 'synthetic'}}})
    project['arrangements']['piano'].update(pedal=[], attack_events=[], notes=[
        {'id': 'bass', 'pitch_midi': 48, 'hand': 'left', 'role': 'bass', 'start_tick': 0, 'end_tick': 480,
         'chord_id': 'c', 'phrase_harmony_generated': True},
        {'id': 'right', 'pitch_midi': 67, 'hand': 'right', 'role': 'harmony', 'start_tick': 240, 'end_tick': 480,
         'chord_id': 'g'}])
    return project


class PianoPreservedSyncTests(unittest.TestCase):
    def test_short_label_can_be_simplified_without_rewriting_any_note(self):
        project = example()
        before = deepcopy(project)
        result = revise_piano_labels(project)
        self.assertEqual(project, before)
        self.assertEqual(result['arrangements']['piano']['notes'], before['arrangements']['piano']['notes'])
        self.assertEqual(result['shared_analysis'], before['shared_analysis'])
        self.assertEqual(result['accepted_vocal_project'], before['accepted_vocal_project'])
        self.assertEqual(result['arrangements']['guitar'], before['arrangements']['guitar'])
        self.assertTrue(assess_piano_labels(result)['valid'])
        self.assertEqual(result['arrangements']['piano']['readable_harmony'][0]['name'], 'C')

    def test_changed_note_invalidates_previous_label_review(self):
        result = revise_piano_labels(example())
        result['arrangements']['piano']['notes'][0]['pitch_midi'] = 49
        self.assertFalse(assess_piano_labels(result)['valid'])

    def test_changed_label_cannot_reuse_old_passed_record(self):
        result = revise_piano_labels(example())
        result['arrangements']['piano']['readable_harmony'][0]['name'] = 'wrong'
        self.assertFalse(assess_piano_labels(result)['valid'])

    def collision(self):
        # 钢琴同步已认可词音：新增两个原循环挤到同一拍、来自不同和弦的生成相邻低音。
        project = example()
        notes = project['arrangements']['piano']['notes']
        notes.append({**deepcopy(notes[0]), 'id': 'collision', 'pitch_midi': 49, 'chord_id': 'other'})
        return project

    def test_colliding_generated_bass_cannot_be_removed_without_original_audio(self):
        with self.assertRaisesRegex(ValueError, '缺少来源证据'):
            revise_piano_labels(self.collision())

    def test_clear_source_keeps_supported_bass_and_only_omits_generated_collision(self):
        project = self.collision()
        chroma = np.zeros(12)
        chroma[0], chroma[1] = .9, .1
        features = SimpleNamespace(source={'sha256': 'synthetic'}, chroma=lambda *a, **k: chroma)
        revised = revise_piano_labels(project, features)
        self.assertEqual([n['id'] for n in revised['arrangements']['piano']['notes']], ['bass', 'right'])
        self.assertEqual(len(revised['arrangements']['piano']['piano_label_revision']['removed_generated_bass_notes']), 1)
        self.assertTrue(assess_piano_labels(revised)['valid'])

    def test_ambiguous_source_cannot_force_a_collision_resolution(self):
        chroma = np.zeros(12)
        chroma[0], chroma[1] = .51, .49
        features = SimpleNamespace(source={'sha256': 'synthetic'}, chroma=lambda *a, **k: chroma)
        with self.assertRaisesRegex(ValueError, '双窗口未支持'):
            revise_piano_labels(self.collision(), features)

    def test_real_instrumental_note_cannot_be_deleted_as_generated_bass(self):
        project = self.collision()
        project['arrangements']['piano']['notes'][-1]['source_melody_id'] = 'original-melody'
        chroma = np.zeros(12)
        chroma[0] = 1
        features = SimpleNamespace(source={'sha256': 'synthetic'}, chroma=lambda *a, **k: chroma)
        with self.assertRaisesRegex(ValueError, '缺少来源证据'):
            revise_piano_labels(project, features)

    def test_same_chord_semitone_voicing_is_not_a_quantized_cycle_collision(self):
        project = self.collision()
        project['arrangements']['piano']['notes'][-1]['chord_id'] = 'c'
        # 钢琴同步已认可词音：新增本例不应调用删音证据入口；无合适和弦时保留待审失败。
        with self.assertRaisesRegex(ValueError, '保留本拍真实低音'):
            revise_piano_labels(project)

    def test_main_entry_does_not_rearrange_guitar_or_enter_old_local_lyric_export(self):
        from generate_accompaniment import generate
        args = SimpleNamespace(edited_project=Path('sync.json'), output=Path('new'))
        with patch('generate_accompaniment.read_json', return_value={'piano_sync_revision': {'version': 1}, 'local_lyric_revision': {}}), \
             patch('piano_preserved_sync.export_preserved_piano_sync', return_value={'valid': True}) as exported, \
             patch('local_lyric_revision.export_preserved_local_project', side_effect=AssertionError('不能走旧词音入口')):
            self.assertEqual(generate(args), {'valid': True})
            exported.assert_called_once_with(args.edited_project, args.output)

    def test_main_entry_rejects_whole_song_rebuild_for_synced_project(self):
        from generate_accompaniment import generate
        args = SimpleNamespace(edited_project=Path('sync.json'), output=Path('new'), rearrange=True)
        with patch('generate_accompaniment.read_json', return_value={'piano_sync_revision': {'version': 1}}):
            with self.assertRaisesRegex(ValueError, '不能同时重建'):
                generate(args)


if __name__ == '__main__':
    # 钢琴同步已认可词音：新增独立行为测试入口。
    unittest.main()
