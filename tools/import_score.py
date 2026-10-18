"""歌词对齐与真实制谱：将真实 MusicXML 校正另存回项目，声学原始数据保持独立。"""
# 歌词对齐与真实制谱：新增标准库回导依赖，不安装环境、不接触模型或GPU。
from __future__ import annotations
import argparse
import copy
import hashlib
import json
import math
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path
from notation_smoke import inspect_xml, TYPES

ROOT = Path(__file__).resolve().parents[1]
PPQ = 480
PITCH_CLASS = dict(C=0, D=2, E=4, F=5, G=7, A=9, B=11)

# 歌词对齐与真实制谱：新增确定性哈希和另存工具，用于独立核验原稿及f0完整性。
def file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def value_sha(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def save_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


# 歌词对齐与真实制谱：新增真实谱解析适配，沿用已有时值/延音/歌词核查并增强合法音高和稳定ID。
def inspect_real_score(root):
    root = copy.deepcopy(root)
    for node in root.iter():
        node.tag = node.tag.rsplit("}", 1)[-1]
    try:
        inspection = inspect_xml(root)
    except (TypeError, ValueError, KeyError, ZeroDivisionError) as error:
        return {"valid": False, "errors": [f"不可解析的谱面语义：{type(error).__name__}: {error}"],
                "warnings": [], "events": [], "tempo_events": [], "measures": []}
    errors, warnings = list(inspection["errors"]), list(inspection["warnings"])
    # 歌词对齐与真实制谱：新增先拒绝已有语义错误，避免对非法音名继续计算MIDI值。
    if not inspection["valid"]:
        return {"valid": False, "errors": errors, "warnings": warnings,
                "events": [], "tempo_events": [], "measures": []}
    measures = inspection["score"]["measures"]
    flat = []
    absolute = Fraction(0)
    xml_measures = root.findall("part/measure")
    for measure, xml_measure in zip(measures, xml_measures):
        if len(xml_measure.findall("attributes")) > 1:
            errors.append(f'第{measure["index"]}小节：暂不支持小节内多次attributes变更。')
        for semantic, note in zip(measure["events"], xml_measure.findall("note")):
            pitch, midi = semantic["pitch"], None
            if semantic["type"] not in TYPES:
                errors.append(f'{semantic["ref"]}：未知时值类型，不将未核验时值标为有效。')
            if pitch is not None:
                alter = Fraction(pitch["alter"])
                candidate = 12 * (pitch["octave"] + 1) + PITCH_CLASS[pitch["step"]] + alter
                if alter.denominator != 1 or candidate.denominator != 1 or not 0 <= candidate <= 127:
                    errors.append(f'{semantic["ref"]}：当前只支持MIDI 0–127内整数半音。')
                else:
                    midi = int(candidate)
            start = (absolute + Fraction(semantic["onset_quarters"])) * PPQ
            duration = Fraction(semantic["duration_quarters"]) * PPQ
            if start.denominator != 1 or duration.denominator != 1:
                errors.append(f'{semantic["ref"]}：当前480 PPQ无法精确表达时值，拒绝静默舍入。')
            lyrics = semantic["lyrics"]
            for lyric in lyrics:
                if lyric["syllabic"] not in (None, "single", "begin", "middle", "end"):
                    errors.append(f'{semantic["ref"]}：非法syllabic。')
                if lyric["extend"] not in (None, "start", "continue", "stop"):
                    errors.append(f'{semantic["ref"]}：非法歌词延长类型。')
            if any(value not in ("start", "stop") for value in semantic["ties"]):
                errors.append(f'{semantic["ref"]}：不支持此tie类型。')
            flat.append({"id": note.get("id"), "xml_ref": semantic["ref"], "measure": measure["index"],
                         "offset_ticks": int(Fraction(semantic["onset_quarters"]) * PPQ),
                         "start_tick": int(start), "duration_ticks": int(duration),
                         "pitch_midi": midi, "pitch_spelling": pitch, "is_rest": semantic["rest"],
                         "grace": semantic["grace"], "type": semantic["type"], "dots": semantic["dots"],
                         "ties": semantic["ties"], "tuplet_ratio": semantic["tuplet_ratio"], "lyrics": lyrics})
        absolute += Fraction(measure["duration_quarters"])
    # 歌词对齐与真实制谱：新增真正的声音tempo偏移解释，不能把视觉offset误当播放位置。
    tempos = []
    divisions, bar_start = None, Fraction(0)
    for measure, xml_measure in zip(measures, xml_measures):
        cursor = Fraction(0)
        for child in xml_measure:
            if child.tag == "attributes" and child.find("divisions") is not None:
                divisions = Fraction(child.findtext("divisions"))
            elif child.tag == "note" and child.find("grace") is None and divisions:
                cursor += Fraction(child.findtext("duration", "0")) / divisions
            elif child.tag in ("direction", "sound") and divisions:
                sound = child if child.tag == "sound" else child.find("sound")
                if sound is None or sound.get("tempo") is None:
                    if child.find("direction-type/metronome") is not None:
                        warnings.append("发现无sound tempo的节拍器记号；其播放器行为未由回导器推断。")
                    continue
                bpm = float(sound.get("tempo"))
                offset = child.find("offset")
                delta = Fraction(0)
                if offset is not None and (child.tag == "sound" or offset.get("sound", "no") == "yes"):
                    delta = Fraction(offset.text) / divisions
                elif offset is not None and Fraction(offset.text or "0"):
                    warnings.append("direction offset未启用sound，实际tempo按当前音乐位置解释。")
                tick = (bar_start + cursor + delta) * PPQ
                if not math.isfinite(bpm) or bpm <= 0 or tick < 0 or tick.denominator != 1:
                    errors.append("声音tempo或其生效位置非法/无法精确表达。")
                else:
                    tempos.append({"tick": int(tick), "bpm": bpm})
        bar_start += Fraction(measure["duration_quarters"])
    if not tempos:
        warnings.append("未找到声音tempo；不声明播放时间已与原曲对齐。")
    return {"valid": not errors, "errors": errors, "warnings": warnings, "events": flat,
            "tempo_events": tempos, "measures": measures, "total_ticks": int(absolute * PPQ),
            "scope": "complete_measures_single_voice_integer_semitones_480_ppq_not_full_musicxml_xsd"}


# 歌词对齐与真实制谱：新增ID优先映射及歧义记录；无ID的位置候选从不自动当作原始音符身份。
def map_events(imported, originals):
    by_id = {event["id"]: event for event in originals if event.get("id")}
    original_counts = Counter(event.get("id") for event in originals)
    imported_counts = Counter(event.get("id") for event in imported)
    order = {event["id"]: index for index, event in enumerate(originals) if event.get("id")}
    sequence = [order[event["id"]] for event in imported if event.get("id") in order]
    reordered = any(right < left for left, right in zip(sequence, sequence[1:]))
    issues, changes, mapped = [], [], []
    if reordered:
        issues.append({"type": "known_ids_reordered", "requires_review": True})
    for event in imported:
        event = copy.deepcopy(event)
        identity = event.get("id")
        source = by_id.get(identity)
        if source and imported_counts[identity] == 1 and original_counts[identity] == 1 and not reordered:
            event["source_mapping"] = {"status": "unique_stable_id", "source_event_id": identity,
                                       "piece_id": source.get("piece_id"),
                                       "identity_verification": "xml_id_based_not_verified_editor_identity"}
            for field in ("pitch_midi", "start_tick", "duration_ticks", "grace", "ties"):
                before, after = source.get(field), event.get(field)
                if field == "ties":
                    before, after = sorted(before or []), sorted(after or [])
                if before != after:
                    changes.append({"event_id": identity, "field": field, "before": before, "after": after})
            before_lyric = source.get("lyric") or {}
            before = [{"verse": "1", "text": before_lyric.get("text") or "", "extend": before_lyric.get("extend"),
                       "syllabic": "single" if before_lyric.get("text") is not None else None}] if before_lyric else []
            if before != event["lyrics"]:
                changes.append({"event_id": identity, "field": "lyrics", "before": before, "after": event["lyrics"]})
        else:
            candidates = [old["id"] for old in originals if all(old.get(key) == event.get(key) for key in
                          ("measure", "offset_ticks", "duration_ticks", "grace"))]
            event["source_mapping"] = {"status": "uncertain_requires_review", "candidate_event_ids": candidates,
                                       "reason": "known_ids_reordered" if reordered else "missing_changed_or_duplicate_id"}
            issues.append({"type": "uncertain_event_identity", "xml_ref": event["xml_ref"],
                           "xml_id": identity, "candidate_event_ids": candidates, "requires_review": True})
        mapped.append(event)
    present = {event.get("id") for event in imported}
    missing = [event["id"] for event in originals if event.get("id") not in present]
    if missing:
        issues.append({"type": "original_ids_missing_or_replaced", "event_ids": missing, "requires_review": True})
    return mapped, changes, issues


# 歌词对齐与真实制谱：新增拍号/调号/tempo全局修订记录，避免只记录单音字段而漏掉播放语义。
def global_changes(inspection, project, prior_layer):
    changes = []
    original_measures = prior_layer.get("measures", []) if prior_layer else []
    expected_count = len(original_measures) if prior_layer else project.get("statistics", {}).get("measure_count")
    if expected_count is not None and expected_count != len(inspection["measures"]):
        changes.append({"field": "measure_count", "before": expected_count, "after": len(inspection["measures"])})
    for index, measure in enumerate(inspection["measures"]):
        previous = original_measures[index] if index < len(original_measures) else None
        old_meter = previous["time"] if previous else project.get("timing", {}).get("meter")
        # 十一首可编辑五线谱：原单一调号比较保留；回导未改谱时按原项目分段调号比较。
        # definition = project.get("notation", {}).get("key")
        definition = project.get("notation", {}).get("key")
        for section in sorted(project.get("notation", {}).get("key_segments", []), key=lambda row: row["start_measure"]):
            if section["start_measure"] <= index + 1:
                definition = section["key"]
        old_key = previous["key"] if previous else [definition["fifths"], definition["mode"]] if definition else None
        for field, old, new in (("meter", old_meter, measure["time"]), ("key", old_key, measure["key"])):
            if old is not None and old != new:
                changes.append({"measure": index + 1, "field": field, "before": old, "after": new})
    old_tempo = prior_layer.get("tempo_events", []) if prior_layer else project.get("tempo_events", [])
    new_tempo = inspection["tempo_events"]
    equivalent = len(old_tempo) == len(new_tempo) and all(
        left["tick"] == right["tick"] and math.isclose(left["bpm"], right["bpm"], rel_tol=0, abs_tol=0.00001)
        for left, right in zip(old_tempo, new_tempo))
    if not equivalent:
        changes.append({"field": "tempo_events", "before": old_tempo, "after": new_tempo})
    return changes


# 歌词对齐与真实制谱：新增校正版项目层及原始分析完整归档，原自动事件、f0和时间戳不覆盖。
def import_correction(musicxml, project_path, output_path, report_path=None):
    musicxml, project_path, output_path = (Path(path).resolve() for path in (musicxml, project_path, output_path))
    project = read_json(project_path)
    analysis_path = Path(project["inputs"]["notes_path"]).resolve()
    protected = {musicxml, project_path, analysis_path}
    if output_path in protected or (report_path and Path(report_path).resolve() in protected | {output_path}):
        raise ValueError("回导结果及报告必须另存，不能覆盖MusicXML、原项目或原始分析。")
    source_hashes = {str(path): file_sha(path) for path in protected}
    if source_hashes[str(analysis_path)] != project["inputs"]["notes_sha256"]:
        raise ValueError("原项目引用的分析SHA不符，停止回导。")
    analysis = read_json(analysis_path)
    inspection = inspect_real_score(ET.parse(musicxml).getroot())
    if not inspection["valid"]:
        report = {"status": "rejected_invalid_or_unsupported_score", "validation": inspection,
                  "output_written": False, "external_editor_roundtrip": "not_tested"}
        if report_path:
            save_json(report_path, report)
        return report
    # 歌词对齐与真实制谱：新增多轮修订的参照层选择，累计历史不丢失初始自动稿。
    prior_layer = project.get("corrected_score")
    reference = project["events"] if prior_layer is None else prior_layer["events"]
    if prior_layer is not None:
        reference = copy.deepcopy(reference)
        for event in reference:
            if event.get("lyrics"):
                lyric = event["lyrics"][0]
                event["lyric"] = {"text": lyric["text"] or None, "extend": lyric["extend"]}
    mapped, changes, mapping_issues = map_events(inspection["events"], reference)
    # 歌词对齐与真实制谱：新增全局记谱/播放修订合并；不改变原始音频秒时间。
    changes.extend(global_changes(inspection, project, prior_layer))
    corrected = copy.deepcopy(project)
    archive = corrected.setdefault("preserved_analysis", {"path": str(analysis_path),
        "file_sha256": source_hashes[str(analysis_path)], "pitch_frames_sha256": value_sha(analysis["pitch_frames"]),
        "content": copy.deepcopy(analysis)})
    if archive["content"] != analysis or archive["pitch_frames_sha256"] != value_sha(analysis["pitch_frames"]):
        raise ValueError("既有声学归档与原分析不一致，停止追加修订。")
    corrected["artifact_kind"] = "real_audio_corrected_score_project"
    corrected["active_notation_layer"] = "corrected_score"
    corrected["automatic_layer_preservation"] = {
        "events_and_quantized_notes": "unchanged_original_automatic_draft",
        "raw_audio_and_continuous_f0": "unchanged_preserved_analysis_content_and_source_file",
        "score_edit_timing": "score_ticks_only_does_not_reestimate_audio_alignment"}
    corrected["corrected_score"] = {"source_musicxml": str(musicxml), "source_musicxml_sha256": source_hashes[str(musicxml)],
        "events": mapped, "measures": inspection["measures"], "tempo_events": inspection["tempo_events"],
        "total_ticks": inspection["total_ticks"], "ppq": PPQ, "validation_scope": inspection["scope"],
        "mapping_status": "requires_review" if mapping_issues else "unique_ids_preserved", "mapping_issues": mapping_issues}
    revision = {"created_utc": datetime.now(timezone.utc).isoformat(), "operation": "explicit_musicxml_correction_import",
                "input_project": str(project_path), "input_project_sha256": source_hashes[str(project_path)],
                "musicxml": str(musicxml), "musicxml_sha256": source_hashes[str(musicxml)],
                "changes": changes, "mapping_issues": mapping_issues, "external_editor_roundtrip": "not_tested"}
    corrected.setdefault("revision_history", []).append(revision)
    save_json(output_path, corrected)
    unchanged = {path: file_sha(path) == fingerprint for path, fingerprint in source_hashes.items()}
    report = {"status": "imported_requires_identity_review" if mapping_issues else "corrected_score_imported",
              "input_project": str(project_path), "input_musicxml": str(musicxml), "output_project": str(output_path),
              "output_sha256": file_sha(output_path), "changed_fields": changes,
              "mapped_event_count": sum(event["source_mapping"]["status"] == "unique_stable_id" for event in mapped),
              "uncertain_event_count": sum(event["source_mapping"]["status"] != "unique_stable_id" for event in mapped),
              "event_count": len(mapped), "mapping_issues": mapping_issues,
              "validation": {"valid": True, "errors": [], "warnings": inspection["warnings"],
                             "measure_count": len(inspection["measures"]), "total_ticks": inspection["total_ticks"],
                             "scope": inspection["scope"]},
              "original_hashes_unchanged": unchanged, "original_pitch_frames_sha256": archive["pitch_frames_sha256"],
              "complete_analysis_preserved": archive["content"] == analysis,
              "automatic_events_unchanged": corrected["events"] == project["events"],
              "revision_count": len(corrected["revision_history"]), "external_editor_roundtrip": "not_tested",
              "limitations": ["程序化回导不是实际GUI编辑器往返", "校正层时间使用乐谱ticks，不重估原音频对齐",
                              "无ID/ID重排仅记录候选，不静默绑定原始声学音符", "限定单声部完整小节，非完整MusicXML XSD验证"]}
    if not all(unchanged.values()):
        raise RuntimeError("回导期间检测到原文件变化，需重新核查来源。")
    if report_path:
        save_json(report_path, report)
    return report


# 歌词对齐与真实制谱：新增真实副本上的一处音高和一处歌词程序化校正，明示演示而非人工校准。
def demonstration(musicxml, project_path, directory, report_path):
    directory = Path(directory).resolve()
    source_paths = [Path(musicxml).resolve(), Path(project_path).resolve()]
    # 歌词对齐与真实制谱：新增演示报告的覆盖保护，源分析与输入路径不能被指定为报告。
    analysis_path = Path(read_json(project_path)["inputs"]["notes_path"]).resolve()
    if Path(report_path).resolve() in set(source_paths + [analysis_path]):
        raise ValueError("演示报告必须另存，不能覆盖任何输入。")
    before = {str(path): file_sha(path) for path in source_paths}
    tree = ET.parse(musicxml)
    root = tree.getroot()
    eligible = [note for note in root.findall("part/measure/note") if note.find("pitch") is not None
                and note.find("grace") is None and not note.findall("tie")]
    if not eligible:
        raise ValueError("演示需要一个不带延音的普通音符。")
    target = eligible[0]
    pitch = target.find("pitch")
    old = 12 * (int(pitch.findtext("octave")) + 1) + PITCH_CLASS[pitch.findtext("step")] + int(pitch.findtext("alter", "0"))
    new = old + 1 if old < 127 else old - 1
    names = [("C", 0), ("C", 1), ("D", 0), ("D", 1), ("E", 0), ("F", 0),
             ("F", 1), ("G", 0), ("G", 1), ("A", 0), ("A", 1), ("B", 0)]
    step, alter = names[new % 12]
    pitch.clear()
    ET.SubElement(pitch, "step").text = step
    if alter:
        ET.SubElement(pitch, "alter").text = str(alter)
    ET.SubElement(pitch, "octave").text = str(new // 12 - 1)
    lyric_note = next((note for note in root.findall("part/measure/note") if note.find("lyric/text") is not None), None)
    if lyric_note is None:
        raise ValueError("真实谱尚无歌词，暂不构造虚假歌词回导证据。")
    lyric_note.find("lyric/text").text = "校"
    directory.mkdir(parents=True, exist_ok=True)
    changed_path = directory / "programmatic_correction.musicxml"
    if changed_path.resolve() in source_paths:
        raise ValueError("演示副本不得覆盖源MusicXML。")
    ET.indent(root, space="  ")
    tree.write(changed_path, encoding="utf-8", xml_declaration=True)
    report = import_correction(changed_path, project_path, directory / "corrected_project.json")
    report["demonstration"] = {"kind": "programmatic_two_field_edit_not_gui", "pitch_event_id": target.get("id"),
        "pitch_before": old, "pitch_after": new, "lyric_event_id": lyric_note.get("id"), "replacement_lyric": "校",
        "source_hashes_unchanged": {path: file_sha(path) == fingerprint for path, fingerprint in before.items()}}
    save_json(report_path, report)
    Path(report_path).with_suffix(".md").write_text(
        "# 真实谱校正版程序化回导\n\n" +
        f"状态：{report['status']}。真实MusicXML副本改一处音高和一处歌词，另存校正版项目。\n\n" +
        f"核查 {report.get('event_count', 0)} 个记谱事件；更改字段数 {len(report.get('changed_fields', []))}；" +
        f"身份不确定事件 {report.get('uncertain_event_count', 0)}。\n\n" +
        "完整原分析（含连续f0、原始分段和原始音符）、原路径/SHA、自动量化事件和修订历史均保留。" +
        "原项目、原MusicXML及分析文件没有覆盖。\n\n" +
        "实际GUI编辑器往返未测试；这只证明当前格式的程序化校正回导与结构完整性。" +
        "丢失/重排ID必须审阅匹配候选，校正时间不自动重估与原歌曲的同步。\n\n" +
        f"产物：{directory / 'corrected_project.json'}\n", encoding="utf-8")
    return report


# 歌词对齐与真实制谱：新增明确的回导与演示命令，需复核身份时返回独立状态码2。
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("import", "demonstrate"))
    parser.add_argument("--musicxml", type=Path, default=ROOT / "test_outputs/scores/latest/vocal_draft.musicxml")
    parser.add_argument("--project", type=Path, default=ROOT / "test_outputs/scores/latest/project.json")
    parser.add_argument("--output", type=Path, default=ROOT / "test_outputs/scores/correction_check/corrected_project.json")
    parser.add_argument("--report", type=Path, default=ROOT / "reports/score_correction.latest.json")
    args = parser.parse_args()
    try:
        result = demonstration(args.musicxml, args.project, args.output.parent, args.report) if args.command == "demonstrate" else import_correction(args.musicxml, args.project, args.output, args.report)
        print(json.dumps({"status": result["status"], "output": result.get("output_project"),
                          "changes": len(result.get("changed_fields", [])), "uncertain": result.get("uncertain_event_count", 0),
                          "report": str(args.report.resolve())}, ensure_ascii=False))
        return 1 if result["status"].startswith("rejected") else 2 if result.get("uncertain_event_count") else 0
    except (OSError, ValueError, KeyError, TypeError, ET.ParseError, ZeroDivisionError) as error:
        print(f"校正版回导失败：{type(error).__name__}: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
