"""歌词对齐与真实制谱：保留原始分析，生成可复核的单人声非重叠事件。"""
from __future__ import annotations

# 歌词对齐与真实制谱：新增只读输入、稳定标识、统计与派生文件工具。
import argparse
from collections import Counter
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
from workspace_location import local_path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
EPS = 1e-8
DEFAULT_RULES = {"pitch_tolerance_semitones": 0.65, "short_note_seconds": 0.09,
                 "low_voiced_fraction": 0.25, "low_pitch_support": 0.55,
                 "quiet_dbfs": -55.0, "boundary_window_seconds": 0.12}


def hash_file(path):
    h = hashlib.sha256()
    with local_path(path).open("rb") as stream:
        for data in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(data)
    return h.hexdigest()


def write_json(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def raw_reference(note):
    return f"segment:{note.get('segment', -1)}/note:{note.get('local_index', -1)}"


def stable_id(source_digest, references):
    identity = source_digest + "|" + "|".join(sorted(references))
    return "note_" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]


# 歌词对齐与真实制谱：新增统一 f0 查询和重叠上下文读取，不把连续轨迹拆成音符。
class Evidence:
    def __init__(self, analysis, arrays=None, audio=None, audio_rate=None):
        self.step = float(analysis["configuration"]["frame_step_seconds"])
        rows = analysis["pitch_frames"]
        self.times = np.asarray([row["time_seconds"] for row in rows], dtype=float)
        self.f0 = np.asarray([row["f0_hz"] for row in rows], dtype=float)
        self.voiced = np.asarray([not row.get("unvoiced", row["f0_hz"] <= 0) for row in rows]) & (self.f0 > 0)
        if len(self.times) == 0 or np.any(np.diff(self.times) <= 0):
            raise ValueError("Pitch frames must have strictly increasing timestamps")
        if not np.isfinite(self.times).all() or not np.isfinite(self.f0).all():
            raise ValueError("Pitch evidence contains non-finite values")
        self.segments = {int(s["index"]): s for s in analysis.get("segments", analysis.get("raw_segments", []))}
        self.arrays = arrays or {}
        self.audio, self.audio_rate = audio, audio_rate
        self.offset = float(analysis["source"].get("offset_seconds", 0.0))

    def samples(self, start, end, segment=None):
        if segment is not None and f"segment_{segment}_f0_hz" in self.arrays and segment in self.segments:
            hz = np.asarray(self.arrays[f"segment_{segment}_f0_hz"], dtype=float)
            begin = float(self.segments[segment]["start_seconds"])
            times = begin + np.arange(len(hz)) * self.step
            uv = np.asarray(self.arrays.get(f"segment_{segment}_unvoiced", hz <= 0), dtype=bool)
            voiced = (~uv) & (hz > 0)
        else:
            times, hz, voiced = self.times, self.f0, self.voiced
        a, b = np.searchsorted(times, [start, end])
        selected_hz = hz[a:b]
        midi = np.zeros_like(selected_hz)
        mask = voiced[a:b]
        midi[mask] = 69.0 + 12.0 * np.log2(selected_hz[mask] / 440.0)
        return times[a:b], midi, mask

    def context_notes(self, source_segments, start, end):
        found = []
        for segment in sorted(set(source_segments)):
            for n in self.segments.get(segment, {}).get("raw_notes", []):
                if n["end_seconds"] >= start and n["start_seconds"] <= end:
                    found.append(n)
        return found

    def rms_dbfs(self, start, end):
        if self.audio is None or self.audio_rate is None:
            return None
        a = max(0, int((start - self.offset) * self.audio_rate))
        b = min(len(self.audio), int(math.ceil((end - self.offset) * self.audio_rate)))
        if b <= a:
            return None
        rms = float(np.sqrt(np.mean(np.square(self.audio[a:b], dtype=np.float64))))
        return 20.0 * math.log10(max(rms, 1e-12))


