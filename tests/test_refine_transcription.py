"""歌词对齐与真实制谱：可听语义、边界证据及真实接缝的回归。"""
import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from refine_transcription import refine_analysis, hash_file


# 歌词对齐与真实制谱：新增可控 f0/音符夹具，验证行为而不复制实现。
def note(start, end, pitch, segment=0, index=0):
    return {"start_seconds": start, "end_seconds": end, "pitch_midi": pitch,
            "is_rest": pitch == 0, "segment": segment, "local_index": index}


def fixture(notes, midi_function, duration=4.0, step=0.01):
    frames = []
    for t in np.arange(0, duration, step):
        pitch = midi_function(float(t))
        frames.append({"time_seconds": float(t), "f0_hz": 0.0 if pitch is None else float(440 * 2 ** ((pitch - 69) / 12)), "unvoiced": pitch is None})
    segments = [{"index": i, "start_seconds": 0.0, "end_seconds": duration,
                 "core_start_seconds": 0.0, "core_end_seconds": duration,
                 "raw_notes": [copy.deepcopy(n) for n in notes if n["segment"] == i]}
                for i in sorted({n["segment"] for n in notes})]
    return {"source": {"path": "synthetic_test_only.wav", "duration_seconds": duration, "offset_seconds": 0.0},
            "configuration": {"frame_step_seconds": step}, "notes": notes, "segments": segments, "pitch_frames": frames}


