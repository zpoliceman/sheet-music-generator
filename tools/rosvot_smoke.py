"""兼容性与样曲验证：单进程调用官方 ROSVOT，并保留原始分析时间轴。"""
from __future__ import annotations

# 兼容性与样曲验证：新增命令行、校验、计时与可复现元数据工具。
import argparse
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.metadata
import json
import math
from pathlib import Path
import platform
import subprocess
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def arguments():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--repo", type=Path, default=ROOT / "third_party" / "ROSVOT")
    parser.add_argument("--check-imports", action="store_true")
    parser.add_argument("--source-offset-seconds", type=float, default=0.0)
    parser.add_argument("--segment-seconds", type=float, default=30.0)
    parser.add_argument("--context-seconds", type=float, default=1.0)
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--note-threshold", type=float, default=0.85)
    parser.add_argument("--word-threshold", type=float, default=0.5)
    args = parser.parse_args()
    if not args.check_imports and (args.input is None or args.output_dir is None):
        parser.error("--input and --output-dir are required for inference")
    if args.segment_seconds <= 0 or args.context_seconds < 0 or args.source_offset_seconds < 0:
        parser.error("Invalid segment/context/source offset")
    return args


# 兼容性与样曲验证：新增延迟导入；检查模式不加载权重或执行 GPU 计算。
def load_dependencies(repo):
    sys.path.insert(0, str(repo))
    import numpy as np
    import torch
    import librosa
    import soundfile as sf
    import yaml
    import pretty_midi
    from modules.pe.rmvpe import RMVPE
    from modules.rosvot.rosvot import MidiExtractor, WordbdExtractor
    from utils.audio.mel import MelNet
    from utils.audio.pitch_utils import norm_interp_f0, denorm_f0, f0_to_coarse, boundary2Interval
    from utils.commons.ckpt_utils import load_ckpt
    from utils.commons.dataset_utils import pad_or_cut_xd
    return locals()


def package_versions():
    names = ("torch", "torchaudio", "numpy", "librosa", "soundfile", "scipy", "PyYAML", "pretty_midi", "pyworld")
    return {name: importlib.metadata.version(name) for name in names}


