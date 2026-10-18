# 歌词对齐与真实制谱：新增真实普通话 TIFA 强制对齐与明确标注的近似基线。
from __future__ import annotations

import argparse
import difflib
import importlib.metadata
import json
import os
import re  # 歌词对齐与真实制谱：新增识别稿疑似署名行的复核标记。
from pathlib import Path
import sys
import time
import traceback
import unicodedata

from lyrics_transcribe import ROOT, DEFAULT_OUT, file_sha256, read_json, save_json
# 字音归属修复：新增音素传递接口，保持全局秒坐标与原始owner。
from phoneme_evidence import character_phonemes
# 第二首跨歌曲验证：新增整曲后端同样检查普通话文本支持范围。
# 中文版本冻结与英文融合验证：注释保留被替换的原实现。
# from lyrics_quality import check_mandarin_reference
# 中文版本冻结与英文融合验证：新增中英文兼容实现。
from lyrics_quality import check_multilingual_reference
# 第二首跨歌曲验证：新增胡哼标记单位化及官方显式音素输入。
# 第四首《日落大道》男声跨歌曲验证：修改统一PFML检测导入，原行保留。
# from lyrics_tokens import text_units, tifa_pfml
# 中文版本冻结与英文融合验证：注释保留被替换的原实现。
# from lyrics_tokens import text_units, tifa_pfml, requires_tifa_pfml
# 中文版本冻结与英文融合验证：新增中英文兼容实现。
from lyrics_tokens import text_units, tifa_pfml, requires_tifa_pfml, lyric_match_key, languages_for_text


# 歌词对齐与真实制谱：新增标点过滤与行索引保留，字符序列与 G2P 输入一致。
def reference_characters(reference: dict) -> list[dict]:
    chars = []
    for line_index, line in enumerate(reference["lines"]):
        # 第二首跨歌曲验证：修改，原逐字符扫描保留；胡哼标签按完整音节扫描。
        # for text in line:
        #     if text.isspace() or unicodedata.category(text).startswith(("P", "S")):
        #         continue
        for unit in text_units(line):
            text = unit["text"]
            chars.append({"index": len(chars), "text": text, "line_index": line_index,
                          "start_seconds": None, "end_seconds": None, "method": "alignment_missing",
                          # 第二首跨歌曲验证：修改，保留单位类型；原结束字段注释保存。
                          # "confidence": None, "warnings": ["alignment_missing"], "group_id": None})
                          "confidence": None, "warnings": ["alignment_missing"], "group_id": None,
                          # 中文版本冻结与英文融合验证：注释保留被替换的原实现。
                          # "unit_kind": unit["kind"], "pronunciation_candidates": unit.get("pronunciation_candidates")})
                          # 中文版本冻结与英文融合验证：新增中英文兼容实现。
                          "unit_kind": unit["kind"], "pronunciation_candidates": unit.get("pronunciation_candidates")})
            if unit["kind"] == "english_word":
                chars[-1]["language"] = "en"
    return chars


