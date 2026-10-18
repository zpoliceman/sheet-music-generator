# 歌词对齐与真实制谱：新增真实本地歌词识别、用户文本覆盖与来源绑定缓存。
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
from workspace_location import local_path
import time
import traceback


# 歌词对齐与真实制谱：新增统一人声来源解析，避免混用不同分离结果。
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "test_outputs" / "lyrics" / "first_song"
os.environ.setdefault("NUMBA_CACHE_DIR", str(ROOT / ".cache" / "numba"))
os.environ.setdefault("MPLCONFIGDIR", str(ROOT / ".cache" / "matplotlib"))


def read_json(path: Path) -> dict:
    return json.loads(local_path(path).read_text(encoding="utf-8-sig"))


# 歌词对齐与真实制谱：新增流式哈希与原始秒时间核验，保留整首时间轴。
def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with local_path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def resolve_source(summary_path: Path | None = None) -> tuple[dict, Path]:
    if summary_path is None:
        pipeline = read_json(ROOT / "reports" / "integrated_pipeline.full.json")
        summary_path = Path(pipeline["run"]["transcription_summary"])
    summary = read_json(summary_path)
    source = summary["source"].copy()
    path = Path(source["path"])
    if file_sha256(path) != source["sha256"]:
        raise ValueError("统一转录人声 SHA256 不匹配，拒绝混用来源")
    return source, summary_path.resolve()


# 歌词对齐与真实制谱：新增 UTF-8 原始识别与任务报告保存。
def save_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


