# 歌词对齐与真实制谱：新增显式ASR型号转发和原混音哈希保护，修改前行注释保留。
from pathlib import Path
p = Path('run_score.ps1')
s = p.read_text(encoding='utf-8-sig')
s = s.replace("    [string]$LyricsFile = '',\n", "    [string]$LyricsFile = '',\n    # 歌词对齐与真实制谱：新增识别型号参数，质量对照后可明确选择已下载模型。\n    [ValidateSet('turbo', 'medium')][string]$AsrModel = 'turbo',\n")
old = "    input_audio = $mixAudioPath; output_dir = $outputDir; completed_stages = @(); status = 'running'"
new = "    # 歌词对齐与真实制谱：原输入记录行注释保留，新增原混音SHA及识别型号证据。\n    # " + old.strip() + "\n" + old + "\n    input_audio_sha256 = (Get-FileHash -LiteralPath $mixAudioPath -Algorithm SHA256).Hash; asr_model = $AsrModel"
s = s.replace(old, new)
old = "    $asrArgs = @('-B', (Join-Path $projectRoot 'tools\\lyrics_transcribe.py'), '--source-summary', $summaryPath, '--output-dir', $lyricsDir)"
new = "    # 歌词对齐与真实制谱：原参数行注释保留，新增显式型号避免质量对照缓存被默认型号误替换。\n    # " + old.strip() + "\n" + old[:-1] + ", '--model', $AsrModel)"
assert old in s
s = s.replace(old, new)
old = "    if ($finalAnalysisHash -ne $run.source_analysis_sha256) { throw '原始模型分析在处理期间发生变化。' }"
new = old + "\n    # 歌词对齐与真实制谱：新增原混音完整哈希复核，后续制谱仅生成独立派生文件。\n    if ((Get-FileHash -LiteralPath $mixAudioPath -Algorithm SHA256).Hash -ne $run.input_audio_sha256) { throw '原混音在处理期间发生变化。' }"
assert old in s
s = s.replace(old, new)
p.write_text(s, encoding='utf-8-sig')
print('ASR model and original mix integrity added')
