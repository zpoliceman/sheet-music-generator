"""人工 MusicXML 兼容性样例；不是音频推理或自动转谱效果。"""
# 兼容性与样曲验证：新增标准库依赖，避免为交换样例安装模型环境。
from __future__ import annotations
import argparse
import copy
import hashlib
import json
import sys
import xml.etree.ElementTree as ET
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "test_outputs" / "notation"
TYPES = {"whole": Fraction(4), "half": Fraction(2), "quarter": Fraction(1),
         "eighth": Fraction(1, 2), "16th": Fraction(1, 4), "32nd": Fraction(1, 8)}

# 兼容性与样曲验证：新增 UTF-8 标准输出，确保 Windows 自动化读取中文 JSON。
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

# 兼容性与样曲验证：新增 JSON 与 XML 小工具，所有生成结果另存。
def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

def element(parent: ET.Element, tag: str, text: object | None = None, **attrs: str) -> ET.Element:
    node = ET.SubElement(parent, tag, attrs)
    if text is not None:
        node.text = str(text)
    return node

def event(pitch: str | None, duration: int, kind: str, text: str | None = None, **extra: object) -> dict:
    return {"pitch": pitch, "duration": duration, "type": kind, "text": text, **extra}

# 兼容性与样曲验证：新增四小节自拟样例；风是一字多音，山跨小节延音。
def make_fixture() -> ET.Element:
    measures = [
        [event("C4", 480, "quarter", "春"),
         event("D4", 360, "eighth", "风", dots=1, extend="start", slur="start"),
         event("E4", 120, "16th", extend="stop", slur="stop"),
         event(None, 480, "quarter"), event("G4", 480, "quarter", "轻")],
        [event("F4", 0, "eighth", grace=True),
         event("G4", 480, "quarter", "拂"), event("A4", 960, "half", "过"),
         event("A4", 480, "quarter", "山", tie="start", extend="start")],
        [event("A4", 480, "quarter", tie="stop", extend="stop"),
         event("G4", 480, "quarter", "岗"),
         event("E4", 160, "eighth", "云", triplet=True, tuplet="start"),
         event("F4", 160, "eighth", "在", triplet=True),
         event("G4", 160, "eighth", "远", triplet=True, tuplet="stop"),
         event("E4", 480, "quarter", "方")],
        [event("D4", 480, "quarter", "等", slur="start"),
         event("E4", 240, "eighth", "你"), event("F4", 240, "eighth", "回"),
         event("D4", 960, "half", "望", slur="stop")],
    ]
    root = ET.Element("score-partwise", version="4.0")
    element(element(root, "work"), "work-title", "春风样例（人工兼容性测试，非音频转谱）")
    identification = element(root, "identification")
    element(identification, "creator", "项目自拟测试旋律与歌词", type="composer")
    misc = element(identification, "miscellaneous")
    element(misc, "miscellaneous-field", "synthetic_compatibility_fixture", name="artifact-kind")
    part_list = element(root, "part-list")
    part_info = element(part_list, "score-part", id="P1")
    element(part_info, "part-name", "人声")
    part = element(root, "part", id="P1")
    for bar_number, notes in enumerate(measures, 1):
        measure = element(part, "measure", number=str(bar_number))
        if bar_number == 1:
            attributes = element(measure, "attributes")
            element(attributes, "divisions", 480)
            key = element(attributes, "key")
            element(key, "fifths", 0)
            element(key, "mode", "major")
            time = element(attributes, "time")
            element(time, "beats", 4)
            element(time, "beat-type", 4)
            clef = element(attributes, "clef")
            element(clef, "sign", "G")
            element(clef, "line", 2)
            direction = element(measure, "direction", placement="above")
            element(element(direction, "direction-type"), "words",
                    "人工样例：请检查中文歌词、附点、延音、装饰音和三连音")
            element(direction, "sound", tempo="80")
        for note_number, spec in enumerate(notes, 1):
            note = element(measure, "note", id=f"m{bar_number}n{note_number}")
            if spec.get("grace"):
                element(note, "grace", slash="yes")
            if spec["pitch"] is None:
                element(note, "rest")
            else:
                pitch = element(note, "pitch")
                element(pitch, "step", spec["pitch"][0])
                element(pitch, "octave", spec["pitch"][1:])
            if not spec.get("grace"):
                element(note, "duration", spec["duration"])
            if spec.get("tie"):
                element(note, "tie", type=str(spec["tie"]))
            element(note, "voice", 1)
            element(note, "type", spec["type"])
            for _ in range(spec.get("dots", 0)):
                element(note, "dot")
            if spec.get("triplet"):
                modification = element(note, "time-modification")
                element(modification, "actual-notes", 3)
                element(modification, "normal-notes", 2)
                element(modification, "normal-type", "eighth")
            if spec.get("tie") or spec.get("slur") or spec.get("tuplet"):
                notations = element(note, "notations")
                if spec.get("tie"):
                    element(notations, "tied", type=str(spec["tie"]))
                if spec.get("slur"):
                    element(notations, "slur", type=str(spec["slur"]), number="1")
                if spec.get("tuplet"):
                    element(notations, "tuplet", type=str(spec["tuplet"]), number="1")
            if spec["text"] is not None or spec.get("extend"):
                lyric = element(note, "lyric", number="1")
                if spec["text"] is not None:
                    element(lyric, "syllabic", "single")
                    element(lyric, "text", spec["text"])
                if spec.get("extend"):
                    element(lyric, "extend", type=str(spec["extend"]))
        if bar_number == len(measures):
            element(element(measure, "barline", location="right"), "bar-style", "light-heavy")
    return root