# 歌词对齐与真实制谱：新增普通话专用配置；不构造日语/英语可选资源。
def tifa_align(reference: dict, output: Path, report: dict) -> list[dict]:
    # 第二首跨歌曲验证：新增普通话后端前置检查，不静默删掉真实英文歌词。
    # 中文版本冻结与英文融合验证：注释保留被替换的原实现。
    # preflight = check_mandarin_reference(reference)
    # if not preflight["valid_for_mandarin_tifa"]:
    # 中文版本冻结与英文融合验证：新增中英文兼容实现。
    preflight = check_multilingual_reference(reference)
    if not preflight["valid_for_multilingual_tifa"]:
        save_json(output / "text_preflight.json", preflight)
        # 中文版本冻结与英文融合验证：注释保留被替换的原实现。
        # raise ValueError("当前普通话TIFA不支持该歌词文本；详见text_preflight.json。")
        # 中文版本冻结与英文融合验证：新增中英文兼容实现。
        raise ValueError("中英文TIFA前端不支持该歌词文本；详见text_preflight.json。")
    import shutil
    import torch
    import lightning.pytorch as pl
    from g2pflow import G2PPipelineConfig
    checkout = ROOT / "third_party" / "TIFA"
    sys.path.insert(0, str(checkout))
    from inference.api import load_inference_model, run_inference
    from inference.callbacks import SaveTextGridCallback, StatisticsCallback
    from inference.data import AudioTextDataset
    from lib.config.schema import ConfigurationScope
    model_dir = ROOT / ".cache" / "tifa" / "model" / "TIFA-1.0-ST"
    model_path = model_dir / "model.pt"
    if not model_path.is_file():
        raise FileNotFoundError(f"官方 TIFA 权重尚未准备：{model_path}")
    raw_output = output / "tifa"
    raw_output.mkdir(parents=True, exist_ok=True)
    paired = output / "tifa_input"
    paired.mkdir(parents=True, exist_ok=True)
    # 歌词对齐与真实制谱：新增同源副本，避免在原模型运行目录旁写歌词文件。
    audio_path = paired / "vocals.wav"
    if not audio_path.is_file() or file_sha256(audio_path) != reference["source"]["sha256"]:
        shutil.copy2(reference["source"]["path"], audio_path)
    audio_path.with_suffix(".txt").write_text(reference["text"] + "\n", encoding="utf-8")
    # 第二首跨歌曲验证：新增仅含哼唱时使用PFML；汉字继续官方G2P，显示原文不替换。
    # 第四首《日落大道》男声跨歌曲验证：修改显式读音入口，原Hu条件保留；源汉字和owner不变。
    # if any(unit["kind"] == "vocalization" for unit in text_units(reference["text"])):
    if requires_tifa_pfml(reference["text"]):
        paired_input = audio_path.with_suffix(".pfml")
        paired_input.write_text(tifa_pfml(reference["text"]) + "\n", encoding="utf-8")
        report["vocalization_input"] = str(paired_input)
    # 中文版本冻结与英文融合验证：注释保留被替换的原实现。
    # config = G2PPipelineConfig.model_validate({
        # "preprocessors": [{"id": "filter-punctuation"}, {"id": "strip-whitespace"}, {"id": "lowercase"}],
        # "converters": [{"id": "chinese-pinyin", "kwargs": {"dict_path": str(model_dir / "dictionaries" / "ds-zh-pinyin-lite.txt")}},
                       # {"id": "dictionary", "language": "zh", "kwargs": {"dict_path": str(model_dir / "dictionaries" / "ds-zh-pinyin-lite.txt")}}]})
    # 中文版本冻结与英文融合验证：新增中英文兼容实现。
    from english_lyrics import multilingual_g2p_config
    languages = languages_for_text(reference["text"])
    config = G2PPipelineConfig.model_validate(multilingual_g2p_config(model_dir, languages))
    report['languages'] = languages
    report['english_word_count'] = sum(u['kind'] == 'english_word' for u in text_units(reference['text']))
    started = time.perf_counter()
    backend, vocabulary, inference_config = load_inference_model(model_path, scope=ConfigurationScope.FA)
    backend = backend.to("cuda")
    torch.cuda.synchronize()
    report["timings"]["model_load_to_gpu_seconds"] = time.perf_counter() - started
    started = time.perf_counter()
    dataset = AudioTextDataset({"vocals": audio_path}, config, ROOT, vocabulary, backend.sample_rate,
                               # 中文版本冻结与英文融合验证：注释保留被替换的原实现。
                               # language=["zh"], oov_handling="raise")
                               # 中文版本冻结与英文融合验证：新增中英文兼容实现。
                               language=languages, oov_handling="raise")
    prepared = dataset[0]
    if prepared.get("skip"):
        raise RuntimeError(prepared.get("error") or prepared.get("warning") or "TIFA 跳过输入")
    report["timings"]["g2p_decode_resample_seconds"] = time.perf_counter() - started
    report["g2p_word_count"] = len(prepared["texts"])
    report["prepared_audio_seconds"] = prepared["duration"]
    captured = []

    # 歌词对齐与真实制谱：新增一次预处理缓存，防止预测计时包含重复 G2P 和解码。
    class PreparedDataset(torch.utils.data.Dataset):
        collate = staticmethod(AudioTextDataset.collate)
        def __len__(self):
            return 1
        def __getitem__(self, index):
            return prepared

    # 歌词对齐与真实制谱：新增原始状态起止时间保存，不把 TextGrid 的零宽修补当精准对齐。
    class CaptureRawAlignment(pl.Callback):
        def on_predict_batch_end(self, trainer, pl_module, outputs, batch, *args, **kwargs):
            for value in outputs:
                spans = (value["spans"].detach().float().cpu() * backend.timestep).tolist()
                owners = value["words"].detach().cpu().tolist()
                records = []
                for owner, span, phoneme in zip(owners, spans, value["phonemes"]):
                    records.append({"word_owner": owner, "text": value["texts"][owner - 1],
                                    "start_seconds": span[0], "end_seconds": span[1], "phoneme": phoneme})
                captured.append({"identifier": value["identifier"], "texts": value["texts"],
                                 "agreement": value["agreement"], "phoneme_states": records})
                save_json(raw_output / "raw_alignment.json", {"source": reference["source"],
                          "timestep_seconds": backend.timestep, "results": captured})

    callbacks = [CaptureRawAlignment(), SaveTextGridCallback(raw_output, language="zh", timestep=backend.timestep,
                                                            skip_handling="omit"),
                 StatisticsCallback(raw_output / "statistics")]
    torch.cuda.reset_peak_memory_stats()
    torch.cuda.synchronize()
    started = time.perf_counter()
    run_inference(backend, PreparedDataset(), callbacks, batch_size=1, num_workers=0,
                  precision="32-true", mode="predict", score_unit="levenshtein", skip_penalty=0.5)
    torch.cuda.synchronize()
    report["timings"]["predict_diagnostics_export_seconds"] = time.perf_counter() - started
    report["peak_gpu_allocated_bytes"] = torch.cuda.max_memory_allocated()
    report["peak_gpu_reserved_bytes"] = torch.cuda.max_memory_reserved()
    if not captured:
        raise RuntimeError("TIFA 没有返回真实对齐结果")
    result = captured[0]
    chars = reference_characters(reference)
    # 第二首跨歌曲验证：修改，原字符平铺保留，模型结果按歌词单位验证。
    # generated = list("".join(result["texts"]))
    # 中文版本冻结与英文融合验证：注释保留被替换的原实现。
    # generated = [unit["text"] for text in result["texts"] for unit in text_units(text)]
    # canonical = [c["text"] for c in chars]
    # 中文版本冻结与英文融合验证：新增中英文兼容实现。
    generated = [lyric_match_key(unit["text"]) for text in result["texts"] for unit in text_units(text)]
    canonical = [lyric_match_key(c["text"]) for c in chars]
    if generated != canonical:
        raise RuntimeError("TIFA G2P 文本序列与参考字符不一致；拒绝通过机械分配伪造逐字结果")
    cursor = 0
    offset = reference["source"].get("offset_seconds", 0.0)
    for owner, text in enumerate(result["texts"], start=1):
        states = [s for s in result["phoneme_states"] if s["word_owner"] == owner]
        valid = [s for s in states if s["end_seconds"] > s["start_seconds"]]
        # 第二首跨歌曲验证：新增原owner的歌词单位数，Hu虽两字母但只有一个音节。
        owner_units = text_units(text)
        warnings = []
        if len(valid) != len(states):
            warnings.append("tifa_skipped_phoneme")
        # 第二首跨歌曲验证：修改，原按字符串长度判断多字保留。
        # if len(text) != 1:
        if len(owner_units) != 1:
            warnings += ["not_character_alignment", "shared_word_span"]
        # 第二首跨歌曲验证：修改，原按字母个数切片保留。
        # for char in chars[cursor:cursor + len(text)]:
        for char in chars[cursor:cursor + len(owner_units)]:
            # 字音归属修复：新增原始音素旁路信息，多字词绝不按字均分。
            # 第二首跨歌曲验证：修改，原音素限制保留；完整Hu单位也接入真实音素。
            # char["phonemes"] = character_phonemes(states, offset) if len(text) == 1 else []
            char["phonemes"] = character_phonemes(states, offset) if len(owner_units) == 1 else []
            char["phoneme_source"] = {"word_owner": owner, "timestep_seconds": backend.timestep}
            if valid:
                start = min(s["start_seconds"] for s in valid)
                end = max(s["end_seconds"] for s in valid)
                if end - start < 0.03:
                    warnings.append("near_zero_duration")
                char.update(start_seconds=round(start + offset, 6), end_seconds=round(end + offset, 6),
                            # 第二首跨歌曲验证：修改，原按字母数方法判断保留。
                            # method="tifa_texts_tier" if len(text) == 1 else "tifa_word_group_span",
                            method="tifa_texts_tier" if len(owner_units) == 1 else "tifa_word_group_span",
                            warnings=list(dict.fromkeys(warnings)), group_id=f"tifa_word_{owner}")
            else:
                char["warnings"].append("tifa_word_fully_skipped")
        # 第二首跨歌曲验证：修改，原owner游标更新保留，防止Hu后全部歌词串位。
        # cursor += len(text)
        cursor += len(owner_units)
    report.update(model=str(model_path), model_sha256=file_sha256(model_path),
                  model_timestep_seconds=backend.timestep, agreement=result["agreement"],
                  raw_alignment=str(raw_output / "raw_alignment.json"),
                  textgrid=str(raw_output / "vocals.TextGrid"),
                  diagnostics=str(raw_output / "statistics" / "diagnosis.json"),
                  quality_note="真实强制对齐完成；文本未校正，agreement 是模型内部诊断，不是校准正确率。")
    return chars