# 歌词对齐与真实制谱：新增可审计支持指标，confidence 是规则分数而非校准准确概率。
def event_quality(note, evidence, rules):
    start, end, pitch = note["start_seconds"], note["end_seconds"], note["pitch_midi"]
    _, midi, voiced = evidence.samples(start, end)
    count, voiced_count = len(midi), int(voiced.sum())
    fraction = voiced_count / count if count else 0.0
    values = midi[voiced]
    errors = values - pitch if pitch else np.empty(0)
    support = float(np.mean(np.abs(errors) <= rules["pitch_tolerance_semitones"])) if len(errors) else 0.0
    median_error = float(np.median(errors)) if len(errors) else None
    median_midi = float(np.median(values)) if len(values) else None
    span = float(np.percentile(values, 90) - np.percentile(values, 10)) if len(values) else None
    octave_support = float(np.mean(np.abs(np.abs(errors) - 12.0) <= rules["pitch_tolerance_semitones"])) if len(errors) else 0.0
    semitone_support = float(np.mean(np.abs(np.abs(errors) - 1.0) <= 0.35)) if len(errors) else 0.0
    rms = evidence.rms_dbfs(start, end)
    flags = []
    if count < 3:
        flags.append("insufficient_f0_frames")
    if pitch:
        if end - start < rules["short_note_seconds"]:
            flags.append("short_note_possible_ornament")
        if fraction < rules["low_voiced_fraction"]:
            flags.append("low_voicing_support")
        if support < rules["low_pitch_support"]:
            flags.append("low_pitch_support")
        if median_error is not None and abs(abs(median_error) - 12.0) < 0.8:
            flags.append("possible_octave_disagreement")
        elif median_error is not None and 0.65 <= abs(median_error) <= 1.4:
            flags.append("possible_semitone_disagreement")
        if span is not None and span > 1.5:
            flags.append("wide_pitch_motion_preserved")
        if rms is not None and rms < rules["quiet_dbfs"]:
            flags.append("very_low_audio_energy")
        confidence = fraction * support
    else:
        if fraction > 0.25:
            flags.append("rest_contains_voiced_f0")
        confidence = 1.0 - fraction
    metrics = {"duration_seconds": end - start, "frame_count": count, "voiced_frame_count": voiced_count,
               "voiced_fraction": fraction, "pitch_support_fraction": support,
               "median_f0_midi": median_midi, "median_error_semitones": median_error,
               "f0_p90_p10_semitones": span, "octave_offset_support_fraction": octave_support,
               "semitone_offset_support_fraction": semitone_support, "rms_dbfs": rms}
    return metrics, float(np.clip(confidence, 0.0, 1.0)), flags


# 歌词对齐与真实制谱：新增同音续音判据；有重发音边界或弱 f0 支持时保留两个音。
def continuation_evidence(left, right, evidence):
    segments = sorted(set(left["provenance"]["source_segments"] + right["provenance"]["source_segments"]))
    middle = (right["start_seconds"] + left["end_seconds"]) / 2.0
    margin = max(evidence.step * 2, 0.015)
    start, end = max(left["start_seconds"], middle - 0.08), min(right["end_seconds"], middle + 0.08)
    _, midi, voiced = evidence.samples(start, end)
    support = float(np.mean(np.abs(midi[voiced] - left["pitch_midi"]) <= 0.65)) if voiced.any() else 0.0
    voiced_fraction = float(voiced.mean()) if len(voiced) else 0.0
    crossing, boundaries = [], []
    for segment in segments:
        raw = evidence.segments.get(segment, {}).get("raw_notes", [])
        if any(n["pitch_midi"] == left["pitch_midi"] and n["start_seconds"] < middle - margin and n["end_seconds"] > middle + margin for n in raw):
            crossing.append(segment)
        for a, b in zip(raw, raw[1:]):
            if a["pitch_midi"] == b["pitch_midi"] == left["pitch_midi"] and abs(a["end_seconds"] - middle) <= 0.045:
                boundaries.append({"segment": segment, "time_seconds": a["end_seconds"]})
    data = {"crossing_context_segments": crossing, "same_pitch_reattack_boundaries": boundaries,
            "voiced_fraction": voiced_fraction, "pitch_support_fraction": support, "inspection_center_seconds": middle}
    merge = len(segments) >= 2 and len(crossing) >= 2 and not boundaries and voiced_fraction >= 0.7 and support >= 0.8
    return merge, data


