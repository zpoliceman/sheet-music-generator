# 歌词对齐与真实制谱：新增入口严格对齐选择与复核导出，保留本次替换前代码注释。
from pathlib import Path
p = Path('run_score.ps1')
s = p.read_text(encoding='utf-8-sig')
s = s.replace("    [switch]$ForceAsr\n", "    # 歌词对齐与真实制谱：新增对齐后端选择，默认要求真实TIFA，近似基线需显式选择。\n    [ValidateSet('tifa', 'asr-baseline')][string]$AlignmentBackend = 'tifa',\n    [switch]$ForceAsr\n")
old = "    & $pythonPath -B (Join-Path $projectRoot 'tools\\lyrics_align.py') --reference (Join-Path $lyricsDir 'lyrics_reference.json') --output-dir $lyricsDir"
new = "    # 歌词对齐与真实制谱：原自动后端调用注释保留，修改为明确后端，避免失败后被误认真实对齐。\n    # " + old.strip() + "\n" + old + " --backend $AlignmentBackend"
assert old in s
s = s.replace(old, new)
old = "    $finalAnalysisHash = (Get-FileHash -LiteralPath $analysisPath -Algorithm SHA256).Hash"
new = "    # 歌词对齐与真实制谱：新增本地片段试听与优先复核HTML，核对人声/歌词/音符源哈希。\n    & $pythonPath -B (Join-Path $projectRoot 'tools\\review_bundle.py') --analysis (Join-Path $refinedDir 'analysis.json') --lyrics $charactersPath --score-dir $scoreDir --output (Join-Path $scoreDir 'review.html')\n    if ($LASTEXITCODE -ne 0) { throw '复核报告生成或源一致性检查失败。' }\n" + old
assert old in s
s = s.replace(old, new)
p.write_text(s, encoding='utf-8-sig')
p = Path('tools/review_bundle.py')
s = p.read_text(encoding='utf-8-sig')
old = '    document = re.sub("|".join(sorted(map(re.escape, replacements), key=len, reverse=True)), lambda match: replacements[match[0]], document)'
new = '# 歌词对齐与真实制谱：修改模板匹配边界，避免XML占位符误替换MusicXML正文；原行注释保留。\n# ' + old + '\n    document = re.sub(r"(?<![A-Za-z])(?:" + "|".join(sorted(map(re.escape, replacements), key=len, reverse=True)) + r")(?![A-Za-z])", lambda match: replacements[match[0]], document)'
assert old in s
p.write_text(s.replace(old, new), encoding='utf-8-sig')
print('strict backend and local review integrated')
