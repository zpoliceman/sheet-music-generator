"""主旋律简化版：直接导出已完成ticks层简化的项目，不重新识别或量化。"""
# 主旋律简化版：新增CPU导出接口，复用已验证的 MusicXML/MIDI/简谱实现。
from __future__ import annotations
import argparse
import copy
import hashlib
import html
import json
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
import score_export as score

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

# 主旋律简化版：新增从实际事件核查字序、正时值和无倚音，防止只隐藏图形。
def validate_simplified(project):
    errors = []
    if not isinstance(project.get("simplification"), dict) or not project["simplification"]:
        errors.append("输入没有明确的 simplification 派生信息，拒绝把详细版当简化版。")
    events = project.get("events", [])
    notes = project.get("quantized_notes", [])
    if not events or not notes:
        errors.append("简化项目没有事件或发声音符。")
    if any(event.get("grace") for event in events):
        errors.append("简化events仍含倚音，不能仅在预览中隐藏。")
    if any(int(event.get("duration_ticks", 0)) <= 0 for event in events):
        errors.append("简化events仍含非正时值。")
    if any(int(note["end_tick"]) <= int(note["start_tick"]) or note.get("collapsed_to_grace") for note in notes):
        errors.append("发声音符仍有零时值或collapsed_to_grace标记，MIDI会重新制造倚音。")
    if any(not 1 <= int(note["pitch_midi"]) <= 127 for note in notes):
        errors.append("发声音符MIDI音高超范围。")
    ordered = sorted(notes, key=lambda note: (note["start_tick"], note["end_tick"]))
    if any(int(left["end_tick"]) > int(right["start_tick"]) for left, right in zip(ordered, ordered[1:])):
        errors.append("简化发声音符有重叠，不能作为单声部导出。")
    characters = project.get("lyrics", {}).get("characters", [])
    expected = [(int(char["index"]), str(char["text"])) for char in characters]
    if len({index for index, _ in expected}) != len(expected):
        errors.append("原歌词字符索引重复。")
    actual = []
    for event in events:
        lyric = event.get("lyric")
        if lyric and lyric.get("text") is not None:
            actual.append((int(lyric["character_index"]), str(lyric["text"])))
    if actual != expected:
        errors.append("events中的歌词索引/文字/顺序与完整原歌词不一致。")
    if len({note["id"] for note in notes}) != len(notes):
        errors.append("简化发声音符id重复。")
    return {"valid": not errors, "errors": errors, "characters": len(expected),
            "actual_lyric_labels": len(actual), "all_lyrics_same_order": actual == expected,
            "pitched_pieces": len(notes), "grace_events": sum(bool(event.get("grace")) for event in events),
            "zero_duration_pieces": sum(int(note["end_tick"]) <= int(note["start_tick"]) for note in notes)}

# 主旋律简化版：新增详细稿对照，避免简化项目自己删词或改tempo后仍被当作完整保留。
def validate_detailed_reference(project):
    summary = project["simplification"]
    original_path = summary.get("source_project")
    original_hash = summary.get("source_project_sha256")
    if not isinstance(original_path, str) or not original_hash:
        raise ValueError("simplification必须声明source_project及source_project_sha256。")
    original_path = Path(original_path).resolve()
    if score.sha256(original_path) != original_hash:
        raise ValueError("详细源project与声明SHA不一致，拒绝用变化的基线验收。")
    original = score.read_json(original_path)
    comparisons = {
        "complete_lyric_records_preserved": project.get("lyrics") == original.get("lyrics"),
        "timing_preserved": project.get("timing") == original.get("timing"),
        "tempo_events_preserved": project.get("tempo_events") == original.get("tempo_events"),
        "measure_and_total_ticks_preserved": all(project["statistics"].get(key) == original["statistics"].get(key)
                                               for key in ("measure_count", "bar_ticks", "total_ticks")),
        "key_ppq_and_octave_reference_preserved": all(project["notation"].get(key) == original["notation"].get(key)
                                                    for key in ("key", "ppq", "jianpu_reference_midi")),
        "raw_analysis_references_preserved": all(project.get("raw_analysis_preservation", {}).get(key) == value
                                                for key, value in original.get("raw_analysis_preservation", {}).items()),
        "original_inputs_preserved": all(project.get("inputs", {}).get(key) == value
                                         for key, value in original.get("inputs", {}).items()),
    }
    failed = [key for key, value in comparisons.items() if not value]
    if failed:
        raise ValueError("简化项目未保留详细稿前提：" + ", ".join(failed))
    return {"valid": True, "source_project": str(original_path), "source_project_sha256": original_hash,
            "checks": comparisons, "original_characters": len(original["lyrics"]["characters"]),
            "original_total_ticks": original["statistics"]["total_ticks"]}

