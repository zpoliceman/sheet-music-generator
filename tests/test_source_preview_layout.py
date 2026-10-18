"""新曲慢拍生成与转调标签同步：显式新显示参考与密集行预算的保护反例。"""
# 新曲慢拍生成与转调标签同步：新增转调后数字1必须改变参照而实际音高不变的测试。
from copy import deepcopy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path[:0] = [str(Path(__file__).resolve().parents[1] / 'tools'), str(Path(__file__).resolve().parent)]
from test_source_timing_revision import fixture
from score_export import key_definition, jianpu_pitch
from export_timing_revision import local_view, readable_notation_blocks


class SourcePreviewLayoutTests(unittest.TestCase):
    def project(self, enabled):
        voice, clock = fixture()
        voice['tempo_events'] = [{'tick': 0, 'bpm': 60}]
        voice['notation']['key_segments'] = [{'start_tick': 1920, 'start_measure': 2,
            'key': key_definition('D:major'), 'jianpu_reference_midi': 62, 'start_seconds': 4}]
        if enabled:
            voice['time_only_key_projection'] = {'version': 1}
        return {'accepted_vocal_project': voice}, clock['measure_timeline'][1]

    def test_new_local_key_uses_its_own_number_one_without_transposing_notes(self):
        project, measure = self.project(True)
        before = deepcopy(project)
        voice, _, _ = local_view(project, measure)
        self.assertEqual(voice['notation']['jianpu_reference_midi'], 62)
        self.assertEqual(jianpu_pitch(62, voice['notation']['key'], 62), ('1', 0, ''))
        self.assertEqual(project, before)

    def test_legacy_display_reference_is_preserved(self):
        project, measure = self.project(False)
        voice, _, _ = local_view(project, measure)
        self.assertEqual(voice['notation']['jianpu_reference_midi'], 60)

    def test_dense_four_bars_split_by_real_width_without_reordering(self):
        measures = [{'number': i} for i in range(1, 9)]
        with patch('export_timing_revision.render_row', return_value='<svg width="900"/>'):
            rows = readable_notation_blocks({}, measures, native_width_budget=2000)
        self.assertEqual([len(row) for row in rows], [2, 2, 2, 2])
        self.assertEqual([m for row in rows for m in row], measures)

    def test_sparse_rows_still_stop_at_four_measures(self):
        measures = [{'number': i} for i in range(1, 10)]
        with patch('export_timing_revision.render_row', return_value='<svg width="100"/>'):
            rows = readable_notation_blocks({}, measures)
        self.assertEqual([len(row) for row in rows], [4, 4, 1])


if __name__ == '__main__':
    unittest.main()
