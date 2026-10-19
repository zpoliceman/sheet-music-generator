# 自动乐谱生成器

在Windows本机分析歌曲音频，生成人声简谱、歌词和吉他伴奏谱，并提供网页看谱、试听与PDF／整套JPG下载。右手编辑器支持55种4/4拍分解、合拨和扫弦，可按小节选择、调整时值并另存版本。

统一网页支持朋友凭访问码上传MP3／NCM音源和TXT歌词。**新上传素材的整首自动制谱尚未接入网页**，初次制谱使用下方脚本；网页下载和右手编辑需要已有的伴奏工程。自动制谱结果需要人工核对。

## 配置环境

使用64位Windows、PowerShell和Python 3.11。完整制谱需要支持CUDA（Compute Unified Device Architecture，统一计算设备架构）的NVIDIA显卡及驱动。网页打印需要默认位置安装的Google Chrome和微软雅黑字体。

在项目根目录打开PowerShell，建立模型环境并安装依赖：

```powershell
py -3.11 -m venv .venv-gpu
.\.venv-gpu\Scripts\python.exe -m pip install torch==2.7.1 torchaudio==2.7.1 --index-url https://download.pytorch.org/whl/cu128
.\.venv-gpu\Scripts\python.exe -m pip install -r requirements.txt
.\.venv-gpu\Scripts\python.exe -B tools/initialize_workspace.py
```

第二行安装本项目当前使用的CUDA 12.8版PyTorch；驱动需支持该版本。最后一行创建空白复核配置，已有配置保持原样。`requirements.txt`列出主流程直接依赖，`requirements-staff.txt`列出五线谱渲染依赖。

完整制谱还需准备以下外部文件，安装环境、模型权重和个人歌曲均不包含在仓库内：

| 外部依赖 | 放置位置或配置要求 |
| --- | --- |
| FFmpeg的`ffmpeg.exe`、`ffprobe.exe` | 放入`.tools/ffmpeg/任意版本/bin/`，并将该目录加入当前终端的`PATH`环境变量。 |
| NCM转换工具`ncmdump.exe` | 放入`.tools/ncmdump/`；当前音频检查入口会检查该工具，即使输入为MP3也需准备。 |
| [ROSVOT](https://github.com/RickyL-2000/ROSVOT) | 代码放入`third_party/ROSVOT/`；按上游说明下载权重，使`checkpoints/rosvot/model.pt`、`checkpoints/rwbd/model.pt`和`checkpoints/rmvpe/model.pt`存在。当前接入版本为`3c8332b`。 |
| [TIFA](https://github.com/openvpi/TIFA) | 代码放入`third_party/TIFA/`；按上游说明准备TIFA-1.0-ST模型及配套配置，放入`.cache/tifa/model/TIFA-1.0-ST/`。当前接入版本为`614a277`。 |

Demucs、Whisper及节拍模型首次使用时可能联网下载。以上为当前工程的安装入口，尚未在全新电脑完成整套安装验证；第三方模型和权重需要单独准备，安装Python依赖不等于全部模型已经就绪。

## 从歌曲制谱

把音源和UTF-8编码的歌词放入自行创建的`test_music/`。在根目录依次执行；将示例文件名和“实际编号”替换为自己的文件及上一步输出路径：

```powershell
.\run_models.ps1 -Full -Song '歌曲.mp3'
.\run_score.ps1 -ModelReport 'reports/runs/实际编号/integrated_pipeline.json' -LyricsFile 'test_music/歌曲.txt'
.\run_accompaniment.ps1 -VocalProject 'test_outputs/score_runs/实际编号/score/project.json' -DemucsReport 'reports/runs/实际编号/demucs.json' -Output 'test_outputs/accompaniment_runs/my_song/delivery' -AnalysisDir 'test_outputs/accompaniment_runs/my_song/analysis' -ExportVocal
```

三步分别执行音频分析、人声与歌词制谱、伴奏编配。每首歌使用新的输出目录；结果和报告保存在终端显示的路径。程序不会自动把待检查结果发布到正常曲谱库。

## 打开网页

统一网页先安装独立依赖，再启动：

```powershell
.\HTML\准备环境.ps1
.\HTML\启动网页.cmd
```

本机网址为[http://127.0.0.1:8768/](http://127.0.0.1:8768/)。管理员访问码保存在`HTML/runtime/app/管理员访问码.txt`；登录后为朋友生成独立访问码。启动器显示临时分享网址，分享期间电脑需开机联网。上传、分享与下载操作见[网页使用说明](HTML/README.md)。

双击根目录的`启动右手选择.cmd`打开[右手编辑器](http://127.0.0.1:8766/)。它读取本机正常曲谱库`results/accompaniment/index.html`所引用的工程，新克隆的仓库没有预装私人曲谱。

选择歌曲后添加起止小节、选择右手型及音符时值，查看实时谱面并试听；点击“保存并生成整曲”另存版本，然后下载PDF（Portable Document Format，便携式文档格式）或整套JPG。未选择的范围沿用原谱。

## 主要目录

| 路径 | 内容 |
| --- | --- |
| `tools/`、`tools/data/` | 分析、编配、导出、右手编辑程序，以及指型和节奏定义。 |
| `HTML/` | 统一网页、启动器、网页依赖与打印下载程序。 |
| `config/` | 不含个人复核记录的空白配置示例。 |
| `run_*.ps1` | 本地模型分析、制谱、伴奏及环境检查入口。 |

程序运行后使用`data/`保存本机配置，`test_music/`保存输入，`test_outputs/`保存工程及另存版本，`results/`保存整理后的曲谱库，`reports/`保存运行日志。这些本机数据不随源码上传。
