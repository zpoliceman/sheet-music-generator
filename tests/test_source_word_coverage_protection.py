"""字音唯一挂词音保护通用修复：完整挂词、可行归属迁移与历史政策反例。"""
# 字音唯一挂词音保护通用修复：新增任意字窗与合成原声，避免用歌曲歌词作为修复答案。
from copy import deepcopy
from pathlib import Path
import sys
import unittest
sys.path[:0] = [str(Path(__file__).resolve().parents[1] / 'tools'), str(Path(__file__).resolve().parent)]
from test_source_coverage_quality import char, note, analysis
from musical_decode import AcousticEvidence
from source_vocal_quality import repair_owners


class WordCoverageProtectionTests(unittest.TestCase):
    # 字音唯一挂词音保护通用修复：新增音素错位不能搬走唯一计量挂词音，原音高与音段不变。
    def test_only_metered_owner_is_retained_with_explicit_conflict(self):
        original = [note('only', .55, .85, 63, 0), note('next', .85, 1.1, 65, 1)]
        before = deepcopy(original)
        output, audit = repair_owners(original, [char(0, .1, .4), char(1, .4, 1.2)], .5,
                                      AcousticEvidence(analysis([63] * 300), False), protect_coverage=True)
        self.assertEqual(output, original); self.assertEqual(original, before)
        self.assertTrue(audit[0]['requires_ownership_review'])
        self.assertEqual(audit[0]['proposed_owner'], 1)

    # 字音唯一挂词音保护通用修复：新增已经有其它计量音覆盖时，强音素重叠仍允许修正。
    def test_redundant_owner_can_still_move(self):
        original = [note('head', .1, .3, 63, 0), note('wrong', .55, .85, 63, 0)]
        output, audit = repair_owners(original, [char(0, .1, .4), char(1, .4, 1.2)], .5,
                                      AcousticEvidence(analysis([63] * 300), False), protect_coverage=True)
        self.assertEqual([n['lyric_index'] for n in output], [0, 1])
        self.assertEqual(audit[0]['evidence'], 'dominant_adjacent_phoneme_overlap')

    # 字音唯一挂词音保护通用修复：新增多个依次迁移不能搬空同一个字。
    def test_sequential_moves_cannot_empty_a_word(self):
        original = [note('one', .5, .7, 63, 0), note('two', .7, .9, 63, 0)]
        output, audit = repair_owners(original, [char(0, .1, .4), char(1, .4, 1.2)], .5,
                                      AcousticEvidence(analysis([63] * 300), False), protect_coverage=True)
        # 字音唯一挂词音保护通用修复：修改原逆序期待，原式保留；整组迁移不得产生后字再回前字。
        # self.assertEqual([n['lyric_index'] for n in output], [1, 0])
        self.assertEqual([n['lyric_index'] for n in output], [0, 0])
        self.assertTrue(any(row.get('requires_ownership_review') for row in audit))

    # 字音唯一挂词音保护通用修复：新增无词装饰音不能充当替代挂词音。
    def test_grace_cannot_count_as_replacement(self):
        grace = note('ornament', .1, .2, 63, 0); grace['grace'] = True
        original = [grace, note('only', .5, .8, 63, 0)]
        output, _ = repair_owners(original, [char(0, .1, .4), char(1, .4, 1.2)], .5,
                                 AcousticEvidence(analysis([63] * 300), False), protect_coverage=True)
        self.assertEqual(output[-1]['lyric_index'], 0)

    # 字音唯一挂词音保护通用修复：新增旧默认仍逐音按原政策迁移，确保历史账本严格重放。
    def test_legacy_default_is_unchanged(self):
        original = [note('only', .5, .8, 63, 0)]
        output, audit = repair_owners(original, [char(0, .1, .4), char(1, .4, 1.2)], .5,
                                      AcousticEvidence(analysis([63] * 300), False))
        self.assertEqual(output[0]['lyric_index'], 1)
        self.assertFalse(any(row.get('requires_ownership_review') for row in audit))

    # 字音唯一挂词音保护通用修复：新增有声跨字分音仍完整覆盖原音段，并保留两字的计量音。
    def test_supported_short_prefix_partition_remains_available(self):
        output, _ = repair_owners([note('joined', .93, 1.13, 63, 1)],
            [char(0, .7, 1.), char(1, 1., 1.4)], .5,
            AcousticEvidence(analysis([63] * 300), False), protect_coverage=True)
        self.assertEqual([n['lyric_index'] for n in output], [0, 1])
        self.assertEqual([(n['start_seconds'], n['end_seconds']) for n in output], [(.93, 1.), (1., 1.13)])


# 字音唯一挂词音保护通用修复：新增标准测试入口。
if __name__ == '__main__': unittest.main()