# 兼容性与样曲验证：新增限定范围的语义检查；拒绝多声部，避免误读为单旋律。
def inspect_xml(root: ET.Element) -> dict:
    root = copy.deepcopy(root)
    for node in root.iter():
        node.tag = node.tag.rsplit("}", 1)[-1]
    errors: list[str] = []
    warnings: list[str] = []
    score: dict = {"measures": [], "lyrics": []}
    if root.tag != "score-partwise":
        return {"valid": False, "errors": ["仅支持 score-partwise。"], "warnings": [], "score": score}
    parts = root.findall("part")
    if len(parts) != 1:
        return {"valid": False, "errors": ["本次检查仅支持一个人声声部。"], "warnings": [], "score": score}
    divisions = None
    beats = 4
    beat_type = 4
    fifths = 0
    mode = "major"
    absolute = Fraction(0)
    open_tie = None
    open_slurs: dict[str, str] = {}
    open_tuplets: dict[str, str] = {}
    melisma: dict[str, dict] = {}
    voices: set[str] = set()
    note_ids: set[str] = set()
    measures = parts[0].findall("measure")
    if not measures:
        errors.append("乐谱没有小节。")
    for bar_index, measure in enumerate(measures, 1):
        cursor = Fraction(0)
        events = []
        location = f"第{bar_index}小节"
        attributes = measure.find("attributes")
        if attributes is not None:
            if attributes.find("divisions") is not None:
                divisions = Fraction(attributes.findtext("divisions"))
            if attributes.find("time") is not None:
                beats = int(attributes.findtext("time/beats"))
                beat_type = int(attributes.findtext("time/beat-type"))
            if attributes.find("key/fifths") is not None:
                fifths = int(attributes.findtext("key/fifths"))
                mode = attributes.findtext("key/mode", "major")
            if attributes.find("transpose") is not None or int(attributes.findtext("staves", "1")) != 1:
                errors.append(f"{location}：移调乐器或多谱表不在此次检查范围。")
        if not divisions or divisions <= 0 or beats <= 0 or beat_type <= 0:
            errors.append(f"{location}：divisions 或拍号非法。")
            break
        expected = Fraction(beats * 4, beat_type)
        if measure.findall("backup") or measure.findall("forward"):
            errors.append(f"{location}：含 backup/forward，需更完整的声部解析器。")
        for note_index, note in enumerate(measure.findall("note"), 1):
            ref = f"m{bar_index}n{note_index}"
            source_id = note.get("id")
            if source_id:
                if source_id in note_ids:
                    errors.append(f"{ref}：XML id 重复。")
                note_ids.add(source_id)
            voice = note.findtext("voice", "1")
            voices.add(voice)
            if note.find("chord") is not None or note.find("unpitched") is not None:
                errors.append(f"{ref}：和弦或无固定音高不在此次检查范围。")
            rest = note.find("rest") is not None
            grace = note.find("grace") is not None
            pitch_node = note.find("pitch")
            pitch = None
            if pitch_node is not None:
                step = pitch_node.findtext("step")
                octave = int(pitch_node.findtext("octave"))
                if step not in "CDEFGAB" or not 0 <= octave <= 9:
                    errors.append(f"{ref}：音高无效。")
                pitch = {"step": step, "alter": str(Fraction(pitch_node.findtext("alter", "0"))),
                         "octave": octave}
            if (pitch is None) == (not rest):
                errors.append(f"{ref}：必须且只能有 pitch 或 rest。")
            duration_text = note.findtext("duration")
            duration = Fraction(duration_text) / divisions if duration_text is not None else Fraction(0)
            if grace and duration_text is not None:
                errors.append(f"{ref}：装饰音不能占用 duration。")
            if not grace and duration <= 0:
                errors.append(f"{ref}：普通音符或休止必须有正时值。")
            kind = note.findtext("type")
            dots = len(note.findall("dot"))
            tuple_ratio = None
            modification = note.find("time-modification")
            if modification is not None:
                actual = int(modification.findtext("actual-notes"))
                normal = int(modification.findtext("normal-notes"))
                if actual <= 0 or normal <= 0:
                    errors.append(f"{ref}：连音比率必须大于零。")
                else:
                    tuple_ratio = [actual, normal]
            if not grace and kind in TYPES:
                written = TYPES[kind] * sum((Fraction(1, 2**i) for i in range(dots + 1)), Fraction(0))
                if tuple_ratio:
                    written *= Fraction(tuple_ratio[1], tuple_ratio[0])
                if written != duration:
                    errors.append(f"{ref}：记谱时值 {written} 与 duration {duration} 不符。")
            elif kind not in TYPES:
                warnings.append(f"{ref}：未核验音符类型 {kind!r} 的记谱时值。")
            ties = sorted(tie.get("type") for tie in note.findall("tie"))
            tied = sorted(tie.get("type") for tie in note.findall("notations/tied"))
            if ties != tied:
                errors.append(f"{ref}：发声 tie 与显示 tied 不一致。")
            if "stop" in ties:
                if open_tie != (pitch, absolute + cursor):
                    errors.append(f"{ref}：延音终点音高或相邻时刻不匹配。")
                open_tie = None
            elif open_tie is not None and not grace:
                errors.append(f"{ref}：延音起点后未接终点。")
                open_tie = None
            if "start" in ties:
                if rest or grace:
                    errors.append(f"{ref}：该延音起点不是普通有音高音符。")
                open_tie = (pitch, absolute + cursor + duration)
            slurs = []
            tuplets = []
            for notation_name, active, output in (("slur", open_slurs, slurs), ("tuplet", open_tuplets, tuplets)):
                for mark in note.findall(f"notations/{notation_name}"):
                    mark_type = mark.get("type")
                    number = mark.get("number", "1")
                    output.append(mark_type)
                    if mark_type == "start":
                        if number in active:
                            errors.append(f"{ref}：{notation_name} 重复起点。")
                        active[number] = ref
                    elif mark_type == "stop":
                        if number not in active:
                            errors.append(f"{ref}：{notation_name} 终点缺少起点。")
                        active.pop(number, None)
            lyric_items = []
            for lyric in note.findall("lyric"):
                verse = lyric.get("number", "1")
                text = "".join(item.text or "" for item in lyric.findall("text"))
                extension = lyric.find("extend")
                extend_type = extension.get("type", "start") if extension is not None else None
                if rest or grace:
                    errors.append(f"{ref}：样例约定休止或装饰音不承载歌词。")
                lyric_items.append({"verse": verse, "text": text, "extend": extend_type,
                                    "syllabic": lyric.findtext("syllabic")})
                if text:
                    if verse in melisma:
                        errors.append(f"{ref}：前一个一字多音尚未闭合就遇到新歌词。")
                    alignment = {"text": text, "verse": verse, "note_refs": [ref]}
                    score["lyrics"].append(alignment)
                    if extend_type == "start":
                        melisma[verse] = alignment
                elif extend_type in ("continue", "stop"):
                    if verse not in melisma:
                        errors.append(f"{ref}：歌词延长终点缺少对应文字起点。")
                    else:
                        melisma[verse]["note_refs"].append(ref)
                elif extend_type == "start":
                    errors.append(f"{ref}：歌词延长起点没有文字。")
                if extend_type == "stop":
                    melisma.pop(verse, None)
            events.append({"ref": ref, "onset_quarters": str(cursor),
                           "duration_quarters": str(duration), "pitch": pitch, "rest": rest,
                           "grace": grace, "type": kind, "dots": dots, "tuplet_ratio": tuple_ratio,
                           "ties": ties, "slurs": sorted(slurs), "tuplets": sorted(tuplets),
                           "lyrics": lyric_items})
            if not grace:
                cursor += duration
        if cursor != expected:
            errors.append(f"{location}：总时值 {cursor} 拍，拍号要求 {expected} 拍。")
        score["measures"].append({"index": bar_index, "time": [beats, beat_type],
                                  "key": [fifths, mode], "duration_quarters": str(cursor),
                                  "events": events})
        absolute += cursor
    if len(voices) > 1:
        errors.append("发现多个 voice，拒绝按单旋律回导。")
    if open_tie is not None or open_slurs or open_tuplets or melisma:
        errors.append("延音、连线、连音组或歌词延长存在未闭合起点。")
    score["total_quarters"] = str(absolute)
    return {"valid": not errors, "errors": errors, "warnings": warnings, "score": score}

