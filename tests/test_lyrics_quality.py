"""第二首跨歌曲验证：异常文本不能强制挂谱，正常转音和重复歌词应保持。"""
# 第二首跨歌曲验证：新增独立行为回归，不要求GPU，不改输入资料。
import copy
from pathlib import Path
import sys
import unittest
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from lyrics_quality import check_mandarin_reference


def sample(text, kind="asr_unverified", start=1.0, end=5.0):
    # 第二首跨歌曲验证：新增可控时间夹具。
    ref = {"lines": text.splitlines(), "text": text, "reference_kind": kind}
    raw = {"source": {"duration_seconds": 30.0}, "result": {"segments": [
        {"id": 0, "text": text, "start": start, "end": end}]}}
    return ref, raw


class LyricsQualityRegression(unittest.TestCase):
    # 第二首跨歌曲验证：新增对齐后端能力边界和不改原文验证。
    def test_real_english_is_preserved_and_requires_supported_backend(self):
        ref, raw = sample("我说Love")
        before = copy.deepcopy((ref, raw))
        report = check_mandarin_reference(ref, raw)
        self.assertFalse(report["valid_for_mandarin_tifa"])
        self.assertEqual(report["issues"][0]["type"], "mandarin_backend_unsupported_latin_text")
        self.assertEqual((ref, raw), before)

    def test_collapsed_repetition_is_blocked_before_gpu_alignment(self):
        ref, raw = sample("小" * 220, start=29.3, end=29.72)
        report = check_mandarin_reference(ref, raw)
        self.assertFalse(report["valid_for_mandarin_tifa"])
        self.assertIn("asr_impossible_character_density", report["issues"][0]["reasons"])

    def test_repeated_chorus_with_normal_duration_is_allowed(self):
        ref, raw = sample("在追逐中追逐着", start=2, end=5)
        ref["lines"].append("在追逐中追逐着")
        raw["result"]["segments"].append({"id": 1, "text": "在追逐中追逐着", "start": 12, "end": 15})
        self.assertTrue(check_mandarin_reference(ref, raw)["valid_for_mandarin_tifa"])

    def test_sustained_word_is_not_a_hallucination(self):
        ref, raw = sample("啊——", start=2, end=12)
        self.assertTrue(check_mandarin_reference(ref, raw)["valid_for_mandarin_tifa"])

    def test_user_correction_is_not_blocked_by_old_anchor_hallucination(self):
        ref, raw = sample("听见冬天的离开", kind="user_supplied")
        raw["result"]["segments"] = [{"id": 0, "text": "听见冬天的离开", "start": 2, "end": 2}]
        self.assertTrue(check_mandarin_reference(ref, raw)["valid_for_mandarin_tifa"])

    def test_invalid_or_out_of_source_timestamps_require_review(self):
        for start, end in [(2, 2), (3, 2), (-1, 2), (1, 31), (float("nan"), 4)]:
            with self.subTest(start=start, end=end):
                ref, raw = sample("听见", start=start, end=end)
                self.assertFalse(check_mandarin_reference(ref, raw)["valid_for_mandarin_tifa"])

    def test_pass_does_not_claim_lyric_or_musical_accuracy(self):
        ref, raw = sample("渴", start=2, end=3)
        report = check_mandarin_reference(ref, raw)
        self.assertTrue(report["valid_for_mandarin_tifa"])
        self.assertFalse(report["musical_accuracy_verified"])
        self.assertFalse(report["text_changed"])


if __name__ == "__main__":
    unittest.main()
