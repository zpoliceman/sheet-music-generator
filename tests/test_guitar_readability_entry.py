"""吉他编配规则与统一验收修复：入口不得偷偷重算已认可音乐。"""
# 吉他编配规则与统一验收修复：新增跨入口行为反例，防止自动纠拍抢先执行与旧通过状态发布。
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import json
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from generate_accompaniment import generate, write_collection_index
from guitar_readability_acceptance import assess_guitar_readability
from test_guitar_readability_acceptance import fixture


class GuitarReadabilityEntryTests(unittest.TestCase):
    # 吉他编配规则与统一验收修复：新增旧API丢顶层字段的真实旁路反例，音乐与身份不能降级。
    def test_nested_revision_cannot_escape_source_guard_or_publication(self):
        from guitar_readability_acceptance import require_guitar_readability
        from revise_guitar_readability import protected_baseline
        project = fixture()
        project['arrangements']['guitar']['guitar_readability_revision'] = {'version': 2}
        assessment = assess_guitar_readability(project, require_repeat=False)
        with self.assertRaisesRegex(ValueError, '原低音独立验收'):
            require_guitar_readability(project, assessment, final=False)
        with self.assertRaisesRegex(ValueError, '原低音独立验收'):
            protected_baseline(project, Path('nested.json'))
        with tempfile.TemporaryDirectory() as folder:
            parent = Path(folder)
            candidate = parent / 'candidate'
            candidate.mkdir()
            (candidate / 'index.html').write_text('new', 'utf-8')
            (candidate / 'project.json').write_text(json.dumps(project), 'utf-8')
            (parent / 'index.html').write_text('old', 'utf-8')
            with self.assertRaisesRegex(ValueError, '入口保持原状'):
                write_collection_index(parent, candidate / 'index.html')
            self.assertEqual((parent / 'index.html').read_text('utf-8'), 'old')

    def test_legacy_parameter_export_rejects_revision_before_writing(self):
        from accompaniment_export import export_all
        project = fixture()
        project['arrangements']['guitar']['guitar_readability_revision'] = {'version': 2}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'new'
            with self.assertRaisesRegex(ValueError, '完整project'):
                export_all(path, project['shared_analysis'], project['accepted_vocal_project'], project['arrangements'])
            self.assertFalse(path.exists())

    def test_nested_revision_inherits_safe_route(self):
        args = SimpleNamespace(edited_project=Path('existing.json'), output=Path('new'))
        nested = {'arrangements': {'guitar': {'guitar_readability_revision': {'version': 2}}}}
        with patch('generate_accompaniment.read_json', return_value=nested), \
             patch('source_meter_entry.prepare_edited_request', side_effect=AssertionError('不能重猜拍轴')), \
             patch('revise_guitar_readability.revise', return_value={'valid': True}) as revise:
            generate(args)
            self.assertEqual(revise.call_count, 1)

    # 吉他编配规则与统一验收修复：新增实际来源基线反例，防止失败稿通过自比重新获证。
    def test_reimport_missing_or_failed_bass_guard_is_rejected_before_rearrangement(self):
        from revise_guitar_readability import protected_baseline
        for guard in (None, {'valid': False, 'status': 'needs_review'}):
            project = fixture()
            project['guitar_readability_revision'] = {'version': 2}
            project['guitar_source_bass_acceptance'] = guard
            with self.assertRaisesRegex(ValueError, '原低音独立验收未通过'):
                protected_baseline(project, Path('untrusted.json'))

    def test_reimport_uses_original_baseline_and_rejects_changed_ancestor(self):
        from revise_guitar_readability import protected_baseline
        from guitar_source_bass_acceptance import assess_changed_bass_source
        from score_export import sha256
        baseline = fixture()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'original.json'
            path.write_text(json.dumps(baseline), 'utf-8')
            revised = deepcopy(baseline)
            revised['guitar_readability_revision'] = {'version': 2}
            revised['guitar_source_bass_acceptance'] = assess_changed_bass_source(revised, baseline)
            revised['readability_source'] = {'project': str(path), 'project_sha256': sha256(path)}
            actual, actual_path, digest = protected_baseline(revised, Path(folder) / 'revised.json')
            self.assertEqual(actual, baseline)
            self.assertEqual(actual_path, path.resolve())
            self.assertEqual(digest, sha256(path))
            path.write_text('{}', 'utf-8')
            with self.assertRaisesRegex(ValueError, '原工程已改变'):
                protected_baseline(revised, Path(folder) / 'revised.json')

    def test_reimport_cannot_substitute_a_different_baseline_even_with_its_file_sha(self):
        from revise_guitar_readability import protected_baseline
        from guitar_source_bass_acceptance import assess_changed_bass_source
        from score_export import sha256
        baseline = fixture()
        revised = deepcopy(baseline)
        revised['guitar_readability_revision'] = {'version': 2}
        revised['guitar_source_bass_acceptance'] = assess_changed_bass_source(revised, baseline)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'different.json'
            baseline['arrangements']['guitar']['notes'][0]['velocity'] += 1
            path.write_text(json.dumps(baseline), 'utf-8')
            revised['readability_source'] = {'project': str(path), 'project_sha256': sha256(path)}
            with self.assertRaisesRegex(ValueError, '受保护基线不一致'):
                protected_baseline(revised, Path(folder) / 'revised.json')

    def test_explicit_revision_routes_before_old_clock_decoder(self):
        args = SimpleNamespace(edited_project=Path('existing.json'), readable_guitar=True,
                               output=Path('new'), rearrange=False)
        with patch('generate_accompaniment.read_json', return_value={'arrangements': {'guitar': {}}}), \
             patch('source_meter_entry.prepare_edited_request', side_effect=AssertionError('不能重猜拍轴')), \
             patch('revise_guitar_readability.revise', return_value={'valid': True}) as revise:
            self.assertEqual(generate(args), {'valid': True})
            revise.assert_called_once_with(args.edited_project, args.output, None)

    def test_new_revision_inherits_safe_route_without_adding_the_flag_again(self):
        args = SimpleNamespace(edited_project=Path('existing.json'), output=Path('new'))
        with patch('generate_accompaniment.read_json', return_value={'guitar_readability_revision': {'version': 1}}), \
             patch('source_meter_entry.prepare_edited_request', side_effect=AssertionError('不能重猜拍轴')), \
             patch('revise_guitar_readability.revise', return_value={'valid': True}) as revise:
            generate(args)
            self.assertEqual(revise.call_count, 1)

    def test_readable_revision_and_whole_song_reanalysis_cannot_be_combined(self):
        args = SimpleNamespace(edited_project=Path('existing.json'), readable_guitar=True, rearrange=True)
        with patch('generate_accompaniment.read_json', return_value={'arrangements': {'guitar': {}}}):
            with self.assertRaisesRegex(ValueError, '不能同时'):
                generate(args)

    def test_source_directory_cannot_be_overwritten(self):
        from revise_guitar_readability import revise
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            (path / 'original').write_text('must-stay', 'utf-8')
            with patch('revise_guitar_readability.require_isolated_output', return_value=path), \
                 patch('revise_guitar_readability.read_json', side_effect=AssertionError('覆盖检查应先执行')):
                with self.assertRaisesRegex(ValueError, '已有内容'):
                    revise(path / 'project.json', path)
            self.assertEqual((path / 'original').read_text('utf-8'), 'must-stay')

    def test_stale_guitar_pass_cannot_publish_even_if_music_field_says_passed(self):
        project = fixture()
        assessment = assess_guitar_readability(project, require_repeat=False)
        assessment['stage'] = 'export'
        project['guitar_readability_acceptance'] = assessment
        project['arrangements']['guitar']['notes'][0]['end_tick'] = 30
        project['music_acceptance'] = {'status': 'passed', 'unresolved': []}
        with tempfile.TemporaryDirectory() as folder:
            parent = Path(folder)
            candidate = parent / 'candidate'
            candidate.mkdir()
            (candidate / 'index.html').write_text('new', 'utf-8')
            (candidate / 'project.json').write_text(json.dumps(project), 'utf-8')
            (parent / 'index.html').write_text('old', 'utf-8')
            with self.assertRaisesRegex(ValueError, '入口保持原状'):
                write_collection_index(parent, candidate / 'index.html')
            self.assertEqual((parent / 'index.html').read_text('utf-8'), 'old')


if __name__ == '__main__':
    # 吉他编配规则与统一验收修复：新增unittest直接入口。
    unittest.main()