# 兼容性与样曲验证：新增语义差异比较，忽略排版、XML id 和 divisions 缩放。
def differences(before: object, after: object, path: str = "score") -> list[dict]:
    if isinstance(before, dict) and isinstance(after, dict):
        changes = []
        for key in sorted(before.keys() | after.keys()):
            changes.extend(differences(before.get(key), after.get(key), f"{path}.{key}"))
        return changes
    if isinstance(before, list) and isinstance(after, list):
        if len(before) != len(after):
            return [{"path": path, "before": before, "after": after}]
        changes = []
        for index, (left, right) in enumerate(zip(before, after)):
            changes.extend(differences(left, right, f"{path}[{index}]"))
        return changes
    return [] if before == after else [{"path": path, "before": before, "after": after}]

# 兼容性与样曲验证：新增负例核查，检出超拍、丢字、损坏延音与误占时值的装饰音。
def run_self_check(root: ET.Element, reference: dict) -> dict:
    cases = {}
    bad = copy.deepcopy(root)
    bad.find("part/measure/note/duration").text = "481"
    cases["reject_overfull_measure"] = not inspect_xml(bad)["valid"]
    bad = copy.deepcopy(root)
    bad.find("part/measure/note/lyric/text").text = "错"
    inspected = inspect_xml(bad)
    cases["detect_changed_lyric"] = inspected["valid"] and bool(differences(reference, inspected["score"]))
    bad = copy.deepcopy(root)
    tied_stop = bad.findall("part/measure")[2].find("note/pitch/step")
    tied_stop.text = "B"
    cases["reject_broken_cross_bar_tie"] = not inspect_xml(bad)["valid"]
    bad = copy.deepcopy(root)
    grace_note = bad.findall("part/measure")[1].find("note")
    element(grace_note, "duration", 1)
    cases["reject_grace_duration"] = not inspect_xml(bad)["valid"]
    # 兼容性与样曲验证：新增合法 divisions 缩放核查，避免编辑器重采样引起误报。
    scaled = copy.deepcopy(root)
    for node in scaled.findall(".//divisions") + scaled.findall(".//duration"):
        node.text = str(int(node.text) * 2)
    scaled_result = inspect_xml(scaled)
    cases["accept_equivalent_divisions_scale"] = scaled_result["valid"] and not differences(reference, scaled_result["score"])
    return {"passed": all(cases.values()), "cases": cases}

