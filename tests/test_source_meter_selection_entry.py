"""自动拍层级与首拍盲测：通用诊断接线、只读来源和防覆盖门禁。"""
# 自动拍层级与首拍盲测：新增实际公共入口的边界测试，避免只有核心函数通过却未接入流程。
from pathlib import Path
from unittest.mock import patch
import json
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from diagnose_source_timing import diagnose
from select_source_meter import choose_evidence, prepare_evidence, _cached_track


class UnreadableOldVocal:
    # 自动拍层级与首拍盲测：新增访问旧拍速／歌词就失败的哨兵，证明自动分流不使用这些字段。
    def __getitem__(self, key):
        raise AssertionError('盲选不应读取旧人声工程：' + key)

    def get(self, key, default=None):
        raise AssertionError('盲选不应读取旧人声工程：' + key)


class SourceMeterEntryTests(unittest.TestCase):
    # 自动拍层级与首拍盲测：新增公共诊断确实分流，且从未读取旧谱或人工表。
    def test_auto_select_enters_raw_source_path_before_any_old_clock_access(self):
        binding = {'sources': {'mix': {'sha256': 'source'}}}
        project = {'accepted_vocal_project': UnreadableOldVocal(), 'shared_analysis': {'input_binding': binding}}
        result = {'status': 'needs_review'}
        with patch('diagnose_source_timing.read_json', return_value=project) as read, \
             patch('diagnose_source_timing.sha256', return_value='unchanged'), \
             patch('diagnose_source_timing.require_isolated_output', return_value=Path('unused')), \
             patch('select_source_meter.select_from_sources', return_value=result) as select, \
             patch('diagnose_source_timing.copy_features', side_effect=AssertionError('旧流程不可执行')):
            actual = diagnose('unused-project', 'unused-output', features_from=['raw-cache'], auto_select=True)
        self.assertEqual(actual, result)
        self.assertEqual(read.call_count, 1)
        self.assertEqual(select.call_args.args, (binding, Path('unused'), None, ['raw-cache']))

    # 自动拍层级与首拍盲测：新增不能同时启用人工复核和盲选。
    def test_human_review_flag_is_incompatible_with_blind_selection(self):
        project = {'accepted_vocal_project': {}, 'shared_analysis': {'input_binding': {}}}
        with patch('diagnose_source_timing.read_json', return_value=project), \
             patch('diagnose_source_timing.sha256', return_value='unchanged'), \
             patch('diagnose_source_timing.require_isolated_output', return_value=Path('unused')), \
             patch('select_source_meter.select_from_sources') as select:
            with self.assertRaisesRegex(ValueError, '不能同时'):
                diagnose('unused-project', 'unused-output', use_source_review=True, auto_select=True)
        select.assert_not_called()

    # 自动拍层级与首拍盲测：新增证据包缺少和声缓存时停止，不自动启动音高重识别。
    def test_missing_acoustic_cache_stops_without_reanalysis(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError, '只读声学缓存'):
                _cached_track({'sha256': 'a' * 64}, 'bass', [folder])
            self.assertEqual(list(Path(folder).iterdir()), [])

    # 自动拍层级与首拍盲测：新增错误原音SHA在创建证据目录前停止。
    def test_changed_original_source_is_rejected_before_writing(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'new-case'
            binding = {'sources': {'mix': {'path': 'unused', 'sha256': 'expected'}}}
            with patch('select_source_meter.require_isolated_output', return_value=target), \
                 patch('select_source_meter.sha256', return_value='wrong'), \
                 patch('select_source_meter.read_source_model') as model:
                with self.assertRaisesRegex(ValueError, 'SHA改变'):
                    prepare_evidence(binding, target)
            model.assert_not_called()
            self.assertFalse(target.exists())

    # 自动拍层级与首拍盲测：新增已有预测不会被新一次猜测覆盖。
    def test_existing_prediction_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'prediction.json'
            output.write_text('sealed', 'utf-8')
            with patch('select_source_meter.require_isolated_output'), \
                 patch('select_source_meter.read_json', side_effect=AssertionError('不应读取')):
                with self.assertRaisesRegex(ValueError, '预测已存在'):
                    choose_evidence(Path(folder) / 'raw.json', output)
            self.assertEqual(output.read_text('utf-8'), 'sealed')

    # 自动拍层级与首拍盲测：新增证据包后来被改动时，不能沿用原判断。
    def test_changed_evidence_archive_blocks_prediction(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'raw.json'
            path.write_text(json.dumps({'array_sha256': 'expected'}), 'utf-8')
            path.with_suffix('.npz').write_bytes(b'changed')
            with patch('select_source_meter.require_isolated_output'), \
                 patch('select_source_meter.select_meter', side_effect=AssertionError('不应计算')):
                with self.assertRaisesRegex(ValueError, 'SHA改变'):
                    choose_evidence(path, Path(folder) / 'prediction.json')


# 自动拍层级与首拍盲测：新增标准测试入口。
if __name__ == '__main__':
    unittest.main()
