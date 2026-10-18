# 歌词对齐与真实制谱：新增首曲串行入口，复用模型分析且每次另存派生乐谱。
[CmdletBinding()]
param(
    [string]$ModelReport = '',
    [string]$LyricsFile = '',
    # 歌词对齐与真实制谱：新增仅供句窗定位的ASR锚点，用户歌词仍是权威文本。
    [string]$AsrAnchor = '',
    # 歌词对齐与真实制谱：新增已对齐字符缓存输入，避免把质量对照GPU推理重复计作新推理。
    [string]$AlignedLyrics = '',
    # 歌词对齐与真实制谱：新增识别型号参数，质量对照后可明确选择已下载模型。
    # 歌词对齐与真实制谱：原turbo默认注释保留，修改为首尾幻觉较少的medium基线（仍需校正）。
    # [ValidateSet('turbo', 'medium')][string]$AsrModel = 'turbo',
    [ValidateSet('turbo', 'medium')][string]$AsrModel = 'medium',
    [double]$Tempo = 0,
    # 自动音乐解码改造：新增默认音乐层选择；Key在musical层表示输出目标调，默认保留源音高。
    [ValidateSet('musical', 'legacy')][string]$NotationProfile = 'musical',
    [string]$Key = '',
    [string]$Meter = '',
    [double]$BeatOrigin = [double]::NaN,
    [int]$Subdivision = 4,
    # 歌词对齐与真实制谱：新增对齐后端选择，默认要求真实TIFA，近似基线需显式选择。
    # 歌词对齐与真实制谱：原后端参数注释保留，新增分句TIFA（待实测后再决定默认）。
    # [ValidateSet('tifa', 'asr-baseline')][string]$AlignmentBackend = 'tifa',
    # 歌词对齐与真实制谱：原整曲默认注释保留，修改为实测改善首句且覆盖全文的分句模型路线。
    # [ValidateSet('tifa', 'tifa-phrases', 'asr-baseline')][string]$AlignmentBackend = 'tifa',
    [ValidateSet('tifa', 'tifa-phrases', 'asr-baseline')][string]$AlignmentBackend = 'tifa-phrases',
    [switch]$ForceAsr
)
$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
. (Join-Path $projectRoot 'tools/Resolve-WorkspaceInput.ps1')
foreach ($inputName in @('ModelReport','LyricsFile','AsrAnchor','AlignedLyrics')) {
    $inputValue = Get-Variable -Name $inputName -ValueOnly
    if ($inputValue) { Set-Variable -Name $inputName -Value (Resolve-WorkspaceInput -Value $inputValue -Root $projectRoot) }
}
$pythonPath = Join-Path $projectRoot '.venv-gpu\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) { throw '缺少项目内 .venv-gpu 环境。' }
if (-not $ModelReport) { $ModelReport = Join-Path $projectRoot 'reports\integrated_pipeline.full.json' }
$pipeline = Get-Content -LiteralPath $ModelReport -Raw -Encoding UTF8 | ConvertFrom-Json
if (-not $pipeline.run.full_song -or $pipeline.run.source_offset_seconds -ne 0) {
    throw '当前制谱入口要求完整歌曲、零偏移模型报告，防止将片段时间轴混用整首节拍。'
}
$summaryPath = Resolve-WorkspaceInput -Value $pipeline.run.transcription_summary -Root $projectRoot
$analysisPath = Join-Path (Split-Path -Parent $summaryPath) 'analysis.json'
$mixAudioPath = Resolve-WorkspaceInput -Value $pipeline.run.input -Root $projectRoot
foreach ($requiredPath in @($summaryPath, $analysisPath, $mixAudioPath)) {
    if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) { throw ('缺少输入：' + $requiredPath) }
}
if ($LyricsFile) {
    $LyricsFile = (Resolve-Path -LiteralPath $LyricsFile).Path
    if (-not (Test-Path -LiteralPath $LyricsFile -PathType Leaf)) { throw '歌词参数必须为UTF-8文本文件。' }
}
if ($Tempo -lt 0 -or [double]::IsNaN($Tempo) -or [double]::IsInfinity($Tempo)) { throw 'Tempo必须为0（自动）或正数。' }
if ([double]::IsInfinity($BeatOrigin)) { throw 'BeatOrigin必须为有限秒数。' }
if ($Subdivision -lt 1) { throw 'Subdivision必须为正整数。' }

