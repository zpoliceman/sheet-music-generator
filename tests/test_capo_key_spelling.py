"""新曲慢拍生成与转调标签同步：所有已有大调和夹位均应有等音等价的有效指型调号。"""
# 新曲慢拍生成与转调标签同步：新增音高等价及历史可用拼写保持反例。
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from accompaniment_arrange import capo_shape_key
from accompaniment_analysis import pc_name
from score_export import key_definition, MAJOR_FIFTHS


class CapoShapeKeyTests(unittest.TestCase):
    def test_every_major_key_and_capo_has_same_sounding_pitch(self):
        for tonic in MAJOR_FIFTHS:
            sounding = key_definition(tonic + ':major')
            for capo in range(13):
                shape = capo_shape_key(sounding, capo)
                self.assertEqual((shape['tonic_pc'] + capo) % 12, sounding['tonic_pc'])
                previous = pc_name(sounding['tonic_pc'] - capo, sounding)
                if previous in MAJOR_FIFTHS:
                    self.assertEqual(shape, key_definition(previous + ':major'))

    def test_unsupported_sharp_major_uses_equivalent_flat_key(self):
        shape = capo_shape_key(key_definition('B:major'), 3)
        self.assertEqual(shape['label'], 'Ab:major')
        self.assertEqual(shape['tonic_pc'], 8)


if __name__ == '__main__':
    unittest.main()
