"""原声覆盖与选音归属通用修复：已有v1源拍轴工程的明确质量升级。"""
# 原声覆盖与选音归属通用修复：新增真实入口反例，不允许“已经校过拍轴”跳过新质量检查，也不丢弃人工改动。
from copy import deepcopy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from source_meter_project import prepare_source_vocal, QUALITY_POLICY


class SourceQualityUpgradeEntryTests(unittest.TestCase):
    def setUp(self):
        self.old = {'source_meter_rebuild_correction': {'version': 1}, 'quantized_notes': ['old_wrong_notes']}
        self.binding = {'vocal_project': 'source.json', 'vocal_project_sha256': 'original', 'sources': {}}

    def test_normal_old_request_retains_existing_music(self):
        with patch('source_meter_project.infer_source_clock') as clock:
            result, evidence = prepare_source_vocal(self.old, self.binding, 'unused')
        self.assertIs(result, self.old); clock.assert_not_called()

    def test_explicit_quality_upgrade_reconstructs_source_then_checks_missing_voice(self):
        raw = {'quantized_notes': ['raw']}; base = {'quantized_notes': ['baseline']}
        prepared = {'quantized_notes': ['actual_recovered_voice']}; rebuilt = {'quantized_notes': ['notated_recovered_voice']}
        with patch('source_meter_project.read_json', return_value=raw), \
             patch('source_meter_project.derive_source_vocal', return_value=deepcopy(self.old)), \
             patch('source_meter_project.baseline', return_value=base) as restore, \
             patch('source_meter_project.infer_source_clock', return_value=({'timing': 1}, {'status': 'supported'})), \
             patch('source_meter_project.prepare_quality_vocal', return_value=(prepared, {'recovered_note_count': 1})) as quality, \
             patch('source_meter_project.rebuild_source_vocal', return_value=(rebuilt, {'source_notes': 1})) as rebuild, \
             patch('source_meter_project.source_dependencies', return_value={}), \
             patch('source_meter_project.cache_dependencies', return_value={}), \
             patch('source_meter_project.save_json'):
            result, evidence = prepare_source_vocal(self.old, self.binding, 'unused', quality=True)
        restore.assert_called_once_with(raw, self.binding, self.old['source_meter_rebuild_correction'])
        # 字音唯一挂词音保护通用修复：修改新质量升级入口期待，原断言保留；v3必须启用完整挂词保护。
        # quality.assert_called_once_with(base, self.binding, {'timing': 1})
        quality.assert_called_once_with(base, self.binding, {'timing': 1}, protect_coverage=True)
        rebuild.assert_called_once_with(prepared, {'timing': 1})
        self.assertEqual(result['quantized_notes'], ['notated_recovered_voice'])
        self.assertEqual(result['source_meter_rebuild_correction']['policy'], QUALITY_POLICY)

    def test_edited_old_vocal_not_discarded_by_upgrade(self):
        altered = deepcopy(self.old); altered['quantized_notes'] = ['user_edited']
        with patch('source_meter_project.read_json', return_value={}), \
             patch('source_meter_project.derive_source_vocal', return_value=deepcopy(self.old)), \
             patch('source_meter_project.prepare_quality_vocal') as quality:
            with self.assertRaisesRegex(ValueError, '已改写'):
                prepare_source_vocal(altered, self.binding, 'unused', quality=True)
            quality.assert_not_called()


if __name__ == '__main__':
    unittest.main()