# 歌词对齐与真实制谱：新增缓存参数绑定；歌词识别时戳不等同歌声强制对齐。
# 中文版本冻结与英文融合验证：注释保留被替换的原实现。
# def transcribe(source: dict, model_name: str, output: Path, force: bool) -> tuple[dict, dict]:
# 中文版本冻结与英文融合验证：新增中英文兼容实现。
def transcribe(source: dict, model_name: str, output: Path, force: bool, language: str = "zh") -> tuple[dict, dict]:
    import numpy as np
    import scipy.signal
    import soundfile as sf
    import torch
    import whisper
    # 第二首跨歌曲验证：修改，Whisper提示是转录上下文，指令型提示会混入歌词；原配置注释保留。
    # config = {"model": model_name, "language": "zh", "task": "transcribe", "temperature": 0.0,
    # "word_timestamps": True, "condition_on_previous_text": False,
    # "initial_prompt": "请用简体中文转录普通话演唱内容。"}
    # 第二首跨歌曲验证：新增，无指令提示的普通话识别；缓存按新配置自动隔离。
    # 第二首跨歌曲验证：修改，仅移除提示仍出现前奏幻觉；原无过滤配置注释保留。
    # config = {"model": model_name, "language": "zh", "task": "transcribe", "temperature": 0.0,
    # "word_timestamps": True, "condition_on_previous_text": False}
    # 第二首跨歌曲验证：新增Whisper内置静音幻觉检查，并在过度重复时启用温度回退。
    # 中文版本冻结与英文融合验证：注释保留被替换的原实现。
    # config = {"model": model_name, "language": "zh", "task": "transcribe",
    # 中文版本冻结与英文融合验证：新增中英文兼容实现。
    if language not in ("zh", "en", "auto"):
        raise ValueError("ASR语言必须为zh、en或auto。")
    config = {"model": model_name, "language": None if language == "auto" else language, "task": "transcribe",
              "temperature": [0.0, 0.2, 0.4, 0.6, 0.8, 1.0],
              "word_timestamps": True, "condition_on_previous_text": False,
              "hallucination_silence_threshold": 1.0}
    raw_path = output / "asr_raw.json"
    if raw_path.is_file() and not force:
        cached = read_json(raw_path)
        if cached.get("source", {}).get("sha256") == source["sha256"] and cached.get("configuration") == config:
            return cached, {"status": "cache_hit", "model_load_seconds": 0.0, "asr_seconds": 0.0}
    if not torch.cuda.is_available():
        raise RuntimeError("Whisper 实测要求 CUDA，目前不可用")
    torch.manual_seed(20261005)
    timings = {}
    started = time.perf_counter()
    cache = ROOT / ".cache" / "whisper"
    weight_path = Path(whisper._download(whisper._MODELS[model_name], str(cache), False))
    timings["weight_download_or_cached_sha256_seconds"] = time.perf_counter() - started
    started = time.perf_counter()
    model = whisper.load_model(str(weight_path), device="cuda", download_root=str(cache))
    torch.cuda.synchronize()
    timings["model_load_seconds"] = time.perf_counter() - started
    started = time.perf_counter()
    audio, rate = sf.read(local_path(source["path"]), dtype="float32", always_2d=True)
    mono = audio.mean(axis=1)
    factor = math.gcd(rate, 16000)
    if rate != 16000:
        mono = scipy.signal.resample_poly(mono, 16000 // factor, rate // factor).astype(np.float32)
    timings["decode_resample_seconds"] = time.perf_counter() - started
    torch.cuda.reset_peak_memory_stats()
    torch.cuda.synchronize()
    started = time.perf_counter()
    result = model.transcribe(mono, **{k: v for k, v in config.items() if k != "model"},
                              fp16=True, verbose=False)
    torch.cuda.synchronize()
    timings["asr_seconds"] = time.perf_counter() - started
    timings["peak_gpu_allocated_bytes"] = torch.cuda.max_memory_allocated()
    timings["peak_gpu_reserved_bytes"] = torch.cuda.max_memory_reserved()
    timings["status"] = "inference_completed_transcript_unverified"
    raw = {"schema_version": 1, "source": source, "reference_kind": "asr_unverified",
           "recognizer": "openai-whisper", "package_version": importlib.metadata.version("openai-whisper"),
           "configuration": config, "model_file": str(weight_path), "model_sha256": file_sha256(weight_path),
           "timings": timings, "result": result,
           "warnings": ["模型识别文本尚未人工校正；Whisper 词时戳不是歌声逐字强制对齐。"]}
    save_json(raw_path, raw)
    return raw, timings


# 歌词对齐与真实制谱：新增独立文本覆盖接口，保留自动识别缓存供比较。
def main() -> int:
    parser = argparse.ArgumentParser(description="真实普通话歌词识别与用户文本覆盖")
    parser.add_argument("--source-summary", type=Path)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUT)
    # 中文版本冻结与英文融合验证：注释保留被替换的原实现。
    # parser.add_argument("--model", default="turbo")
    # 中文版本冻结与英文融合验证：新增中英文兼容实现。
    parser.add_argument("--model", default="turbo")
    parser.add_argument("--language", choices=("zh", "en", "auto"), default="zh")
    parser.add_argument("--lyrics-file", type=Path, help="用户提供的 UTF-8 正确歌词；不需要重新运行 ASR")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    report = {"task": "歌词对齐与真实制谱", "operation": "lyrics_recognition", "timings": {}}
    started = time.perf_counter()
    try:
        source, summary = resolve_source(args.source_summary)
        if args.lyrics_file:
            text = args.lyrics_file.read_text(encoding="utf-8-sig").strip()
            if not text:
                raise ValueError("用户歌词文件为空")
            kind = "user_supplied"
            artifact = str(args.lyrics_file.resolve())
            report["status"] = "user_lyrics_loaded_no_asr_run"
        else:
            # 中文版本冻结与英文融合验证：注释保留被替换的原实现。
            # raw, timings = transcribe(source, args.model, output, args.force)
            # 中文版本冻结与英文融合验证：新增中英文兼容实现。
            raw, timings = transcribe(source, args.model, output, args.force, language=args.language)
            text = "\n".join(s["text"].strip() for s in raw["result"]["segments"] if s["text"].strip())
            kind = "asr_unverified"
            artifact = str(output / "asr_raw.json")
            report.update(status=timings["status"], timings=timings)
            (output / "asr_draft.txt").write_text(text + "\n", encoding="utf-8")
        reference = {"schema_version": 1, "source": source, "transcription_summary": str(summary),
                     "reference_kind": kind, "text": text,
                     "lines": [line.strip() for line in text.splitlines() if line.strip()],
                     "reference_artifact": artifact,
                     "alignment_status": "not_yet_aligned", "warnings": ["歌词文本与时间对齐质量需人工核验。"]}
        # 中文版本冻结与英文融合验证：注释保留被替换的原实现。
        # save_json(output / "lyrics_reference.json", reference)
        # 中文版本冻结与英文融合验证：新增中英文兼容实现。
        from lyrics_tokens import languages_for_text, asr_language_for_text
        reference["languages"] = languages_for_text(text)
        reference["asr_language"] = asr_language_for_text(text)
        save_json(output / "lyrics_reference.json", reference)
        report.update(source=source, reference_kind=kind, output_reference=str(output / "lyrics_reference.json"),
                      line_count=len(reference["lines"]), text_character_count=len(text))
    except Exception as exc:
        report.update(status="failed", error=f"{type(exc).__name__}: {exc}", traceback=traceback.format_exc())
    report["wall_seconds"] = time.perf_counter() - started
    save_json(ROOT / "reports" / "lyrics_asr.json", report)
    # 歌词对齐与真实制谱：新增按模型保留独立实测报告，质量对照不覆盖坏稿基线。
    save_json(ROOT / "reports" / f"lyrics_asr.{args.model}.json", report)
    print(json.dumps(report, ensure_ascii=False), flush=True)
    return 1 if report["status"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
