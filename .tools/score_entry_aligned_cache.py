# 歌词对齐与真实制谱：新增显式复用已对齐字稿，真实源/文本/分析哈希一致才接入。
from pathlib import Path
p=Path('run_score.ps1')
s=p.read_text(encoding='utf-8-sig')
s=s.replace("    [string]$AsrAnchor = '',\n", "    [string]$AsrAnchor = '',\n    # 歌词对齐与真实制谱：新增已对齐字符缓存输入，避免把质量对照GPU推理重复计作新推理。\n    [string]$AlignedLyrics = '',\n")
anchor="    if ($AlignmentBackend -eq 'tifa-phrases') {"
assert s.count(anchor)==1
prefix='''    # 歌词对齐与真实制谱：新增明确对齐缓存复用，保留原候选/phone证据目录引用。
    if ($AlignedLyrics) {
        $AlignedLyrics = (Resolve-Path -LiteralPath $AlignedLyrics).Path
        $aligned = Get-Content -LiteralPath $AlignedLyrics -Raw -Encoding UTF8 | ConvertFrom-Json
        $textHasher = [System.Security.Cryptography.SHA256]::Create()
        try { $expectedTextSha = [BitConverter]::ToString($textHasher.ComputeHash([Text.Encoding]::UTF8.GetBytes($lyricReference.text))).Replace('-','').ToLowerInvariant() }
        finally { $textHasher.Dispose() }
        if ($aligned.source.sha256 -ne $lyricReference.source.sha256 -or $aligned.cache_key.text_sha256 -ne $expectedTextSha -or $aligned.reference_kind -ne $lyricReference.reference_kind) {
            throw '已对齐缓存的源音频、歌词原文或来源类型与本次不一致。'
        }
        if ($aligned.cache_key.analysis_sha256 -and $aligned.cache_key.analysis_sha256 -ne (Get-FileHash -LiteralPath (Join-Path $refinedDir 'analysis.json') -Algorithm SHA256).Hash) {
            throw '分句对齐缓存关联的派生分析与本次不一致。'
        }
        $alignmentReportPath = Join-Path (Split-Path -Parent $AlignedLyrics) 'alignment_report.json'
        if (-not (Test-Path -LiteralPath $alignmentReportPath -PathType Leaf)) { throw '缓存缺少独立原始对齐报告。' }
        Copy-Item -LiteralPath $AlignedLyrics -Destination (Join-Path $lyricsDir 'characters.json')
        $run.alignment_reused = $true
        $run.alignment_reused_from = $AlignedLyrics
        $run.alignment_reused_sha256 = (Get-FileHash -LiteralPath $AlignedLyrics -Algorithm SHA256).Hash
        $run.alignment_timing_scope = '本次为哈希核对后复用；独立报告中的推理时间属于原质量对照运行'
    }
    else {
'''
s=s.replace(anchor,prefix+anchor)
anchor="    if ($LASTEXITCODE -ne 0) { throw '歌词对齐失败。' }"
assert anchor in s
s=s.replace(anchor,"    }\n"+anchor)
p.write_text(s,encoding='utf-8-sig')
print('explicit aligned cache reuse with provenance guards added')