# 兼容性与样曲验证：新增生成入口，同时保存原始项目数据和语义基线。
def generate(directory: Path) -> int:
    directory.mkdir(parents=True, exist_ok=True)
    root = make_fixture()
    inspected = inspect_xml(root)
    if not inspected["valid"]:
        raise ValueError("; ".join(inspected["errors"]))
    ET.indent(root, space="  ")
    xml_path = directory / "synthetic_vocal.musicxml"
    ET.ElementTree(root).write(xml_path, encoding="utf-8", xml_declaration=True)
    project = {"schema_version": 1, "artifact_kind": "synthetic_compatibility_fixture",
               "audio_source": None, "audio_inference_performed": False,
               "description": "四小节人工自拟样例，不是音频识别结果，也不是简谱编辑器渲染截图。",
               "analysis": {"continuous_f0": None, "original_audio_timestamps": None},
               "score": inspected["score"], "correction_history": []}
    write_json(directory / "synthetic_vocal.project.json", project)
    summary = {"artifact_kind": project["artifact_kind"], "xml_structure_check": inspected,
               "negative_and_normalization_checks": run_self_check(root, inspected["score"]),
               "external_editor_roundtrip": "not_tested"}
    write_json(directory / "fixture_validation.json", summary)
    print(json.dumps({"generated": str(xml_path), "valid": inspected["valid"],
                      "self_checks": summary["negative_and_normalization_checks"]}, ensure_ascii=False))
    return 0 if summary["negative_and_normalization_checks"]["passed"] else 1

