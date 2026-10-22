# 兼容性与样曲验证：新增隔离环境、真实 GPU 运算与 Demucs 基线验证工具。
from __future__ import annotations

import argparse
import contextlib
import ctypes  # 兼容性与样曲验证：新增 Windows 进程峰值内存记录。
import hashlib
import importlib.metadata
import json
import os
import pickle  # 兼容性与样曲验证：精确识别旧权重加载兼容错误。
import re  # 兼容性与样曲验证：从官方权重文件名提取 SHA256 校验前缀。
import random  # 兼容性与样曲验证：固定 Demucs 随机平移，便于复现后续测试。
from pathlib import Path
import platform
import subprocess
import sys
import time
import traceback


# 兼容性与样曲验证：所有分析缓存和报告限定在项目目录内。
ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / ".cache" / "torch"
REPORT = ROOT / "reports" / "environment.json"
os.environ["TORCH_HOME"] = str(CACHE)
os.environ.setdefault("HF_HOME", str(ROOT / ".cache" / "huggingface"))


# 兼容性与样曲验证：逐步保存证据，失败时也保留错误与已完成结果。
def save_report(report: dict) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = ["# 隔离 GPU 环境验证", "", f"- 时间：{report['checked_at_local']}",
             f"- Python：{report['python']['version']}", f"- 解释器：{report['python']['executable']}"]
    for name, version in report.get("packages", {}).items():
        lines.append(f"- {name}：{version}")
    lines += ["", "## 验证结果", ""]
    for name, result in report.get("checks", {}).items():
        lines.append(f"- {name}：{result['status']}，耗时 {result.get('seconds', 0):.3f} 秒")
        if result.get("error"):
            lines.append(f"  - 错误：{result['error']}")
    lines += ["", "细节与原始错误保存在 environment.json。首次下载和推理单独计时。", "",
              "官方依据：https://pytorch.org/get-started/previous-versions/ 、https://pytorch.org/blog/pytorch-2-7/ 、https://github.com/facebookresearch/demucs", ""]
    REPORT.with_suffix(".md").write_text("\n".join(lines), encoding="utf-8")


# 兼容性与样曲验证：同步 GPU 后计时，避免只测到异步任务提交时间。
def timed_check(report: dict, name: str, action) -> dict:
    started = time.perf_counter()
    try:
        result = action() or {}
        result.update(status="passed", seconds=round(time.perf_counter() - started, 6))
    except Exception as exc:
        result = {"status": "failed", "seconds": round(time.perf_counter() - started, 6),
                  "error": f"{type(exc).__name__}: {exc}", "traceback": traceback.format_exc()}
    report["checks"][name] = result
    # 兼容性与样曲验证：每步附加本进程内存，支持本机容量与性能评估。
    if os.name == "nt":
        class MemoryCounters(ctypes.Structure):
            _fields_ = [("cb", ctypes.c_ulong), ("PageFaultCount", ctypes.c_ulong),
                        ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
        counters = MemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        # 兼容性与样曲验证：修改；明确 64 位句柄类型，避免 ctypes 默认 int 截断。
        # process = ctypes.windll.kernel32.GetCurrentProcess()
        # if ctypes.windll.psapi.GetProcessMemoryInfo(process, ctypes.byref(counters), counters.cb):
        current_process = ctypes.windll.kernel32.GetCurrentProcess
        current_process.restype = ctypes.c_void_p
        memory_info = ctypes.windll.psapi.GetProcessMemoryInfo
        memory_info.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong]
        process = current_process()
        if memory_info(process, ctypes.byref(counters), counters.cb):
            result["process_peak_working_set_bytes"] = counters.PeakWorkingSetSize
            result["process_working_set_bytes"] = counters.WorkingSetSize
    save_report(report)
    print(json.dumps({"check": name, **result}, ensure_ascii=False), flush=True)
    return result


# 兼容性与样曲验证：检查实际执行的 GPU 算子及数值有效性。
def check_gpu() -> dict:
    import torch
    if not torch.cuda.is_available():
        raise RuntimeError("torch.cuda.is_available() 为 False")
    torch.manual_seed(20261005)
    random.seed(20261005)  # 兼容性与样曲验证：新增固定随机平移种子。
    torch.cuda.reset_peak_memory_stats()
    device = torch.device("cuda")
    x = torch.randn(128, 128, device=device)
    matrix = x @ x.T
    wave = torch.randn(2, 44100, device=device)
    spectrum = torch.fft.rfft(wave)
    restored = torch.fft.irfft(spectrum, n=wave.shape[-1])
    conv = torch.nn.Conv1d(2, 16, 7, padding=3).to(device)
    convolved = conv(wave[None])
    torch.cuda.synchronize()
    error = float((restored - wave).abs().max().item())
    if not (torch.isfinite(matrix).all() and torch.isfinite(convolved).all() and error < 1e-4):
        raise RuntimeError(f"GPU 计算数值异常：FFT 最大误差 {error}")
    return {"name": torch.cuda.get_device_name(0), "capability": list(torch.cuda.get_device_capability(0)),
            "cuda_runtime": torch.version.cuda, "compiled_arches": torch.cuda.get_arch_list(),
            "memory_total_bytes": torch.cuda.get_device_properties(0).total_memory,
            "matrix_shape": list(matrix.shape), "conv_shape": list(convolved.shape),
            "fft_roundtrip_max_error": error, "peak_allocated_bytes": torch.cuda.max_memory_allocated()}


