"""歌词对齐与真实制谱：从真实秒时间音符生成可校正的人声谱草稿。"""
# 歌词对齐与真实制谱：新增标准库接口；声学分析和图像渲染按需加载现有包。
from __future__ import annotations
import argparse
import bisect
import copy
import hashlib
import html
import json
import math
import statistics
import struct
import sys
import time
import xml.etree.ElementTree as ET
from collections import defaultdict  # 通用段落强拍与乐句节奏修复：新增简谱连音组绘图索引。
from pathlib import Path
from workspace_location import local_path
# 小节划分与拍速层级纠错：新增实际四分拍速度的统一读取，显示与报告不引用未解释的检测脉冲。
from metrical_timing import selected_quarter_tempo

ROOT = Path(__file__).resolve().parents[1]
PPQ = 480
VERSION = 1
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

# 歌词对齐与真实制谱：新增独立产物读写和内容指纹，不覆盖音频或原始分析。
def read_json(path):
    return json.loads(local_path(path).read_text(encoding="utf-8-sig"))

def save_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

def sha256(path):
    digest = hashlib.sha256()
    with local_path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()

# 歌词对齐与真实制谱：修改，XML辅助参数不能与MusicXML的name属性冲突，旧实现保留。
# def tag(parent, name, text=None, **attrs):
#     result = ET.SubElement(parent, name, {key: str(value) for key, value in attrs.items()})
#     if text is not None:
#         result.text = str(text)
#     return result
def tag(parent, element_tag, text=None, **attrs):
    result = ET.SubElement(parent, element_tag, {key: str(value) for key, value in attrs.items()})
    if text is not None:
        result.text = str(text)
    return result

# 歌词对齐与真实制谱：新增有明确调式和升降号的调性解析，支持人工覆盖。
MAJOR_FIFTHS = {"Cb": -7, "Gb": -6, "Db": -5, "Ab": -4, "Eb": -3, "Bb": -2,
               "F": -1, "C": 0, "G": 1, "D": 2, "A": 3, "E": 4, "B": 5, "F#": 6, "C#": 7}
MINOR_RELATIVE = {"Ab": "Cb", "Eb": "Gb", "Bb": "Db", "F": "Ab", "C": "Eb", "G": "Bb",
                  "D": "F", "A": "C", "E": "G", "B": "D", "F#": "A", "C#": "E", "G#": "B",
                  "D#": "F#", "A#": "C#"}
PITCH_CLASS = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}

def key_definition(label):
    fields = label.split(":")
    tonic = fields[0].strip()
    mode = fields[1].lower() if len(fields) > 1 else "major"
    if mode not in ("major", "minor"):
        raise ValueError("调式只能是 major 或 minor，例如 Ab:major。")
    major = tonic if mode == "major" else MINOR_RELATIVE.get(tonic)
    if major not in MAJOR_FIFTHS:
        raise ValueError(f"不支持的调性：{label}")
    def pc(name):
        return (PITCH_CLASS[name[0]] + name.count("#") - name.count("b")) % 12
    return {"label": tonic + ":" + mode, "tonic": tonic, "mode": mode,
            "tonic_pc": pc(tonic), "fifths": MAJOR_FIFTHS[major],
            "jianpu_one": major, "jianpu_one_pc": pc(major)}

# 歌词对齐与真实制谱：新增真实混音拍点、色度与拍重音初估；缓存绑定源 SHA。
def analyze_audio(audio_path, cache_path=None):
    import numpy as np
    import librosa
    import soundfile as sf
    audio_path = Path(audio_path)
    fingerprint = sha256(audio_path)
    if cache_path and Path(cache_path).exists():
        cached = read_json(cache_path)
        if cached.get("source_sha256") == fingerprint and cached.get("analysis_version") == VERSION:
            return cached
    started = time.perf_counter()
    audio, sr = sf.read(str(audio_path), dtype="float32", always_2d=True)
    duration = len(audio) / sr
    mono = librosa.resample(audio.mean(axis=1), orig_sr=sr, target_sr=22050)
    onset = librosa.onset.onset_strength(y=mono, sr=22050, hop_length=256)
    tempo, beat_frames = librosa.beat.beat_track(onset_envelope=onset, sr=22050, hop_length=256, trim=False)
    beat_times = librosa.frames_to_time(beat_frames, sr=22050, hop_length=256)
    if len(beat_times) < 8:
        raise ValueError("有效拍点少于八个，不能自动建立全曲拍时间轴；需检查音频。")
    strength = onset[beat_frames]
    meter_candidates = []
    for beats_per_bar in (3, 4):
        means = np.array([np.mean(strength[phase::beats_per_bar]) for phase in range(beats_per_bar)])
        phase = int(np.argmax(means))
        score = float((means[phase] - np.mean(np.delete(means, phase))) / (np.std(strength) + 1e-9))
        meter_candidates.append({"meter": f"{beats_per_bar}/4", "phase": phase,
                                 "accent_score": score, "phase_means": means.tolist()})
    meter_candidates.sort(key=lambda item: item["accent_score"], reverse=True)
    margin = meter_candidates[0]["accent_score"] - meter_candidates[1]["accent_score"]
    # 歌词对齐与真实制谱：新增显式弱证据先验，拍重音不够区分时注明暂用4/4而非已识别。
    chosen = meter_candidates[0] if margin >= 0.15 else next(x for x in meter_candidates if x["meter"] == "4/4")
    chroma = librosa.feature.chroma_stft(y=mono, sr=22050, hop_length=1024, n_fft=4096).mean(axis=1)
    profiles = {
        "major": np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]),
        "minor": np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17]),
    }
    names = ["C", "Db", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]
    minor_names = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "G#", "A", "Bb", "B"]
    keys = []
    for mode, profile in profiles.items():
        for pitch_class in range(12):
            label = (names if mode == "major" else minor_names)[pitch_class] + ":" + mode
            correlation = float(np.corrcoef(chroma, np.roll(profile, pitch_class))[0, 1])
            keys.append({"key": label, "correlation": correlation})
    keys.sort(key=lambda item: item["correlation"], reverse=True)
    periods = np.diff(beat_times)
    median_period = float(np.median(periods))
    irregularity = float(np.median(np.abs(periods - median_period)) / median_period)
    result = {
        "analysis_version": VERSION, "source_path": str(audio_path.resolve()), "source_sha256": fingerprint,
        "duration_seconds": duration, "analysis_seconds": time.perf_counter() - started,
        "method": "librosa beat_track / STFT chroma / Krumhansl-Schmuckler profile correlation",
        "tempo": {"bpm": float(np.asarray(tempo).reshape(-1)[0]),
                  "confidence": max(0.0, min(0.85, 1 - 5 * irregularity)),
                  "confidence_kind": "heuristic_regular_beat_support_not_calibrated_probability",
                  "requires_confirmation": True, "half_double_time_ambiguity_unresolved": True},
        "beat_times_seconds": beat_times.tolist(), "beat_strength": strength.tolist(),
        "period_seconds_percentiles": np.percentile(periods, [0, 10, 50, 90, 100]).tolist(),
        "meter": {"selected": chosen["meter"], "phase": chosen["phase"],
                  "confidence": max(0.0, min(0.5, margin)),
                  "method": "accent_candidate" if margin >= 0.15 else "ambiguous_accent_explicit_4_4_prior",
                  "candidates": meter_candidates, "requires_confirmation": True},
        "key": {"selected": keys[0]["key"], "confidence": max(0.0, min(0.8, 3 * (keys[0]["correlation"] - keys[1]["correlation"]))),
                "confidence_kind": "uncalibrated_top_two_correlation_margin",
                "candidates": keys[:6], "requires_confirmation": True, "modulation_not_modeled": True},
        "chroma_mean": chroma.tolist(),
    }
    if cache_path:
        save_json(cache_path, result)
    return result

# 歌词对齐与真实制谱：新增严格单调的秒/四分拍双向映射，保留局部tempo map。
class TempoMap:
    def __init__(self, knots):
        self.knots = [{"seconds": float(x["seconds"]), "quarter": float(x["quarter"])} for x in knots]
        self.seconds = [x["seconds"] for x in self.knots]
        self.quarters = [x["quarter"] for x in self.knots]
        if len(knots) < 2 or any(b <= a for a, b in zip(self.seconds, self.seconds[1:])) or any(
                b <= a for a, b in zip(self.quarters, self.quarters[1:])):
            raise ValueError("tempo map 必须至少包含两个严格递增的时间/拍位置。")

    @staticmethod
    def interpolate(value, xs, ys):
        index = max(0, min(len(xs) - 2, bisect.bisect_right(xs, value) - 1))
        ratio = (value - xs[index]) / (xs[index + 1] - xs[index])
        return ys[index] + ratio * (ys[index + 1] - ys[index])

    def seconds_to_quarters(self, seconds):
        return self.interpolate(seconds, self.seconds, self.quarters)

    def quarters_to_seconds(self, quarter):
        return self.interpolate(quarter, self.quarters, self.seconds)

    def tempo_at(self, quarter):
        index = max(0, min(len(self.quarters) - 2, bisect.bisect_right(self.quarters, quarter) - 1))
        return 60 * (self.quarters[index + 1] - self.quarters[index]) / (self.seconds[index + 1] - self.seconds[index])

def make_timing(analysis, tempo=None, meter=None, beat_origin=None):
    selected_meter = meter or analysis["meter"]["selected"]
    numerator, denominator = (int(value) for value in selected_meter.split("/"))
    if numerator <= 0 or denominator not in (2, 4, 8, 16):
        raise ValueError("拍号须为正整数/2、4、8或16。")
    phase = analysis["meter"]["phase"] if meter is None else 0
    knots = [{"seconds": seconds, "quarter": index - phase}
             for index, seconds in enumerate(analysis["beat_times_seconds"])]
    mapping = TempoMap(knots)
    origin = mapping.quarters_to_seconds(0) if beat_origin is None else float(beat_origin)
    if tempo is not None:
        if not 20 <= tempo <= 300:
            raise ValueError("覆盖tempo应在20–300 BPM之间。")
        mapping = TempoMap([{"seconds": origin, "quarter": 0}, {"seconds": origin + 60 / tempo, "quarter": 1}])
    elif beat_origin is not None:
        origin_quarter = mapping.seconds_to_quarters(origin)
        mapping = TempoMap([{"seconds": point["seconds"], "quarter": point["quarter"] - origin_quarter}
                            for point in knots])
    bar_quarters = numerator * 4 / denominator
    score_start = math.floor(mapping.seconds_to_quarters(0) / bar_quarters) * bar_quarters
    # 小节划分与拍速层级纠错：修改，原直接返回检测拍时间轴注释保留；记录并应用独立四分拍层级。
    # return mapping, {"meter": [numerator, denominator], "meter_source": "user_override" if meter else analysis["meter"],
    timing = {"meter": [numerator, denominator], "meter_source": "user_override" if meter else analysis["meter"],
                     "tempo_source": "user_override" if tempo else analysis["tempo"],
                     "beat_origin_seconds": origin, "beat_origin_source": "user_override" if beat_origin is not None else "weak_accent_phase",
                     "score_start_quarter": score_start, "score_start_seconds": mapping.quarters_to_seconds(score_start),
                     "knots": mapping.knots, "extrapolation": "linear_first_last_interval", "requires_confirmation": True}
    # 小节划分与拍速层级纠错：新增所有制谱路径共用的身份复核，显式tempo始终优先。
    from metrical_timing import resolve_timing
    return resolve_timing(analysis, timing, explicit_tempo=tempo is not None)