# 歌词对齐与真实制谱：新增明确近似的 ASR 词范围，不把多字词平均拆成精准字边界。
def approximate_asr(reference: dict, output: Path) -> list[dict]:
    raw = read_json(output / "asr_raw.json")
    if raw["source"]["sha256"] != reference["source"]["sha256"]:
        raise ValueError("ASR 缓存与统一人声来源不一致")
    source_chars = []
    offset = reference["source"].get("offset_seconds", 0.0)
    for segment_index, segment in enumerate(raw["result"]["segments"]):
        for word_index, word in enumerate(segment.get("words", [])):
            # 中文版本冻结与英文融合验证：注释保留被替换的原实现。
            # for text in word["word"]:
                # if text.isspace() or unicodedata.category(text).startswith(("P", "S")):
                    # continue
                # source_chars.append({"text": text, "start_seconds": word["start"] + offset,
            # 中文版本冻结与英文融合验证：新增中英文兼容实现。
            for unit in text_units(word["word"]):
                source_chars.append({"text": unit["text"], "start_seconds": word["start"] + offset,
                                     "end_seconds": word["end"] + offset, "confidence": word.get("probability"),
                                     "group_id": f"asr_segment_{segment_index}_word_{word_index}"})
    chars = reference_characters(reference)
    # 中文版本冻结与英文融合验证：注释保留被替换的原实现。
    # matcher = difflib.SequenceMatcher(a=[c["text"] for c in chars], b=[c["text"] for c in source_chars], autojunk=False)
    # 中文版本冻结与英文融合验证：新增中英文兼容实现。
    matcher = difflib.SequenceMatcher(a=[lyric_match_key(c["text"]) for c in chars], b=[lyric_match_key(c["text"]) for c in source_chars], autojunk=False)
    for match in matcher.get_matching_blocks():
        for i in range(match.size):
            char = chars[match.a + i]
            # 中文版本冻结与英文融合验证：注释保留被替换的原实现。
            # char.update(source_chars[match.b + i])
            # 中文版本冻结与英文融合验证：新增中英文兼容实现。
            char.update({k:v for k,v in source_chars[match.b + i].items() if k != "text"})
            char.update(method="whisper_word_shared_span", warnings=["approximate", "shared_word_span", "not_forced_alignment"])
    return chars