# 主旋律简化版：新增独立MIDI回读，音高/起止/次数与简化发声音符逐项一致。
def validate_midi(path, project):
    import mido
    midi = mido.MidiFile(path)
    sounded = []
    active = {}
    ends = []
    for track in midi.tracks:
        tick = 0
        for message in track:
            tick += message.time
            if message.type == "note_on" and message.velocity > 0:
                key = (message.channel, message.note)
                active.setdefault(key, []).append(tick)
            elif message.type == "note_off" or (message.type == "note_on" and message.velocity == 0):
                key = (message.channel, message.note)
                if not active.get(key):
                    raise ValueError("MIDI包含没有起音的终音。")
                begin = active[key].pop(0)
                sounded.append((begin, tick, message.note))
        ends.append(tick)
    expected = sorted((int(note["start_tick"]), int(note["end_tick"]), int(note["pitch_midi"]))
                      for note in project["quantized_notes"])
    if any(active.values()):
        raise ValueError("MIDI仍有未终止音符。")
    if midi.ticks_per_beat != project["notation"]["ppq"] or sorted(sounded) != expected:
        raise ValueError("MIDI的实际发声音符与简化项目不一致。")
    total = int(project["statistics"]["total_ticks"])
    if max(ends, default=0) != total:
        raise ValueError("MIDI总时值与完整简化谱不一致。")
    return {"valid": True, "attacks": len(sounded), "exact_note_intervals_and_pitches": True,
            "total_ticks": total, "ticks_per_beat": midi.ticks_per_beat}

# 主旋律简化版：新增统一渲染导语，只替换场景中的目标提示，不改音符或绘图坐标。
def render_scene(project, first_measure=1, last_measure=None, excerpt=False):
    scene = score.render_jianpu(project, first_measure, last_measure, excerpt)
    replacement = "调性、拍号及拍位需核对；短回摆已归并。连线表示延音，歌词下划线表示一字多音。"
    count = 0
    for index, item in enumerate(scene.items):
        if item[0] == "text" and "橙色音符" in item[3]:
            changed = list(item)
            changed[3] = replacement
            scene.items[index] = tuple(changed)
            count += 1
    if count != 1:
        raise ValueError(f"简化版导语定位数量异常：{count}")
    return scene