# 歌词对齐与真实制谱：新增字音重叠匹配；只有真实逐字边界支持时才拆分同音，不拼塞多字。
def match_lyrics(raw_notes, lyric_data):
    characters = copy.deepcopy(lyric_data.get("characters", []))
    # 歌词对齐与真实制谱：修改，原排序未处理TIFA未对齐字符的null时间，保留旧代码。
    # characters.sort(key=lambda x: (float(x["start_seconds"]), int(x.get("index", 0))))
    # for index, char in enumerate(characters):
    #     char["index"] = int(char.get("index", index))
    #     if float(char["end_seconds"]) <= float(char["start_seconds"]):
    #         char.setdefault("warnings", []).append("nonpositive_character_duration")
    for index, char in enumerate(characters):
        char["index"] = int(char.get("index", index))
        start, end = char.get("start_seconds"), char.get("end_seconds")
        char["time_valid"] = start is not None and end is not None and math.isfinite(float(start)) and math.isfinite(float(end)) and float(end) > float(start)
        if not char["time_valid"]:
            char.setdefault("warnings", []).append("missing_or_nonpositive_character_time")
    characters.sort(key=lambda x: x["index"])
    issues = []
    pieces = []
    for note in raw_notes:
        if note.get("is_rest") or int(note.get("pitch_midi", 0)) <= 0:
            continue
        start, end = float(note["start_seconds"]), float(note["end_seconds"])
        if end <= start:
            raise ValueError(f"音符 {note.get('id')} 时长非正数")
        base = {"id": str(note["id"]), "source_note_id": str(note["id"]),
                "start_seconds": start, "end_seconds": end, "pitch_midi": int(note["pitch_midi"]),
                "confidence": note.get("confidence"), "review_flags": note.get("review_flags", []),
                "lyric_index": None, "boundary_source": "refined_model"}
        candidates = []
        for char in characters:
            # 歌词对齐与真实制谱：新增未对齐字符跳过策略；其索引与文本仍保留在项目JSON。
            if not char["time_valid"]:
                continue
            overlap = min(end, float(char["end_seconds"])) - max(start, float(char["start_seconds"]))
            if overlap > 0.015:
                candidates.append((overlap, char))
        if len(candidates) <= 1:
            if candidates:
                base["lyric_index"] = candidates[0][1]["index"]
            pieces.append(base)
            continue
        ordered = sorted((char for _, char in candidates), key=lambda x: x["start_seconds"])
        accurate = all("tifa" in str(char.get("method", "")).lower() and not any(
            "approx" in str(warning).lower() or "均分" in str(warning) for warning in char.get("warnings", [])) for char in ordered)
        boundaries = [start] + [
            max(start, min(end, (float(left["end_seconds"]) + float(right["start_seconds"])) / 2))
            for left, right in zip(ordered, ordered[1:])
        ] + [end]
        valid_split = accurate and all(b - a >= 0.06 for a, b in zip(boundaries, boundaries[1:])) and all(
            float(left["end_seconds"]) <= float(right["start_seconds"]) + 0.04 for left, right in zip(ordered, ordered[1:]))
        if valid_split:
            issues.append({"type": "same_pitch_split_by_forced_character_boundary", "source_note_id": note["id"],
                           "character_indices": [char["index"] for char in ordered],
                           "requires_review": True})
            for position, char in enumerate(ordered):
                piece = dict(base, id=f"{base['id']}.c{char['index']}",
                             start_seconds=boundaries[position], end_seconds=boundaries[position + 1],
                             lyric_index=char["index"], boundary_source="forced_alignment_syllable_split")
                pieces.append(piece)
        else:
            best_overlap, best_char = max(candidates, key=lambda item: item[0])
            base["lyric_index"] = best_char["index"]
            pieces.append(base)
            issues.append({"type": "multiple_characters_compete_for_one_note", "source_note_id": note["id"],
                           "candidate_indices": [char["index"] for char in ordered],
                           "selected_index": best_char["index"], "unresolved": True,
                           "reason": "没有可信且有足够间隔的逐字边界，未把多个字强行塞在同一个音符"})
    return pieces, characters, issues

# 歌词对齐与真实制谱：新增十六分等固定网格量化，保留原始秒及偏移，不删除塌缩短音。
DURATIONS = [(1920, "whole", 0), (1440, "half", 1), (960, "half", 0), (720, "quarter", 1),
             (480, "quarter", 0), (360, "eighth", 1), (240, "eighth", 0), (180, "16th", 1),
             # 小节划分与拍速层级纠错：修改，原列表尾行保留；保留正确半速记谱后的可靠短音。
             # (120, "16th", 0), (90, "32nd", 1), (60, "32nd", 0)]
             (120, "16th", 0), (90, "32nd", 1), (60, "32nd", 0), (45, "64th", 1), (30, "64th", 0)]

def split_interval(start_tick, end_tick, bar_ticks):
    output = []
    cursor = start_tick
    while cursor < end_tick:
        limit = min(end_tick - cursor, bar_ticks - cursor % bar_ticks)
        if cursor % PPQ:
            limit = min(limit, PPQ - cursor % PPQ)
        choice = next((value for value in DURATIONS if value[0] <= limit), None)
        if choice is None:
            raise ValueError(f"无法表示剩余 {limit} ticks；网格必须至少为三十二分音符。")
        ticks, kind, dots = choice
        output.append({"start_tick": cursor, "duration_ticks": ticks, "type": kind, "dots": dots})
        cursor += ticks
    return output