# 兼容性与样曲验证：新增校正版回导；参考数据不覆盖，音频分析保持独立。
def check(args: argparse.Namespace) -> int:
    root = ET.parse(args.musicxml).getroot()
    inspected = inspect_xml(root)
    reference = json.loads(args.reference.read_text(encoding="utf-8"))
    delta = differences(reference["score"], inspected["score"])
    report = {"source_musicxml": str(args.musicxml.resolve()), "valid": inspected["valid"],
              "errors": inspected["errors"], "warnings": inspected["warnings"],
              "matches_reference": not delta, "differences": delta,
              "scope": "单声部、无和弦、完整小节；不是完整 MusicXML XSD 验证，也不证明简谱显示正确。"}
    if args.report:
        write_json(args.report, report)
    if args.import_project:
        if not inspected["valid"]:
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 1
        if args.import_project.resolve() == args.reference.resolve():
            raise ValueError("回导输出必须另存，不能覆盖参考项目。")
        corrected = copy.deepcopy(reference)
        corrected["score"] = inspected["score"]
        corrected["correction_history"].append({
            "source_musicxml": str(args.musicxml.resolve()),
            "sha256": hashlib.sha256(args.musicxml.read_bytes()).hexdigest(),
            "differences": delta, "import_kind": "explicit_musicxml_correction"})
        write_json(args.import_project, corrected)
        report["imported_project"] = str(args.import_project.resolve())
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if inspected["valid"] and (not args.require_match or not delta) else 1

# 兼容性与样曲验证：新增命令行参数和失败退出码，方便后续重复执行。
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    gen = commands.add_parser("generate", help="生成四小节人工样例及检查结果")
    gen.add_argument("--output-dir", type=Path, default=OUT)
    chk = commands.add_parser("check", help="核查外部 MusicXML 并显示语义差异")
    chk.add_argument("musicxml", type=Path)
    chk.add_argument("--reference", type=Path, default=OUT / "synthetic_vocal.project.json")
    chk.add_argument("--report", type=Path)
    chk.add_argument("--require-match", action="store_true", help="用于未修改的编辑器往返")
    chk.add_argument("--import-project", type=Path, help="将结构有效的校正版另存为项目 JSON")
    args = parser.parse_args()
    try:
        return generate(args.output_dir) if args.command == "generate" else check(args)
    except (OSError, ValueError, TypeError, ET.ParseError, ZeroDivisionError) as exc:
        print(f"检查失败：{exc}", file=sys.stderr)
        return 1

if __name__ == "__main__":
    raise SystemExit(main())