# 兼容性与样曲验证：新增阶段同步计时，模型下载从独立来源记录读取，不计入推理。
def infer(args, deps):
    np, torch, sf = deps["np"], deps["torch"], deps["sf"]
    repo = args.repo.resolve()
    output = args.output_dir.resolve()
    input_path = args.input.resolve(strict=True)
    if output == input_path.parent or output == repo:
        raise ValueError("Use a separate inference output directory")
    output.mkdir(parents=True, exist_ok=True)
    if (output / "analysis.json").exists():
        raise FileExistsError("analysis.json already exists; use a new output directory")
    started = time.perf_counter()
    timing = defaultdict(float)
    device = torch.device(args.device)
    if device.type == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("Requested CUDA is not available; no silent CPU fallback")
    if device.type == "cuda":
        # 兼容性与样曲验证：注释原先未初始化上下文的显存重置调用，修正执行顺序。
        # torch.cuda.reset_peak_memory_stats(device)
        torch.cuda.init()  # 兼容性与样曲验证：新增显式 CUDA 上下文初始化。
        torch.cuda.set_device(device)
        torch.cuda.reset_peak_memory_stats(device)
    torch.set_grad_enabled(False)
    torch.manual_seed(42)

    def timed(label, fn):
        if device.type == "cuda":
            torch.cuda.synchronize(device)
        t0 = time.perf_counter()
        result = fn()
        if device.type == "cuda":
            torch.cuda.synchronize(device)
        timing[label] += time.perf_counter() - t0
        return result

    # 兼容性与样曲验证：新增官方归档校验，避免以不同权重冒充已记录的模型。
    provenance_path = ROOT / "reports" / "rosvot_compatibility.json"
    if not provenance_path.is_file():
        provenance_path = ROOT / "config" / "rosvot_weights.json"
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    weight_files = []
    for item in provenance["files"]:
        local_path = ROOT / item["path"]
        actual_sha = sha256(local_path)
        if actual_sha != item["sha256"]:
            raise ValueError(f"Checkpoint/config hash mismatch: {local_path}")
        weight_files.append({"path": str(local_path), "sha256": actual_sha, "bytes": local_path.stat().st_size})
    config = deps["yaml"].safe_load((repo / "checkpoints/rosvot/config.yaml").read_text(encoding="utf-8"))
    word_config = deps["yaml"].safe_load((repo / "checkpoints/rwbd/config.yaml").read_text(encoding="utf-8"))
    config["note_bd_threshold"] = args.note_threshold
    word_config["word_bd_threshold"] = args.word_threshold
    sr, hop = config["audio_sample_rate"], config["hop_size"]
    if (word_config["audio_sample_rate"], word_config["hop_size"]) != (sr, hop):
        raise ValueError("ROSVOT and RWBD timing configurations differ")
    step = hop / sr

    # 兼容性与样曲验证：新增独立模型加载计时；沿用官方结构与严格参数检查。
    def load_network(cls, settings, name):
        model = cls(settings)
        deps["load_ckpt"](model, str(repo / "checkpoints" / name / "model.pt"), verbose=False)
        return model.eval().to(device)
    rmvpe = timed("load_rmvpe_seconds", lambda: deps["RMVPE"](str(repo / "checkpoints/rmvpe/model.pt"), device=device))
    word_model = timed("load_rwbd_seconds", lambda: load_network(deps["WordbdExtractor"], word_config, "rwbd"))
    note_model = timed("load_rosvot_seconds", lambda: load_network(deps["MidiExtractor"], config, "rosvot"))
    mel_model = deps["MelNet"](config)
    mel_model.to(device)

    # 兼容性与样曲验证：新增只读解码与单声道重采样，原始素材不改写。
    def decode_audio():
        audio, source_sr = sf.read(str(input_path), dtype="float32", always_2d=True)
        if len(audio) == 0 or not np.isfinite(audio).all():
            raise ValueError("Empty or non-finite audio")
        channels = audio.shape[1]
        mono = np.mean(audio, axis=1)
        if source_sr != sr:
            mono = deps["librosa"].resample(mono, orig_sr=source_sr, target_sr=sr)
        return mono.astype(np.float32), source_sr, channels
    audio, input_sr, input_channels = timed("decode_resample_seconds", decode_audio)
    duration = len(audio) / sr
    core_samples = max(hop, int(args.segment_seconds * sr) // hop * hop)
    context_samples = int(args.context_seconds * sr) // hop * hop
    notes, words, frames, segments = [], [], [], []
    raw_arrays = {}

    # 兼容性与样曲验证：新增分段上下文及所有原始片段输出；接缝结果仍需人工核验。
    # 兼容性与样曲验证：注释原固定范围迭代，合并重采样舍入造成的不足一帧尾段。
    # for index, core_start in enumerate(range(0, len(audio), core_samples)):
    #     core_end = min(len(audio), core_start + core_samples)
    core_starts = list(range(0, len(audio), core_samples))
    if len(core_starts) > 1 and len(audio) - core_starts[-1] < hop:
        core_starts.pop()
    for index, core_start in enumerate(core_starts):
        core_end = core_starts[index + 1] if index + 1 < len(core_starts) else len(audio)
        begin = max(0, core_start - context_samples)
        end = min(len(audio), core_end + context_samples)
        waveform = torch.from_numpy(audio[begin:end]).unsqueeze(0).to(device)
        real_frames = math.ceil((end - begin) / hop)
        if end - begin < config["fft_size"]:
            raise ValueError("Audio segment is too short for the model")
        multiple = math.lcm(config["frames_multiple"], word_config["frames_multiple"])
        padded_frames = math.ceil(real_frames / multiple) * multiple
        f0s, uv_flags = timed("infer_rmvpe_seconds", lambda: rmvpe.get_pitch_batch(
            waveform, sample_rate=sr, hop_size=hop, lengths=[real_frames],
            fmin=config["f0_min"], fmax=config["f0_max"]))
        original_f0, original_uv = f0s[0].copy(), uv_flags[0].copy()
        normalized, uv = deps["norm_interp_f0"](original_f0.copy())
        normalized = deps["pad_or_cut_xd"](torch.tensor(normalized, dtype=torch.float32), padded_frames, 0)
        uv_tensor = deps["pad_or_cut_xd"](torch.tensor(uv, dtype=torch.float32), padded_frames, 0)
        pitch = deps["f0_to_coarse"](deps["denorm_f0"](normalized, uv_tensor)).unsqueeze(0).to(device)
        uv_tensor = uv_tensor.long().unsqueeze(0).to(device)
        mel = timed("mel_seconds", lambda: mel_model(waveform))
        mel = deps["pad_or_cut_xd"](mel, padded_frames, 1)
        mask = torch.arange(padded_frames, device=device).unsqueeze(0) < real_frames
        mel = mel * mask.unsqueeze(-1)
        word_out = timed("infer_rwbd_seconds", lambda: word_model(
            mel=mel[:, :, :word_config["use_mel_bins"]], pitch=pitch,
            uv=uv_tensor, non_padding=mask, train=False))
        word_boundary = word_out["word_bd_pred"]
        note_out = timed("infer_rosvot_seconds", lambda: note_model(
            mel=mel[:, :, :config["use_mel_bins"]], word_bd=word_boundary,
            pitch=pitch, uv=uv_tensor, non_padding=mask, train=False))
        count = int(note_out["note_lengths"][0].item())
        pitches = note_out["note_pred"][0, :count].cpu().numpy()
        note_bd = note_out["note_bd_pred"][0, :real_frames].cpu().numpy()
        word_bd = word_boundary[0, :real_frames].cpu().numpy()
        intervals = deps["boundary2Interval"](note_bd)
        if len(intervals) != len(pitches):
            raise ValueError("Note boundary/pitch count mismatch")
        relative_start = begin / sr
        absolute_start = args.source_offset_seconds + relative_start
        owner_start = args.source_offset_seconds + core_start / sr
        owner_end = args.source_offset_seconds + core_end / sr
        segment_notes = []
        for local_index, (pitch_value, interval) in enumerate(zip(pitches, intervals)):
            start_s = absolute_start + int(interval[0]) * step
            end_s = absolute_start + int(interval[1]) * step
            event = {"segment": index, "local_index": local_index,
                     "pitch_midi": int(pitch_value), "is_rest": int(pitch_value) == 0,
                     "start_seconds": start_s, "end_seconds": end_s,
                     "note2words": None, "lyrics": None}
            segment_notes.append(event)
            if end_s > start_s and owner_start <= (start_s + end_s) / 2 < owner_end:
                notes.append(event.copy())
        word_intervals = deps["boundary2Interval"](word_bd)
        segment_words = []
        for local_index, interval in enumerate(word_intervals):
            start_s = absolute_start + int(interval[0]) * step
            end_s = absolute_start + int(interval[1]) * step
            event = {"segment": index, "local_index": local_index,
                     "start_seconds": start_s, "end_seconds": end_s, "text": None}
            segment_words.append(event)
            if end_s > start_s and owner_start <= (start_s + end_s) / 2 < owner_end:
                words.append(event.copy())
        for frame_index, frequency in enumerate(original_f0):
            frame_time = absolute_start + frame_index * step
            if owner_start <= frame_time < owner_end:
                frames.append({"time_seconds": frame_time, "f0_hz": float(frequency),
                               "unvoiced": bool(original_uv[frame_index])})
        raw_arrays[f"segment_{index}_f0_hz"] = original_f0
        raw_arrays[f"segment_{index}_unvoiced"] = original_uv
        raw_arrays[f"segment_{index}_note_boundaries"] = note_bd
        raw_arrays[f"segment_{index}_word_boundaries"] = word_bd
        raw_arrays[f"segment_{index}_note_boundary_probability"] = torch.sigmoid(note_out["note_bd_logits"])[0, :real_frames].cpu().numpy()
        raw_arrays[f"segment_{index}_word_boundary_probability"] = torch.sigmoid(word_out["word_bd_logits"])[0, :real_frames].cpu().numpy()
        segments.append({"index": index, "start_seconds": absolute_start,
                         "end_seconds": args.source_offset_seconds + end / sr,
                         "core_start_seconds": owner_start, "core_end_seconds": owner_end,
                         "frames": real_frames, "raw_notes": segment_notes,
                         "raw_word_segments": segment_words})
        print(json.dumps({"segment": index, "core_end_seconds": owner_end,
                          "notes_so_far": len(notes)}, ensure_ascii=False), flush=True)

    # 兼容性与样曲验证：新增统一 JSON、可复核 NPZ 与试听 MIDI；不宣称已有歌词对齐或量化乐谱。
    notes.sort(key=lambda x: (x["start_seconds"], x["end_seconds"]))
    words.sort(key=lambda x: x["start_seconds"])
    frames.sort(key=lambda x: x["time_seconds"])
    midi = deps["pretty_midi"].PrettyMIDI()
    voice = deps["pretty_midi"].Instrument(program=0, name="ROSVOT vocal draft")
    for note in notes:
        if 0 < note["pitch_midi"] <= 127 and note["end_seconds"] > note["start_seconds"]:
            voice.notes.append(deps["pretty_midi"].Note(velocity=90, pitch=note["pitch_midi"],
                start=note["start_seconds"] - args.source_offset_seconds,
                end=note["end_seconds"] - args.source_offset_seconds))
    midi.instruments.append(voice)
    midi.write(str(output / "vocal_draft.mid"))
    np.savez_compressed(output / "raw_arrays.npz", **raw_arrays)
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    result = {"schema_version": 1, "task": "兼容性与样曲验证", "status": "inference_completed_quality_unverified",
              "recorded_at": datetime.now(timezone(timedelta(hours=8))).isoformat(),
              "source": {"path": str(input_path), "sha256": sha256(input_path),
                         "sample_rate": input_sr, "channels": input_channels,
                         "duration_seconds": duration, "offset_seconds": args.source_offset_seconds},
              "runtime": {"python": platform.python_version(), "packages": package_versions(),
                          "device": str(device), "gpu_name": torch.cuda.get_device_name(device) if device.type == "cuda" else None,
                          "torch_cuda": torch.version.cuda, "upstream_commit": commit,
                          "wrapper_sha256": sha256(__file__), "weights": weight_files},
              "configuration": {"sample_rate": sr, "hop_size": hop, "frame_step_seconds": step,
                                "segment_seconds": args.segment_seconds, "context_seconds": args.context_seconds,
                                "note_threshold": args.note_threshold, "word_threshold": args.word_threshold,
                                "f0_min": config["f0_min"], "f0_max": config["f0_max"]},
              "download": provenance["download"], "timings": dict(timing),
              "peak_gpu_allocated_bytes": torch.cuda.max_memory_allocated(device) if device.type == "cuda" else None,
              "peak_gpu_reserved_bytes": torch.cuda.max_memory_reserved(device) if device.type == "cuda" else None,
              "alignment": {"lyrics_available": False, "word_boundary_source": "RWBD prediction only",
                            "note2words": None, "status": "not_aligned_to_lyrics"},
              "stitching": "Keep segment events whose midpoint lies in its core; original segment events are retained. Seam quality is unverified.",
              "notes": notes, "predicted_word_segments": words, "pitch_frames": frames, "segments": segments}
    result["timings"]["pipeline_before_json_export_seconds"] = time.perf_counter() - started
    write_json(output / "analysis.json", result)
    result["timings"]["pipeline_seconds"] = time.perf_counter() - started
    summary = {key: value for key, value in result.items() if key not in ("notes", "predicted_word_segments", "pitch_frames", "segments")}
    summary["counts"] = {"note_events": len(notes), "pitched_notes": len(voice.notes), "pitch_frames": len(frames), "segments": len(segments)}
    summary["artifacts"] = {name: str(output / name) for name in ("analysis.json", "raw_arrays.npz", "vocal_draft.mid")}
    write_json(output / "summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


# 兼容性与样曲验证：新增失败记录，保存异常证据而不报告为推理通过。
def main():
    args = arguments()
    try:
        deps = load_dependencies(args.repo.resolve())
        if args.check_imports:
            print(json.dumps({"status": "imports_ok", "python": platform.python_version(), "packages": package_versions()}, ensure_ascii=False, indent=2))
            return 0
        return infer(args, deps)
    except Exception as exc:
        error = {"status": "failed", "error_type": type(exc).__name__, "message": str(exc), "traceback": traceback.format_exc()}
        if args.output_dir:
            args.output_dir.mkdir(parents=True, exist_ok=True)
            write_json(args.output_dir / "failure.json", error)
        print(json.dumps(error, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