def quantize(pieces, mapping, timing, duration_seconds, subdivision=4):
    if subdivision not in (2, 4, 8):
        raise ValueError("每四分拍网格只支持2、4或8份。")
    step = PPQ // subdivision
    score_start = timing["score_start_quarter"]
    numerator, denominator = timing["meter"]
    bar_ticks = numerator * PPQ * 4 // denominator
    events = []
    quantized = []
    cursor = 0
    previous_end_seconds = -math.inf
    for piece in sorted(pieces, key=lambda x: (x["start_seconds"], x["end_seconds"])):
        start_seconds, end_seconds = piece["start_seconds"], piece["end_seconds"]
        if start_seconds + 1e-5 < previous_end_seconds:
            raise ValueError("派生音符仍有重叠，不能静默制成单声部谱。")
        previous_end_seconds = end_seconds
        begin = max(0, int(math.floor((mapping.seconds_to_quarters(start_seconds) - score_start) * PPQ / step + 0.5)) * step)
        end = max(begin, int(math.floor((mapping.seconds_to_quarters(end_seconds) - score_start) * PPQ / step + 0.5)) * step)
        if begin < cursor:
            raise ValueError("量化后出现非单调事件，需检查源音符或tempo map。")
        if begin > cursor:
            for part in split_interval(cursor, begin, bar_ticks):
                events.append(dict(part, piece_id=None, pitch_midi=None, grace=False, ties=[], lyric_index=None))
        record = dict(piece, start_tick=begin, end_tick=end,
                      quantized_start_seconds=mapping.quarters_to_seconds(begin / PPQ + score_start),
                      quantized_end_seconds=mapping.quarters_to_seconds(end / PPQ + score_start))
        record["start_error_seconds"] = record["quantized_start_seconds"] - start_seconds
        record["end_error_seconds"] = record["quantized_end_seconds"] - end_seconds
        record["collapsed_to_grace"] = end == begin
        quantized.append(record)
        if end == begin:
            events.append({"start_tick": begin, "duration_ticks": 0, "type": "eighth", "dots": 0,
                           "piece_id": piece["id"], "pitch_midi": piece["pitch_midi"], "grace": True,
                           "ties": [], "lyric_index": None, "review": "grid_collapsed_note_preserved_as_grace"})
        else:
            parts = split_interval(begin, end, bar_ticks)
            for index, part in enumerate(parts):
                ties = (["stop"] if index else []) + (["start"] if index < len(parts) - 1 else [])
                events.append(dict(part, piece_id=piece["id"], pitch_midi=piece["pitch_midi"], grace=False,
                                   ties=ties, lyric_index=piece["lyric_index"],
                                   review="large_quantization_error" if max(abs(record["start_error_seconds"]), abs(record["end_error_seconds"])) > 0.08 else None))
        cursor = end
    final_tick = max(cursor, int(math.ceil((mapping.seconds_to_quarters(duration_seconds) - score_start) * PPQ)))
    total_ticks = max(bar_ticks, math.ceil(final_tick / bar_ticks) * bar_ticks)
    if events and events[-1]["grace"] and events[-1]["start_tick"] >= total_ticks:
        total_ticks += bar_ticks
    if cursor < total_ticks:
        for part in split_interval(cursor, total_ticks, bar_ticks):
            events.append(dict(part, piece_id=None, pitch_midi=None, grace=False, ties=[], lyric_index=None))
    for index, event in enumerate(events):
        event["id"] = f"score_n{index + 1}"
        event["measure"] = event["start_tick"] // bar_ticks + 1
        event["offset_ticks"] = event["start_tick"] % bar_ticks
    errors = sorted(abs(x[key]) for x in quantized for key in ("start_error_seconds", "end_error_seconds"))
    stats = {"grid_quarters": 1 / subdivision, "raw_pitched_notes": len({x["source_note_id"] for x in pieces}),
             "lyric_split_pieces": len(pieces), "grace_notes_from_collapsed_grid": sum(x["collapsed_to_grace"] for x in quantized),
             "quantization_error_seconds": {"median_abs": statistics.median(errors) if errors else 0,
                                           "p95_abs": errors[min(len(errors) - 1, int(0.95 * len(errors)))] if errors else 0,
                                           "max_abs": max(errors, default=0)},
             "measure_count": total_ticks // bar_ticks, "total_ticks": total_ticks, "bar_ticks": bar_ticks}
    return events, quantized, stats

# 歌词对齐与真实制谱：新增一字多音歌词延长与缺字清单，装饰音不承载词。
def attach_lyrics(events, characters):
    by_index = {char["index"]: char for char in characters}
    assigned = {}
    for event in events:
        if event.get("lyric_index") is not None and not event["grace"]:
            assigned.setdefault(event["lyric_index"], []).append(event)
    issues = []
    last_index = -1
    for event in events:
        index = event.get("lyric_index")
        if index is not None:
            if index < last_index:
                issues.append({"type": "nonmonotonic_character_mapping", "event": event["id"], "character_index": index})
            last_index = max(last_index, index)
    for index, group in assigned.items():
        char = by_index[index]
        for position, event in enumerate(group):
            event["lyric"] = {"text": char["text"] if position == 0 else None,
                              "extend": ("start" if position == 0 else "stop" if position == len(group) - 1 else "continue") if len(group) > 1 else None,
                              "character_index": index, "method": char.get("method"),
                              "confidence": char.get("confidence")}
    missing = [char["index"] for char in characters if char["index"] not in assigned]
    return {"character_count": len(characters), "mapped_characters": len(assigned),
            "unmapped_character_indices": missing, "issues": issues,
            "mapping": [{"character_index": index, "event_ids": [event["id"] for event in group]} for index, group in assigned.items()]}



# 歌词对齐与真实制谱：新增按调号选择的音名与简谱级数，八度基准保存在项目中。
def spell_pitch(midi, key):
    sharps = [("C", 0), ("C", 1), ("D", 0), ("D", 1), ("E", 0), ("F", 0),
              ("F", 1), ("G", 0), ("G", 1), ("A", 0), ("A", 1), ("B", 0)]
    flats = [("C", 0), ("D", -1), ("D", 0), ("E", -1), ("E", 0), ("F", 0),
             ("G", -1), ("G", 0), ("A", -1), ("A", 0), ("B", -1), ("B", 0)]
    step, alter = (flats if key["fifths"] < 0 else sharps)[midi % 12]
    return step, alter, (midi - PITCH_CLASS[step] - alter) // 12 - 1

def jianpu_pitch(midi, key, reference_midi):
    if midi is None:
        return "0", 0, ""
    octave, semitone = divmod(midi - reference_midi, 12)
    degrees = {0: ("1", ""), 1: ("1", "♯"), 2: ("2", ""), 3: ("3", "♭"), 4: ("3", ""),
               5: ("4", ""), 6: ("4", "♯"), 7: ("5", ""), 8: ("6", "♭"), 9: ("6", ""),
               10: ("7", "♭"), 11: ("7", "")}
    degree, accidental = degrees[semitone]
    return degree, octave, accidental

# 歌词对齐与真实制谱：新增局部tempo事件导出；MIDI和MusicXML使用同一张映射表。
def tempo_events(mapping, timing, total_ticks):
    shift = timing["score_start_quarter"]
    events = {0: mapping.tempo_at(shift)}
    for point in mapping.knots:
        tick = round((point["quarter"] - shift) * PPQ)
        if 0 <= tick < total_ticks:
            events[tick] = mapping.tempo_at(point["quarter"] + 1e-8)
    return [{"tick": tick, "bpm": bpm} for tick, bpm in sorted(events.items())]

# 歌词对齐与真实制谱：新增歌词来源文案区分，用户提供文本不再标为自动识别未校正。
# 大调约束与强拍先验：修改歌词状态说明，保留原提示；确认吞字不等于有声学时间。
# def lyric_notice(project):
#     if project.get("lyrics", {}).get("reference_kind") == "user_supplied":
#         return "歌词由用户提供；字音对齐、旋律与节奏待核对"
#     return "自动识别歌词未经校正；字音对齐、旋律与节奏待核对"
# 连续转调识别与不确定调性保护：扩展谱面说明，原歌词/吞字函数完整注释保留。
# def lyric_notice(project):
#     base = ("歌词由用户提供；字音对齐、旋律与节奏待核对" if project.get("lyrics", {}).get("reference_kind") == "user_supplied"
#             else "自动识别歌词未经校正；字音对齐、旋律与节奏待核对")
#     elided=sum(c.get("human_review",{}).get("status")=="user_confirmed_elided" for c in project.get("lyrics",{}).get("characters",[]))
#     return base+(f"；{elided}字为用户已确认吞字，原文保留" if elided else "")

# 连续转调识别与不确定调性保护：保留歌词来源与吞字说明作为基础提示。
def _lyric_notice_before_tonality(project):
    base = ("歌词由用户提供；字音对齐、旋律与节奏待核对" if project.get("lyrics", {}).get("reference_kind") == "user_supplied"
            else "自动识别歌词未经校正；字音对齐、旋律与节奏待核对")
    elided=sum(c.get("human_review",{}).get("status")=="user_confirmed_elided" for c in project.get("lyrics",{}).get("characters",[]))
    return base+(f"；{elided}字为用户已确认吞字，原文保留" if elided else "")

# 连续转调识别与不确定调性保护：新增调性待确认段提示，同一提示用于SVG/HTML/MusicXML。
def lyric_notice(project):
    base=_lyric_notice_before_tonality(project)
    regions=project.get('notation',{}).get('tonality_uncertain_regions',[])
    return base+(f'；调性有{len(regions)}段待确认，保留演唱音高' if regions else '')

# 歌词对齐与真实制谱：新增真正可编辑的 MusicXML，原始声学数据只引用而不伪装成记谱。
# 第四首《日落大道》男声跨歌曲验证：新增统一的当前调号查询；旧无转调项目保持原默认值。
def notation_at(project,measure=None,seconds=None):
    # 第四首《日落大道》男声跨歌曲验证：修改最小XML项目兼容默认参考，不要求无关显示字段。
    # notation=project['notation'];result=(notation['key'],notation['jianpu_reference_midi'])
    notation=project['notation'];result=(notation['key'],notation.get('jianpu_reference_midi',60+notation['key'].get('jianpu_one_pc',0)))
    for segment in notation.get('key_segments',[]):
        eligible=(segment['start_measure']<=(measure if measure is not None else 1)) if seconds is None else segment['start_seconds']<=seconds
        if eligible:result=(segment['key'],segment['jianpu_reference_midi'])
    return result

def build_musicxml(project):
    root = ET.Element("score-partwise", version="4.0")
    tag(tag(root, "work"), "work-title", project["title"] + " · 自动人声草稿")
    identification = tag(root, "identification")
    # 歌词对齐与真实制谱：修改，按真实歌词来源区分提示，旧文案保留。
    # tag(identification, "creator", "自动识别草稿；歌词、音高、节奏及调号均待校正", type="composer")
    tag(identification, "creator", lyric_notice(project), type="composer")
    misc = tag(identification, "miscellaneous")
    tag(misc, "miscellaneous-field", "real_audio_automatic_draft", name="artifact-kind")
    tag(misc, "miscellaneous-field", project["inputs"]["notes_path"], name="original-analysis-reference")
    part_list = tag(root, "part-list")
    part_info = tag(part_list, "score-part", id="P1")
    tag(part_info, "part-name", "人声（待校正）")
    part = tag(root, "part", id="P1")
    key = project["notation"]["key"]
    meter = project["timing"]["meter"]
    bar_ticks = project["statistics"]["bar_ticks"]
    grouped = {}
    for event in project["events"]:
        grouped.setdefault(event["measure"], []).append(event)
    # 乐句节奏与音值分组：新增新版XML与简谱共用拍号层级，历史工程XML语义保持。
    beam_map={}
    if project.get('statistics',{}).get('phrase_rhythm'):
        from rhythm_notation import xml_beams
        beam_map=xml_beams(project['events'],meter,project['timing'].get('beat_groups'))
    # 连续转调识别与不确定调性保护：整条跨调号延音维持起点拼写，实际MIDI音高不改变。
    tie_spelling=None
    for measure_number in range(1, project["statistics"]["measure_count"] + 1):
        measure = tag(part, "measure", number=measure_number)
        # 第四首《日落大道》男声跨歌曲验证：新增每段用自己的调号拼写实际音高，XML属性只在调号变化时插入。
        key,_ = notation_at(project,measure=measure_number)
        if measure_number>1 and key!=notation_at(project,measure=measure_number-1)[0]:
            attributes=tag(measure,'attributes');key_node=tag(attributes,'key')
            tag(key_node,'fifths',key['fifths']);tag(key_node,'mode',key['mode'])
            direction=tag(measure,'direction',placement='above')
            tag(tag(direction,'direction-type'),'words','转1='+key['jianpu_one'])
        if measure_number == 1:
            attributes = tag(measure, "attributes")
            tag(attributes, "divisions", PPQ)
            key_node = tag(attributes, "key")
            tag(key_node, "fifths", key["fifths"])
            tag(key_node, "mode", key["mode"])
            time_node = tag(attributes, "time")
            tag(time_node, "beats", meter[0])
            tag(time_node, "beat-type", meter[1])
            clef = tag(attributes, "clef")
            tag(clef, "sign", "G")
            tag(clef, "line", 2)
            direction = tag(measure, "direction", placement="above")
            # 歌词对齐与真实制谱：修改，按真实歌词来源区分提示，旧文案保留。
            # tag(tag(direction, "direction-type"), "words", "自动草稿：歌词未经校正；调号、拍号及字音对应待核对")
            tag(tag(direction, "direction-type"), "words", "自动草稿：" + lyric_notice(project))
        start_tick = (measure_number - 1) * bar_ticks
        for tempo in project["tempo_events"]:
            if start_tick <= tempo["tick"] < start_tick + bar_ticks:
                direction = tag(measure, "direction", placement="above")
                direction_type = tag(direction, "direction-type")
                if tempo["tick"] == 0:
                    metronome = tag(direction_type, "metronome")
                    tag(metronome, "beat-unit", "quarter")
                    tag(metronome, "per-minute", f'{tempo["bpm"]:.3f}')
                else:
                    tag(direction_type, "words", "", **{"print-object": "no"})
                if tempo["tick"] != start_tick:
                    # 歌词对齐与真实制谱：修改，offset默认不影响声音；显式sound=yes保留小节内变速。
                    # tag(direction, "offset", tempo["tick"] - start_tick)
                    tag(direction, "offset", tempo["tick"] - start_tick, sound="yes")
                tag(direction, "sound", tempo=f'{tempo["bpm"]:.6f}')
        for event in grouped.get(measure_number, []):
            note = tag(measure, "note", id=event["id"])
            if event["grace"]:
                # 自动音乐解码改造：修改，增加后主音时间分配参数；原实现注释保留。
                # tag(note, "grace", slash="yes")
                attrs = {"slash": "yes"}
                if event.get("grace_steal_percent") is not None:
                    attrs["steal-time-following"] = f'{event["grace_steal_percent"]:.6f}'
                tag(note, "grace", **attrs)
            if event["pitch_midi"] is None:
                tag(note, "rest")
            else:
                # 连续转调识别与不确定调性保护：原按当前调独立拼写保留，延音终点沿用起点音名。
                # step, alter, octave = spell_pitch(event["pitch_midi"], key)
                step, alter, octave = spell_pitch(event["pitch_midi"], key)
                if "stop" in event["ties"] and tie_spelling is not None:
                    if PITCH_CLASS[tie_spelling[0]]+tie_spelling[1]+12*(tie_spelling[2]+1)!=event["pitch_midi"]:
                        raise ValueError("延音两端实际音高不一致，不能靠拼写掩盖。")
                    step,alter,octave=tie_spelling
                if "start" in event["ties"]:tie_spelling=(step,alter,octave)
                elif "stop" in event["ties"]:tie_spelling=None
                pitch = tag(note, "pitch")
                tag(pitch, "step", step)
                if alter:
                    tag(pitch, "alter", alter)
                tag(pitch, "octave", octave)
            if not event["grace"]:
                tag(note, "duration", event["duration_ticks"])
            for tie_type in event["ties"]:
                tag(note, "tie", type=tie_type)
            tag(note, "voice", 1)
            tag(note, "type", event["type"])
            for _ in range(event["dots"]):
                tag(note, "dot")
            # 通用段落强拍与乐句节奏修复：新增真实3:2时值；duration使用有效tick，type使用名义音值。
            if event.get('tuplet'):
                modification=tag(note,'time-modification')
                tag(modification,'actual-notes',event['tuplet']['actual_notes'])
                tag(modification,'normal-notes',event['tuplet']['normal_notes'])
                tag(modification,'normal-type',event['type'])
                for _ in range(event['dots']):tag(modification,'normal-dot')
            # 乐句节奏与音值分组：新增显式横梁，不能在排版层连接已经错误跨拍的音值。
            for level,state in beam_map.get(event['id'],[]):
                tag(note,'beam',state,number=level)
            # 自动音乐解码改造：修改，分别导出同音tied与不同音slur；原实现注释保留。
            # if event["ties"]:
            #     notations = tag(note, "notations")
            #     for tie_type in event["ties"]:
            #         tag(notations, "tied", type=tie_type)
            # 通用段落强拍与乐句节奏修复：修改，原延音/连奏条件保留；加入连音括号语义。
            # if event["ties"] or event.get("slurs"):
            if event["ties"] or event.get("slurs") or event.get('tuplet_start') or event.get('tuplet_stop'):
                notations = tag(note, "notations")
                for tie_type in event["ties"]:
                    tag(notations, "tied", type=tie_type)
                # 自动音乐解码改造：新增独立转音连奏语义，不改变同音延音时值。
                for slur in event.get("slurs", []):
                    tag(notations, "slur", type=slur["type"], number=slur["number"])
                # 通用段落强拍与乐句节奏修复：新增整拍3:2括号；不以绘图替代MusicXML连音。
                if event.get('tuplet_start'):tag(notations,'tuplet',type='start',number=1,bracket='yes')
                if event.get('tuplet_stop'):tag(notations,'tuplet',type='stop',number=1)
            lyric_data = event.get("lyric")
            if lyric_data:
                lyric = tag(note, "lyric", number="1")
                if lyric_data["text"] is not None:
                    tag(lyric, "syllabic", "single")
                    tag(lyric, "text", lyric_data["text"])
                if lyric_data["extend"]:
                    tag(lyric, "extend", type=lyric_data["extend"])
        if measure_number == project["statistics"]["measure_count"]:
            tag(tag(measure, "barline", location="right"), "bar-style", "light-heavy")
    return root

# 歌词对齐与真实制谱：新增标准 MIDI 文件写入，跨小节延音合成一个发声事件。
def variable_length(value):
    if value < 0:
        raise ValueError("MIDI delta time 不能为负。")
    result = [value & 127]
    value >>= 7
    while value:
        result.insert(0, (value & 127) | 128)
        value >>= 7
    return bytes(result)

def write_midi(path, project):
    midi_events = [(0, -2, b"\xc0\x35")]
    for tempo in project["tempo_events"]:
        micros = min(0xFFFFFF, max(1, round(60000000 / tempo["bpm"])))
        midi_events.append((tempo["tick"], -1, b"\xff\x51\x03" + micros.to_bytes(3, "big")))
    numerator, denominator = project["timing"]["meter"]
    midi_events.append((0, -1, bytes([0xFF, 0x58, 4, numerator, int(math.log2(denominator)), 24, 8])))
    # 第四首《日落大道》男声跨歌曲验证：修改MIDI首调与XML/简谱用同一查询，旧值保留。
    # key = project["notation"]["key"]
    key,_ = notation_at(project,measure=1)
    midi_events.append((0, -1, b"\xff\x59\x02" + struct.pack("bb", key["fifths"], key["mode"] == "minor")))
    # 第四首《日落大道》男声跨歌曲验证：新增MIDI调号事件，音符的绝对音高及时间不受影响。
    for segment in project['notation'].get('key_segments',[]):
        if segment['start_tick']:
            segment_key=segment['key']
            midi_events.append((segment['start_tick'],-1,b'\xff\x59\x02'+struct.pack('bb',segment_key['fifths'],segment_key['mode']=='minor')))
    for piece in project["quantized_notes"]:
        # 自动音乐解码改造：修改，MIDI采用音乐层明确的倚音时间分配，旧项目保留原行为；原实现注释保留。
        # begin, end = piece["start_tick"], piece["end_tick"]
        begin = piece.get("playback_start_tick", piece["start_tick"])
        end = piece.get("playback_end_tick", piece["end_tick"])
        if end == begin:
            # 歌词对齐与真实制谱：新增可试听的短倚音替代时长，明确它是试听近似。
            begin, end = max(0, begin - 24), begin
            if end == begin:
                end += 24
        pitch = piece["pitch_midi"]
        midi_events.extend([(begin, 1, bytes([0x90, pitch, 80])), (end, 0, bytes([0x80, pitch, 0]))])
    midi_events.sort(key=lambda event: (event[0], event[1]))
    track = bytearray()
    previous = 0
    for tick, _, payload in midi_events:
        track.extend(variable_length(tick - previous))
        track.extend(payload)
        previous = tick
    # 歌词对齐与真实制谱：修改，MIDI终止时间应包括末尾休止，保留原零delta结尾。
    # track.extend(b"\x00\xff\x2f\x00")
    track.extend(variable_length(max(0, project["statistics"]["total_ticks"] - previous)) + b"\xff\x2f\x00")
    Path(path).write_bytes(b"MThd" + struct.pack(">IHHH", 6, 0, 1, PPQ) + b"MTrk" + struct.pack(">I", len(track)) + track)

# 歌词对齐与真实制谱：新增同一绘图命令生成 SVG 和系统中文字体 PNG，便于静态视觉核查。
class Scene:
    def __init__(self, width=1440):
        self.width, self.height, self.items = width, 0, []

    def text(self, x, y, value, size=24, color="#14243b", anchor="middle", weight="normal"):
        self.items.append(("text", x, y, str(value), size, color, anchor, weight))

    def line(self, x1, y1, x2, y2, color="#14243b", width=1.5):
        self.items.append(("line", x1, y1, x2, y2, color, width))

    def dot(self, x, y, radius=2.5, color="#14243b"):
        self.items.append(("dot", x, y, radius, color))

    def arc(self, x1, y, x2, height=17, color="#14243b"):
        self.items.append(("arc", x1, y, x2, height, color))

    # 简谱小节对齐与人工复核汇总：新增小节SVG锚点，复核清单可直接跳到对应谱面；PNG忽略分组标记。
    def start_measure(self, number):
        self.items.append(("group_start", f"measure-{number}"))

    def end_measure(self):
        self.items.append(("group_end",))

    def svg(self):
        elements = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.width}" height="{self.height}" viewBox="0 0 {self.width} {self.height}">',
                    '<rect width="100%" height="100%" fill="#ffffff"/>',
                    '<g font-family="Microsoft YaHei, SimHei, sans-serif">']
        for item in self.items:
            kind, *args = item
            # 简谱小节对齐与人工复核汇总：新增小节分组，不改音符绘制语义。
            if kind == "group_start":
                elements.append(f'<g id="{html.escape(args[0], quote=True)}">')
            elif kind == "group_end":
                elements.append('</g>')
            # 简谱小节对齐与人工复核汇总：修改分支入口，原条件注释保留。
            # if kind == "text":
            elif kind == "text":
                x, y, value, size, color, anchor, weight = args
                elements.append(f'<text x="{x}" y="{y}" font-size="{size}" fill="{color}" text-anchor="{anchor}" dominant-baseline="middle" font-weight="{weight}">{html.escape(value)}</text>')
            elif kind == "line":
                x1, y1, x2, y2, color, width = args
                elements.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" stroke-width="{width}"/>')
            elif kind == "dot":
                x, y, radius, color = args
                elements.append(f'<circle cx="{x}" cy="{y}" r="{radius}" fill="{color}"/>')
            elif kind == "arc":
                x1, y, x2, height, color = args
                elements.append(f'<path d="M{x1},{y} Q{(x1+x2)/2},{y-height} {x2},{y}" stroke="{color}" fill="none" stroke-width="1.4"/>')
        return "\n".join(elements + ["</g>", "</svg>"])

    def png(self, path):
        from PIL import Image, ImageDraw, ImageFont
        normal = Path("C:/Windows/Fonts/msyh.ttc")
        bold = Path("C:/Windows/Fonts/msyhbd.ttc")
        if not normal.exists():
            raise FileNotFoundError("未找到系统微软雅黑字体，无法可靠绘制中文 PNG。")
        image = Image.new("RGB", (self.width, self.height), "white")
        draw = ImageDraw.Draw(image)
        cache = {}
        for item in self.items:
            kind, *args = item
            if kind == "text":
                x, y, value, size, color, anchor, weight = args
                key = (size, weight)
                if key not in cache:
                    cache[key] = ImageFont.truetype(str(bold if weight == "bold" else normal), size)
                draw.text((x, y), value, font=cache[key], fill=color, anchor={"middle": "mm", "start": "lm", "end": "rm"}[anchor])
            elif kind == "line":
                x1, y1, x2, y2, color, width = args
                draw.line((x1, y1, x2, y2), fill=color, width=max(1, round(width)))
            elif kind == "dot":
                x, y, radius, color = args
                draw.ellipse((x-radius, y-radius, x+radius, y+radius), fill=color)
            elif kind == "arc":
                x1, y, x2, height, color = args
                points = [(x1 + (x2-x1)*t/40, y-2*(t/40)*(1-t/40)*height) for t in range(41)]
                draw.line(points, fill=color, width=2)
        image.save(path)

