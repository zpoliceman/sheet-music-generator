"""简谱小节对齐与人工复核汇总：按实际歌词和音段整理可试听清单，不把候选当作错误真值。"""
from __future__ import annotations

# 简谱小节对齐与人工复核汇总：新增独立展示层，不参与音高、挂词或节奏推理。
from collections import Counter, defaultdict
import html
import json
from pathlib import Path
import score_export as score
# 小节划分与拍速层级纠错：新增谱头与复核页共用的实际四分拍速度。
from metrical_timing import selected_quarter_tempo


def time_text(seconds):
    # 简谱小节对齐与人工复核汇总：新增可读的分秒时间，正确处理小数进位。
    centiseconds = max(0, round(float(seconds) * 100))
    minutes, remainder = divmod(centiseconds, 6000)
    return f"{minutes}:{remainder//100:02d}.{remainder%100:02d}"


# 第四首《日落大道》男声跨歌曲验证：修改复核音名支持原声时间对应调号，旧签名保留。
# def pitch_text(project, midi, source=False):
def pitch_text(project, midi, source=False,seconds=None):
    # 简谱小节对齐与人工复核汇总：新增目标调简谱音名，源候选按项目实际移调换算。
    if midi is None:
        return "休止"
    if source:
        midi += project["notation"].get("transpose_semitones", 0)
    # 第四首《日落大道》男声跨歌曲验证：修改复核文字与谱面同步按段取调，旧全曲同调换算保留。
    # degree, octave, accidental = score.jianpu_pitch(midi, project['notation']['key'], project['notation']['jianpu_reference_midi'])
    degree, octave, accidental = score.jianpu_pitch(midi,*score.notation_at(project,seconds=seconds))
    prefix = {"♭": "降", "♯": "升", "#": "升"}.get(accidental, accidental)
    register = "低" if octave == -1 else "高" if octave == 1 else f"{abs(octave)}个低八度" if octave < -1 else f"{octave}个高八度" if octave > 1 else ""
    return register + prefix + degree


def note_text(project, notes):
    # 简谱小节对齐与人工复核汇总：新增按原声顺序展示最终记谱音与倚音区别。
    return "→".join(pitch_text(project, n.get("pitch_midi"),seconds=n["start_seconds"]) + ("（倚）" if n.get("grace") else "")
                    for n in sorted(notes, key=lambda n: (n["start_seconds"], n["end_seconds"]))) or "待定位"


def measure_text(measures):
    return "、".join(map(str, measures)) if measures else "待定位"


def locate(project, start, end):
    # 简谱小节对齐与人工复核汇总：新增原声秒区间到小节的交叠定位，支持已归并声段。
    notes = [n for n in project["quantized_notes"]
             if min(n["end_seconds"], end) > max(n["start_seconds"], start) + 1e-6]
    piece_ids = {n["id"] for n in notes}
    measures = sorted({e["measure"] for e in project["events"] if e.get("piece_id") in piece_ids})
    return notes, measures


