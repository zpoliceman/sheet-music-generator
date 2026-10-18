"""歌词自动加载与伴随声部音区保护：缓存跨运行复用、自动加载和缺失拒绝。"""
# 歌词自动加载与伴随声部音区保护：新增真实PCM／音素夹具，不运行模型；旧字音严格规则由原测试继续覆盖。
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from first_generation_word_cache import register_cache, apply_cached_words
from first_generation_analysis_bundle import save_bundle, resolve_words, resolve_companion
from first_generation_words import apply_words
from score_export import read_json, save_json, sha256
from test_first_generation_words import fixture


class AnalysisBundleTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[1] / 'test_outputs/accompaniment_runs/tests'
        root.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=root)
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.base, self.legacy, self.binding = fixture(self.folder)
        self.base_path = self.folder / 'base.json'
        self.legacy_path = self.folder / 'words.json'
        save_json(self.base_path, self.base)
        save_json(self.legacy_path, self.legacy)

    def cache(self):
        # 歌词自动加载与伴随声部音区保护：新增仅隔离来源门禁的单元夹具；实际双来源严格重放另由三曲真实入口验证。
        with patch('source_meter_entry.require_calibrated_source', return_value={'status': 'fixture'}):
            path = register_cache(self.legacy_path, self.base_path, self.binding, self.folder / 'cache.json')
        return path

    def test_recomputed_clock_receipt_uses_same_music_without_changing_old_artifact(self):
        cache = self.cache()
        updated = deepcopy(self.base)
        updated['first_source_meter_correction'].update(decision_path='new_run.json', decision_sha256='new_independently_verified_receipt')
        prior_sha = sha256(self.legacy_path)
        with patch('source_meter_entry.require_calibrated_source', return_value={'status': 'fixture'}) as check:
            result = apply_cached_words(updated, read_json(cache), self.binding)
            self.assertEqual(check.call_count, 2)
        expected = apply_words(self.base, self.legacy, self.binding)
        expected['first_source_meter_correction'] = updated['first_source_meter_correction']
        self.assertEqual(result, expected)
        self.assertEqual(sha256(self.legacy_path), prior_sha)

    def test_real_music_changes_are_rejected_even_with_verified_receipt(self):
        cache = read_json(self.cache())
        for kind in ('pitch', 'clock', 'duration', 'word_owner'):
            changed = deepcopy(self.base)
            if kind == 'pitch': changed['quantized_notes'][0]['pitch_midi'] += 1
            if kind == 'clock': changed['timing']['knots'][1]['seconds'] += .01
            if kind == 'duration': changed['quantized_notes'][0]['end_seconds'] -= .01
            if kind == 'word_owner': changed['quantized_notes'][0]['lyric_index'] = 1
            with self.subTest(kind=kind), patch('source_meter_entry.require_calibrated_source', return_value={}), self.assertRaisesRegex(ValueError, '实际拍点'):
                apply_cached_words(changed, cache, self.binding)

    def test_invalid_new_clock_is_not_hidden_by_music_identity(self):
        cache = read_json(self.cache())
        with patch('source_meter_entry.require_calibrated_source', side_effect=[{}, ValueError('new receipt changed')]), self.assertRaisesRegex(ValueError, 'new receipt'):
            apply_cached_words(self.base, cache, self.binding)

    def test_old_source_or_phoneme_file_change_is_rejected(self):
        cache = read_json(self.cache())
        save_json(self.legacy_path, {**self.legacy, 'jobs': []})
        with self.assertRaisesRegex(ValueError, '已经改变'):
            apply_cached_words(self.base, cache, self.binding)

    def test_normal_cache_load_finds_words_without_word_argument(self):
        cache = self.cache()
        shared = self.folder / 'shared_analysis.json'
        save_json(shared, {'input_binding': self.binding, 'harmony': [], 'harmony_windows': []})
        save_bundle(shared, cache)
        self.assertEqual(resolve_words(shared), cache.resolve())
        self.assertIsNone(resolve_companion(shared))

    def test_required_words_missing_changed_or_entire_manifest_missing_are_rejected(self):
        cache = self.cache()
        shared = self.folder / 'shared_analysis.json'
        save_json(shared, {'input_binding': self.binding})
        manifest = save_bundle(shared, cache)
        cache_bytes = cache.read_bytes()
        cache.unlink()
        with self.assertRaisesRegex(ValueError, '缺失'):
            resolve_words(shared)
        cache.write_bytes(cache_bytes)
        save_json(cache, {})
        with self.assertRaisesRegex(ValueError, '已经改变'):
            resolve_words(shared)
        cache.write_bytes(cache_bytes)
        manifest.unlink()
        with self.assertRaisesRegex(ValueError, '清单缺失'):
            resolve_words(shared)

    def test_explicit_file_cannot_silently_override_declared_correction(self):
        cache = self.cache()
        shared = self.folder / 'shared_analysis.json'
        save_json(shared, {'input_binding': self.binding})
        save_bundle(shared, cache)
        wrong = self.folder / 'different.json'
        save_json(wrong, {'different': True})
        with self.assertRaisesRegex(ValueError, '冲突'):
            resolve_words(shared, wrong)


if __name__ == '__main__':
    unittest.main()