# 兼容性与样曲验证：仅为官方 Demucs 权重加载临时启用旧格式兼容，退出后恢复进程环境。
@contextlib.contextmanager
def legacy_official_demucs_checkpoint():
    key = "TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD"
    previous = os.environ.get(key)
    os.environ[key] = "1"
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = previous


# 兼容性与样曲验证：先独立下载和加载模型，保留官方缓存路径及完整校验值。
def prepare_demucs(report: dict):
    # 兼容性与样曲验证：修改；先从已安装的官方清单下载，单独计时与校验。
    # from demucs.pretrained import get_model
    from demucs.pretrained import get_model, REMOTE_ROOT, _parse_remote_files
    import torch
    import yaml
    manifests = _parse_remote_files(REMOTE_ROOT / "files.txt")
    bag = yaml.safe_load((REMOTE_ROOT / "htdemucs.yaml").read_text(encoding="utf-8"))
    def download():
        files = []
        for signature in bag["models"]:
            url = manifests[signature]
            if not url.startswith("https://dl.fbaipublicfiles.com/demucs/"):
                raise ValueError(f"不是官方 Demucs 权重来源：{url}")
            name = url.rsplit("/", 1)[-1]
            prefix_match = re.search(r"-([a-f0-9]+)\.th$", name)
            if not prefix_match:
                raise ValueError(f"官方文件名没有校验前缀：{name}")
            target = CACHE / "hub" / "checkpoints" / name
            target.parent.mkdir(parents=True, exist_ok=True)
            was_cached = target.is_file()
            if not was_cached:
                torch.hub.download_url_to_file(url, target, hash_prefix=prefix_match.group(1), progress=True)
            digest = hashlib.sha256(target.read_bytes()).hexdigest()
            if not digest.startswith(prefix_match.group(1)):
                raise ValueError(f"权重校验不符：{target}")
            files.append({"path": str(target), "source": url, "bytes": target.stat().st_size,
                          "sha256": digest, "cached_before_run": was_cached})
        return {"files": files}
    downloaded = timed_check(report, "demucs_weight_download", download)
    if downloaded["status"] != "passed":
        return None
    model_holder = {}
    def load():
        # 兼容性与样曲验证：修改；原先直接启用旧格式，现先验证默认加载再按实际错误适配。
        # with legacy_official_demucs_checkpoint():
        #     model = get_model("htdemucs")
        compatibility = "默认 torch 权重加载接口成功，不需要旧格式适配。"
        try:
            model = get_model("htdemucs")
        except pickle.UnpicklingError as exc:
            report["demucs_default_load_error"] = str(exc)
            if "Weights only load failed" not in str(exc):
                raise
            with legacy_official_demucs_checkpoint():
                model = get_model("htdemucs")
            compatibility = "实际遇到 Weights only load failed；仅官方 Demucs 权重加载期间临时设置 TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD=1。"
        model.eval()
        model_holder["model"] = model
        cached = [{"path": str(path), "bytes": path.stat().st_size,
                   "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                  for path in sorted((CACHE / "hub" / "checkpoints").glob("*.th"))]
        return {"model": "htdemucs", "sources": list(model.sources), "samplerate": model.samplerate,
                "audio_channels": model.audio_channels, "weights": cached,
                # 兼容性与样曲验证：修改；报告实测是否触发兼容路径，保留原说明作为注释。
                # "compatibility": "仅官方 Demucs 权重加载期间设置 TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD=1；第三方任意权重不使用此入口。"}
                "compatibility": compatibility}
    # 兼容性与样曲验证：修改；原下载与加载合并计时，现独立记录模型初始化。
    # result = timed_check(report, "demucs_download_and_load", load)
    result = timed_check(report, "demucs_model_load", load)
    return model_holder.get("model") if result["status"] == "passed" else None


# 兼容性与样曲验证：对真实短片段按官方分块逻辑推理，保存人声与伴奏供人工试听。
def separate_audio(model, audio_path: Path, output_dir: Path) -> dict:
    import numpy as np
    import soundfile as sf
    import torch
    import torchaudio
    from demucs.apply import apply_model
    audio, samplerate = sf.read(audio_path, dtype="float32", always_2d=True)
    mix = torch.from_numpy(audio.T.copy())
    if samplerate != model.samplerate:
        mix = torchaudio.functional.resample(mix, samplerate, model.samplerate)
    if mix.shape[0] == 1:
        mix = mix.repeat(2, 1)
    if mix.shape[0] != model.audio_channels:
        raise ValueError(f"不支持的输入声道数：{mix.shape[0]}")
    ref = mix.mean(0)
    std = ref.std()
    if not torch.isfinite(std) or std < 1e-8:
        raise ValueError("输入片段静音或数值无效")
    mean = ref.mean()
    normalized = (mix - mean) / std
    torch.cuda.reset_peak_memory_stats()
    torch.cuda.synchronize()
    inference_start = time.perf_counter()
    with torch.inference_mode():
        sources = apply_model(model, normalized[None], device="cuda", shifts=1,
                              split=True, overlap=0.25, segment=7, progress=True)[0]
    torch.cuda.synchronize()
    inference_seconds = time.perf_counter() - inference_start
    sources = sources.cpu() * std + mean
    output_dir.mkdir(parents=True, exist_ok=True)
    files = {}
    for name, source in zip(model.sources, sources):
        target = output_dir / f"{name}.wav"
        sf.write(target, source.numpy().T, model.samplerate, subtype="FLOAT")
        files[name] = str(target)
    vocal_index = list(model.sources).index("vocals")
    accompaniment = sources.sum(0) - sources[vocal_index]
    target = output_dir / "accompaniment.wav"
    sf.write(target, accompaniment.numpy().T, model.samplerate, subtype="FLOAT")
    files["accompaniment"] = str(target)
    # 兼容性与样曲验证：修改；保存实际编码、帧数等信息，原时长读取保留为注释。
    # durations = [sf.info(path).duration for path in files.values()]
    audio_info = {}
    for name, path in files.items():
        info = sf.info(path)
        audio_info[name] = {"samplerate": info.samplerate, "channels": info.channels,
                            "frames": info.frames, "duration": info.duration,
                            "format": info.format, "subtype": info.subtype}
    durations = [info["duration"] for info in audio_info.values()]
    if not np.isfinite(sources.numpy()).all() or max(durations) - min(durations) > 1 / model.samplerate:
        raise RuntimeError("分离输出非有限值或长度不一致")
    return {"input": str(audio_path), "input_duration_seconds": len(audio) / samplerate,
            "output_duration_seconds": durations[0], "inference_seconds": round(inference_seconds, 6),
            "settings": {"shifts": 1, "segment_seconds": 7, "overlap": 0.25, "device": "cuda"},
            "peak_allocated_bytes": torch.cuda.max_memory_allocated(),
            # 兼容性与样曲验证：修改；输出结构加入实际音频编码，保留原报告字段作注释。
            # "outputs": files, "quality": "仅验证运行及输出结构；需人工试听，不代表分离质量通过。"}
            "outputs": files, "output_audio_info": audio_info,
            "random_shift_seed": 20261005,
            "quality": "仅验证运行及输出结构；需人工试听，不代表分离质量通过。"}


# 兼容性与样曲验证：命令行区分环境检查、权重准备和真实音频推理。
def main() -> int:
    global REPORT  # 兼容性与样曲验证：短片段与整首使用各自报告路径，保留独立证据。
    parser = argparse.ArgumentParser(description="项目内隔离 GPU 与 Demucs 基线验证")
    parser.add_argument("--prepare-demucs", action="store_true")
    parser.add_argument("--audio", type=Path)
    parser.add_argument("--report", type=Path, default=REPORT)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "artifacts" / "demucs_baseline")
    args = parser.parse_args()
    REPORT = args.report.resolve()
    report = {"checked_at_local": time.strftime("%Y-%m-%d %H:%M:%S"), "project_root": str(ROOT),
              "python": {"version": platform.python_version(), "executable": sys.executable,
                         "prefix": sys.prefix, "base_prefix": sys.base_prefix}, "packages": {}, "checks": {}}
    # 兼容性与样曲验证：修改；uv 为独立工具，避免按 Python 包误报为未安装。
    # for name in ("torch", "torchaudio", "demucs", "numpy", "soundfile", "librosa", "uv"):
    for name in ("torch", "torchaudio", "demucs", "numpy", "soundfile", "librosa"):
        try:
            report["packages"][name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            report["packages"][name] = "未安装"
    uv_path = ROOT / ".runtime" / "uv" / "uv.exe"
    # uv只用于安装，不是已安装模型的运行依赖。
    uv_version = subprocess.run([str(uv_path), "--version"], capture_output=True, text=True).stdout.strip() if uv_path.is_file() else "not_installed_not_required_for_inference"
    report["runtime_tools"] = {"uv": uv_version}
    driver = subprocess.run(["nvidia-smi", "--query-gpu=name,driver_version,memory.total,compute_cap",
                             "--format=csv,noheader"], capture_output=True, text=True)
    report["driver_raw"] = driver.stdout.strip()
    gpu = timed_check(report, "cuda_tensor_fft_conv", check_gpu)
    if gpu["status"] != "passed":
        return 1
    if args.prepare_demucs or args.audio:
        model = prepare_demucs(report)
        if model is None:
            return 1
        if args.audio:
            result = timed_check(report, "demucs_short_inference",
                                 lambda: separate_audio(model, args.audio.resolve(), args.output_dir.resolve()))
            if result["status"] != "passed":
                return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