def build_summary(project, lyrics, analysis):
    # 简谱小节对齐与人工复核汇总：新增按实际歌词分句，重复句与同句重复字明确标注遍次。
    characters = {c["index"]: c for c in project["lyrics"]["characters"]}
    lines = defaultdict(list)
    for character in characters.values():
        lines[character["line_index"]].append(character)
    # 中文版本冻结与英文融合验证：注释保留被替换的原实现。
    # line_texts = {index: "".join(c["text"] for c in chars) for index, chars in lines.items()}
    # 中文版本冻结与英文融合验证：新增中英文兼容实现。
    from lyrics_tokens import readable_lyric_units
    line_texts = {index: readable_lyric_units(chars) for index, chars in lines.items()}
    duplicate_lines = Counter(line_texts.values())
    line_order = defaultdict(list)
    for index, text in sorted(line_texts.items()):
        line_order[text].append(index)

    def line_title(index):
        text = line_texts.get(index, "无挂词片段")
        if duplicate_lines[text] > 1:
            text += f"（第{line_order[text].index(index)+1}遍）"
        return text

    def caption(index):
        char = characters.get(index)
        if not char:
            return "待定位"
        same = [c for c in lines[char["line_index"]] if c["text"] == char["text"]]
        return char["text"] + (f"（本句第{[c['index'] for c in same].index(index)+1}个）" if len(same)>1 else "")

    # 简谱小节对齐与人工复核汇总：新增同一声段去重，合并路径接近与时间敏感的全部可信候选字。
    unique = {}
    for item in project.get("alignment_issues", []):
        if not item.get("type", "").startswith("word_ownership"):
            continue
        start, end = float(item["start_seconds"]), float(item["end_seconds"])
        key = (item.get("piece_id"), round(start, 7), round(end, 7))
        current = characters.get(item.get("character_index"))
        if current is None:
            continue
        entry = unique.setdefault(key, {"character_index": current["index"], "character": caption(current["index"]),
            "line_index": current["line_index"], "start_seconds": start, "end_seconds": end,
            "piece_id": item.get("piece_id"), "source_note_id": item.get("source_note_id"),
            "alternative_indices": [], "reason_types": [], "raw_prompt_count": 0})
        entry["raw_prompt_count"] += 1
        if item["type"] not in entry["reason_types"]:
            entry["reason_types"].append(item["type"])
        for alternative in item.get("alternatives", []) + item.get("sensitivity_alternatives", []):
            index = alternative.get("character_index")
            if alternative.get("path_extra_cost", 0) <= .35 and index in characters and index != current["index"] and index not in entry["alternative_indices"]:
                entry["alternative_indices"].append(index)
    ownership = sorted(unique.values(), key=lambda entry: entry["start_seconds"])
    for number, entry in enumerate(ownership, 1):
        notes, measures = locate(project, entry["start_seconds"], entry["end_seconds"])
        alternatives = sorted(entry["alternative_indices"])
        entry.update(id=f"ownership-{number}", alternatives=[caption(i) for i in alternatives],
                     line_text=line_title(entry["line_index"]), measures=measures,
                     notes=note_text(project, notes),
                     # 中文版本冻结与英文融合验证：注释保留被替换的原实现。
                     # context="".join("【"+c["text"]+"】" if c["index"]==entry["character_index"] else c["text"] for c in lines[entry["line_index"]]),
                     # 中文版本冻结与英文融合验证：新增中英文兼容实现。
                     context=readable_lyric_units("【"+c["text"]+"】" if c["index"]==entry["character_index"] else c["text"] for c in lines[entry["line_index"]]),
                     instruction="判断这段音归在当前字，还是相邻候选字；不需要重新选唯一主音。")

    def infer_line(notes, start, end, explicit=None):
        if explicit in characters:
            return characters[explicit]["line_index"]
        overlap = defaultdict(float)
        for note in notes:
            if note.get("lyric_index") in characters:
                overlap[characters[note["lyric_index"]]["line_index"]] += max(0,min(note["end_seconds"],end)-max(note["start_seconds"],start))
        return max(overlap, key=overlap.get) if overlap else None

    # 简谱小节对齐与人工复核汇总：新增音高/短音候选按歌词分组，保持原证据与最终记谱音的区分。
    # 连续转调识别与不确定调性保护：新增调性复核区域，不将其混入短音/装饰音候选。
    tonality_regions=[]
    for region in project.get('notation',{}).get('tonality_uncertain_regions',[]):
        _,measures=locate(project,float(region['start_seconds']),float(region['end_seconds']))
        tonality_regions.append({**region,'measures':measures})
    # 连续转调识别与不确定调性保护：已接受转调的共有音边界单独复核，不当作未确认调性或音高错误。
    modulation_boundaries=[]
    sections=project.get('notation',{}).get('key_segments',[])
    for previous,section in zip(sections,sections[1:]):
        boundary=section.get('evidence',{}).get('boundary',{})
        if not boundary.get('boundary_requires_review'):continue
        indices=sorted(set(boundary.get('tied_boundary_indices',[])+[section['first_character_index']]))
        chars=[characters[i] for i in indices if i in characters and characters[i].get('start_seconds') is not None]
        if not chars:continue
        start=min(c['start_seconds'] for c in chars);end=max(c['end_seconds'] for c in chars);_,measures=locate(project,start,end)
        modulation_boundaries.append({'previous_source_key':previous['source_key']['label'],'new_source_key':section['source_key']['label'],'chosen_start_measure':section['start_measure'],'chosen_first_character_index':section['first_character_index'],'possible_character_indices':indices,'start_seconds':start,'end_seconds':end,'measures':measures,'reason':'shared_pitches_make_boundary_ambiguous'})
    musical = []
    for number, item in enumerate(project.get("review_candidates", []), 1):
        # 连续转调识别与不确定调性保护：新增区域提示去重，真实音高和短音候选不删。
        if item.get('type')=='tonality_uncertain_region':continue
        evidence = item.get("candidate", item)
        start, end = evidence.get("start_seconds"), evidence.get("end_seconds")
        if start is None or end is None:
            continue
        notes, measures = locate(project, float(start), float(end))
        line_index = infer_line(notes, start, end, evidence.get("lyric_index"))
        kind = "pitch" if item.get("type") == "local_pitch_recheck" else "detail"
        label = "音高候选" if kind == "pitch" else "短音/装饰音候选"
        instruction = "对照原声确认音高与转折；不因出现候选就改谱。" if kind == "pitch" else "确认能否听到独立音高；保留普通转音、记成倚音或合并应按演唱判断。"
        candidates = sorted({pitch_text(project, c["pitch_midi"], True,seconds=c.get("start_seconds",start)) for c in item.get("candidates",[]) if c.get("pitch_midi") is not None})
        musical.append({"id": f"music-{number}", "kind": kind, "label": label, "source_type": item.get("type"),
            "line_index": line_index, "line_text": line_title(line_index), "start_seconds": float(start),
            "end_seconds": float(end), "measures": measures, "notes": note_text(project,notes),
            "alternative_notes": candidates, "instruction": instruction,
            "action": item.get("action"), "source_note_id": item.get("source_note_id",evidence.get("source_note_id"))})
    musical.sort(key=lambda entry: entry["start_seconds"])
    musical_groups = []
    for line_index in sorted({e["line_index"] for e in musical}, key=lambda i: (i is None, i if i is not None else 0)):
        entries = [e for e in musical if e["line_index"] == line_index]
        musical_groups.append({"line_index": line_index, "line_text": line_title(line_index), "entries": entries,
                               "pitch_count": sum(e["kind"]=="pitch" for e in entries),
                               "detail_count": sum(e["kind"]=="detail" for e in entries)})
    warned = [c for c in lyrics.get("characters",[]) if c.get("warnings") or c.get("start_seconds") is None or c.get("end_seconds") is None]
    cached_groups = []
    for index in sorted({c.get("line_index") for c in warned}, key=lambda i: (i is None, i if i is not None else 0)):
        chars = [c for c in warned if c.get("line_index") == index]
        cached_groups.append({"line_index":index,"line_text":line_title(index),"character_count":len(chars),
                              "flags":dict(Counter(w for c in chars for w in c.get("warnings",[])))})
    raw_flags={"possible_octave_disagreement","possible_semitone_disagreement","low_pitch_support","rest_contains_voiced_f0","overlap_boundary_adjusted","cross_segment_continuation_merged","short_note_possible_ornament","low_voicing_support","very_low_audio_energy","insufficient_f0_frames"}
    flagged = [n for n in analysis.get("notes",[]) if any(f in raw_flags for f in n.get("review_flags",[]))]
    lyric_lines=[]
    for index,chars in sorted(lines.items()):
        starts=[c["start_seconds"] for c in chars if c.get("start_seconds") is not None]
        ends=[c["end_seconds"] for c in chars if c.get("end_seconds") is not None]
        if starts and ends:
            lyric_lines.append({"line_index":index,"text":line_title(index),"start_seconds":min(starts),"end_seconds":max(ends)})
    # 第二首跨歌曲验证：新增未挂词音段汇总；可能是哼唱/漏词/和声/残余伴奏，不能一律删掉。
    unassigned = []; previous = None
    for note in sorted(project["quantized_notes"], key=lambda n:n["start_seconds"]):
        if note.get("lyric_index") is not None:
            previous = None
            continue
        if previous is None or note["start_seconds"]-previous["end_seconds"]>.35:
            previous = {"start_seconds":note["start_seconds"],"end_seconds":note["end_seconds"],"note_count":0}
            unassigned.append(previous)
        previous["end_seconds"] = max(previous["end_seconds"],note["end_seconds"])
        previous["note_count"] += 1
    for segment in unassigned:
        _, measures = locate(project,segment["start_seconds"],segment["end_seconds"])
        segment["measures"] = measures
    # 第四首《日落大道》男声跨歌曲验证：新增原文未定位字与整句试听位置，绝不把句范围写成字时间。
    unmapped=[]
    line_lookup={entry["line_index"]:entry for entry in lyric_lines}
    for index in project["lyric_mapping"].get("unmapped_character_indices",[]):
        char=characters[index];line=line_lookup.get(char["line_index"])
        unmapped.append({"character_index":index,"text":char["text"],"line_index":char["line_index"],
            "context":"".join("【"+c["text"]+"】" if c["index"]==index else c["text"] for c in lines[char["line_index"]]),
            "candidate_start_seconds":char.get("candidate_start_seconds"),"candidate_end_seconds":char.get("candidate_end_seconds"),
            "context_start_seconds":line["start_seconds"] if line else None,"context_end_seconds":line["end_seconds"] if line else None,
            # 大调约束与强拍先验：修改未挂词说明，用户已确认吞字不再要求判断是否唱出；原说明保留。
            # "instruction":"原文保留，尚无可靠字界；试听是否实际唱出、连读或省略，不补造音符/时间。"})
            # 连续转调识别与不确定调性保护：已知英文后端限制不能提示成吞字，旧文案完整保留。
            # "status":char.get("human_review",{}).get("status","unresolved"),
            # "instruction":("用户已确认演唱吞字；标准歌词保留，不补造音符或字音时间。" if char.get("human_review",{}).get("status")=="user_confirmed_elided"
            # else "原文保留，尚无可靠字界；试听是否实际唱出、连读或省略，不补造音符/时间。")})
            "status":char.get("human_review",{}).get("status","unsupported_language" if char.get("method")=="unsupported_language_unaligned" else "unresolved"),
            "instruction":("用户已确认演唱吞字；标准歌词保留，不补造音符或字音时间。" if char.get("human_review",{}).get("status")=="user_confirmed_elided"
                           else "当前普通话对齐器不支持这段英文；原文保留，时间与音素为空，需多语言对齐或人工定位。" if char.get("method")=="unsupported_language_unaligned"
                           else "原文保留，尚无可靠字界；试听是否实际唱出、连读或省略，不补造音符/时间。")})
    # 大调约束与强拍先验：新增区分真实未挂数量与仍需用户判断数量，不能用确认状态冒充已对齐。
    confirmed=[item for item in unmapped if item["status"]=="user_confirmed_elided"]
    unresolved=[item for item in unmapped if item["status"]!="user_confirmed_elided"]
    return {"schema_version":1,"kind":"human_review_summary","is_confirmed_error_count":False,
        "unmapped_characters":unmapped,"unmapped_character_count":len(unmapped),
        # 大调约束与强拍先验：新增已确认吞字/未解决字分别计数，原未挂数量不变。
        "confirmed_elided_characters":confirmed,"confirmed_elided_count":len(confirmed),
        "unresolved_characters":unresolved,"unresolved_character_count":len(unresolved),
        # 第二首跨歌曲验证：新增来源与无挂词声段信息，不把全量挂词当录音不存在漏词。
        "lyrics_reference_kind":project["lyrics"].get("reference_kind"),
        "unassigned_segments":unassigned,"unassigned_note_count":sum(e["note_count"] for e in unassigned),
        "ownership_prompt_count":sum(e["raw_prompt_count"] for e in ownership),
        "ownership_unique_segments":len(ownership),"ownership_line_count":len({e["line_index"] for e in ownership}),
        "boundary_sensitive_segments":sum("word_ownership_boundary_sensitive" in e["reason_types"] for e in ownership),
        # 连续转调识别与不确定调性保护：新增区域/保音数量，候选不当作错误数量。
        "tonality_regions":tonality_regions,"tonality_region_count":len(tonality_regions),
        # 连续转调识别与不确定调性保护：新增边界复核统计，与未确认调性分开。
        "modulation_boundaries":modulation_boundaries,"modulation_boundary_review_count":len(modulation_boundaries),
        "tonality_guarded_note_count":project.get('decoder',{}).get('tonal_rhythm_priors',{}).get('guarded_notes',0),
        "pitch_candidate_count":sum(e["kind"]=="pitch" for e in musical),
        "detail_candidate_count":sum(e["kind"]=="detail" for e in musical),
        "cached_character_warning_count":len(warned),"raw_acoustic_warning_count":len(flagged),
        "ownership":ownership,"musical_groups":musical_groups,"cached_warning_groups":cached_groups,
        # 小节划分与拍速层级纠错：修改，原把检测脉冲当四分拍保留；复核页与实际声音/谱头共用速度。
        # "tempo_bpm":project["audio_analysis"]["tempo"]["bpm"] if project["overrides"].get("tempo") is None else project["overrides"]["tempo"],
        # 小节划分与拍速层级纠错：修改，原动态导入保留；使用明确导入以便跟踪速度来源。
        # "tempo_bpm":__import__('metrical_timing').selected_quarter_tempo(project),
        "tempo_bpm":selected_quarter_tempo(project),
        "timing_requires_confirmation":project["timing"].get("requires_confirmation",False),
        "coda_ritardando":project["timing"].get("coda_ritardando"),"lyrics_lines":lyric_lines}