# 歌词对齐与真实制谱：新增唯一输出和运行清单，出错也保留已完成阶段与错误证据。
$runId = [datetime]::UtcNow.AddHours(8).ToString('yyyyMMdd_HHmmss_fff')
$reportDir = Join-Path $projectRoot ('reports\score_runs\' + $runId)
$outputDir = Join-Path $projectRoot ('test_outputs\score_runs\' + $runId)
$refinedDir = Join-Path $outputDir 'refined'
$lyricsDir = Join-Path $outputDir 'lyrics'
$scoreDir = Join-Path $outputDir 'score'
New-Item -ItemType Directory -Path $reportDir, $refinedDir, $lyricsDir, $scoreDir -Force | Out-Null
$watch = [System.Diagnostics.Stopwatch]::StartNew()
$run = [ordered]@{
    task = '歌词对齐与真实制谱'; run_id = $runId; model_report = (Resolve-Path -LiteralPath $ModelReport).Path
    source_analysis = $analysisPath; source_analysis_sha256 = (Get-FileHash -LiteralPath $analysisPath -Algorithm SHA256).Hash
    # 歌词对齐与真实制谱：原输入记录行注释保留，新增原混音SHA及识别型号证据。
    # input_audio = $mixAudioPath; output_dir = $outputDir; completed_stages = @(); status = 'running'
    input_audio = $mixAudioPath; output_dir = $outputDir; completed_stages = @(); status = 'running'
    input_audio_sha256 = (Get-FileHash -LiteralPath $mixAudioPath -Algorithm SHA256).Hash; asr_model = $AsrModel
    lyrics_file = $LyricsFile; external_editor_roundtrip = 'not_tested'; musical_accuracy_verified = $false
    overrides = @{ tempo = $Tempo; key = $Key; meter = $Meter; beat_origin_seconds = "$BeatOrigin"; subdivision = $Subdivision }
}
function Save-ScoreRun {
    # 歌词对齐与真实制谱：新增阶段落盘和用户要求的实时工作日志/当前任务书更新。
    param([string]$Completed, [string]$Next)
    if ($Completed) { $run.completed_stages += $Completed }
    $run.wall_seconds = $watch.Elapsed.TotalSeconds
    $run | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath (Join-Path $reportDir 'run.json') -Encoding UTF8
    if ($Completed) {
        $stamp = [datetime]::UtcNow.AddHours(8).ToString('yyyy-MM-dd HH:mm:ss')
        "`r`n### $stamp｜歌词对齐与真实制谱 $runId`r`n- 已完成：$Completed`r`n- 决策：同一源分析/人声时间轴；原始结果不覆盖；模型依次运行。`r`n- 待办：$Next`r`n" | Add-Content -LiteralPath (Join-Path $projectRoot 'progress.md') -Encoding UTF8
        $todoPath = Join-Path $projectRoot 'todo.md'
        $todoText = Get-Content -LiteralPath $todoPath -Raw -Encoding UTF8
        $currentSteps = "## 上一步`r`n`r`n$Completed（运行 $runId）。`r`n`r`n## 下一步`r`n`r`n$Next`r`n"
        $todoText = [regex]::Replace($todoText, '(?s)## 上一步\r?\n.*\z', { param($match) $currentSteps })
        $todoText | Set-Content -LiteralPath $todoPath -Encoding UTF8
    }
}
$previousEncoding = $env:PYTHONIOENCODING
$previousTorchHome = $env:TORCH_HOME
$previousHfHome = $env:HF_HOME
try {
    $env:PYTHONIOENCODING = 'utf-8'
    $env:TORCH_HOME = Join-Path $projectRoot '.cache\torch'
    $env:HF_HOME = Join-Path $projectRoot '.cache\huggingface'
    Save-ScoreRun '已创建独立输出目录并核对完整歌曲报告输入' '处理接缝并保留音符质量证据。'

    # 歌词对齐与真实制谱：新增CPU接缝整理，不修改原始分析或原始音频。
    & $pythonPath -B (Join-Path $projectRoot 'tools\refine_transcription.py') --input $analysisPath --output-dir $refinedDir --no-plots
    if ($LASTEXITCODE -ne 0) { throw '接缝与音符派生处理失败。' }
    Save-ScoreRun '接缝派生音符和质量标记生成完成' '识别歌词或读取用户提供文本，然后真实歌声时间对齐。'

    # 歌词对齐与真实制谱：新增已校验ASR缓存候选复制，识别器仍自行检查源哈希及全部配置。
    # 歌词对齐与真实制谱：原缓存固定路径注释保留，按显式型号选择既有基线。
    # $cacheCandidate = Join-Path $projectRoot 'test_outputs\lyrics\first_song\asr_raw.json'
    # 第二首跨歌曲验证：修改，明确提供的同源ASR锚点也可作识别缓存；原固定分支注释保留。
    # if ($AsrModel -eq 'medium') { $cacheCandidate = Join-Path $projectRoot 'test_outputs\lyrics\medium_candidate\asr_raw.json' }
    # else { $cacheCandidate = Join-Path $projectRoot 'test_outputs\lyrics\first_song\asr_raw.json' }
    # 第二首跨歌曲验证：新增实际识别器仍核对源SHA和完整配置，错误缓存自动重识别。
    if ($AsrAnchor -and -not $LyricsFile -and -not $ForceAsr) { $cacheCandidate = (Resolve-Path -LiteralPath $AsrAnchor).Path }
    elseif ($AsrModel -eq 'medium') { $cacheCandidate = Join-Path $projectRoot 'test_outputs\lyrics\medium_candidate\asr_raw.json' }
    else { $cacheCandidate = Join-Path $projectRoot 'test_outputs\lyrics\first_song\asr_raw.json' }
    if (-not $LyricsFile -and -not $ForceAsr -and (Test-Path -LiteralPath $cacheCandidate -PathType Leaf)) {
        Copy-Item -LiteralPath $cacheCandidate -Destination (Join-Path $lyricsDir 'asr_raw.json')
    }
    # 歌词对齐与真实制谱：原参数行注释保留，新增显式型号避免质量对照缓存被默认型号误替换。
    # $asrArgs = @('-B', (Join-Path $projectRoot 'tools\lyrics_transcribe.py'), '--source-summary', $summaryPath, '--output-dir', $lyricsDir)
    $asrArgs = @('-B', (Join-Path $projectRoot 'tools\lyrics_transcribe.py'), '--source-summary', $summaryPath, '--output-dir', $lyricsDir, '--model', $AsrModel)
    if ($LyricsFile) { $asrArgs += @('--lyrics-file', $LyricsFile) }
    if ($ForceAsr) { $asrArgs += '--force' }
    & $pythonPath @asrArgs
    if ($LASTEXITCODE -ne 0) { throw '歌词识别/用户文本读取失败。' }
    Copy-Item -LiteralPath (Join-Path $projectRoot 'reports\lyrics_asr.json') -Destination (Join-Path $reportDir 'lyrics_asr.json')
    # 歌词对齐与真实制谱：原固定自动歌词日志注释保留，修改为区分用户文本与ASR来源。
    # Save-ScoreRun '歌词参考文本生成完成（自动结果尚未人工校正）' '完成TIFA对齐并核对对齐状态、逐字时间和旋律关系。'
    # 中文版本冻结与英文融合验证：注释保留被替换的原实现。
    # $lyricReference = Get-Content -LiteralPath (Join-Path $lyricsDir 'lyrics_reference.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    # 中文版本冻结与英文融合验证：新增中英文兼容实现。
    $lyricReference = Get-Content -LiteralPath (Join-Path $lyricsDir 'lyrics_reference.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    $anchorLanguage = if ($lyricReference.asr_language) { [string]$lyricReference.asr_language } else { 'zh' }
    $expectedAnchorLanguage = if ($anchorLanguage -eq 'auto') { $null } else { $anchorLanguage }
    $run.lyrics_languages = @($lyricReference.languages)
    $run.asr_anchor_language = $anchorLanguage
    Save-ScoreRun ('歌词参考文本生成完成，来源：' + $lyricReference.reference_kind) '完成TIFA对齐并核对对齐状态、逐字时间和旋律关系。'

    # 歌词对齐与真实制谱：新增真实对齐独立阶段，状态区分强制对齐与明确近似基线。
    # 歌词对齐与真实制谱：原自动后端调用注释保留，修改为明确后端，避免失败后被误认真实对齐。
    # & $pythonPath -B (Join-Path $projectRoot 'tools\lyrics_align.py') --reference (Join-Path $lyricsDir 'lyrics_reference.json') --output-dir $lyricsDir
    # 歌词对齐与真实制谱：原单后端调用注释保留，新增分句真实模型与同源句窗锚点。
    # & $pythonPath -B (Join-Path $projectRoot 'tools\lyrics_align.py') --reference (Join-Path $lyricsDir 'lyrics_reference.json') --output-dir $lyricsDir --backend $AlignmentBackend
    # 歌词对齐与真实制谱：新增明确对齐缓存复用，保留原候选/phone证据目录引用。
    if ($AlignedLyrics) {
        $AlignedLyrics = (Resolve-Path -LiteralPath $AlignedLyrics).Path
        $aligned = Get-Content -LiteralPath $AlignedLyrics -Raw -Encoding UTF8 | ConvertFrom-Json
        $textHasher = [System.Security.Cryptography.SHA256]::Create()
        try { $expectedTextSha = [BitConverter]::ToString($textHasher.ComputeHash([Text.Encoding]::UTF8.GetBytes($lyricReference.text))).Replace('-','').ToLowerInvariant() }
        finally { $textHasher.Dispose() }
        # 歌词对齐与真实制谱：原缓存匹配条件注释保留，新增偏移/时长，防止相同字节错用不同时间坐标。
        # if ($aligned.source.sha256 -ne $lyricReference.source.sha256 -or $aligned.cache_key.text_sha256 -ne $expectedTextSha -or $aligned.reference_kind -ne $lyricReference.reference_kind) {
        if ($aligned.source.sha256 -ne $lyricReference.source.sha256 -or $aligned.cache_key.text_sha256 -ne $expectedTextSha -or $aligned.reference_kind -ne $lyricReference.reference_kind -or $aligned.source.offset_seconds -ne $lyricReference.source.offset_seconds -or $aligned.source.duration_seconds -ne $lyricReference.source.duration_seconds) {
            throw '已对齐缓存的源音频、歌词原文或来源类型与本次不一致。'
        }
        if ($aligned.cache_key.analysis_sha256 -and $aligned.cache_key.analysis_sha256 -ne (Get-FileHash -LiteralPath (Join-Path $refinedDir 'analysis.json') -Algorithm SHA256).Hash) {
            throw '分句对齐缓存关联的派生分析与本次不一致。'
        }
        $alignmentReportPath = Join-Path (Split-Path -Parent $AlignedLyrics) 'alignment_report.json'
        if (-not (Test-Path -LiteralPath $alignmentReportPath -PathType Leaf)) { throw '缓存缺少独立原始对齐报告。' }
        Copy-Item -LiteralPath $AlignedLyrics -Destination (Join-Path $lyricsDir 'characters.json')
        # 歌词对齐与真实制谱：新增实际缓存后端状态记录，不把缓存命中说成本次新GPU推理。
        $run.alignment_backend_requested = $AlignmentBackend
        $run.alignment_reused = $true
        $run.alignment_reused_from = $AlignedLyrics
        $run.alignment_reused_sha256 = (Get-FileHash -LiteralPath $AlignedLyrics -Algorithm SHA256).Hash
        $run.alignment_timing_scope = '本次为哈希核对后复用；独立报告中的推理时间属于原质量对照运行'
    }
    else {
    if ($AlignmentBackend -eq 'tifa-phrases') {
        # 第二首《渴》跨歌曲验证：新增复用本次ASR锚点，核对源SHA、偏移和时长，避免对新歌重复GPU识别。
        if (-not $AsrAnchor) {
            $sameRunAsr = Join-Path $lyricsDir 'asr_raw.json'
            if (Test-Path -LiteralPath $sameRunAsr -PathType Leaf) {
                $sameRunData = Get-Content -LiteralPath $sameRunAsr -Raw -Encoding UTF8 | ConvertFrom-Json
                if ($sameRunData.source.sha256 -eq $lyricReference.source.sha256 -and
                    $sameRunData.source.offset_seconds -eq $lyricReference.source.offset_seconds -and
                    # 中文版本冻结与英文融合验证：注释保留被替换的原实现。
                    # $sameRunData.source.duration_seconds -eq $lyricReference.source.duration_seconds) {
                    # 中文版本冻结与英文融合验证：新增中英文兼容实现。
                    $sameRunData.source.duration_seconds -eq $lyricReference.source.duration_seconds -and
                    $sameRunData.configuration.language -eq $expectedAnchorLanguage) {
                    $AsrAnchor = $sameRunAsr
                }
            }
        }
        if (-not $AsrAnchor) {
            $cachedAnchor = Join-Path $projectRoot 'test_outputs\lyrics\medium_candidate\asr_raw.json'
            if (Test-Path -LiteralPath $cachedAnchor -PathType Leaf) {
                $cachedAnchorData = Get-Content -LiteralPath $cachedAnchor -Raw -Encoding UTF8 | ConvertFrom-Json
                # 中文版本冻结与英文融合验证：注释保留被替换的原实现。
                # if ($cachedAnchorData.source.sha256 -eq $lyricReference.source.sha256) { $AsrAnchor = $cachedAnchor }
                # 中文版本冻结与英文融合验证：新增中英文兼容实现。
                if ($cachedAnchorData.source.sha256 -eq $lyricReference.source.sha256 -and
                    $cachedAnchorData.configuration.language -eq $expectedAnchorLanguage) { $AsrAnchor = $cachedAnchor }
            }
        }
        if (-not $AsrAnchor) {
            # 歌词对齐与真实制谱：新增独立识别锚点目录，绝不覆盖用户歌词参考文本。
            $anchorDir = Join-Path $lyricsDir 'asr_anchor'
            # 中文版本冻结与英文融合验证：注释保留被替换的原实现。
            # & $pythonPath -B (Join-Path $projectRoot 'tools\lyrics_transcribe.py') --source-summary $summaryPath --output-dir $anchorDir --model medium
            # 中文版本冻结与英文融合验证：新增中英文兼容实现。
            & $pythonPath -B (Join-Path $projectRoot 'tools\lyrics_transcribe.py') --source-summary $summaryPath --output-dir $anchorDir --model medium --language $anchorLanguage
            if ($LASTEXITCODE -ne 0) { throw '分句音频窗口识别锚点生成失败。' }
            $AsrAnchor = Join-Path $anchorDir 'asr_raw.json'
        }
        $run.asr_anchor = (Resolve-Path -LiteralPath $AsrAnchor).Path
        $run.asr_anchor_sha256 = (Get-FileHash -LiteralPath $AsrAnchor -Algorithm SHA256).Hash
        & $pythonPath -B (Join-Path $projectRoot 'tools\lyrics_align_phrases.py') --reference (Join-Path $lyricsDir 'lyrics_reference.json') --asr-anchor $AsrAnchor --analysis (Join-Path $refinedDir 'analysis.json') --output-dir $lyricsDir
        $alignmentReportPath = Join-Path $projectRoot 'reports\lyrics_phrase_alignment.json'
    }
    else {
        & $pythonPath -B (Join-Path $projectRoot 'tools\lyrics_align.py') --reference (Join-Path $lyricsDir 'lyrics_reference.json') --output-dir $lyricsDir --backend $AlignmentBackend
        $alignmentReportPath = Join-Path $projectRoot 'reports\lyrics_alignment.json'
    }
    }
    if ($LASTEXITCODE -ne 0) { throw '歌词对齐失败。' }
    # 歌词对齐与真实制谱：新增本次TIFA计时与诊断报告快照，避免后续运行覆盖本次证据。
    # 歌词对齐与真实制谱：原固定报告复制注释保留，按真实运行后端保存计时快照。
    # Copy-Item -LiteralPath (Join-Path $projectRoot 'reports\lyrics_alignment.json') -Destination (Join-Path $reportDir 'lyrics_alignment.json')
    Copy-Item -LiteralPath $alignmentReportPath -Destination (Join-Path $reportDir 'lyrics_alignment.json')
    $charactersPath = Join-Path $lyricsDir 'characters.json'
    # 字音归属修复：新增旧缓存/新推理统一音素回填，原字界文件保持，派生文件另存。
    if ($NotationProfile -eq 'musical') {
        $rawCharactersPath = $charactersPath
        $charactersPath = Join-Path $lyricsDir 'characters_phonemes.json'
        # 中文版本冻结与英文融合验证：注释保留被替换的原实现。
        # & $pythonPath -B (Join-Path $projectRoot 'tools\phoneme_evidence.py') --characters $rawCharactersPath --alignment-report (Join-Path $reportDir 'lyrics_alignment.json') --output $charactersPath
        # 中文版本冻结与英文融合验证：新增中英文兼容实现。
        & $pythonPath -B (Join-Path $projectRoot 'tools\phoneme_evidence.py') --characters $rawCharactersPath --alignment-report (Join-Path $reportDir 'lyrics_alignment.json') --output $charactersPath --reference-file (Join-Path $lyricsDir 'lyrics_reference.json')
        if ($LASTEXITCODE -ne 0) { throw '音素证据回填失败，不能伪造字音归属。' }
        $run.phoneme_characters = $charactersPath
    }
    $characters = Get-Content -LiteralPath $charactersPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $run.alignment_status = $characters.alignment_status
    Save-ScoreRun ('逐字时间导出完成，状态：' + $characters.alignment_status) '生成节奏/调性候选、歌词映射、MusicXML/MIDI与简谱。'

    # 歌词对齐与真实制谱：新增人工覆盖参数转发，自动初估与量化误差保留在项目JSON。
    # 自动音乐解码改造：修改，默认接通量化前音乐解码；原入口行注释保留，legacy可明确调用。
    # $scoreArgs = @('-B', (Join-Path $projectRoot 'tools\score_export.py'), '--notes', (Join-Path $refinedDir 'analysis.json'), '--lyrics', $charactersPath, '--audio', $mixAudioPath, '--output-dir', $scoreDir, '--report', (Join-Path $reportDir 'score_export.json'), '--title', [IO.Path]::GetFileNameWithoutExtension($mixAudioPath), '--subdivision', "$Subdivision")
    $scoreScript = if ($NotationProfile -eq 'musical') { 'tools\musical_decode.py' } else { 'tools\score_export.py' }
    $run.notation_profile = $NotationProfile
    $scoreArgs = @('-B', (Join-Path $projectRoot $scoreScript), '--notes', (Join-Path $refinedDir 'analysis.json'), '--lyrics', $charactersPath, '--audio', $mixAudioPath, '--output-dir', $scoreDir, '--report', (Join-Path $reportDir 'score_export.json'), '--title', [IO.Path]::GetFileNameWithoutExtension($mixAudioPath), '--subdivision', "$Subdivision")
    if ($Tempo -gt 0) { $scoreArgs += @('--tempo', "$Tempo") }
    if ($Key) { $scoreArgs += @('--key', $Key) }
    if ($Meter) { $scoreArgs += @('--meter', $Meter) }
    if (-not [double]::IsNaN($BeatOrigin)) { $scoreArgs += @('--beat-origin', "$BeatOrigin") }
    & $pythonPath @scoreArgs
    if ($LASTEXITCODE -ne 0) { throw '乐谱生成或语义验证失败。' }
    # 歌词对齐与真实制谱：新增本地片段试听与优先复核HTML，核对人声/歌词/音符源哈希。
    & $pythonPath -B (Join-Path $projectRoot 'tools\review_bundle.py') --analysis (Join-Path $refinedDir 'analysis.json') --lyrics $charactersPath --score-dir $scoreDir --output (Join-Path $scoreDir 'review.html')
    if ($LASTEXITCODE -ne 0) { throw '复核报告生成或源一致性检查失败。' }
    $finalAnalysisHash = (Get-FileHash -LiteralPath $analysisPath -Algorithm SHA256).Hash
    if ($finalAnalysisHash -ne $run.source_analysis_sha256) { throw '原始模型分析在处理期间发生变化。' }
    # 歌词对齐与真实制谱：新增原混音完整哈希复核，后续制谱仅生成独立派生文件。
    if ((Get-FileHash -LiteralPath $mixAudioPath -Algorithm SHA256).Hash -ne $run.input_audio_sha256) { throw '原混音在处理期间发生变化。' }
    $run.status = 'draft_generated_requires_musical_review'
    $run.musicxml = Join-Path $scoreDir 'vocal_draft.musicxml'
    # 十一首可编辑五线谱：新增运行报告可编辑五线谱与预览路径，生成器已自动导出。
    $run.staff_musicxml = Join-Path $scoreDir 'staff_score.musicxml'
    $run.staff_mxl = Join-Path $scoreDir 'staff_score.mxl'
    $run.staff_preview = Join-Path $scoreDir 'staff.html'
    if (-not (Test-Path -LiteralPath $run.staff_musicxml -PathType Leaf)) { throw '可编辑五线谱没有生成。' }
    $run.preview = Join-Path $scoreDir 'jianpu.html'
    $run.project_json = Join-Path $scoreDir 'project.json'
    Save-ScoreRun '真实歌曲乐谱草稿及独立项目数据生成，原分析哈希未变化' '人工核对歌词/短音符/拍号调性与量化；完成实际写谱编辑器往返。'
    Write-Output ('草稿生成完成，运行报告：' + (Join-Path $reportDir 'run.json'))
}
catch {
    # 歌词对齐与真实制谱：新增错误阶段留痕并返回失败，不将部分输出报告为完整成功。
    $run.status = 'failed'
    $run.error = $_.Exception.Message
    Save-ScoreRun ('流程失败：' + $run.error) '查看该运行报告，解决失败后另存重试；已完成输出保留。'
    throw
}
finally {
    # 歌词对齐与真实制谱：新增调用环境恢复，不永久改变系统变量或全局PATH。
    $watch.Stop()
    $env:PYTHONIOENCODING = $previousEncoding
    $env:TORCH_HOME = $previousTorchHome
    $env:HF_HOME = $previousHfHome
}