# 歌词对齐与真实制谱：新增矢量升降号，避免中文字体缺少音乐字形显示方框。
def draw_accidental(scene, x, y, accidental, color):
    if accidental == "♭":
        scene.line(x-2, y-13, x-2, y+9, color, 1.7)
        points = [(x-2, y), (x+2, y-3), (x+6, y-2), (x+7, y+1), (x+5, y+5), (x-2, y+9)]
        for left, right in zip(points, points[1:]):
            scene.line(*left, *right, color, 1.7)
    else:
        scene.line(x-3, y-10, x-3, y+11, color, 1.7)
        scene.line(x+3, y-12, x+3, y+9, color, 1.7)
        scene.line(x-7, y-3, x+7, y-6, color, 2)
        scene.line(x-7, y+5, x+7, y+2, color, 2)

# 歌词对齐与真实制谱：新增按小节排版的静态简谱，显示八度、时值线、附点、延音和歌词。
# 第二首跨歌曲验证：新增优先预览首个有歌词的发声音，纯旋律项目退回首个发声音。
def first_vocal_measure(project):
    pitched = [event for event in project["events"] if event.get("pitch_midi") is not None]
    mapped = [event for event in pitched if event.get("lyric_index") is not None]
    return min((event["measure"] for event in mapped or pitched), default=1)


# 简谱按拍分组优化：新增拍单位解析；复拍子按三个八分单位分组，普通拍号按分母分组。
def jianpu_beat_unit(meter):
    numerator, denominator = meter
    compound = denominator == 8 and numerator > 3 and numerator % 3 == 0
    units = 3 if compound else 1
    return PPQ * 4 // denominator * units, numerator // units


# 简谱按拍分组优化：新增纯显示布局；长音横线作为对应四分拍的字形，不拆改原音符。
# 中文版本冻结与英文融合验证：英文排版按实际字体宽度留位，避免套用汉字等宽把页面撑得过宽。
def lyric_half_width(text):
    from lyrics_tokens import text_units
    units = text_units(text)
    if len(units) == 1 and units[0]['kind'] == 'english_word':
        # 中文版本冻结与英文融合验证：注释保留被替换的原实现。
        # from PIL import ImageFont
        # from functools import lru_cache
        # font_path = Path('C:/Windows/Fonts/msyh.ttc')
        # 中文版本冻结与英文融合验证：新增中英文兼容实现。
        font_path = Path('C:/Windows/Fonts/msyh.ttc')
        if font_path.is_file():
            # 中文版本冻结与英文融合验证：注释保留被替换的原实现。
            # return max(12., _english_lyric_width(text) / 2 + 2.)
            # 中文版本冻结与英文融合验证：新增中英文兼容实现。
            return max(12, math.ceil(_english_lyric_width(text) / 2 + 2.))
    return max(12, len(text) * 10)


# 中文版本冻结与英文融合验证：缓存固定20像素字体的真实英文宽度，和SVG/PNG使用同一字体。
from functools import lru_cache
@lru_cache(maxsize=512)
def _english_lyric_width(text):
    from PIL import ImageFont
    font = ImageFont.truetype('C:/Windows/Fonts/msyh.ttc', 20)
    box = font.getbbox(text)
    return max(font.getlength(text), box[2] - box[0])


