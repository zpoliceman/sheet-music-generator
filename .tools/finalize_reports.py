# 兼容性与样曲验证：新增本轮报告整理器，仅汇总已经落盘的本机证据。
import json
from pathlib import Path
root = Path.cwd()
def read(path):
    return json.loads((root / path).read_text(encoding='utf-8-sig'))
inventory = read('reports/audio_inventory.json')
short_pipeline = read('reports/integrated_pipeline.json')
full_pipeline = read('reports/integrated_pipeline.full.json')
full_demucs = read('reports/environment.full.json')
full_rosvot = read('test_outputs/rosvot/first_song/summary.json')
structure = read('test_outputs/rosvot/first_song/structural_validation.json')
bootstrap = read('reports/environment.bootstrap.json')
weights = read('reports/rosvot_compatibility.json')
actual_run_summary_path = Path(full_pipeline['run']['transcription_summary'])
actual_run_summary = json.loads(actual_run_summary_path.read_text(encoding='utf-8'))
report = f'''# 首曲兼容性与样曲验证

日期：2026-10-05（Asia/Shanghai）。首曲：《遇见》，209.76 秒。

## 本轮结果

已实际跑通原始 NCM → 原编码 FLAC → 完整解码 → GPU 人声分离 → GPU 音符/连续音高识别 → JSON/NPZ/MIDI 草稿。统一入口整首本次墙钟 **{full_pipeline['wall_clock_seconds']:.3f} 秒**，包含原音频核查、GPU 核查、缓存权重校验与加载、分离、转录及导出；首次软件/权重下载、歌词识别/对齐、节奏制谱和人工校正均不在这个计时范围内。

尚未生成真实歌曲的带词简谱。人工 MusicXML 样例通过的是结构和程序化回导，不代表易谱显示与导入/导出已通过。

## 素材与环境

- 十首全部还原为双声道16位FLAC，并通过完整解码；原始NCM转换前后SHA256一致。
- 七首不超过五分钟；《我不难过》《Bruce Lee》《黑夜中 (Live)》保留为范围外压力样本。
- 项目内Python3.11.14、torch/torchaudio2.7.1+cu128、Demucs4.0.1、NumPy1.26.4、librosa0.10.2.post1等依赖已锁定。
- GPU为RTX5070、CUDA运行时12.8，张量/FFT/卷积通过；未修改全局Python或注册表。
- pretty_midi缺pkg_resources问题已通过setuptools80.9.0解决；ROSVOT首次CUDA初始化调用顺序错误已修复并留存失败证据。

## 性能证据

| 实测范围 | 音频长度 | 耗时 | 口径 |
| --- | ---: | ---: | --- |
| 独立Demucs整首 | 209.76秒 | {full_demucs['checks']['demucs_short_inference']['inference_seconds']:.3f}秒 | apply_model同步前后计时，不含权重下载/加载 |
| 独立ROSVOT整首 | 209.76秒 | {full_rosvot['timings']['pipeline_seconds']:.3f}秒 | wrapper内部、含加载和音频I/O/JSON导出，不含解释器启动/导入 |
| 独立ROSVOT整进程 | 209.76秒 | 7.995秒 | 含解释器/依赖导入/权重校验/加载/I/O/导出，不含分离 |
| 统一片段入口 | 30秒 | {short_pipeline['wall_clock_seconds']:.3f}秒 | 两模型及验证/导出完整入口墙钟，已安装环境 |
| 统一整首入口 | 209.76秒 | {full_pipeline['wall_clock_seconds']:.3f}秒 | 两模型及验证/导出完整入口墙钟，已安装环境 |

独立结果与统一入口是不同运行，不能混加来声称完整产品处理时间。首次短片段模型/重采样较慢，可能受初始化和缓存影响，尚未分离测量；上述是单次基线，不是长期性能保证。

独立Demucs PyTorch峰值已分配显存约{full_demucs['checks']['demucs_short_inference']['peak_allocated_bytes'] / 2**30:.3f}GiB；独立ROSVOT约{full_rosvot['peak_gpu_allocated_bytes'] / 2**30:.3f}GiB（保留显存约{full_rosvot['peak_gpu_reserved_bytes'] / 2**30:.3f}GiB）。这里1GiB=1,073,741,824字节，是单模型进程的PyTorch统计，不是系统全部显存占用或整条产品流程峰值。

首次torch下载/解压/安装{bootstrap['torch']['download_unpack_install_seconds']:.3f}秒；ROSVOT/RWVBD/RMVPE共享归档下载{weights['download']['seconds']:.3f}秒；Demucs权重下载4.741秒。下载时间独立保留，不计入模型推理。

## 数据完整性与接口

独立整首ROSVOT：7段连续覆盖0–209.76秒，39,330帧连续f0，384个音符/休止事件，329个非休止音符；MIDI/NPZ与JSON计数、时间步一致。统一整首复验：{actual_run_summary['counts']['segments']}段、{actual_run_summary['counts']['pitch_frames']}帧、{actual_run_summary['counts']['pitched_notes']}个非休止音符，另存独立目录，不覆盖先前证据。

原始连续f0、UV、音符起止、分段原始事件和预测字边界均保留。预测字边界没有歌词文字，lyrics/note2words仍为未对齐状态。独立整首在60秒接缝有约26.7毫秒的不同音高事件重叠，已记录而未静默裁剪，接缝音乐质量尚未通过。

人工MusicXML为四小节自拟中文歌词，覆盖附点、休止、一字多音、跨小节延音、装饰音、三连音和普通连线。语义核查与另存校正版JSON通过；本机未找到易谱/MuseScore，真实写谱软件往返尚未实测。

## 可重复执行

```powershell
.\\run_validation.ps1 -Stage AudioAll
.\\run_validation.ps1 -Stage Notation
.\\run_validation.ps1 -Stage GPU
.\\run_models.ps1
.\\run_models.ps1 -Full
```

模型入口默认30秒片段，-Full处理整首；每次串行运行模型并另存test_outputs/runs及reports/runs。原素材始终保留；素材缓存绑定源与产物SHA256，片段清单绑定源音频/参数/产物哈希并核对实际WAV帧数。

## 后续任务

1. 人工试听分离人声并对照MIDI/连续音高，建立音高、漏音、节奏与修谱时间基线。
2. 处理并验证分段接缝，保留原始分析，避免直接裁剪丢失演唱细节。
3. 接入自动歌词识别与用户歌词覆盖，再做实际歌声逐字对齐和字音映射。
4. 完成节拍/拍号/调性/时值整理，导出真实歌曲带词MusicXML，并验证易谱实际编辑往返。
5. 样曲通过后扩展范围内七首，再测三首压力样本；以后才进入吉他编配和应用界面。

证据入口：reports/audio_validation.md、reports/environment.md、reports/rosvot_compatibility.md、reports/notation_compatibility.md、reports/integrated_pipeline.full.json。完整日志见progress.md，当前计划见todo.md。
'''
(root / 'reports/first_sample.md').write_text(report, encoding='utf-8')
readme = (root / 'README.md').read_text(encoding='utf-8-sig')
readme = readme.replace('- GPU 模型环境及推理仍在验证；结果会写入 reports，不以文档能力代替实测。', '- GPU 张量、FFT、卷积及 Demucs/ROSVOT 短片段与整首推理通过；《遇见》音频到转录数据/MIDI 的本次完整入口墙钟约16.94秒，不含歌词识别对齐、节奏制谱或首次下载。')
readme = readme.replace('- 人工 MusicXML 样例仅用于格式兼容检查，明确不是音频转谱效果样例；写谱软件实际导入、修改、导出尚待验证。', '- 人工 MusicXML 语义与程序化校正版回导通过；它不是音频转谱效果样例，易谱实际往返尚待验证。真实歌曲歌词、节奏制谱、接缝音乐质量仍待完成。')
readme = readme.replace('.\\run_validation.ps1 -Stage GPU\n', '.\\run_validation.ps1 -Stage GPU\n.\\run_models.ps1\n.\\run_models.ps1 -Full\n')
readme = readme.replace('素材检查可重复执行，已有还原文件复用并重新完整解码。测试片段已有时保留原产物；避免把转换缓存命中时间当作首次转换耗时。', '素材检查可重复执行，源与产物SHA256一致的还原缓存复用，并重新完整解码。片段核对真实帧数且同参数可复用；不同参数独立输出。模型入口默认30秒片段，-Full处理整首，每次另存独立报告与输出目录；避免把缓存命中时间当作首次下载或转换耗时。')
readme = readme.replace('- [项目素材验证报告](reports/audio_validation.md)', '- [首曲验证汇总](reports/first_sample.md)\n- [项目素材验证报告](reports/audio_validation.md)\n- [本机模型环境及依赖锁](reports/environment.md)\n- [ROSVOT实测](reports/rosvot_compatibility.md)\n- [MusicXML编辑兼容检查](reports/notation_compatibility.md)')
(root / 'README.md').write_text(readme, encoding='utf-8')
print(json.dumps({'full_wall_clock_seconds': full_pipeline['wall_clock_seconds'], 'full_run_counts': actual_run_summary['counts'], 'summary': str(root / 'reports/first_sample.md')}, ensure_ascii=False))