# 歌词对齐与真实制谱：新增异常候选拒绝策略；原始模型时间保留，不硬塞到音符。
def reject_unreliable_candidates(chars: list[dict], reference: dict, report: dict) -> list[dict]:
    suspicious_lines = set()
    if reference["reference_kind"] == "asr_unverified":
        for index, line in enumerate(reference["lines"]):
            if re.match(r"^(?:作[词詞曲]|编曲|編曲|演唱|[词詞曲][：: ])", line):
                suspicious_lines.add(index)
    for char in chars:
        reasons = []
        if char["line_index"] in suspicious_lines:
            reasons.append("asr_suspected_credit_hallucination")
        # 中文版本冻结与英文融合验证：注释保留被替换的原实现。
        # if "near_zero_duration" in char["warnings"]:
        # 中文版本冻结与英文融合验证：新增中英文兼容实现。
        if char.get("unit_kind") == "english_word" and not any(p.get("role") == "nucleus" and not p.get("skipped") for p in char.get("phonemes", [])):
            reasons.append("english_vowel_unavailable_review_required")
        if "near_zero_duration" in char["warnings"]:
            reasons.append("duration_below_30ms_review_required")
        if "tifa_skipped_phoneme" in char["warnings"]:
            reasons.append("skipped_phoneme_review_required")
        if reasons:
            if char["start_seconds"] is not None:
                char["candidate_start_seconds"] = char["start_seconds"]
                char["candidate_end_seconds"] = char["end_seconds"]
            char.update(start_seconds=None, end_seconds=None, method="tifa_alignment_rejected",
                        warnings=list(dict.fromkeys(char["warnings"] + reasons + ["alignment_unassigned"])))
    report["rejection_policy"] = {"min_character_duration_seconds": 0.03,
                                   "asr_credit_line_indices": sorted(suspicious_lines),
                                   "skipped_phoneme_action": "保留原候选；公开字边界置空待复核"}
    return chars