class RefinementRegression(unittest.TestCase):
    # 歌词对齐与真实制谱：新增不同音转移与同音续音/重发音的语义测试。
    def test_different_pitch_uses_f0_transition(self):
        source = fixture([note(0, 2.06, 60), note(1.94, 4, 62, 1)], lambda t: 60 if t < 2 else 62)
        result = refine_analysis(source, "fixture")
        left, right = result["notes"]
        self.assertAlmostEqual(left["end_seconds"], 2.0, delta=0.011)
        self.assertEqual(left["end_seconds"], right["start_seconds"])
        self.assertEqual([n["pitch_midi"] for n in result["notes"]], [60, 62])
        self.assertEqual(result["refinement"]["actions"][0]["evidence"]["method"], "f0_and_overlap_context_search")
        self.assertEqual(left["provenance"]["raw_events"][0]["end_seconds"], 2.06)

    def test_same_pitch_continuation_merges_with_two_context_votes(self):
        source = fixture([note(0, 2.06, 60), note(1.94, 4, 60, 1)], lambda t: 60)
        result = refine_analysis(source, "fixture")
        self.assertEqual(len(result["notes"]), 1)
        self.assertEqual((result["notes"][0]["start_seconds"], result["notes"][0]["end_seconds"]), (0, 4))
        self.assertEqual(len(result["notes"][0]["provenance"]["raw_events"]), 2)

    def test_same_pitch_reattack_is_not_erased(self):
        source = fixture([note(0, 2.03, 60), note(1.98, 4, 60, 1)], lambda t: 60)
        source["segments"][0]["raw_notes"].append(note(2.03, 4, 60, 0, 1))
        source["segments"][1]["raw_notes"].insert(0, note(0, 1.98, 60, 1, 2))
        result = refine_analysis(source, "fixture")
        self.assertEqual(len(result["notes"]), 2)
        self.assertIn("same_pitch_reattack_preserved", result["notes"][0]["review_flags"])
        self.assertEqual(result["notes"][0]["end_seconds"], result["notes"][1]["start_seconds"])

    def test_no_voicing_keeps_uncertainty_explicit(self):
        source = fixture([note(0, 2.06, 60), note(1.94, 4, 62, 1)], lambda t: None)
        result = refine_analysis(source, "fixture")
        self.assertEqual(len(result["notes"]), 2)
        self.assertIn("boundary_requires_manual_review", result["notes"][0]["review_flags"])
        self.assertFalse(result["refinement"]["musical_accuracy_verified"])

    # 歌词对齐与真实制谱：新增短音/滑音保留、半音/八度冲突与低能量测试。
    def test_short_gliding_ornament_is_kept_as_original_note(self):
        source = fixture([note(0, 0.05, 60)], lambda t: 59 + t * 100, duration=0.05, step=0.005)
        result = refine_analysis(source, "fixture")
        self.assertEqual(len(result["notes"]), 1)
        self.assertEqual(result["notes"][0]["pitch_midi"], 60)
        self.assertIn("short_note_possible_ornament", result["notes"][0]["review_flags"])
        self.assertIn("wide_pitch_motion_preserved", result["notes"][0]["review_flags"])
        self.assertEqual(result["pitch_frames"], source["pitch_frames"])

    def test_octave_and_semitone_disagreements_are_flags_not_pitch_edits(self):
        for f0_pitch, flag in [(72, "possible_octave_disagreement"), (61, "possible_semitone_disagreement")]:
            with self.subTest(pitch=f0_pitch):
                result = refine_analysis(fixture([note(0, 1, 60)], lambda t: f0_pitch, duration=1), "fixture")
                self.assertEqual(result["notes"][0]["pitch_midi"], 60)
                self.assertIn(flag, result["notes"][0]["review_flags"])

    def test_audio_silence_is_independent_from_f0_support(self):
        source = fixture([note(0, 1, 60)], lambda t: 60, duration=1)
        result = refine_analysis(source, "fixture", audio=np.zeros(8000), audio_rate=8000)
        self.assertIn("very_low_audio_energy", result["notes"][0]["review_flags"])
        self.assertEqual(result["notes"][0]["pitch_midi"], 60)

    def test_rest_with_f0_is_not_silently_converted_to_note(self):
        result = refine_analysis(fixture([note(0, 1, 0)], lambda t: 60, duration=1), "fixture")
        self.assertTrue(result["notes"][0]["is_rest"])
        self.assertIn("rest_contains_voiced_f0", result["notes"][0]["review_flags"])

    # 歌词对齐与真实制谱：新增无损来源、稳定 id 与严格时间轴的完整性测试。
    def test_source_is_unchanged_and_ids_are_stable(self):
        source = fixture([note(0, 2.06, 60), note(1.94, 4, 62, 1)], lambda t: 60 if t < 2 else 62)
        before = copy.deepcopy(source)
        one, two = refine_analysis(source, "fixture"), refine_analysis(source, "fixture")
        self.assertEqual(source, before)
        self.assertEqual([n["id"] for n in one["notes"]], [n["id"] for n in two["notes"]])
        self.assertEqual(one["raw_notes"], source["notes"])

    def test_non_overlapping_note_timings_are_untouched(self):
        source = fixture([note(0, 1, 60), note(1, 2, 62, 0, 1)], lambda t: 60 if t < 1 else 62, duration=2)
        result = refine_analysis(source, "fixture")
        self.assertEqual(result["refinement"]["actions"], [])
        self.assertEqual([(n["start_seconds"], n["end_seconds"]) for n in result["notes"]], [(0, 1), (1, 2)])

    def test_duplicate_pitch_frame_timestamps_are_rejected(self):
        source = fixture([note(0, 1, 60)], lambda t: 60, duration=1)
        source["pitch_frames"][1]["time_seconds"] = source["pitch_frames"][0]["time_seconds"]
        with self.assertRaises(ValueError):
            refine_analysis(source, "fixture")

    # 歌词对齐与真实制谱：新增真实旧接缝与最新整首回归，不执行模型或改写原始文件。
    def test_real_old_26ms_seam_and_latest_analysis(self):
        old = ROOT / "test_outputs/rosvot/first_song/analysis.json"
        integrated = ROOT / "reports/integrated_pipeline.full.json"
        if not old.exists() or not integrated.exists():
            self.skipTest("Local real-audio regression assets are unavailable")
        latest = Path(json.loads(integrated.read_text(encoding="utf-8-sig"))["run"]["transcription_summary"]).parent / "analysis.json"
        for path in [old, latest]:
            with self.subTest(path=str(path)):
                before = hash_file(path)
                raw = json.loads(path.read_text(encoding="utf-8-sig"))
                with np.load(path.parent / "raw_arrays.npz", allow_pickle=False) as loaded:
                    arrays = {key: loaded[key] for key in loaded.files}
                result = refine_analysis(raw, before, arrays)
                self.assertEqual(hash_file(path), before)
                self.assertEqual(result["pitch_frames"], raw["pitch_frames"])
                self.assertTrue(all(a["end_seconds"] <= b["start_seconds"] + 1e-8 for a, b in zip(result["notes"], result["notes"][1:])))
                self.assertTrue(all(0 <= n["confidence"] <= 1 for n in result["notes"]))
                seams = [a for a in result["refinement"]["actions"] if a["type"] == "resolve_overlap"]
                self.assertTrue(any(59.9 < a["boundary_seconds"] < 60.1 for a in seams))
                if path == old:
                    self.assertTrue(any(abs(a["original_overlap_seconds"] - 0.02666666666666373) < 1e-8 for a in seams))


if __name__ == "__main__":
    unittest.main(verbosity=2)