def jianpu_beat_plan(events, meter, key, reference):
    beat_ticks, beat_count = jianpu_beat_unit(meter)
    beats = [[] for _ in range(beat_count)]
    for order, event in enumerate(events):
        _, _, accidental = jianpu_pitch(event["pitch_midi"], key, reference)
        lyric = (event.get("lyric") or {}).get("text") or ""
        # 中文版本冻结与英文融合验证：注释保留被替换的原实现。
        # half_lyric = max(12, len(lyric) * 10)
        # 中文版本冻结与英文融合验证：新增中英文兼容实现。
        half_lyric = lyric_half_width(lyric)
        quarters = {"whole": 4, "half": 2}.get(event["type"], 1)
        for part in range(quarters):
            tick = event["offset_ticks"] + part * PPQ
            beat = int(tick // beat_ticks)
            if not 0 <= beat < beat_count:
                raise ValueError(f"音符{event['id']}的显示拍位超出当前小节")
            left = max(27 if accidental and part == 0 else 12,
                       half_lyric if part == 0 else 12)
            right = max(half_lyric if part == 0 else 12,
                        20 if event["dots"] and part == quarters - 1 else 12)
            beats[beat].append({"event": event, "part": part, "tick": tick,
                                "order": order, "left": left, "right": right})
    widths = []
    for units in beats:
        units.sort(key=lambda unit: (unit["tick"], unit["order"], unit["part"]))
        for index, unit in enumerate(units):
            # 简谱按拍分组优化：新增拍内紧凑间距；小号倚音后留六像素，其余字形之间留八像素。
            unit["gap_after"] = (6 if unit["event"]["grace"] else 8) if index < len(units) - 1 else 0
        widths.append(max(24, sum(unit["left"] + unit["right"] + unit["gap_after"]
                                 for unit in units)))
    return {"beat_ticks": beat_ticks, "beat_count": beat_count, "beats": beats,
            "widths": widths, "beat_gap": 28,
            "minimum_width": sum(widths) + 28 * (beat_count - 1)}


# 简谱按拍分组优化：新增按实际拍位、连续时值和减时线层数分组，短休止符也保留拍内关系。
def jianpu_beam_groups(events, beat_ticks):
    # 小节划分与拍速层级纠错：修改，原三层映射保留；同步支持正确时间轴中的极短人声音符。
    # flags = {"eighth": 1, "16th": 2, "32nd": 3}
    flags = {"eighth": 1, "16th": 2, "32nd": 3, "64th": 4}
    result = []
    for grace in (False, True):
        # 简谱按拍分组优化：新增普通音忽略零时值倚音；倚音仅与同一挂靠时间的邻接倚音连接。
        sequence = events if grace else [event for event in events if not event["grace"]]
        # 小节划分与拍速层级纠错：修改，原三层遍历保留；极短人声音符的第四条减时线同步输出。
        # for level in range(1, 4):
        for level in range(1, max(flags.values())+1):
            run = []
            for event in sequence:
                eligible = bool(event["grace"]) == grace and flags.get(event["type"], 0) >= level
                previous = run[-1] if run else None
                contiguous = previous is not None and (
                    previous["offset_ticks"] == event["offset_ticks"] if grace else
                    previous["offset_ticks"] + previous["duration_ticks"] == event["offset_ticks"])
                same_beat = previous is not None and (
                    previous["offset_ticks"] // beat_ticks == event["offset_ticks"] // beat_ticks)
                if run and (not eligible or not contiguous or not same_beat):
                    result.append({"level": level, "grace": grace, "events": run})
                    run = []
                if eligible:
                    run.append(event)
            if run:
                result.append({"level": level, "grace": grace, "events": run})
    return result


def render_jianpu(project, first_measure=1, last_measure=None, excerpt=False):
    scene = Scene()
    last_measure = last_measure or project["statistics"]["measure_count"]
    # 第四首《日落大道》男声跨歌曲验证：修改节选抬头使用所在段调号，原固定主调保留。
    # key = project["notation"]["key"]
    key,header_reference = notation_at(project,measure=first_measure)
    # 小节划分与拍速层级纠错：修改，原检测BPM/覆盖拼接保留；显示实际记谱时间轴的四分拍速度。
    # tempo = project["audio_analysis"]["tempo"]["bpm"]
    # if project["overrides"]["tempo"] is not None:
    #     tempo = project["overrides"]["tempo"]
    from metrical_timing import selected_quarter_tempo
    tempo = selected_quarter_tempo(project)
    meter = "/".join(str(x) for x in project["timing"]["meter"])
    # 歌词对齐与真实制谱：新增动态简谱基准音名与寄存器，仅改变显示，不改变调性或音符。
    display_tonic = key["jianpu_one"]
    # 第四首《日落大道》男声跨歌曲验证：修改节选八度基准随调号；原值保留。
    # display_reference = project["notation"]["jianpu_reference_midi"]
    display_reference = header_reference
    display_alter = display_tonic.count("#") - display_tonic.count("b")
    display_octave = (display_reference - PITCH_CLASS[display_tonic[0]] - display_alter) // 12 - 1
    scene.text(52, 40, project["title"] + (" · 人声简谱节选" if excerpt else " · 人声简谱"), 32, anchor="start", weight="bold")
    # 歌词对齐与真实制谱：修改，按真实歌词来源区分提示，旧文案保留。
    # scene.text(52, 84, f'自动草稿 · 歌词未经校正 · 1={key["jianpu_one"]}  {meter}  四分音符≈{tempo:.1f}/分', 20, "#4b5e73", "start")
    # 歌词对齐与真实制谱：修改，抬头注明简谱1的实际八度基准，保留旧文案。
    # scene.text(52, 84, f'自动草稿 · {"歌词由用户提供" if project.get("lyrics", {}).get("reference_kind") == "user_supplied" else "自动歌词未经校正"} · 1={key["jianpu_one"]}  {meter}  四分音符≈{tempo:.1f}/分', 20, "#4b5e73", "start")
    # 简谱小节对齐与人工复核汇总：修改抬头为常规简谱调号/拍号/速度，原技术字段文案注释保留。
    # scene.text(52, 84, f'自动草稿 · {"歌词由用户提供" if project.get("lyrics", {}).get("reference_kind") == "user_supplied" else "自动歌词未经校正"} · 1={display_tonic}{display_octave}（MIDI {display_reference}）  {meter}  四分音符≈{tempo:.1f}/分', 20, "#4b5e73", "start")
    # 第四首《日落大道》男声跨歌曲验证：修改抬头显式标出数字1的八度基准，避免男声基准被误读成移调。
    # scene.text(52,84,f'1={display_tonic}　{meter}　四分音符={tempo:g}　自动草稿',20,"#4b5e73","start")
    scene.text(52,84,f'1={display_tonic}（基准音{display_tonic}{display_octave}）　{meter}　四分音符={tempo:g}　自动草稿',20,"#4b5e73","start")
    # 自动音乐解码改造：修改，分类导语按项目类型选择；原实现注释保留。
    # scene.text(52, 116, "调性、拍号及拍位置为初估；橙色音符需核对短音或节奏。连线表示延音，歌词下划线表示一字多音。", 17, "#8a4b12", "start")
    guide = "调性、拍号及拍位置为初估；橙色音符需核对短音或节奏。连线表示延音，歌词下划线表示一字多音。"
    if project.get("decoder"):
        guide = "小号音为倚音；同音弧线为延音，不同音弧线为转音连奏。疑难候选另见复核页；拍位仍需核查。"
    scene.text(52, 116, guide, 17, "#8a4b12", "start")
    mapped = project["lyric_mapping"]["mapped_characters"]
    count = project["lyric_mapping"]["character_count"]
    # 歌词对齐与真实制谱：修改，按真实歌词来源区分提示，旧文案保留。
    # scene.text(52, 146, f'字音映射 {mapped}/{count} 字；其余字与冲突保留在项目报告。音符与歌词准确性尚未经人工确认。', 17, "#8a4b12", "start")
    # 简谱小节对齐与人工复核汇总：修改谱面提示，字数统计留在清单，避免技术信息占据阅读空间。
    # scene.text(52, 146, f'字音映射 {mapped}/{count} 字；其余字与冲突保留在项目报告。字音对齐与音乐准确性尚未经人工确认。', 17, "#8a4b12", "start")
    scene.text(52,146,"歌词由用户提供；字音与节奏仍需复核。" if project.get("lyrics",{}).get("reference_kind")=="user_supplied" else "歌词与音乐内容仍需复核。",17,"#8a4b12","start")
    # 第四首《日落大道》男声跨歌曲验证：新增未定位歌词提示，原文仍保留在项目及复核清单。
    # 大调约束与强拍先验：修改谱面未挂说明，区分用户已确认吞字和未知字，原显示保留。
    # if project["lyric_mapping"].get("unmapped_character_indices"):
    #     scene.text(560,146,f'另有{len(project["lyric_mapping"]["unmapped_character_indices"])}个歌词单位未定位，未强行挂谱；见复核清单。',17,"#a53b22","start")
    if project["lyric_mapping"].get("unmapped_character_indices"):
        missing=project["lyric_mapping"]["unmapped_character_indices"]
        char_lookup={c["index"]:c for c in project.get("lyrics",{}).get("characters",[])}
        confirmed=sum(char_lookup.get(i,{}).get("human_review",{}).get("status")=="user_confirmed_elided" for i in missing)
        pending=len(missing)-confirmed
        notice=(f"{confirmed}字已确认演唱吞字，{pending}字尚未定位；原文保留，见复核清单。" if pending else
                f"另有{confirmed}字为已确认吞字：原文保留，不补造音符。") if confirmed else f"另有{pending}个歌词单位未定位，未强行挂谱；见复核清单。"
        # 连续转调识别与不确定调性保护：未挂词与调性提示共存时合成简短句，避免抬头互相遮挡。
        regions=project.get('notation',{}).get('tonality_uncertain_regions',[])
        # 连续转调识别与不确定调性保护：保留既有未定位/吞字可读前缀，原简化文案保留。
        # if regions:notice=f"{pending}单位未定位，{confirmed}字已确认吞字；调性有{len(regions)}段待确认，保留原音；见复核页。"
        if regions:
            status=f"另有{pending}个歌词单位未定位" if pending else f"另有{confirmed}字为已确认吞字"
            if pending and confirmed:status+=f"；{confirmed}字已确认吞字"
            notice=status+f"；调性有{len(regions)}段待确认，保留原音；见复核页。"
        scene.text(560,146,notice,17,"#a53b22","start")
    elif project.get('notation',{}).get('tonality_uncertain_regions'):
        # 连续转调识别与不确定调性保护：新增独立SVG/PNG/按拍HTML抬头提示，原画布几何保持。
        scene.text(560,146,f"调性有{len(project['notation']['tonality_uncertain_regions'])}段待确认，保留演唱音高；见复核页。",17,"#a53b22","start")
    grouped = {}
    for event in project["events"]:
        if first_measure <= event["measure"] <= last_measure:
            grouped.setdefault(event["measure"], []).append(event)
    reference = project["notation"]["jianpu_reference_midi"]
    positions = {}
    row = 0
    x = 52
    y = 236
    # 简谱小节对齐与人工复核汇总：修改小节排版，原按音数变宽及自动折行实现注释保留。
    # # 歌词对齐与真实制谱：修改，原事件步进在缩放预览中使连续数字和休止难以区分，保留旧实现。
    # # def width(event):
    # #     base = {"whole": 4, "half": 2}.get(event["type"], 1)
    # #     return (36 if event["grace"] else 48) + (base-1)*24 + 10*event["dots"]
    # def width(event):
    #     # 歌词对齐与真实制谱：新增最小视觉间隔，并为延长横线、附点、升降号和歌词预留宽度。
    #     base = {"whole": 4, "half": 2}.get(event["type"], 1)
    #     accidental = jianpu_pitch(event["pitch_midi"], key, reference)[2]
    #     lyric_text = (event.get("lyric") or {}).get("text") or ""
    #     minimum = 50 if event["grace"] else 64
    #     glyph_span = 28 + (base-1)*26 + 12*event["dots"]
    #     accidental_space = 16 if accidental else 0
    #     lyric_space = max(0, len(lyric_text)*20 - 28)
    #     return max(minimum, glyph_span + accidental_space + lyric_space + 24)
    # for measure, events in sorted(grouped.items()):
    #     # 歌词对齐与真实制谱：修改，小节宽度与新视觉步进同步，保留两端呼吸空间。
    #     # bar_width = max(130, sum(width(event) for event in events) + 22)
    #     bar_width = max(160, sum(width(event) for event in events) + 32)
    #     if x + bar_width > scene.width - 42 and x > 52:
    #         row += 1
    #         x, y = 52, 236 + row * 158
    #     if bar_width > scene.width - 94:
    #         raise ValueError(f"第 {measure} 小节过密，预览需要专门的密集小节排版。")
    #     scene.text(x + 5, y - 59, str(measure), 15, "#718096", "start")
    #     scene.line(x, y-30, x, y+62, "#8fa0b4", 1)
    #     local_x = x + 24
    #     for event in events:
    #         degree, octave, accidental = jianpu_pitch(event["pitch_midi"], key, reference)
    #         color = "#b55b12" if event.get("review") else "#14243b"
    #         glyph_y = y - 12 if event["grace"] else y
    #         size = 19 if event["grace"] else 28
    #         scene.text(local_x, glyph_y, degree, size, color, weight="bold")
    #         if accidental:
    #             # 歌词对齐与真实制谱：修改，旧字体升降号在实测PNG缺字，保留原调用。
    #             # scene.text(local_x - 15, glyph_y - 7, accidental, 17, color)
    #             draw_accidental(scene, local_x - 16, glyph_y, accidental, color)
    #         for dot_number in range(abs(octave)):
    #             scene.dot(local_x, glyph_y + (-24 - 8*dot_number if octave > 0 else 19 + 7*dot_number), 2, color)
    #         base_quarters = {"whole": 4, "half": 2}.get(event["type"], 1)
    #         for dash in range(base_quarters - 1):
    #             scene.text(local_x + 26*(dash+1), y, "–", 24, color)
    #         if event["dots"]:
    #             scene.dot(local_x + 15 + 26*(base_quarters-1), glyph_y, 2.4, color)
    #         underlines = {"eighth": 1, "16th": 2, "32nd": 3}.get(event["type"], 0)
    #         for underline in range(underlines):
    #             scene.line(local_x-9, glyph_y+27+underline*5, local_x+9, glyph_y+27+underline*5, color, 1.4)
    #         lyric = event.get("lyric")
    #         if lyric and lyric["text"]:
    #             scene.text(local_x, y+53, lyric["text"], 20, "#263d54")
    #         positions[event["id"]] = (local_x, y, row, event)
    #         local_x += width(event)
    #     x += bar_width
    #     scene.line(x, y-30, x, y+62, "#8fa0b4", 1)
    # 简谱小节对齐与人工复核汇总：新增四列小节网格；统一留足最密小节的字形空间，过密时扩大画布。
    columns = 4
    left_margin, right_margin, bar_padding = 52, 42, 18

    # 简谱按拍分组优化：修改原逐音步进与单独下划线，完整原实现注释保留。
    # def glyph_space(event):
    #     base = {"whole": 4, "half": 2}.get(event["type"], 1)
    #     accidental = jianpu_pitch(event["pitch_midi"], key, reference)[2]
    #     lyric = (event.get("lyric") or {}).get("text") or ""
    #     lyric_half = max(12, len(lyric) * 10)
    #     left = max(27 if accidental else 12, lyric_half)
    #     right = max(lyric_half, 26 * (base-1) + 12,
    #                 26 * (base-1) + 20 if event["dots"] else 0)
    #     return left, right, 10 if event["grace"] else 14
    #
    # # 简谱小节对齐与人工复核汇总：新增全曲统一列宽，使节选与整曲也使用同一密度标准。
    # all_bars = {}
    # for event in project["events"]:
    #     all_bars.setdefault(event["measure"], []).append(event)
    # densest = max((sum(sum(glyph_space(e)) for e in events) + 2*bar_padding
    #                for events in all_bars.values()), default=160)
    # bar_width = math.ceil(max((scene.width-left_margin-right_margin)/columns, densest))
    # scene.width = left_margin + right_margin + columns*bar_width
    # scene.measure_boxes = {}
    # scene.layout = {"version": 1, "measures_per_row": columns, "measure_width": bar_width,
    #                 "left_margin": left_margin, "right_margin": right_margin,
    #                 "row_height": 158, "minimum_glyph_spacing_preserved": True}
    # # 简谱小节对齐与人工复核汇总：修改标题位置，原左对齐调用已执行，保留其条目并更新为居中展示。
    # title_item = next(i for i, item in enumerate(scene.items)
    #                   if item[0] == "text" and item[2] == 40)
    # original_title = scene.items[title_item]
    # scene.items[title_item] = (original_title[0], scene.width/2, *original_title[2:6], "middle", original_title[7])
    # for index, (measure, events) in enumerate(sorted(grouped.items())):
    #     row, column = divmod(index, columns)
    #     # 简谱小节对齐与人工复核汇总：修改首行基线，给独立小节编号和抬头留出空间；原位置注释保留。
    #     # x, y = left_margin + column*bar_width, 236 + row*158
    #     x, y = left_margin + column*bar_width, 250 + row*158
    #     scene.measure_boxes[measure] = {"row": row, "column": column, "x": x, "y": y,
    #                                     "width": bar_width, "events": []}
    #     scene.start_measure(measure)
    #     # 简谱小节对齐与人工复核汇总：修改小节编号高度，避免密集小节/跨小节连奏弧线覆盖编号。
    #     # scene.text(x+5, y-59, str(measure), 15, "#718096", "start")
    #     scene.text(x+5, y-82, str(measure), 15, "#718096", "start")
    #     scene.line(x, y-30, x, y+62, "#8fa0b4", 1)
    #     spaces = [glyph_space(event) for event in events]
    #     spare = max(0, bar_width - 2*bar_padding - sum(sum(s) for s in spaces))
    #     timed = sum(max(0, event["duration_ticks"]) for event in events)
    #     cursor = x+bar_padding
    #     for event, (glyph_left, glyph_right, gap) in zip(events, spaces):
    #         extra = spare * max(0,event["duration_ticks"]) / timed if timed else spare/len(events)
    #         local_x = cursor+glyph_left
    #         degree, octave, accidental = jianpu_pitch(event["pitch_midi"], key, reference)
    #         color = "#b55b12" if event.get("review") else "#14243b"
    #         glyph_y = y-12 if event["grace"] else y
    #         size = 19 if event["grace"] else 28
    #         scene.text(local_x, glyph_y, degree, size, color, weight="bold")
    #         if accidental:
    #             draw_accidental(scene, local_x-16, glyph_y, accidental, color)
    #         for dot_number in range(abs(octave)):
    #             scene.dot(local_x, glyph_y+(-24-8*dot_number if octave>0 else 19+7*dot_number), 2, color)
    #         base_quarters = {"whole": 4, "half": 2}.get(event["type"], 1)
    #         # 简谱小节对齐与人工复核汇总：新增随空白舒展的延长横线，保持真实时值及字音数据不变。
    #         dash_step = 26 + extra/base_quarters if base_quarters>1 else 26
    #         for dash in range(base_quarters-1):
    #             scene.text(local_x+dash_step*(dash+1), y, "–", 24, color)
    #         if event["dots"]:
    #             scene.dot(local_x+15+dash_step*(base_quarters-1), glyph_y, 2.4, color)
    #         underlines = {"eighth":1, "16th":2, "32nd":3}.get(event["type"],0)
    #         for underline in range(underlines):
    #             scene.line(local_x-9,glyph_y+27+underline*5,local_x+9,glyph_y+27+underline*5,color,1.4)
    #         lyric = event.get("lyric")
    #         if lyric and lyric["text"]:
    #             scene.text(local_x,y+53,lyric["text"],20,"#263d54")
    #         positions[event["id"]] = (local_x,y,row,event)
    #         scene.measure_boxes[measure]["events"].append({"id":event["id"], "x":local_x,
    #             "left":local_x-glyph_left, "right":local_x+glyph_right+extra})
    #         cursor += glyph_left+glyph_right+gap+extra
    #     scene.line(x+bar_width,y-30,x+bar_width,y+62,"#8fa0b4",1)
    #     scene.end_measure()
    # 简谱按拍分组优化：新增按全曲最密小节确定统一列宽，首段节选与完整谱共用同一标准。
    all_bars = {}
    for event in project["events"]:
        all_bars.setdefault(event["measure"], []).append(event)
    # 第四首《日落大道》男声跨歌曲验证：修改拍组宽度按各小节调号计算，保留旧全曲同调布局。
    # plans = {measure: jianpu_beat_plan(events, project['timing']['meter'], key, reference)
    #          for measure, events in all_bars.items()}
    plans = {measure: jianpu_beat_plan(events, project['timing']['meter'], *notation_at(project,measure=measure))
             for measure, events in all_bars.items()}
    densest = max((plan["minimum_width"] + 2 * bar_padding for plan in plans.values()), default=160)
    bar_width = math.ceil(max((scene.width - left_margin - right_margin) / columns, densest))
    scene.width = left_margin + right_margin + columns * bar_width
    scene.measure_boxes = {}
    beat_ticks, beat_count = jianpu_beat_unit(project["timing"]["meter"])
    scene.layout = {"version": 2, "measures_per_row": columns, "measure_width": bar_width,
                    "left_margin": left_margin, "right_margin": right_margin, "row_height": 158,
                    "minimum_glyph_spacing_preserved": True, "beat_ticks": beat_ticks,
                    "beats_per_measure": beat_count, "inside_beat_gap": 8, "grace_gap": 6,
                    "between_beat_gap": 28, "shared_underlines_within_beat": True,
                    "long_note_dashes_follow_quarter_positions": True}
    title_item = next(i for i, item in enumerate(scene.items)
                      if item[0] == "text" and item[2] == 40)
    original_title = scene.items[title_item]
    scene.items[title_item] = (original_title[0], scene.width / 2, *original_title[2:6], "middle", original_title[7])
    for index, (measure, events) in enumerate(sorted(grouped.items())):
        row, column = divmod(index, columns)
        x, y = left_margin + column * bar_width, 250 + row * 158
        box = {"row": row, "column": column, "x": x, "y": y, "width": bar_width,
               "events": [], "beats": [], "beams": []}
        scene.measure_boxes[measure] = box
        scene.start_measure(measure)
        scene.text(x + 5, y - 82, str(measure), 15, "#718096", "start")
        # 第四首《日落大道》男声跨歌曲验证：新增转调标记并从此小节使用该调的数字，不整体移调音符。
        key,reference=notation_at(project,measure=measure)
        if any(segment['start_measure']==measure and measure>1 for segment in project['notation'].get('key_segments',[])):
            scene.text(x+45,y-82,'转1='+key['jianpu_one'],18,'#205a98','start')
        box['key']=key['label'];box['jianpu_reference_midi']=reference
        scene.line(x, y - 30, x, y + 62, "#8fa0b4", 1)
        plan = plans[measure]
        # 简谱按拍分组优化：新增剩余空白只铺在拍组两侧，拍内字形间距不随稀疏小节膨胀。
        extra_per_beat = max(0, bar_width - 2 * bar_padding - plan["minimum_width"]) / beat_count
        cursor = x + bar_padding
        event_boxes = {}
        for beat, (units, minimum) in enumerate(zip(plan["beats"], plan["widths"])):
            beat_width = minimum + extra_per_beat
            beat_box = {"number": beat + 1, "start_tick": beat * beat_ticks,
                        "end_tick": (beat + 1) * beat_ticks, "x": cursor,
                        "width": beat_width, "glyphs": []}
            box["beats"].append(beat_box)
            actual_width = sum(unit["left"] + unit["right"] + unit["gap_after"] for unit in units)
            glyph_cursor = cursor + (beat_width - actual_width) / 2
            for unit in units:
                event, part = unit["event"], unit["part"]
                local_x = glyph_cursor + unit["left"]
                degree, octave, accidental = jianpu_pitch(event["pitch_midi"], key, reference)
                color = "#b55b12" if event.get("review") else "#14243b"
                glyph_y = y - 12 if event["grace"] else y
                if part == 0:
                    scene.text(local_x, glyph_y, degree, 19 if event["grace"] else 28, color, weight="bold")
                    if accidental:
                        draw_accidental(scene, local_x - 16, glyph_y, accidental, color)
                    for dot_number in range(abs(octave)):
                        scene.dot(local_x, glyph_y + (-24 - 8 * dot_number if octave > 0 else 19 + 7 * dot_number), 2, color)
                    lyric = event.get("lyric")
                    if lyric and lyric["text"]:
                        scene.text(local_x, y + 53, lyric["text"], 20, "#263d54")
                    positions[event["id"]] = (local_x, y, row, event)
                    event_boxes[event["id"]] = {"id": event["id"], "x": local_x,
                        "left": local_x - unit["left"], "right": local_x + unit["right"],
                        "beat": beat + 1, "offset_ticks": event["offset_ticks"], "grace": event["grace"]}
                else:
                    scene.text(local_x, y, "–", 24, color)
                    event_boxes[event["id"]]["right"] = local_x + unit["right"]
                quarters = {"whole": 4, "half": 2}.get(event["type"], 1)
                if event["dots"] and part == quarters - 1:
                    scene.dot(local_x + 15, glyph_y, 2.4, color)
                beat_box["glyphs"].append({"id": event["id"], "part": part, "tick": unit["tick"],
                    "x": local_x, "left": local_x - unit["left"], "right": local_x + unit["right"]})
                glyph_cursor += unit["left"] + unit["right"] + unit["gap_after"]
            cursor += beat_width + plan["beat_gap"]
        box["events"] = [event_boxes[event["id"]] for event in events]
        # 简谱按拍分组优化：新增每拍统一减时线高度，为低八度点留空；倚音仍使用独立的小号基线。
        baselines = {}
        for event in events:
            _, octave, _ = jianpu_pitch(event["pitch_midi"], key, reference)
            identity = (event["offset_ticks"] // beat_ticks, bool(event["grace"]))
            baselines[identity] = max(baselines.get(identity, 27), 19 + 7 * (-octave - 1) + 6 if octave < 0 else 27)
        for beam in jianpu_beam_groups(events, beat_ticks):
            members = beam["events"]
            first, last = members[0], members[-1]
            first_x, last_x = positions[first["id"]][0], positions[last["id"]][0]
            identity = (first["offset_ticks"] // beat_ticks, beam["grace"])
            beam_y = y - (12 if beam["grace"] else 0) + baselines[identity] + 5 * (beam["level"] - 1)
            color = "#b55b12" if all(event.get("review") for event in members) else "#14243b"
            scene.line(first_x - 9, beam_y, last_x + 9, beam_y, color, 1.4)
            box["beams"].append({"level": beam["level"], "grace": beam["grace"],
                "beat": int(identity[0]) + 1, "event_ids": [event["id"] for event in members],
                "x1": first_x - 9, "x2": last_x + 9, "y": beam_y})
        # 通用段落强拍与乐句节奏修复：新增简谱连音括号和数字3；转音音数可多于三个歌词音。
        tuple_groups=defaultdict(list)
        for event in events:
            if event.get('tuplet') and not event.get('grace'):tuple_groups[event['tuplet']['id']].append(event)
        for identity,members in tuple_groups.items():
            x1=positions[members[0]['id']][0]-11;x2=positions[members[-1]['id']][0]+11
            mid=(x1+x2)/2;ty=y-60
            scene.line(x1,ty+5,x1,ty,'#14243b',1)
            scene.line(x1,ty,mid-10,ty,'#14243b',1)
            scene.text(mid,ty,'3',15,'#14243b')
            scene.line(mid+10,ty,x2,ty,'#14243b',1)
            scene.line(x2,ty,x2,ty+5,'#14243b',1)
            box.setdefault('tuplets',[]).append({'id':identity,'event_ids':[e['id'] for e in members],'x1':x1,'x2':x2,'y':ty})
        scene.line(x + bar_width, y - 30, x + bar_width, y + 62, "#8fa0b4", 1)
        scene.end_measure()
    # 歌词对齐与真实制谱：新增跨小节/换行延音弧线和歌词延长线。
    previous_by_piece = {}
    previous_by_char = {}
    for event in project["events"]:
        if event["id"] not in positions:
            continue
        ex, ey, erow, _ = positions[event["id"]]
        piece = event.get("piece_id")
        if "stop" in event["ties"]:
            previous = previous_by_piece.get(piece)
            if previous:
                px, py, prow = previous
                if prow == erow:
                    scene.arc(px+7, ey-37, ex-7, 15)
                else:
                    scene.arc(px+7, py-37, scene.width-46, 15)
                    scene.arc(52, ey-37, ex-7, 15)
            else:
                scene.arc(max(52, ex-30), ey-37, ex-7, 12)
        if piece:
            previous_by_piece[piece] = (ex, ey, erow)
        lyric = event.get("lyric")
        if lyric:
            char = lyric["character_index"]
            previous = previous_by_char.get(char)
            if previous:
                px, py, prow = previous
                if prow == erow:
                    scene.line(px+12, ey+59, ex+9, ey+59, "#65788d", 1)
                else:
                    scene.line(px+12, py+59, scene.width-46, py+59, "#65788d", 1)
                    scene.line(52, ey+59, ex+9, ey+59, "#65788d", 1)
            previous_by_char[char] = (ex, ey, erow)
    # 自动音乐解码改造：新增独立slur绘图，使用更高的弧线区分同音延音。
    active_slurs = {}
    for event in project["events"]:
        if event["id"] not in positions:
            continue
        ex, ey, erow, _ = positions[event["id"]]
        for slur in event.get("slurs", []):
            number = slur["number"]
            if slur["type"] == "start":
                active_slurs[number] = (ex, ey, erow)
            elif slur["type"] == "stop" and number in active_slurs:
                px, py, prow = active_slurs.pop(number)
                if prow == erow:
                    scene.arc(px, ey-48, ex, 22, "#263d54")
                else:
                    scene.arc(px, py-48, scene.width-46, 22, "#263d54")
                    scene.arc(52, ey-48, ex, 22, "#263d54")
    scene.height = int(y + 110)
    # 简谱小节对齐与人工复核汇总：修改页脚为谱面范围，原导出技术提示注释保留。
    # scene.text(52, scene.height-25, f'第 {first_measure}–{last_measure} 小节 · 可编辑 MusicXML 与原始秒时间/量化误差另存 · 编辑器往返待验证', 15, "#718096", "start")
    scene.text(52,scene.height-25,f'第 {first_measure}–{last_measure} 小节 · 人声简谱自动稿',15,"#718096","start")
    return scene

# 歌词对齐与真实制谱：新增整体结构验证，复用既有检查器而不修改兼容性样例。
def validate_score(project, xml_root):
    from notation_smoke import inspect_xml
    inspected = inspect_xml(xml_root)
    errors = list(inspected["errors"])
    bar_ticks = project["statistics"]["bar_ticks"]
    totals = {number: 0 for number in range(1, project["statistics"]["measure_count"] + 1)}
    for event in project["events"]:
        totals[event["measure"]] += event["duration_ticks"]
        if event["offset_ticks"] + event["duration_ticks"] > bar_ticks:
            errors.append(f'{event["id"]} 跨越小节但未拆分。')
    if any(total != bar_ticks for total in totals.values()):
        errors.append("至少一个小节时值不完整。")
    represented = {event["piece_id"] for event in project["events"] if event["piece_id"]}
    if represented != {note["id"] for note in project["quantized_notes"]}:
        errors.append("存在遗漏或额外的派生音符。")
    return {"valid": not errors, "errors": errors, "warnings": inspected["warnings"],
            "scope": "single_voice_score_semantics_not_editor_roundtrip",
            "measure_count": len(totals), "all_measure_ticks": bar_ticks,
            "all_source_pieces_represented": represented == {note["id"] for note in project["quantized_notes"]}}



# 歌词对齐与真实制谱：新增全链导出入口和源时间轴一致性检查。
def export_score(args):
    started = time.perf_counter()
    notes_path, lyrics_path, audio_path = Path(args.notes), Path(args.lyrics), Path(args.audio)
    refined = read_json(notes_path)
    source = refined["source"]
    if float(source.get("offset_seconds", 0)) != 0:
        raise ValueError("本入口当前仅接受整首时间轴；片段须先回映为整首秒时间。")
    if lyrics_path.exists():
        lyric_data = read_json(lyrics_path)
    elif args.allow_no_lyrics:
        lyric_data = {"characters": [], "alignment_status": "not_available", "reference_kind": "none"}
    else:
        raise FileNotFoundError(f"逐字对齐文件尚未生成：{lyrics_path}")
    lyric_source = lyric_data.get("source", {})
    if lyric_source.get("sha256") and lyric_source["sha256"] != source["sha256"]:
        raise ValueError("歌词对齐与音符分析不是同一份分离人声，不混用不同运行。")
    if lyric_source.get("offset_seconds", 0) != 0:
        raise ValueError("歌词不是整首零偏移时间轴。")
    analysis = analyze_audio(audio_path, ROOT / "reports" / "score_audio_analysis.json")
    if abs(analysis["duration_seconds"] - float(source["duration_seconds"])) > 0.1:
        raise ValueError("混音与派生音符总时长不一致，拒绝错误映射。")
    mapping, timing = make_timing(analysis, args.tempo, args.meter, args.beat_origin)
    key = key_definition(args.key or analysis["key"]["selected"])
    pieces, characters, alignment_issues = match_lyrics(refined["notes"], lyric_data)
    events, quantized, stats = quantize(pieces, mapping, timing, analysis["duration_seconds"], args.subdivision)
    lyric_mapping = attach_lyrics(events, characters)
    pitches = [piece["pitch_midi"] for piece in pieces]
    tonic_reference = 60 + key["jianpu_one_pc"]
    tonic_reference += 12 * round((statistics.median(pitches) - tonic_reference - 5) / 12)
    project = {
        "schema_version": 1, "artifact_kind": "real_audio_automatic_draft",
        "quality_status": "pending_manual_music_and_lyric_correction", "title": args.title,
        "inputs": {"notes_path": str(notes_path.resolve()), "notes_sha256": sha256(notes_path),
                   "lyrics_path": str(lyrics_path.resolve()) if lyrics_path.exists() else None,
                   "lyrics_sha256": sha256(lyrics_path) if lyrics_path.exists() else None,
                   "mix_audio_path": str(audio_path.resolve()), "mix_audio_sha256": analysis["source_sha256"],
                   "transcription_source": source},
        "raw_analysis_preservation": {"original_notes_and_continuous_f0": str(notes_path.resolve()),
                                      "unchanged_source": True, "time_unit": "original_song_seconds"},
        "audio_analysis": analysis, "timing": timing,
        "notation": {"key": key, "key_source": "user_override" if args.key else analysis["key"],
                     "jianpu_reference_midi": tonic_reference, "ppq": PPQ,
                     "triplet_detection": "not_implemented_in_initial_fixed_grid",
                     "midi_grace_note_playback": "24_tick_lead_in_approximation"},
        "overrides": {"tempo": args.tempo, "key": args.key, "meter": args.meter,
                      "beat_origin": args.beat_origin, "subdivision": args.subdivision},
        "lyrics": {"reference_kind": lyric_data.get("reference_kind", "unknown"),
                   "alignment_status": lyric_data.get("alignment_status", "unknown"),
                   "characters": characters, "review_required": True},
        "alignment_issues": alignment_issues, "lyric_mapping": lyric_mapping,
        "quantized_notes": quantized, "events": events, "statistics": stats,
        "tempo_events": tempo_events(mapping, timing, stats["total_ticks"]),
        "external_editor_roundtrip": "not_tested",
    }
    xml = build_musicxml(project)
    validation = validate_score(project, xml)
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    ET.indent(xml, space="  ")
    ET.ElementTree(xml).write(output / "vocal_draft.musicxml", encoding="utf-8", xml_declaration=True)
    write_midi(output / "vocal_draft.mid", project)
    save_json(output / "project.json", project)
    save_json(output / "validation.json", validation)
    if not validation["valid"]:
        save_json(args.report, {"status": "failed_structure_validation", "validation": validation,
                                "output_dir": str(output.resolve()), "statistics": stats})
        raise ValueError("制谱语义检查未通过：" + "; ".join(validation["errors"][:8]))
    full_scene = render_jianpu(project)
    full_svg = full_scene.svg()
    (output / "jianpu.svg").write_text(full_svg, encoding="utf-8")
    # 第二首跨歌曲验证：修改，原首音选择保留；排除无挂词前奏对预览的抢占。
    # first_vocal = min(event["measure"] for event in events if event["pitch_midi"] is not None)
    first_vocal = first_vocal_measure(project)
    excerpt_start = max(1, first_vocal - 1)
    excerpt_end = min(stats["measure_count"], excerpt_start + 11)
    preview = render_jianpu(project, excerpt_start, excerpt_end, True)
    preview.png(output / "preview_first_vocal.png")
    (output / "preview_first_vocal.svg").write_text(preview.svg(), encoding="utf-8")
    transcript = "".join(str(char["text"]) for char in characters)
    # 歌词对齐与真实制谱：修改，按真实歌词来源区分提示，旧文案保留。
    # html_document = '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>' + html.escape(args.title) + ' · 自动简谱草稿</title><style>body{margin:24px;background:#eef2f6;font-family:"Microsoft YaHei",sans-serif;color:#14243b}main{max-width:1440px;margin:auto;background:white;padding:20px}svg{width:100%;height:auto}a{color:#205a98}p{line-height:1.8}.notice{padding:14px;background:#fff4df;border-left:4px solid #b55b12}</style></head><body><main><p class="notice">自动识别草稿，歌词未经校正。调号、拍号、字音对应及音符均待人工核查；本页是静态谱面预览。</p><p><a href="vocal_draft.musicxml">下载可编辑 MusicXML</a>　<a href="vocal_draft.mid">下载试听 MIDI</a>　<a href="project.json">项目数据</a></p>' + full_svg + '<details><summary>自动识别原文（含未映射字，未经校正）</summary><p>' + html.escape(transcript) + '</p></details></main></body></html>'
    html_document = '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>' + html.escape(args.title) + ' · 自动简谱草稿</title><style>body{margin:24px;background:#eef2f6;font-family:"Microsoft YaHei",sans-serif;color:#14243b}main{max-width:1440px;margin:auto;background:white;padding:20px}svg{width:100%;height:auto}a{color:#205a98}p{line-height:1.8}.notice{padding:14px;background:#fff4df;border-left:4px solid #b55b12}</style></head><body><main><p class="notice">' + html.escape(lyric_notice(project)) + '；本页是静态谱面预览。</p><p><a href="vocal_draft.musicxml">下载可编辑 MusicXML</a>　<a href="vocal_draft.mid">下载试听 MIDI</a>　<a href="project.json">项目数据</a></p>' + full_svg + '<details><summary>' + ('用户提供原文（含未映射字）' if project.get('lyrics', {}).get('reference_kind') == 'user_supplied' else '自动识别原文（含未映射字，未经校正）') + '</summary><p>' + html.escape(transcript) + '</p></details></main></body></html>'
    (output / "jianpu.html").write_text(html_document, encoding="utf-8")
    report = {"status": "automatic_draft_exported_quality_unverified", "title": args.title,
              "inputs": project["inputs"], "statistics": stats, "validation": validation,
              # 小节划分与拍速层级纠错：修改，原报告检测脉冲速度保留；报告实际记谱四分拍速度。
              # "tempo_bpm": args.tempo or analysis["tempo"]["bpm"], "meter": timing["meter"],
              # 小节划分与拍速层级纠错：修改，原动态导入保留；明确使用共用速度接口。
              # "tempo_bpm":__import__('metrical_timing').selected_quarter_tempo(project), "meter": timing["meter"],
              "tempo_bpm":selected_quarter_tempo(project), "meter": timing["meter"],
              "key": key, "confidence": {"tempo": analysis["tempo"], "meter": analysis["meter"], "key": analysis["key"]},
              "lyric_status": project["lyrics"]["alignment_status"], "lyrics_reference_kind": project["lyrics"]["reference_kind"],
              "lyric_mapping": lyric_mapping, "alignment_issues": alignment_issues,
              "seconds": time.perf_counter() - started, "external_editor_roundtrip": "not_tested",
              "artifacts": {name: str((output / name).resolve()) for name in
                            ("vocal_draft.musicxml", "vocal_draft.mid", "project.json", "validation.json",
                             "jianpu.svg", "jianpu.html", "preview_first_vocal.png")},
              # 歌词对齐与真实制谱：修改，按真实歌词来源区分提示，旧文案保留。
              # "limitations": ["所有音符、自动歌词、调性与拍号尚需人工校正",
              "limitations": [lyric_notice(project) + "；调性与拍号仍待确认",
                              "十六分等固定网格暂不自动检测三连音；塌缩短音作为待审倚音保留",
                              "原始秒、f0及量化误差独立保存；没有用分段ASR均分声称精准字音对齐",
                              "实际易谱/MuseScore编辑器往返未测试"] }
    # 十一首可编辑五线谱：新增五线谱交换文件与真实分页预览，复用本次旋律/歌词。
    from staff_export import export_staff_score
    report['staff_export'] = export_staff_score(output)
    save_json(args.report, report)
    # 歌词对齐与真实制谱：修改，旧报告状态文案“歌词、音符、节奏和调性均待人工校正”对用户原文不适用。
    markdown = f"""# 真实人声制谱草稿

来源：{args.title}，真实混音 {analysis["duration_seconds"]:.2f} 秒。状态：自动草稿；{lyric_notice(project)}；调性与拍号待确认。

- 拍速候选：{report["tempo_bpm"]:.3f} BPM；拍号：{timing["meter"][0]}/{timing["meter"][1]}；调性候选：{key["label"]}。置信为未校准的启发式，允许命令行覆盖。
- {stats["raw_pitched_notes"]} 个派生音符，经真实歌词边界处理为 {len(quantized)} 个事件；{stats["measure_count"]} 小节，每小节时值核查通过。
- 字音映射：{lyric_mapping["mapped_characters"]}/{lyric_mapping["character_count"]} 字，未映射索引保留在JSON；歌词来源 {project["lyrics"]["reference_kind"]}，对齐状态 {project["lyrics"]["alignment_status"]}。
- 量化边界误差：中位 {stats["quantization_error_seconds"]["median_abs"]:.4f} 秒，95分位 {stats["quantization_error_seconds"]["p95_abs"]:.4f} 秒，最大 {stats["quantization_error_seconds"]["max_abs"]:.4f} 秒。
- {stats["grace_notes_from_collapsed_grid"]} 个短音量化塌缩，作为橙色待审倚音保留，没有声称这些必然是原唱装饰音。
- 导出和相关分析用时 {report["seconds"]:.3f} 秒；不包括分离、转录、ASR、TIFA、模型下载和人工校正。
- MusicXML内部结构和字音标记核查通过；external_editor_roundtrip=not_tested。

产物目录：{output.resolve()}。可编辑 vocal_draft.musicxml；试听 vocal_draft.mid；静态 jianpu.html / jianpu.svg；首个人声段预览 preview_first_vocal.png；原始秒、局部tempo map、音符量化误差、字音冲突在 project.json。

本实现保留完整源分析引用及文件SHA，未覆盖原始f0或模型音符。当前量化网格每四分拍分{args.subdivision}份，不自动识别三连音。半拍/倍拍与拍号相位存在歧义；自动调性未建模转调。真实编辑器往返及音乐准确性仍待验证。
"""
    Path(args.report).with_suffix(".md").write_text(markdown, encoding="utf-8")
    print(json.dumps({"status": report["status"], "statistics": stats, "lyric_mapping": {
        "mapped": lyric_mapping["mapped_characters"], "total": lyric_mapping["character_count"],
        "unmapped": len(lyric_mapping["unmapped_character_indices"])},
        "tempo_bpm": report["tempo_bpm"], "key": key["label"], "meter": timing["meter"],
        "report": str(Path(args.report).resolve()), "preview": report["artifacts"]["preview_first_vocal.png"]}, ensure_ascii=False))
    return 0

# 歌词对齐与真实制谱：新增显式覆盖参数，缺少真实前提时失败而不是伪造默认谱。
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--notes", type=Path, default=ROOT / "test_outputs/refined/latest/analysis.json")
    parser.add_argument("--lyrics", type=Path, default=ROOT / "test_outputs/lyrics/first_song/characters.json")
    parser.add_argument("--audio", type=Path, default=ROOT / "test_outputs/converted/孙燕姿 - 遇见.flac")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "test_outputs/scores/latest")
    parser.add_argument("--report", type=Path, default=ROOT / "reports/score_export.latest.json")
    parser.add_argument("--title", default="遇见")
    parser.add_argument("--tempo", type=float)
    parser.add_argument("--key", help="如 Ab:major 或 F:minor")
    parser.add_argument("--meter", help="如4/4、3/4或6/8")
    parser.add_argument("--beat-origin", type=float, help="第一小节第一拍对应整首音频的秒时间")
    parser.add_argument("--subdivision", type=int, choices=(2, 4, 8), default=4)
    parser.add_argument("--allow-no-lyrics", action="store_true", help="仅用于歌词尚未就绪时的明确无词预检查")
    args = parser.parse_args()
    try:
        return export_score(args)
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"真实制谱失败：{type(error).__name__}: {error}", file=sys.stderr)
        return 1

if __name__ == "__main__":
    raise SystemExit(main())