# 歌词对齐与真实制谱：新增来源与文本绑定缓存，以及失败证据完整保留。
def main() -> int:
    parser = argparse.ArgumentParser(description="TIFA 普通话歌声强制对齐与近似基线")
    parser.add_argument("--reference", type=Path, default=DEFAULT_OUT / "lyrics_reference.json")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--backend", choices=("auto", "tifa", "asr-baseline"), default="auto")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    reference = read_json(args.reference)
    source = reference["source"]
    if file_sha256(Path(source["path"])) != source["sha256"]:
        raise ValueError("对齐源音频哈希失配")
    output = (args.output_dir or args.reference.parent).resolve()
    output.mkdir(parents=True, exist_ok=True)
    target = output / "characters.json"
    text_sha = __import__("hashlib").sha256(reference["text"].encode("utf-8")).hexdigest()
    # 歌词对齐与真实制谱：修改；缺权重时允许记录失败或使用明确近似基线，不提前中断。
    # cache_key = {"source_sha256": source["sha256"], "text_sha256": text_sha,
    #              "backend": args.backend, "wrapper_sha256": file_sha256(Path(__file__)),
    #              "model_sha256": file_sha256(ROOT / ".cache" / "tifa" / "model" / "TIFA-1.0-ST" / "model.pt")}
    weight = ROOT / ".cache" / "tifa" / "model" / "TIFA-1.0-ST" / "model.pt"
    cache_key = {"source_sha256": source["sha256"], "text_sha256": text_sha,
                 "backend": args.backend, "wrapper_sha256": file_sha256(Path(__file__)),
                 "model_sha256": file_sha256(weight) if weight.is_file() else None}
    # 第二首跨歌曲验证：新增歌词单位模块哈希到完整对齐缓存身份。
    # 中文版本冻结与英文融合验证：注释保留被替换的原实现。
    # cache_key["lyrics_units_sha256"] = file_sha256(ROOT / "tools/lyrics_tokens.py")
    # 中文版本冻结与英文融合验证：新增中英文兼容实现。
    cache_key["lyrics_units_sha256"] = file_sha256(ROOT / "tools/lyrics_tokens.py")
    cache_key["english_frontend_sha256"] = file_sha256(ROOT / "tools/english_lyrics.py")
    cache_key["phoneme_evidence_sha256"] = file_sha256(ROOT / "tools/phoneme_evidence.py")
    report = {"task": "歌词对齐与真实制谱", "operation": "lyrics_alignment", "source": source,
              "timings": {}, "reference_kind": reference["reference_kind"], "warnings": []}
    started = time.perf_counter()
    try:
        if target.is_file() and not args.force and read_json(target).get("cache_key") == cache_key:
            report.update(status="cache_hit", output_characters=str(target))
            report["wall_seconds"] = time.perf_counter() - started
            save_json(ROOT / "reports" / "lyrics_alignment_latest.json", report)
            print(json.dumps(report, ensure_ascii=False))
            return 0
        if args.backend != "asr-baseline":
            try:
                chars = tifa_align(reference, output, report)
                status = "tifa_forced_aligned_unverified"
            except Exception as exc:
                report["tifa_failure"] = {"error": f"{type(exc).__name__}: {exc}", "traceback": traceback.format_exc()}
                save_json(ROOT / "reports" / "lyrics_tifa_failure.json", report)
                if args.backend == "tifa":
                    raise
                chars = approximate_asr(reference, output)
                status = "approximate_asr_baseline"
                report["warnings"].append("TIFA 真实运行失败；时戳仅为 ASR 词范围近似，没有完成强制对齐。")
        else:
            chars = approximate_asr(reference, output)
            status = "approximate_asr_baseline"
        # 歌词对齐与真实制谱：修改；先拒绝异常候选，再写出可供制谱消费的逐字范围。
        # warnings = report["warnings"] + ["歌词文本与逐字时间尚未经人工校正；部分字符可能遗漏或边界错误。"]
        chars = reject_unreliable_candidates(chars, reference, report)
        warnings = report["warnings"] + ["歌词文本与逐字时间尚未经人工校正；部分字符可能遗漏或边界错误。",
                   "近零时长、跳过音素及疑似署名的原时间保留为candidate字段，正式时间为空等待人工复核。"]
        result = {"schema_version": 1, "source": source, "reference_kind": reference["reference_kind"],
                  "alignment_status": status, "reference_file": str(args.reference.resolve()),
                  "cache_key": cache_key, "characters": chars, "warnings": warnings}
        save_json(target, result)
        report.update(status=status, output_characters=str(target), total_characters=len(chars),
                      characters_with_time=sum(c["start_seconds"] is not None for c in chars),
                      characters_with_warnings=sum(bool(c["warnings"]) for c in chars),
                      packages={p: importlib.metadata.version(p) for p in ("g2pflow", "lightning", "pydantic", "torch")})
    except Exception as exc:
        report.update(status="failed", error=f"{type(exc).__name__}: {exc}", traceback=traceback.format_exc())
    report["wall_seconds"] = time.perf_counter() - started
    save_json(ROOT / "reports" / "lyrics_alignment.json", report)
    print(json.dumps(report, ensure_ascii=False), flush=True)
    return 1 if report["status"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
