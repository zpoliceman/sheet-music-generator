"""歌词对齐与真实制谱：生成带本地片段试听的人工复核报告，不替代乐谱编辑器。"""
from __future__ import annotations

# 歌词对齐与真实制谱：新增标准库只读数据与独立HTML导出，源音频不复制或修改。
import argparse
from collections import Counter
import hashlib
import html
import json
import os
from pathlib import Path
from urllib.parse import quote

# 简谱小节对齐与人工复核汇总：新增默认输出按句汇总，证据页和清单共享同源数据。
from review_summary import build_summary, write_bundle


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for data in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(data)
    return digest.hexdigest()


def relative_url(path, directory):
    return quote(os.path.relpath(Path(path).resolve(), directory).replace("\\", "/"), safe="/:")


# 歌词对齐与真实制谱：新增复核优先级和中文标记，规则分数不作为音乐准确概率。
FLAG_NAMES = {
    "low_pitch_support": "音高支持低", "possible_semitone_disagreement": "半音差异候选",
    "possible_octave_disagreement": "八度差异候选", "overlap_boundary_adjusted": "接缝边界已调整",
    "cross_segment_continuation_merged": "跨段同音续音已合并", "short_note_possible_ornament": "短音/装饰音待核对",
    "wide_pitch_motion_preserved": "连续音高运动较宽", "rest_contains_voiced_f0": "休止区有有声帧",
    "low_voicing_support": "有声帧支持低", "very_low_audio_energy": "人声音量低",
    "insufficient_f0_frames": "音高帧不足",
}
PRIORITY = {"possible_octave_disagreement": 5, "possible_semitone_disagreement": 4,
            "low_pitch_support": 3, "rest_contains_voiced_f0": 3,
            "overlap_boundary_adjusted": 2, "cross_segment_continuation_merged": 2,
            "short_note_possible_ornament": 2, "low_voicing_support": 2,
            "very_low_audio_energy": 2, "insufficient_f0_frames": 2}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--analysis", type=Path, required=True)
    parser.add_argument("--lyrics", type=Path, required=True)
    parser.add_argument("--score-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    # 简谱小节对齐与人工复核汇总：新增独立评估说明参数，仅用于展示，不传入生成算法。
    parser.add_argument("--findings", type=Path)
    args = parser.parse_args()
    analysis = read_json(args.analysis)
    lyrics = read_json(args.lyrics)
    audio_path = Path(analysis["source"]["path"]).resolve()
    if not audio_path.is_file():
        raise ValueError("复核报告缺少对应本地人声音频")
    actual_hash = file_sha256(audio_path)
    analysis_hash = analysis["source"].get("sha256")
    lyric_hash = lyrics.get("source", {}).get("sha256")
    if not analysis_hash or actual_hash != analysis_hash or lyric_hash != analysis_hash:
        raise ValueError("人声/派生音符/逐字对齐SHA不一致，不允许混用不同运行")
    offset = float(analysis["source"].get("offset_seconds", 0))
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    escape = lambda value: html.escape(str(value), quote=True)
    characters = lyrics.get("characters", [])
    notes = analysis["notes"]
    flagged = [n for n in notes if any(flag in PRIORITY for flag in n.get("review_flags", []))]
    flagged.sort(key=lambda n: (-max(PRIORITY.get(f, 0) for f in n.get("review_flags", [])), n["start_seconds"]))
    rows = []
    for note in flagged:
        start, end = float(note["start_seconds"]), float(note["end_seconds"])
        nearby = [c for c in characters if c.get("start_seconds") is not None and c.get("end_seconds") is not None
                  and float(c["end_seconds"]) > start and float(c["start_seconds"]) < end]
        # 中文版本冻结与英文融合验证：注释保留被替换的原实现。
        # text = "".join(c.get("text", "") for c in nearby) or "（未确定）"
        # 中文版本冻结与英文融合验证：新增中英文兼容实现。
        from lyrics_tokens import readable_lyric_units
        text = readable_lyric_units(nearby) or "（未确定）"
        flags = "、".join(FLAG_NAMES.get(f, f) for f in note.get("review_flags", []))
        playback_start, playback_end = max(0, start - offset - 1), end - offset + 1
        pitch = "休止" if note.get("is_rest") else f'MIDI {note["pitch_midi"]}'
        rows.append(f'<tr><td>{escape(note.get("id", ""))}</td><td>{start:.3f}–{end:.3f}</td><td>{escape(pitch)}</td>'
                    f'<td>{escape(text)}</td><td>{escape(flags)}</td><td><button onclick="playRange({playback_start:.6f},{playback_end:.6f})">试听人声</button></td></tr>')
    lyric_warnings = []
    for c in characters:
        flags = c.get("warnings", [])
        if flags or c.get("start_seconds") is None or c.get("end_seconds") is None:
            lyric_warnings.append(f'<li>字序{escape(c.get("index", "?"))}「{escape(c.get("text", ""))}」：{escape("；".join(map(str, flags)) or "未得到可靠时间")}</li>')
    warnings = list(dict.fromkeys(analysis.get("warnings", []) + lyrics.get("warnings", [])))
    warning_html = "".join(f'<li>{escape(w)}</li>' for w in warnings)
    score_url = relative_url(args.score_dir / "jianpu.html", output.parent)
    xml_url = relative_url(args.score_dir / "vocal_draft.musicxml", output.parent)
    wav_url = relative_url(audio_path, output.parent)
    flag_counts = Counter(f for n in notes for f in n.get("review_flags", []))
    summary = {"task": "歌词对齐与真实制谱", "kind": "local_manual_review_report", "source_sha256": actual_hash,
               "analysis_sha256": file_sha256(args.analysis), "lyrics_sha256": file_sha256(args.lyrics),
               "note_count": len(notes), "review_row_count": len(rows), "character_warning_count": len(lyric_warnings),
               "review_flag_counts": dict(flag_counts), "musical_accuracy_verified": False,
               "external_editor_roundtrip": "not_tested", "output": str(output)}
    # 歌词对齐与真实制谱：新增用户操作后才播放的本地音频区间，所有动态文本HTML转义。
    document = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>真实乐谱草稿复核</title><style>body{font:16px/1.6 "Microsoft YaHei",sans-serif;margin:24px;background:#faf9f6;color:#263238}
a{color:#185d8c}table{border-collapse:collapse;width:100%;background:white}td,th{border:1px solid #ddd;padding:8px;text-align:left}
th{background:#eef2f5}td:first-child{font:11px monospace}button{padding:6px 10px;white-space:nowrap;cursor:pointer}.notice{background:#fff0cf;padding:14px}
audio{width:min(680px,100%)}details{margin:16px 0}</style><h1>人声旋律与歌词复核</h1>
<div class="notice">这是自动草稿的复核报告。歌词尚未人工校正，音高标记是证据候选，不能换算为准确率。请先试听对应人声，再在MusicXML编辑器改谱或提供正确歌词重新对齐。</div>
<p>对齐状态：ALIGNMENT；歌词来源：REFERENCE。人声、音符和歌词源SHA已核对一致。</p>
<p><a href="SCORE">查看简谱草稿</a> · <a href="XML">MusicXML文件</a></p>
<audio id="player" controls preload="none" src="AUDIO"></audio><p id="status">点击下面的试听按钮播放音符前后各约一秒。全部音频保留在本机。</p>
<details><summary>数据来源与全局警告</summary><p>人声SHA256：HASH</p><ul>WARNINGS</ul></details>
<details><summary>逐字时间警告（LYRICCOUNT项）</summary><ul>LYRICWARNINGS</ul></details>
<h2>优先复核候选（ROWCOUNT项）</h2><p>按八度/半音差异、音高支持、接缝和短音排序；完整候选与连续音高保留在项目数据中。歌词列只显示原时间区间有重叠的候选字符，不等同最终字音归属。</p>
<table><thead><tr><th>音符标识</th><th>整首时间（秒）</th><th>音高</th><th>附近歌词候选</th><th>证据标记</th><th>试听</th></tr></thead><tbody>ROWS</tbody></table>
<script>// 歌词对齐与真实制谱：新增只读试听交互，不自动播放、不上传音频。
const player=document.getElementById('player'),status=document.getElementById('status');let stopAt=null;
async function playRange(start,end){stopAt=end;try{player.currentTime=start;await player.play();status.textContent='正在试听 '+start.toFixed(2)+'–'+end.toFixed(2)+' 秒';}catch(e){status.textContent='无法播放本地音频：'+e.message;}}
player.addEventListener('timeupdate',()=>{if(stopAt!==null&&player.currentTime>=stopAt){player.pause();stopAt=null;}});
</script></html>'''
    # 歌词对齐与真实制谱：新增用户提供歌词的准确来源文案，字音时间仍保留待核查状态。
    if lyrics.get("reference_kind") == "user_supplied":
        document = document.replace("歌词尚未人工校正", "歌词由用户提供，字音时间尚待核查")
    replacements = {"ALIGNMENT": escape(lyrics.get("alignment_status", "unknown")), "REFERENCE": escape(lyrics.get("reference_kind", "unknown")),
                    "SCORE": escape(score_url), "XML": escape(xml_url), "AUDIO": escape(wav_url), "HASH": actual_hash,
                    "WARNINGS": warning_html, "LYRICCOUNT": str(len(lyric_warnings)), "LYRICWARNINGS": "".join(lyric_warnings),
                    "ROWCOUNT": str(len(rows)), "ROWS": "".join(rows)}
    # 歌词对齐与真实制谱：新增单次模板替换，避免插入文本再次被占位词误替换。
    import re
# 歌词对齐与真实制谱：修改模板匹配边界，避免XML占位符误替换MusicXML正文；原行注释保留。
#     document = re.sub("|".join(sorted(map(re.escape, replacements), key=len, reverse=True)), lambda match: replacements[match[0]], document)
    document = re.sub(r"(?<![A-Za-z])(?:" + "|".join(sorted(map(re.escape, replacements), key=len, reverse=True)) + r")(?![A-Za-z])", lambda match: replacements[match[0]], document)
    # 自动音乐解码改造：新增音乐层的疑难候选和逐片试听，原声学证据表仍完整保留。
    project_path = args.score_dir / "project.json"
    if project_path.is_file():
        project = read_json(project_path)
        if project.get("decoder"):
            if project["inputs"]["notes_sha256"] != file_sha256(args.analysis) or project["inputs"]["lyrics_sha256"] != file_sha256(args.lyrics):
                raise ValueError("音乐解码项目与复核声学/歌词输入不一致。")
            candidates = project.get("review_candidates", []) + project.get("alignment_issues", [])
            # 字音归属修复：新增先看挂词候选的排序，原音高候选也继续保留。
            candidates.sort(key=lambda item:(0 if str(item.get("type","")).startswith("word_ownership") else 1,
                                             item.get("start_seconds",item.get("candidate",{}).get("start_seconds",0))))
            character_lookup = {c["index"]:c for c in characters}
            pieces = {n["id"]: n for n in project["quantized_notes"]}
            cards = []
            for item in candidates:
                evidence = item.get("candidate", item)
                if item.get("piece_id") in pieces:
                    evidence = pieces[item["piece_id"]]
                start = evidence.get("start_seconds")
                end = evidence.get("end_seconds")
                button = ""
                if start is not None and end is not None:
                    button = f'<button onclick="playRange({max(0, start-offset-1):.6f},{end-offset+1:.6f})">试听该段</button>'
                # 字音归属修复：修改候选名称，原标签行注释保留。
                # labels = {"local_pitch_recheck": "局部音高已复核，仍需确认音乐作用", "detail_merged_to_neighbor": "疑难细节已归并，原候选保留", "soft_alignment_uncertain": "字音归属仍不确定"}
                labels = {"local_pitch_recheck": "局部音高已复核，仍需确认音乐作用", "detail_merged_to_neighbor": "疑难细节已归并，原候选保留", "soft_alignment_uncertain": "字音归属仍不确定",
                          "word_ownership_uncertain":"相邻字的归属仍不确定", "word_ownership_boundary_sensitive":"挂词对发音边界敏感，请试听确认"}
                label = labels.get(item.get("type"), "音乐解码候选待复核")
                # 字音归属修复：新增直接可读的歌词上下文和候选字，用户无需读内部JSON判断挂词。
                current = character_lookup.get(item.get("character_index"))
                if str(item.get("type","")).startswith("word_ownership") and current:
                    # 中文版本冻结与英文融合验证：注释保留被替换的原实现。
                    # line_text = "".join(c["text"] for c in characters if c.get("line_index")==current.get("line_index"))
                    # 中文版本冻结与英文融合验证：新增中英文兼容实现。
                    from lyrics_tokens import readable_lyric_units
                    line_text = readable_lyric_units(c for c in characters if c.get("line_index")==current.get("line_index"))
                # 简谱小节对齐与人工复核汇总：修改候选集合，原实现注释保留，边界敏感候选也完整显示。
                # alternative_ids = {a.get("character_index") for a in item.get("alternatives",[])
                #                    if a.get("path_extra_cost",0)<=.35 and a.get("character_index")!=current["index"]}
                    alternative_ids = {a.get("character_index") for a in item.get("alternatives",[])+item.get("sensitivity_alternatives",[])
                                       if a.get("path_extra_cost",0)<=.35 and a.get("character_index")!=current["index"]}
                    alternatives = "、".join(character_lookup[idx]["text"] for idx in sorted(i for i in alternative_ids if i in character_lookup))
                    label += "：当前挂在「" + current["text"] + "」，所在句「" + line_text + "」"
                    if alternatives:
                        label += "；另一个可能的字：" + alternatives
                cards.append('<li>' + escape(label) + ' ' + button + '<details><summary>候选证据</summary><pre style="white-space:pre-wrap">' + escape(json.dumps(item, ensure_ascii=False, indent=2)) + '</pre></details></li>')
            section = '<h2>音乐解码复核层</h2><p>候选与主谱分开；同音延音、转音连奏和倚音时间分配分别保存。</p><ol>' + ''.join(cards) + '</ol>'
            document = document.replace('<script>', section + '<script>', 1)
            summary["decoder_review_candidates"] = len(candidates)
            summary["decoder_version"] = project["decoder"]["version"]
            # 简谱小节对齐与人工复核汇总：新增默认清单HTML/文本/JSON和入口，未来生成也自动使用。
            manual = build_summary(project, lyrics, analysis)
            findings = read_json(args.findings) if args.findings else []
            if not isinstance(findings, list):
                raise ValueError("人工评估说明必须是独立条目列表")
            write_bundle(manual, output.parent, wav_url, score_url, output.name, offset, findings)
            summary["manual_review"] = {"output": str(output.parent/"manual_review.html"),
                "ownership_unique_segments": manual["ownership_unique_segments"],
                "ownership_prompt_count": manual["ownership_prompt_count"],
                "ownership_line_count": manual["ownership_line_count"],
                "pitch_candidate_count": manual["pitch_candidate_count"],
                "detail_candidate_count": manual["detail_candidate_count"]}
            manual_url = relative_url(output.parent/"manual_review.html", output.parent)
            document = document.replace('<h2>优先复核候选', '<p><a href="'+escape(manual_url)+'">先看按句汇总的人工复核清单</a></p><h2>优先复核候选', 1)
    output.write_text(document, encoding="utf-8")
    output.with_suffix(".json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