# 歌词对齐与真实制谱：新增基于重叠上下文、f0 和原始边界的边界搜索；弱证据显式标记。
def choose_boundary(left, right, evidence, rules):
    low = max(left["start_seconds"] + EPS, right["start_seconds"])
    high = min(left["end_seconds"], right["end_seconds"] - EPS)
    if low > high:
        raise ValueError("Cannot resolve overlap while preserving positive durations")
    midpoint = (low + high) / 2.0
    segments = sorted(set(left["provenance"]["source_segments"] + right["provenance"]["source_segments"]))
    window = rules["boundary_window_seconds"]
    start = max(left["start_seconds"], low - window)
    end = min(right["end_seconds"], high + window)
    contexts = evidence.context_notes(segments, start, end)
    original_boundaries = []
    for n in contexts:
        if n["pitch_midi"] == left["pitch_midi"] and low - 0.06 <= n["end_seconds"] <= high + 0.06:
            original_boundaries.append(float(n["end_seconds"]))
        if n["pitch_midi"] == right["pitch_midi"] and low - 0.06 <= n["start_seconds"] <= high + 0.06:
            original_boundaries.append(float(n["start_seconds"]))
    prior = float(np.median(original_boundaries)) if original_boundaries else midpoint
    candidates = [low, high, midpoint, float(np.clip(prior, low, high))]
    candidates.extend(evidence.times[(evidence.times >= low) & (evidence.times <= high)].tolist())
    candidates.extend(t for t in original_boundaries if low <= t <= high)
    candidates = sorted(set(candidates))
    samples = []
    for segment in segments:
        if f"segment_{segment}_f0_hz" in evidence.arrays:
            samples.append(evidence.samples(start, end, segment))
    if not samples:
        samples.append(evidence.samples(start, end))
    times = np.concatenate([s[0] for s in samples]); midi = np.concatenate([s[1] for s in samples]); voiced = np.concatenate([s[2] for s in samples])
    def loss_for_pitch(pitch):
        if pitch == 0:
            return np.where(voiced, 1.0, 0.0)
        return np.where(voiced, np.minimum(np.abs(midi - pitch), 4.0) / 4.0, 0.7)
    before, after = loss_for_pitch(left["pitch_midi"]), loss_for_pitch(right["pitch_midi"])
    scores = []
    for candidate in candidates:
        acoustic = float(np.mean(np.where(times < candidate, before, after))) if len(times) else 0.0
        prior_cost = min(abs(candidate - prior) / max(high - low, evidence.step), 1.0) * 0.035
        scores.append((acoustic + prior_cost, abs(candidate - prior), candidate, acoustic))
    scores.sort()
    choice = scores[0]
    informative = int(voiced.sum()) >= 4 and left["pitch_midi"] != right["pitch_midi"]
    method = "f0_and_overlap_context_search" if informative else ("overlap_context_boundary_consensus" if original_boundaries else "overlap_midpoint_weak_evidence")
    if not informative:
        selected = float(np.clip(prior, low, high))
    else:
        selected = float(choice[2])
    evidence_record = {"method": method, "search_range_seconds": [low, high], "selected_seconds": selected,
                       "original_boundary_votes_seconds": original_boundaries, "source_segments": segments,
                       "context_f0_tracks": len(samples), "voiced_evidence_frames": int(voiced.sum()),
                       "candidate_count": len(candidates), "best_cost": float(choice[0]),
                       "next_cost_margin": float(scores[1][0] - choice[0]) if len(scores) > 1 else None,
                       "weak_f0_evidence": not informative}
    return selected, evidence_record


