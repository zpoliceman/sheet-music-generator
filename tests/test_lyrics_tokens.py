"""第二首跨歌曲验证：歌词换行与哼唱单位应保存，不能依赖特定歌曲位置。"""
# 第二首跨歌曲验证：新增真实G2P和窗口行为测试，普通歌词不受Hu适配影响。
from pathlib import Path
import sys
import unittest
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from lyrics_tokens import text_units, tifa_pfml
from lyrics_quality import check_mandarin_reference
from lyrics_align import reference_characters
from lyrics_align_phrases import match_lines, plan_jobs
from g2pflow import parse_pfml


class LyricsUnitsRegression(unittest.TestCase):
    def test_humming_is_one_unit_and_preserves_original_spelling(self):
        ref = {"lines": ["我Hu，你hu。"], "reference_kind": "user_supplied"}
        self.assertEqual([c["text"] for c in reference_characters(ref)], ["我", "Hu", "你", "hu"])
        self.assertTrue(check_mandarin_reference(ref)["valid_for_mandarin_tifa"])

    def test_human_word_is_not_whitelisted_as_hu(self):
        ref = {"lines": ["Human"], "reference_kind": "user_supplied"}
        self.assertFalse(check_mandarin_reference(ref)["valid_for_mandarin_tifa"])
        # 中文版本冻结与英文融合验证：注释保留被替换的原实现。
        # self.assertEqual(len(text_units("Human")), 5)
        # 中文版本冻结与英文融合验证：新增中英文兼容实现。
        self.assertEqual(len(text_units("Human")), 1)
        self.assertEqual(text_units("Human")[0]["kind"], "english_word")

    def test_pfml_preserves_labels_and_expresses_humming_candidates(self):
        plan = parse_pfml(tifa_pfml("我Hu"))
        word = plan.parts[-1]
        self.assertEqual(word.text, "Hu")
        self.assertEqual({tuple(g.phonemes) for r in word.readings for path in r.paths for g in path}, {("h", "u"), ("u",)})

    def test_wrapped_reference_lines_share_one_real_window(self):
        lines = ["我听着", "时间的沙像首歌"]
        segs = [{"text": "我听着时间的沙像首歌", "start": 10., "end": 15.}]
        mapping, actions, cost = match_lines(lines, segs)
        self.assertEqual(mapping[0]["segments"], [0])
        self.assertEqual(mapping[1]["segments"], [0])
        ref = {"lines": lines, "source": {"duration_seconds": 30.}, "reference_kind": "user_supplied"}
        plan = plan_jobs(ref, {"result": {"segments": segs}}, {"notes": []}, .35)
        self.assertEqual(len(plan["jobs"]), 1)
        self.assertEqual(plan["jobs"][0]["line_indices"], [0, 1])
        self.assertAlmostEqual(plan["jobs"][0]["start_seconds"], 9.65)
        self.assertAlmostEqual(plan["jobs"][0]["end_seconds"], 15.35)

    def test_repeated_wrapped_lines_keep_distinct_sung_windows(self):
        lines = ["我听着", "时间的沙像首歌"] * 2
        segs = [{"text": "我听着时间的沙像首歌", "start": a, "end": a+5} for a in (10., 20.)]
        mapping, _, _ = match_lines(lines, segs)
        self.assertEqual([mapping[i]["segments"] for i in range(4)], [[0], [0], [1], [1]])

    # 第二首跨歌曲验证：新增漏识别哼唱的独立窗口真值，后面长句不能把前面的音节吞掉。
    def test_missing_humming_keeps_its_gap_instead_of_the_next_chorus(self):
        lines = ["眺望着", "Hu", "舍不舍", "Hu", "在追逐中追逐着"]
        segs = [{"text":"眺望着","start":50.,"end":54.},
                {"text":"深不深","start":59.,"end":62.},
                {"text":"在追逐中追逐着","start":65.,"end":69.}]
        notes = [{"start_seconds":a,"end_seconds":b,"pitch_midi":60,"is_rest":False,
                  "quality":{"voiced_fraction":1.}} for a,b in [(55.,58.),(60.,62.),(63.,64.),(65.,69.)]]
        ref = {"lines":lines,"source":{"duration_seconds":75.},"reference_kind":"user_supplied"}
        plan = plan_jobs(ref,{"result":{"segments":segs}},{"notes":notes},.35)
        gap = next(j for j in plan["jobs"] if 1 in j["line_indices"])
        self.assertEqual(gap["line_indices"], [1,2,3])
        self.assertAlmostEqual(gap["start_seconds"], 54.65)
        self.assertAlmostEqual(gap["end_seconds"], 64.35)
        self.assertNotIn(4, gap["line_indices"])

    # 第二首跨歌曲验证：新增边缘短句与简繁体匹配的独立行为验证。
    def test_short_last_line_is_not_moved_into_next_asr_segment(self):
        lines = ["有多少曲折", "轻轻哼着", "抚平了", "起风了", "天空一片灰灰的"]
        segs = [{"text":"有多少曲折惊奇喊着抚平了","start":35.,"end":42.},
                {"text":"起风了天空一片灰灰的","start":42.5,"end":47.}]
        ref = {"lines":lines,"source":{"duration_seconds":60.},"reference_kind":"user_supplied"}
        plan = plan_jobs(ref,{"result":{"segments":segs}},{"notes":[]},.35)
        first = next(j for j in plan["jobs"] if 2 in j["line_indices"])
        self.assertEqual(first["line_indices"], [0,1,2])
        self.assertAlmostEqual(first["start_seconds"],34.65)
        self.assertAlmostEqual(first["end_seconds"],42.35)

    # 第二首跨歌曲验证：修改，原著/着夹具含语义多音变体，不是纯简繁关系，保留原测试供说明。
    #     def test_traditional_anchor_matches_simplified_lyrics_without_changing_them(self):
    #         lines = ["我听着", "时间的沙像首歌"]
    #         before = lines.copy()
    #         segs = [{"text":"我聽著時間的沙像首歌","start":10.,"end":15.}]
    #         mapping,_,_=match_lines(lines,segs)
    #         self.assertEqual(mapping[0]["lines"],[0,1])
    #         self.assertEqual(mapping[0]["weighted_edit_ratio"],0)
    #         self.assertEqual(lines,before)
    # 
    def test_traditional_anchor_matches_simplified_lyrics_without_changing_them(self):
        lines = ["我听见", "冬天的离开"]
        before = lines.copy()
        segs = [{"text":"我聽見冬天的離開","start":10.,"end":15.}]
        mapping,_,_=match_lines(lines,segs)
        self.assertEqual(mapping[0]["lines"],[0,1])
        self.assertEqual(mapping[0]["weighted_edit_ratio"],0)
        self.assertEqual(lines,before)

    def test_silence_cannot_be_merged_as_one_phrase(self):
        lines = ["爱何曾干涸"]
        segs = [{"text": "爱何曾", "start": 1., "end": 2.}, {"text": "干涸", "start": 10., "end": 11.}]
        mapping, _, _ = match_lines(lines, segs)
        self.assertNotEqual(mapping[0].get("segments"), [0, 1])


if __name__ == "__main__":
    unittest.main()