# 主旋律简化版：新增独立导出，不进入原始秒的歌词重匹配或量化路径。
def export(args):
    started = time.perf_counter()
    source = Path(args.project).resolve()
    source_hash = score.sha256(source)
    project = score.read_json(source)
    preliminary = validate_simplified(project)
    if not preliminary["valid"]:
        raise ValueError("; ".join(preliminary["errors"]))
    # 主旋律简化版：新增原详细稿严格对照，确认237字和时间轴真正保留。
    detailed_reference = validate_detailed_reference(project)
    # 主旋律简化版：新增展示投影标题，实际原项目、tempo和音符数据不改写。
    display = copy.deepcopy(project)
    if "简化版" not in display["title"]:
        display["title"] += " · 简化版"
    xml = score.build_musicxml(display)
    semantic = score.validate_score(project, xml)
    if not semantic["valid"]:
        raise ValueError("简化谱结构不合法：" + "; ".join(semantic["errors"]))
    output = Path(args.output_dir).resolve()
    # 主旋律简化版：新增详细源目录保护；导出目标不能覆盖派生记录声明的详细稿目录。
    summary = project["simplification"]
    for key in ("source_project", "source_project_path", "input_project_path"):
        original = summary.get(key)
        if isinstance(original, dict):
            original = original.get("path")
        if isinstance(original, str) and original and output == Path(original).resolve().parent:
            raise ValueError("简化导出目录与详细源项目目录相同，请另存。")
    output.mkdir(parents=True, exist_ok=True)
    ET.indent(xml, space="  ")
    ET.ElementTree(xml).write(output / "vocal_draft.musicxml", encoding="utf-8", xml_declaration=True)
    score.write_midi(output / "vocal_draft.mid", project)
    midi_check = validate_midi(output / "vocal_draft.mid", project)
    if source != (output / "project.json").resolve():
        score.save_json(output / "project.json", project)
    # 主旋律简化版：修改，全谱使用专属简化导语，原渲染调用注释保留。
    # scene = score.render_jianpu(display)
    scene = render_scene(display)
    svg = scene.svg()
    (output / "jianpu.svg").write_text(svg, encoding="utf-8")
    first = min(event["measure"] for event in project["events"] if event["pitch_midi"] is not None)
    first, last = max(1, first - 1), min(project["statistics"]["measure_count"], max(1, first - 1) + 11)
    # 主旋律简化版：修改，节选与全谱共用简化导语，原渲染调用注释保留。
    # preview = score.render_jianpu(display, first, last, True)
    preview = render_scene(display, first, last, True)
    preview.png(output / "preview_first_vocal.png")
    (output / "preview_first_vocal.svg").write_text(preview.svg(), encoding="utf-8")
    notice = "主旋律简化草稿：压缩装饰性变化，保留主音和重要转音；" + score.lyric_notice(project) + "。"
    text = "".join(str(char["text"]) for char in project["lyrics"]["characters"])
    document = (
        '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>' +
        html.escape(display["title"]) +
        '</title><style>body{margin:24px;background:#eef2f6;font-family:"Microsoft YaHei",sans-serif;color:#14243b}'
        'main{max-width:1440px;margin:auto;background:white;padding:20px}svg{width:100%;height:auto}'
        'a{color:#205a98}p{line-height:1.8}.notice{padding:14px;background:#fff4df;border-left:4px solid #b55b12}'
        '</style></head><body><main><p class="notice">' + html.escape(notice) +
        '</p><p><a href="vocal_draft.musicxml">可编辑 MusicXML</a>　<a href="vocal_draft.mid">简化版试听 MIDI</a>　'
        '<a href="project.json">简化项目数据</a></p>' + svg +
        '<details><summary>完整歌词</summary><p>' + html.escape(text) +
        '</p></details><p>原详细版、原始音高分析和对齐依据保持独立；本页为静态预览，音乐质量仍需试听校正。</p>'
        '</main></body></html>')
    (output / "jianpu.html").write_text(document, encoding="utf-8")
    if score.sha256(source) != source_hash:
        raise ValueError("导出期间输入简化项目发生变化。")
    validation = {"valid": True, "preflight": preliminary, "musicxml": semantic,
                  "midi": midi_check, "source_project_sha256_unchanged": source_hash,
                  "external_editor_roundtrip": "not_tested"}
    # 主旋律简化版：新增详细源核对证据，随三种导出的一致性报告一起保存。
    validation["detailed_source_reference"] = detailed_reference
    score.save_json(output / "validation.json", validation)
    report = {"status": "simplified_main_melody_exported_quality_unverified", "title": display["title"],
              "input_project": str(source), "input_project_sha256": source_hash,
              "simplification": summary, "statistics": project["statistics"],
              "lyric_mapping": project["lyric_mapping"], "validation": validation,
              "timing_preserved": True, "tempo_events_preserved": len(project["tempo_events"]),
              "external_editor_roundtrip": "not_tested", "seconds": time.perf_counter() - started,
              "artifacts": {name: str(output / name) for name in
                            ("vocal_draft.musicxml", "vocal_draft.mid", "project.json", "validation.json",
                             "jianpu.svg", "jianpu.html", "preview_first_vocal.png")}}
    score.save_json(args.report, report)
    markdown = f"""# 主旋律简化版导出

状态：按派生音符导出的自动简化草稿，仍需试听核对主音、重要转音和字音关系。

- 从完整简化项目直接导出，没有重新识别、歌词匹配或节奏量化。
- {preliminary["characters"]} 字按原文和原顺序完整保留；{preliminary["pitched_pieces"]} 个实际发声事件。
- MusicXML、MIDI和预览均为相同简化音符；0个倚音、0个零时值事件。
- {project["statistics"]["measure_count"]} 小节；{project["statistics"]["total_ticks"]} ticks。
- MIDI独立回读的每个音高及起止tick与简化项目完全一致，尾部休止也保留。
- 原始tempo map与局部tempo事件沿用；原详细版与源分析不覆盖。
- 导出用时 {report["seconds"]:.3f} 秒，CPU执行，不含任何GPU推理。
- external_editor_roundtrip=not_tested。

输入：{source}。SHA-256：{source_hash}。

输出目录：{output}。完整简谱见jianpu.html/svg，可编辑文件vocal_draft.musicxml，试听vocal_draft.mid，首段preview_first_vocal.png。
"""
    Path(args.report).with_suffix(".md").write_text(markdown, encoding="utf-8")
    print(json.dumps({"status": report["status"], "characters": preliminary["characters"],
                      "pitched_pieces": preliminary["pitched_pieces"], "grace_events": 0,
                      "midi_exact": True, "report": str(Path(args.report).resolve()),
                      "preview": str(output / "preview_first_vocal.png")}, ensure_ascii=False))
    return 0

# 主旋律简化版：新增明确输入项目的CLI，不依赖全局当前指针。
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    try:
        return export(args)
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"简化版导出失败：{type(error).__name__}: {error}", file=sys.stderr)
        return 1

if __name__ == "__main__":
    raise SystemExit(main())

