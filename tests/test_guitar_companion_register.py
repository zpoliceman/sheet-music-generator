"""歌词自动加载与伴随声部音区保护：伴随音区与完整旋律配音衔接。"""
# 歌词自动加载与伴随声部音区保护：新增来源匹配和严格候选测试，不以通过低品代替音乐保护。
from copy import deepcopy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from guitar_companion_register import make_protection, active_constraints
# 歌词自动加载与伴随声部音区保护：新增实际多阶段来源链回归，不能错用后期复用的音符编号。
from guitar_companion_register import reference_project
from score_export import save_json, sha256
import tempfile
from guitar_instrumental_register import locations


class CompanionRegisterTests(unittest.TestCase):
    def test_reference_reads_verified_pre_extraction_stage_not_later_reused_note_ids(self):
        # 歌词自动加载与伴随声部音区保护：新增两个阶段同编号不同配音，必须取真正的重提取前来源且逐文件验SHA。
        root = Path(__file__).resolve().parents[1] / 'test_outputs/accompaniment_runs/tests'
        root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=root) as folder:
            folder = Path(folder)
            voice = {'timing': {'knots': [{'quarter': 0, 'seconds': 0}]}, 'quantized_notes': []}
            shared = {'input_binding': {}, 'harmony': [], 'harmony_windows': []}
            upstream = {'accepted_vocal_project': voice, 'shared_analysis': shared,
                        'arrangements': {'guitar': {'notes': [{'id': 'same_id', 'pitch_midi': 43}]}}}
            prior = folder / 'before_extraction.json'
            save_json(prior, upstream)
            stage = deepcopy(upstream)
            stage['arrangements']['guitar']['notes'][0]['pitch_midi'] = 55
            stage['arrangements']['guitar']['instrumental_source_backbone'] = {'upstream_project': str(prior), 'upstream_sha256': sha256(prior)}
            later = folder / 'later_stage.json'
            save_json(later, stage)
            approved = deepcopy(stage)
            approved['vocal_pattern_source'] = {'project': str(later), 'project_sha256': sha256(later)}
            path = folder / 'approved.json'
            save_json(path, approved)
            reference = {'path': str(path), 'sha256': sha256(path)}
            with patch('source_meter_entry.require_calibrated_source', return_value={}):
                result = reference_project(reference, shared, voice)
                self.assertEqual(result['arrangements']['guitar']['notes'][0]['pitch_midi'], 43)
                save_json(prior, {**upstream, 'tampered': True})
                with self.assertRaisesRegex(ValueError, '上游快照'):
                    reference_project(reference, shared, voice)

    def fixture(self):
        notes = [{'id': 'companion', 'pitch_midi': 67, 'string': 1, 'fret': 3, 'start_tick': 0, 'end_tick': 480, 'role': 'harmony', 'section': 'intro'},
                 {'id': 'melody', 'pitch_midi': 79, 'string': 1, 'fret': 15, 'start_tick': 0, 'end_tick': 960, 'role': 'instrumental_melody', 'section': 'intro'}]
        guitar = {'notes': notes}
        old = deepcopy(notes)
        old[0]['pitch_midi'] = 43
        return guitar, {'arrangements': {'guitar': {'notes': old}}}

    def test_register_lock_keeps_pitch_but_allows_other_strings(self):
        note = {'id': 'a', 'role': 'harmony', 'pitch_midi': 67, 'string': 1, 'fret': 3}
        values = locations(note, 0, 0, 12, {'a'}, 2, companion_pitch=43)
        self.assertTrue(values)
        self.assertEqual({v[2] for v in values}, {43})
        self.assertFalse(locations(note, 0, 0, 4, {'a'}, 2, companion_pitch=39))

    def test_only_same_full_time_and_role_companions_are_preserved(self):
        guitar, stage = self.fixture()
        with patch('guitar_companion_register.reference_project', return_value=stage):
            result = make_protection({'path': 'declared', 'sha256': 'declared'}, {}, {}, guitar)
        self.assertEqual(result['pitch_locks'], {'companion': 43})
        stage['arrangements']['guitar']['notes'][0]['end_tick'] -= 1
        with patch('guitar_companion_register.reference_project', return_value=stage):
            self.assertEqual(make_protection({}, {}, {}, guitar)['pitch_locks'], {})

    def test_changed_declaration_is_rejected_not_replanned_at_higher_octave(self):
        guitar, stage = self.fixture()
        with patch('guitar_companion_register.reference_project', return_value=stage):
            guitar['initial_companion_register_protection'] = make_protection({}, {}, {}, guitar)
            self.assertEqual(active_constraints({}, {}, guitar), {'companion': 43})
            guitar['initial_companion_register_protection']['pitch_locks']['companion'] = 55
            with self.assertRaisesRegex(ValueError, '不能由原工程'):
                active_constraints({}, {}, guitar)


if __name__ == '__main__':
    unittest.main()