# 歌词对齐与真实制谱：新增派生事件生成；原始音高和短音不删除、不自动移调。
def refine_analysis(analysis, source_digest, arrays=None, audio=None, audio_rate=None, rules=None):
    rules = dict(DEFAULT_RULES if rules is None else rules)
    evidence = Evidence(analysis, arrays, audio, audio_rate)
    events = []
    for raw in analysis["notes"]:
        if not math.isfinite(raw["start_seconds"]) or not math.isfinite(raw["end_seconds"]) or raw["end_seconds"] <= raw["start_seconds"]:
            raise ValueError("Raw note has invalid time interval")
        note = copy.deepcopy(raw)
        ref = raw_reference(raw)
        note["review_flags"] = []
        note["provenance"] = {"source_analysis_sha256": source_digest, "raw_event_references": [ref],
                              "source_segments": [int(raw.get("segment", -1))], "raw_events": [copy.deepcopy(raw)], "adjustments": []}
        note["id"] = stable_id(source_digest, [ref])
        events.append(note)
    events.sort(key=lambda n: (n["start_seconds"], n["end_seconds"], n["id"]))
    resolved, actions = [], []
    for current in events:
        if not resolved:
            resolved.append(current)
            continue
        previous = resolved[-1]
        overlap = previous["end_seconds"] - current["start_seconds"]
        cross_segment = set(previous["provenance"]["source_segments"]) != set(current["provenance"]["source_segments"])
        near_same = cross_segment and previous["pitch_midi"] == current["pitch_midi"] and abs(overlap) <= evidence.step
        if overlap <= EPS and not near_same:
            resolved.append(current)
            continue
        is_same = previous["pitch_midi"] == current["pitch_midi"]
        merge, continuity = continuation_evidence(previous, current, evidence) if is_same else (False, None)
        if is_same and previous["is_rest"] and overlap > 0:
            merge = True
            continuity = {"reason": "overlapping rest regions share no distinct pitched onset"}
        if merge:
            previous["end_seconds"] = max(previous["end_seconds"], current["end_seconds"])
            previous["provenance"]["raw_event_references"].extend(current["provenance"]["raw_event_references"])
            previous["provenance"]["raw_events"].extend(current["provenance"]["raw_events"])
            previous["provenance"]["source_segments"] = sorted(set(previous["provenance"]["source_segments"] + current["provenance"]["source_segments"]))
            previous["id"] = stable_id(source_digest, previous["provenance"]["raw_event_references"])
            action = {"type": "merge_cross_segment_continuation", "references": previous["provenance"]["raw_event_references"].copy(), "evidence": continuity}
            previous["provenance"]["adjustments"].append(action)
            previous["review_flags"].append("cross_segment_continuation_merged")
            actions.append(action)
            continue
        if overlap <= EPS:
            resolved.append(current)
            continue
        boundary, detail = choose_boundary(previous, current, evidence, rules)
        action = {"type": "resolve_overlap", "left_id": previous["id"], "right_id": current["id"],
                  "original_left_end_seconds": previous["end_seconds"], "original_right_start_seconds": current["start_seconds"],
                  "original_overlap_seconds": overlap, "boundary_seconds": boundary, "evidence": detail}
        if continuity is not None:
            action["same_pitch_continuity_evidence"] = continuity
        previous["end_seconds"], current["start_seconds"] = boundary, boundary
        for note in (previous, current):
            note["provenance"]["adjustments"].append(copy.deepcopy(action))
            note["review_flags"].append("overlap_boundary_adjusted")
            if detail["weak_f0_evidence"]:
                note["review_flags"].append("boundary_requires_manual_review")
            if is_same:
                note["review_flags"].append("same_pitch_reattack_preserved")
        actions.append(action)
        resolved.append(current)
    for note in resolved:
        quality, confidence, flags = event_quality(note, evidence, rules)
        note["quality"], note["confidence"] = quality, confidence
        note["review_flags"] = sorted(set(note["review_flags"] + flags))
    overlaps = [(a["id"], b["id"]) for a, b in zip(resolved, resolved[1:]) if a["end_seconds"] > b["start_seconds"] + EPS]
    if overlaps:
        raise AssertionError(f"Non-overlap invariant failed: {overlaps}")
    gaps = [{"left_id": a["id"], "right_id": b["id"], "start_seconds": a["end_seconds"], "end_seconds": b["start_seconds"]}
            for a, b in zip(resolved, resolved[1:]) if b["start_seconds"] - a["end_seconds"] > evidence.step + EPS]
    output = {"schema_version": 2, "task": "歌词对齐与真实制谱", "status": "derived_monophonic_events_manual_review_required",
              "source": copy.deepcopy(analysis["source"]), "configuration": copy.deepcopy(analysis["configuration"]),
              "pitch_frames": copy.deepcopy(analysis["pitch_frames"]), "raw_segments": copy.deepcopy(analysis.get("segments", [])),
              "raw_notes": copy.deepcopy(analysis["notes"]), "notes": resolved,
              "predicted_word_segments": copy.deepcopy(analysis.get("predicted_word_segments", [])),
              "alignment": copy.deepcopy(analysis.get("alignment", {"status": "not_aligned_to_lyrics"})),
              "refinement": {"source_analysis_sha256": source_digest, "rules": rules, "actions": actions,
                             "confidence_definition": "Heuristic f0 voicing fraction multiplied by pitch-match fraction; rest score is unvoiced fraction. Not calibrated probability or manual accuracy.",
                             "pitch_correction_applied": False, "f0_to_note_splitting_applied": False,
                             "gaps_longer_than_frame": gaps, "musical_accuracy_verified": False}}
    return output


