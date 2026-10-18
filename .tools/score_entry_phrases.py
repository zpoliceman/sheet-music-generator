# 歌词对齐与真实制谱：新增分句真实对齐路由与同源ASR锚点，整曲后端旧代码注释保留。
from pathlib import Path
p = Path('run_score.ps1')
s = p.read_text(encoding='utf-8-sig')
s = s.replace("    [string]$LyricsFile = '',\n", "    [string]$LyricsFile = '',\n    # 歌词对齐与真实制谱：新增仅供句窗定位的ASR锚点，用户歌词仍是权威文本。\n    [string]$AsrAnchor = '',\n")
old = "    [ValidateSet('tifa', 'asr-baseline')][string]$AlignmentBackend = 'tifa',"
new = "    # 歌词对齐与真实制谱：原后端参数注释保留，新增分句TIFA（待实测后再决定默认）。\n    # " + old.strip() + "\n    [ValidateSet('tifa', 'tifa-phrases', 'asr-baseline')][string]$AlignmentBackend = 'tifa',"
assert old in s
s = s.replace(old, new)
old = "    & $pythonPath -B (Join-Path $projectRoot 'tools\\lyrics_align.py') --reference (Join-Path $lyricsDir 'lyrics_reference.json') --output-dir $lyricsDir --backend $AlignmentBackend"
new = "    # 歌词对齐与真实制谱：原单后端调用注释保留，新增分句真实模型与同源句窗锚点。\n    # " + old.strip() + '''
    if ($AlignmentBackend -eq 'tifa-phrases') {
        if (-not $AsrAnchor) {
            $cachedAnchor = Join-Path $projectRoot 'test_outputs\\lyrics\\medium_candidate\\asr_raw.json'
            if (Test-Path -LiteralPath $cachedAnchor -PathType Leaf) {
                $cachedAnchorData = Get-Content -LiteralPath $cachedAnchor -Raw -Encoding UTF8 | ConvertFrom-Json
                if ($cachedAnchorData.source.sha256 -eq $lyricReference.source.sha256) { $AsrAnchor = $cachedAnchor }
            }
        }
        if (-not $AsrAnchor) {
            # 歌词对齐与真实制谱：新增独立识别锚点目录，绝不覆盖用户歌词参考文本。
            $anchorDir = Join-Path $lyricsDir 'asr_anchor'
            & $pythonPath -B (Join-Path $projectRoot 'tools\\lyrics_transcribe.py') --source-summary $summaryPath --output-dir $anchorDir --model medium
            if ($LASTEXITCODE -ne 0) { throw '分句音频窗口识别锚点生成失败。' }
            $AsrAnchor = Join-Path $anchorDir 'asr_raw.json'
        }
        $run.asr_anchor = (Resolve-Path -LiteralPath $AsrAnchor).Path
        $run.asr_anchor_sha256 = (Get-FileHash -LiteralPath $AsrAnchor -Algorithm SHA256).Hash
        & $pythonPath -B (Join-Path $projectRoot 'tools\\lyrics_align_phrases.py') --reference (Join-Path $lyricsDir 'lyrics_reference.json') --asr-anchor $AsrAnchor --analysis (Join-Path $refinedDir 'analysis.json') --output-dir $lyricsDir
        $alignmentReportPath = Join-Path $projectRoot 'reports\\lyrics_phrase_alignment.json'
    }
    else {
        & $pythonPath -B (Join-Path $projectRoot 'tools\\lyrics_align.py') --reference (Join-Path $lyricsDir 'lyrics_reference.json') --output-dir $lyricsDir --backend $AlignmentBackend
        $alignmentReportPath = Join-Path $projectRoot 'reports\\lyrics_alignment.json'
    }'''
assert old in s
s = s.replace(old, new)
old = "    Copy-Item -LiteralPath (Join-Path $projectRoot 'reports\\lyrics_alignment.json') -Destination (Join-Path $reportDir 'lyrics_alignment.json')"
new = "    # 歌词对齐与真实制谱：原固定报告复制注释保留，按真实运行后端保存计时快照。\n    # " + old.strip() + "\n    Copy-Item -LiteralPath $alignmentReportPath -Destination (Join-Path $reportDir 'lyrics_alignment.json')"
assert old in s
s = s.replace(old,new)
p.write_text(s, encoding='utf-8-sig')
print('phrase route staged, default remains full-song until evidence')
