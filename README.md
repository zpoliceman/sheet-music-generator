# 自动乐谱生成器

在Windows本机分析歌曲音频，生成人声简谱、歌词和吉他伴奏谱，并提供网页看谱、试听与PDF／整套JPG下载。右手编辑器支持55种4/4拍分解、合拨和扫弦，可按小节选择、调整时值并另存版本。

统一网页支持朋友凭访问码上传MP3／NCM音源和TXT歌词。**新上传素材的整首自动制谱尚未接入网页**，初次制谱使用本机窗口或下方脚本；网页下载和右手编辑需要已有的伴奏工程。自动制谱结果需要人工核对。

## v1.0.3 下载与使用

2026-10-22 发布 Windows 64位桌面版。前往 [v1.0.3 下载页](https://github.com/zpoliceman/sheet-music-generator/releases/tag/v1.0.3)，在 Assets（附件）中下载 **`sheet-music-generator-v1.0.3-win64.zip`**。这个压缩包包含已编译的`弦页制谱.exe`、同版本源码和中文说明；解压后先准备下方环境，再双击根目录EXE，无需自行编译。

**这不是包含模型的免安装软件。** 压缩包不含Python环境、模型权重、FFmpeg、Chrome或私人歌曲。EXE必须和同版本的`desktop/`、`tools/`、`HTML/`等项目文件一起使用，不能只把EXE复制到另一台电脑。GitHub自动生成的`Source code`压缩包只有源码；仅下载单独EXE时，也要将它放入v1.0.3源码根目录。

完整操作见[桌面版使用说明](desktop/README.md)，包括首次安装、生成曲谱、修改右手型、继续未完成任务、导出和常见问题。附件同时提供独立说明和`SHA256SUMS.txt`文件校验清单。

本版相对v1.0.2新增双击制谱窗口、后台任务取消和继续、音源前置检查、PDF／整套JPG导出，并包含歌词对齐、吉他可弹性与打印排版修复。当前桌面程序输出带“待校对”标记的人声简谱和吉他伴奏谱，不代表已经完成人工音乐校对。

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

## 双击制谱（Windows 64位）

配置完上述模型环境，并运行一次`HTML/准备环境.ps1`安装打印环境后，使用发布压缩包内的EXE即可。只有从源码自行构建时，才需要在项目根目录编译窗口程序：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\desktop\build.ps1
```

随后双击根目录的`弦页制谱.exe`。选择MP3／NCM／FLAC／WAV／M4A音源、TXT歌词、曲谱保存文件夹和PDF／整套JPG格式，点击“一键生成曲谱”。程序会依次分析整首歌、对齐歌词、生成简谱与吉他伴奏，并打开本机手型编辑网页；勾选“生成后自动导出”可同时保存两种曲谱。

窗口会先自动运行音源前置程序，识别实际音频格式并完整解码检查。FLAC、WAV等已可读音源保留原采样率和声道，不重复有损转码；NCM先还原，M4A准备为同长WAV。LRC是带时间戳的歌词文件，不能作为音源。前置程序也可以单独运行，输出目录必须使用新名称：

```powershell
.\.venv-gpu\Scripts\python.exe -B tools/prepare_audio_input.py --input 'test_music/歌曲.flac' --output 'test_outputs/audio_input/my_song'
```

网页支持按小节选择右手型、预览和试听。修改后先点击“保存并生成整曲”，再回到窗口点击“刷新版本”，选择该版本并“一键导出曲谱”。每次导出新建子文件夹；已完成的任务可以重新打开、改手型和导出，无需重复运行模型。

如果任务在旋律识别和歌词对齐完成后停止，可在“最近任务”中选中该任务，点“打开所选任务”，再点“继续未完成任务”。程序核对原音源、歌词和各步结果后复用已完成的分析，新曲谱和日志另存；如果任务已经留下通过文件校验的完整草稿，程序会恢复预览和导出。原文件已修改或前几步未完成时，需要重新生成。

运行时可点击“取消当前任务”；后台未及时处理取消请求时，窗口会结束本次任务启动的后台程序。关闭窗口也会取消本次任务。无法继续生成的错误、后台失去响应或单步超过时间上限时，程序停止并在窗口显示原因，保留已完成的步骤文件。任务结束后，取消按钮显示“无运行任务”，可以重新生成或继续未完成任务。

本入口生成**待校对自动草稿**。节拍或原曲覆盖不确定时，程序保留相应记录并继续输出草稿，页面和每页PDF／JPG均标注“待校对”；弦位、持续按弦、十二品上限和最短十六分等演奏检查仍执行。草稿不会自动进入正常曲谱库。

EXE是小型本机入口，需要与项目目录和已安装环境一起使用，不能只复制这个文件到另一台电脑。任务工程保存在`test_outputs/accompaniment_runs/desktop/`，窗口设置在`test_outputs/desktop/`。下方命令行入口继续保留。

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
| `desktop/` | Windows窗口源码、编译脚本、后台制谱与导出连接程序。 |
| `config/` | 空白复核配置示例，以及官方ROSVOT权重的校验清单。 |
| `run_*.ps1` | 本地模型分析、制谱、伴奏及环境检查入口。 |

程序运行后使用`data/`保存本机配置，`test_music/`保存输入，`test_outputs/`保存工程及另存版本，`results/`保存整理后的曲谱库，`reports/`保存运行日志。这些本机数据不随源码上传。