def write_bundle(summary, output, audio_url, score_url="jianpu.html", detail_url="review.html", offset=0, findings=None):
    # 简谱小节对齐与人工复核汇总：新增HTML/Markdown/JSON清单，用户点击才播放本机原声。
    output=Path(output); output.mkdir(parents=True,exist_ok=True)
    findings = findings or []
    summary["evaluation_findings"] = findings
    esc=lambda value:html.escape(str(value),quote=True)
    def listen(start,end,label="试听这一段"):
        return f'<button onclick="playRange({max(0,start-offset-.8):.6f},{end-offset+.8:.6f})">{esc(label)}</button>'
    def bar_links(measures):
        return "、".join(f'<a href="{esc(score_url)}#measure-{m}" target="_blank">{m}</a>' for m in measures) or "待定位"
    parts=[f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>人工复核清单</title>
<style>body{{font:16px/1.75 "Microsoft YaHei",sans-serif;margin:0;background:#eef2f6;color:#14243b}}main{{max-width:1250px;margin:24px auto;background:white;padding:28px}}a{{color:#205a98}}table{{border-collapse:collapse;width:100%;margin:12px 0}}th,td{{border:1px solid #dce3e9;padding:10px;text-align:left;vertical-align:top}}th{{background:#f1f5f8}}button{{padding:7px 11px;margin:4px;cursor:pointer}}details{{margin:14px 0}}summary{{cursor:pointer}}audio{{width:min(680px,100%)}}.notice{{padding:14px;background:#fff4df}}.time{{white-space:nowrap;font-variant-numeric:tabular-nums}}.scroll{{overflow-x:auto}}:target{{scroll-margin-top:24px;background:#fff7df}}@media(max-width:700px){{main{{margin:0;padding:16px}}}} </style></head><body><main>
<h1>需要你人工复核的地方</h1><p><a href="{esc(score_url)}">打开对齐版简谱</a> · <a href="{esc(detail_url)}">完整候选与证据</a> · <a href="manual_review.md">文字清单</a></p>
<p class="notice">先核对小节起点和重要转音，再按句听字音边界。以下是自动候选和此前发现的问题，不是已经确认的错误清单；不同类别可能指向同一段声音，不能相加当作错误数。</p>
<audio id="player" controls preload="none" src="{esc(audio_url)}"></audio><p id="status">点击试听按钮播放该段和前后上下文。试听是原录音，简谱为目标调版本。</p>
<ul><li>字音归属：{summary['ownership_unique_segments']}段，涉及{summary['ownership_line_count']}句；合并自{summary['ownership_prompt_count']}条提示。</li><li>音高：{summary['pitch_candidate_count']}条候选。短音/装饰音：{summary['detail_candidate_count']}条候选。</li></ul>''']
    markdown=["# 人工复核清单\n",f"字音归属 {summary['ownership_unique_segments']} 段 / {summary['ownership_line_count']} 句（{summary['ownership_prompt_count']}条提示去重）；音高 {summary['pitch_candidate_count']} 条、短音/装饰音 {summary['detail_candidate_count']} 条。它们是候选，不是已确认错误，不应相加当作错误数量。\n", "[按句试听](manual_review.html) · [对齐版简谱](jianpu.html) · [完整证据](review.html)\n"]
    # 简谱小节对齐与人工复核汇总：新增按钮防折行样式，保持试听操作易读。
    parts.append("<style>button{white-space:nowrap}</style>")
    # 连续转调识别与不确定调性保护：新增置顶调性试听清单，区分候选源调与输出目标调。
    if summary.get('tonality_regions'):
        labels={'possible_unconfirmed_modulation':'可能存在局部升调或回调','unsupported_minor_may_fit_better':'可能为小调或其他调式','local_minor_or_modal_ambiguity':'局部调式尚不明确','weak_baseline_tonality':'基准调证据不足'}
        parts.append('<h2 id="tonality">调性待确认的段落</h2><p>以下段落保留演唱音高，请优先听升调、回调与调式变化。候选源调是自动判断，未当作已确认调号。</p><table><tr><th>小节</th><th>说明</th><th>原声试听</th></tr>')
        markdown += ['## 调性待确认的段落\n','以下段落已保留演唱音高，优先复核升调/回调及调式；候选源调未确认为调号。']
        for region in summary['tonality_regions']:
            message=labels.get(region['reason'],region['reason'])+'；候选源调 '+region['candidate_key']
            parts.append('<tr><td>'+bar_links(region['measures'])+'</td><td>'+esc(message)+'</td><td>'+listen(region['start_seconds'],region['end_seconds'])+'</td></tr>')
            markdown.append('- 小节'+','.join(map(str,region['measures']))+'：'+message)
        parts.append('</table>')
    # 连续转调识别与不确定调性保护：新增共有音转调边界的可读试听入口，源调候选不当作已人工确认。
    if summary.get('modulation_boundaries'):
        parts.append('<h2>转调起点复核</h2><p>这些段落已有持续的新调证据，共有音让准确起点存在歧义，请试听确认。</p><table><tr><th>小节</th><th>源调候选与当前起点</th><th>原声试听</th></tr>')
        markdown += ['## 转调起点复核\n','共有音使起点存在歧义，以下为自动选择，待试听确认。']
        for boundary in summary['modulation_boundaries']:
            message=boundary['previous_source_key']+' → '+boundary['new_source_key']+'；当前从第'+str(boundary['chosen_start_measure'])+'小节标调'
            parts.append('<tr><td>'+bar_links(boundary['measures'])+'</td><td>'+esc(message)+'</td><td>'+listen(boundary['start_seconds'],boundary['end_seconds'])+'</td></tr>')
            markdown.append('- 小节'+','.join(map(str,boundary['measures']))+'：'+message)
        parts.append('</table>')
    # 第四首《日落大道》男声跨歌曲验证：新增未挂歌词单独置顶，部分稿不能被显示成全字对齐。
# 大调约束与强拍先验：修改复核展示，保留原全部未挂词置顶代码。
#     if summary.get("unmapped_characters"):
#         parts.append('<h2>尚未可靠挂谱的歌词</h2><table><tr><th>原文位置</th><th>说明</th><th>整句试听</th></tr>')
#         markdown += ["## 尚未可靠挂谱的歌词\n", "原文完整保留，以下字没有可靠时间，不把整句范围当作字界。"]
#         for item in summary["unmapped_characters"]:
#             button=listen(item["context_start_seconds"],item["context_end_seconds"],"试听整句") if item["context_start_seconds"] is not None else '整句也未定位'
#             parts.append('<tr><td>'+esc(item["context"])+'</td><td>'+esc(item["instruction"])+'</td><td>'+button+'</td></tr>')
#             markdown.append('- '+item["context"]+'：'+item["instruction"])
#         parts.append('</table>')
    # 大调约束与强拍先验：新增已确认演唱差异单列，原文未挂状态透明保留。
    if summary.get("confirmed_elided_characters"):
        parts.append('<h2>已确认的演唱差异</h2><p>以下歌词原文保留；演唱吞字无独立音符，不再列为待确认错误。</p><ul>')
        markdown += ["## 已确认的演唱差异\n"]
        for item in summary["confirmed_elided_characters"]:
            parts.append('<li>'+esc(item["context"])+'：'+esc(item["instruction"])+'</li>')
            markdown.append('- '+item["context"]+'：'+item["instruction"])
        parts.append('</ul>')
    pending=summary.get("unresolved_characters",summary.get("unmapped_characters",[]))
    if pending:
        parts.append('<h2>尚未可靠挂谱的歌词</h2><table><tr><th>原文位置</th><th>说明</th><th>整句试听</th></tr>')
        markdown += ["## 尚未可靠挂谱的歌词\n", "原文完整保留，以下字没有可靠时间，不把整句范围当作字界。"]
        for item in pending:
            button=listen(item["context_start_seconds"],item["context_end_seconds"],"试听整句") if item["context_start_seconds"] is not None else '整句也未定位'
            parts.append('<tr><td>'+esc(item["context"])+'</td><td>'+esc(item["instruction"])+'</td><td>'+button+'</td></tr>')
            markdown.append('- '+item["context"]+'：'+item["instruction"])
        parts.append('</table>')
    if findings:
        # 第二首跨歌曲验证：修改，原已发现错误标题保留；候选和待核节拍不应伪称已确认音乐问题。
        # parts.append('<h2>先确认这些已经发现的音乐问题</h2><div class="scroll"><table><tr><th>位置</th><th>当前情况与判断要点</th><th>谱面小节</th><th>试听</th></tr>')
        parts.append('<h2>本轮优先核对的位置</h2><div class="scroll"><table><tr><th>位置</th><th>当前情况与判断要点</th><th>谱面小节</th><th>试听</th></tr>')
        markdown += ["## 优先核对\n", "| 位置 | 当前情况与判断要点 | 时间 / 小节 |", "|---|---|---|"]
        for i,finding in enumerate(findings,1):
            parts.append(f'<tr id="finding-{i}"><td>{esc(finding["label"])}</td><td>{esc(finding["instruction"])}</td><td>{bar_links(finding["measures"])}</td><td>{listen(finding["start_seconds"],finding["end_seconds"])}</td></tr>')
            markdown.append(f'| {finding["label"]} | {finding["instruction"]} | {time_text(finding["start_seconds"])}–{time_text(finding["end_seconds"])} / {measure_text(finding["measures"])} |')
        parts.append('</table></div>')
    else:
        coda='尚未推断' if str(summary.get('coda_ritardando','')).startswith('not_inferred') else '未确认'
        parts.append('<h2>整曲节奏</h2><p>小节起点与弱起仍需核对；当前速度约为 '+str(summary['tempo_bpm'])+'，尾声渐慢：'+esc(coda)+'。</p>')
    # 第二首跨歌曲验证：新增全量无挂词声段入口，用户试听后再区分，不隐瞒识别遗漏。
    if summary.get("unassigned_segments"):
        parts.append(f'<details><summary>未挂歌词的音段：{summary["unassigned_note_count"]}个音，合并为{len(summary["unassigned_segments"])}段</summary><p>这些可能是哼唱、漏识别唱词、和声或人声分离残余的乐器。音高暂时保留；试听后判断是否应补词、保留为无词旋律或排除。</p><table><tr><th>原声时间</th><th>音段数</th><th>小节</th><th>试听</th></tr>')
        markdown += ["\n## 未挂歌词的音段\n", "可能是哼唱、漏词、和声或残余伴奏，保留候选并试听，不作为已确认错误。", "| 原声时间 | 音段数 | 小节 |", "|---|---:|---|"]
        for segment in summary["unassigned_segments"]:
            interval = time_text(segment["start_seconds"])+"–"+time_text(segment["end_seconds"])
            parts.append(f'<tr><td>{interval}</td><td>{segment["note_count"]}</td><td>{bar_links(segment["measures"])}</td><td>{listen(segment["start_seconds"],segment["end_seconds"])}</td></tr>')
            markdown.append(f'| {interval} | {segment["note_count"]} | {measure_text(segment["measures"])} |')
        parts.append('</table></details>')
    parts.append('<h2>字音归属：按演唱顺序检查</h2><p>【】标出当前所属字。“另一可能的字”包括整句路径接近和音素边界扰动后的候选。每行是一段去重后的声音；小节号可直接跳转。</p>')
    markdown += ["\n## 字音归属：全部去重位置\n", "| 歌词 / 当前字 | 另一可能的字 | 目前这一段的音 | 原声时间 | 小节 |", "|---|---|---|---|---|"]
    line_lookup={e['line_index']:e for e in summary['lyrics_lines']}
    for line_index in sorted({e['line_index'] for e in summary['ownership']}):
        entries=[e for e in summary['ownership'] if e['line_index']==line_index]
        line=line_lookup.get(line_index)
        title=line['text'] if line else entries[0]['line_text']
        play=listen(line['start_seconds'],line['end_seconds'],'试听整句') if line else ''
        parts.append(f'<h3>{line_index+1}. {esc(title)}</h3>{play}<div class="scroll"><table><tr><th>所在歌词 / 当前字</th><th>另一可能的字</th><th>当前音</th><th>原声时间</th><th>小节</th><th>试听</th></tr>')
        for entry in entries:
            alternatives="、".join(entry['alternatives']) or '需要人工判断'
            interval=time_text(entry['start_seconds'])+'–'+time_text(entry['end_seconds'])
            parts.append(f'<tr id="{entry["id"]}"><td>{esc(entry["context"])}</td><td>{esc(alternatives)}</td><td>{esc(entry["notes"])}</td><td class="time">{interval}</td><td>{bar_links(entry["measures"])}</td><td>{listen(entry["start_seconds"],entry["end_seconds"])}</td></tr>')
            markdown.append(f'| {entry["line_text"]} / {entry["character"]} | {alternatives} | {entry["notes"]} | {interval} | {measure_text(entry["measures"])} |')
        parts.append('</table></div>')
    parts.append('<h2>音高与装饰音：按句查看</h2><p>确认能听到的独立音高与转折，再判断普通转音、倚音或连续滑音。保留一字多个普通音是允许的，不必给每个字强选一个主音。</p>')
    markdown += ["\n## 音高与装饰音候选：按句汇总\n", "| 歌词 | 原声范围 | 音高候选 | 细节音候选 |", "|---|---|---:|---:|"]
    for group in summary['musical_groups']:
        entries=group['entries'];begin=min(e['start_seconds'] for e in entries);end=max(e['end_seconds'] for e in entries)
        parts.append(f'<details><summary>{esc(group["line_text"])} — 音高{group["pitch_count"]}条、细节{group["detail_count"]}条 · {time_text(begin)}–{time_text(end)}</summary><div class="scroll"><table><tr><th>类别</th><th>当前音 / 其他音高候选</th><th>时间 / 小节</th><th>判断要点</th><th>试听</th></tr>')
        for entry in entries:
            alternatives='；音高候选：'+"、".join(entry['alternative_notes']) if entry['alternative_notes'] else ''
            parts.append(f'<tr id="{entry["id"]}"><td>{esc(entry["label"])}</td><td>{esc(entry["notes"]+alternatives)}</td><td class="time">{time_text(entry["start_seconds"])}–{time_text(entry["end_seconds"])}<br>小节 {bar_links(entry["measures"])}</td><td>{esc(entry["instruction"])}</td><td>{listen(entry["start_seconds"],entry["end_seconds"])}</td></tr>')
        parts.append('</table></div></details>')
        markdown.append(f'| {group["line_text"]} | {time_text(begin)}–{time_text(end)} | {group["pitch_count"]} | {group["detail_count"]} |')
    parts.append(f'<details><summary>其他源数据提示：{summary["cached_character_warning_count"]}个字的时间窗口提示、{summary["raw_acoustic_warning_count"]}条声学提示</summary><p>这些提示来自此前的裁剪/粗定位与声学阶段；可能与上面的字音、音高候选重叠，不代表额外错误。完整原标记在证据页。</p><ul>')
    for group in summary['cached_warning_groups']:
        parts.append(f'<li>{esc(group["line_text"])}：{group["character_count"]}字的裁剪或粗定位窗口未听审。'+('含句末裁剪边缘提示，需确认尾字是否完整。' if 'phrase_crop_right_edge_review_required' in group['flags'] else '')+'</li>')
    parts.append('</ul></details>')
    markdown.append(f"\n另有{summary['cached_character_warning_count']}个字保留旧裁剪/粗定位窗口提示，以及{summary['raw_acoustic_warning_count']}条源声学提示，与上述候选可能重叠，完整原标记见证据页。")
    # 简谱小节对齐与人工复核汇总：新增已听审意见仅作为评估文案，不注入通用生成答案。
    if findings:
        parts.append('<p>本曲已确认的阅读原则：一字多个有时值音可以保留，角色解释的不同不单独作为错误。</p>')
    parts.append('''</main><script>// 简谱小节对齐与人工复核汇总：新增点击后本地试听，播放音频不上传。
const player=document.getElementById('player'),status=document.getElementById('status');let stopAt=null;
async function playRange(start,end){stopAt=end;try{player.currentTime=start;await player.play();status.textContent='正在试听 '+start.toFixed(2)+'–'+end.toFixed(2)+' 秒';}catch(error){status.textContent='无法播放本地音频：'+error.message;}}
player.addEventListener('timeupdate',()=>{if(stopAt!==null&&player.currentTime>=stopAt){player.pause();stopAt=null;}});
</script></body></html>''')
    (output/'manual_review.html').write_text(''.join(parts),encoding='utf-8')
    (output/'manual_review.md').write_text('\n'.join(markdown)+'\n',encoding='utf-8')
    (output/'manual_review.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return summary