# 歌词对齐与真实制谱：新增标准科学绘图，连续 f0 与派生/原始音符同时可核对。
def make_plots(derived, directory):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    times = np.array([f["time_seconds"] for f in derived["pitch_frames"]])
    hz = np.array([f["f0_hz"] for f in derived["pitch_frames"]])
    pitch = np.full_like(hz, np.nan);mask = hz > 0
    pitch[mask] = 69 + 12 * np.log2(hz[mask] / 440)
    for name, limits in [("f0_notes_overview.png", None), ("seam_60s.png", (59.3, 60.6))]:
        fig, ax = plt.subplots(figsize=(15, 5), constrained_layout=True)
        selected = np.ones(len(times), dtype=bool) if limits is None else (times >= limits[0]) & (times <= limits[1])
        ax.plot(times[selected], pitch[selected], color="#1d4ed8", linewidth=0.65, alpha=0.75, label="Continuous f0 (MIDI scale)")
        for group, color, width, alpha, label in [(derived["raw_notes"], "#dc2626", 4, 0.35, "Original note events"), (derived["notes"], "#15803d", 1.5, 0.95, "Derived non-overlapping events")]:
            first = True
            for note in group:
                if note["is_rest"] or (limits and (note["end_seconds"] < limits[0] or note["start_seconds"] > limits[1])):
                    continue
                ax.plot([note["start_seconds"], note["end_seconds"]], [note["pitch_midi"]] * 2,
                        color=color, linewidth=width, alpha=alpha, label=label if first else None)
                first = False
        if limits:
            ax.set_xlim(*limits);ax.set_ylim(50, 60)
        else:
            # 歌词对齐与真实制谱：新增整曲显示范围，静音尾段也保留在总览坐标轴中。
            offset = float(derived["source"].get("offset_seconds", 0.0))
            ax.set_xlim(offset, offset + float(derived["source"]["duration_seconds"]))
        ax.set_xlabel("Song time (seconds)");ax.set_ylabel("MIDI pitch")
        ax.set_title("Automatic transcription evidence; musical accuracy is unverified")
        ax.grid(alpha=0.2);ax.legend(loc="upper right")
        fig.savefig(directory / name, dpi=160);plt.close(fig)


# 歌词对齐与真实制谱：新增命令行与真实回归报告，源分析哈希在处理前后保持不变。
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "test_outputs/refined/latest")
    parser.add_argument("--no-plots", action="store_true")
    args = parser.parse_args()
    if args.input is None:
        current = json.loads((ROOT / "reports/integrated_pipeline.full.json").read_text(encoding="utf-8-sig"))
        args.input = Path(current["run"]["transcription_summary"]).parent / "analysis.json"
    args.input = local_path(args.input).resolve()
    output = args.output_dir.resolve()
    if output == args.input.parent:
        raise ValueError("Refined outputs must be separate from original analysis")
    output.mkdir(parents=True, exist_ok=True)
    source_digest = hash_file(args.input)
    original = json.loads(args.input.read_text(encoding="utf-8-sig"))
    arrays = {}
    npz = args.input.parent / "raw_arrays.npz"
    if npz.exists():
        with np.load(npz, allow_pickle=False) as archive:
            arrays = {key: archive[key] for key in archive.files}
    audio = audio_rate = None
    audio_path = local_path(original["source"]["path"])
    if audio_path.exists():
        import soundfile as sf
        audio, audio_rate = sf.read(audio_path, dtype="float32", always_2d=True)
        audio = audio.mean(axis=1)
    derived = refine_analysis(original, source_digest, arrays, audio, audio_rate)
    derived["refinement"]["source_analysis_path"] = str(args.input)
    derived["refinement"]["tool_sha256"] = hash_file(__file__)
    derived["refinement"]["context_npz_sha256"] = hash_file(npz) if npz.exists() else None
    if hash_file(args.input) != source_digest:
        raise RuntimeError("Original analysis changed during refinement")
    write_json(output / "analysis.json", derived)
    flags = Counter(flag for note in derived["notes"] for flag in note["review_flags"])
    summary = {"recorded_at": datetime.now(timezone(timedelta(hours=8))).isoformat(),
               "input": str(args.input), "output": str(output / "analysis.json"), "source_sha256_unchanged": True,
               "original_events": len(original["notes"]), "derived_events": len(derived["notes"]),
               "original_pitched_notes": sum(not n["is_rest"] for n in original["notes"]),
               "derived_pitched_notes": sum(not n["is_rest"] for n in derived["notes"]),
               "non_overlap_passed": True, "actions": derived["refinement"]["actions"],
               "review_flag_counts": dict(flags), "musical_accuracy_verified": False,
               "confidence_is_calibrated_probability": False}
    write_json(output / "summary.json", summary)
    if not args.no_plots:
        make_plots(derived, output)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
