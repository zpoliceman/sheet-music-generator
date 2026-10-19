# 兼容性与样曲验证：新增真实首曲模型流水线入口，模型顺序运行且每次输出独立保存。
[CmdletBinding()]
# 第二首《渴》跨歌曲验证：修改首曲固定入口，保留默认歌曲并新增素材文件名选择；原参数注释保留。
# param([switch]$Full)
param(
    [switch]$Full,
    [string]$Song = '孙燕姿 - 遇见.ncm'
)
$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$pythonPath = Join-Path $projectRoot '.venv-gpu\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) { throw '请先建立项目内 .venv-gpu 环境。' }
$runId = [datetime]::UtcNow.AddHours(8).ToString('yyyyMMdd_HHmmss_fff')
$reportDir = Join-Path $projectRoot ('reports\runs\' + $runId)
$outputDir = Join-Path $projectRoot ('test_outputs\runs\' + $runId)
New-Item -ItemType Directory -Path $reportDir, $outputDir -Force | Out-Null
$previousEncoding = $env:PYTHONIOENCODING
$previousTorchHome = $env:TORCH_HOME
# 第二首《渴》跨歌曲验证：新增独立模型墙钟计时，不混入歌词/制谱耗时。
$modelWatch = [System.Diagnostics.Stopwatch]::StartNew()
try {
    # 兼容性与样曲验证：新增当前进程编码与缓存设置，源文件先重新验证。
    $env:PYTHONIOENCODING = 'utf-8'
    $env:TORCH_HOME = Join-Path $projectRoot '.cache\torch'
    $inventoryScript = Join-Path $projectRoot 'tools\audio_inventory.py'
    # 第二首《渴》跨歌曲验证：修改素材选择，原固定首曲命令注释保留。
    # if ($Full) { & $pythonPath $inventoryScript --first '孙燕姿 - 遇见.ncm' }
    # else { & $pythonPath $inventoryScript --first '孙燕姿 - 遇见.ncm' --make-sample --sample-start 40 --sample-duration 30 }
    if ($Full) { & $pythonPath $inventoryScript --first $Song }
    else { & $pythonPath $inventoryScript --first $Song --make-sample --sample-start 40 --sample-duration 30 }
    if ($LASTEXITCODE -ne 0) { throw '首曲音频验证失败。' }
    # 第二首《渴》跨歌曲验证：新增本次素材证据快照，原全局首曲报告可能被下一次运行替换。
    Copy-Item -LiteralPath (Join-Path $projectRoot 'reports\first_audio_validation.json') -Destination (Join-Path $reportDir 'audio_validation.json')
    $stageStamp = [datetime]::Now.ToString('yyyy-MM-dd HH:mm:ss')
    "$stageStamp｜模型验证 $runId：已核查素材 $Song；下一步串行分离人声与转录。" | Add-Content -LiteralPath (Join-Path $reportDir 'stages.log') -Encoding UTF8
    # 兼容性与样曲验证：新增全曲或带偏移片段选择，回映整首的时间轴明确保存。
    if ($Full) {
        # 第三首《我不难过》跨歌曲验证：修改UTF-8清单读取，避免PowerShell默认编码损坏中文路径；原代码保留。
        # $inventory = Get-Content -LiteralPath (Join-Path $projectRoot 'reports\first_audio_validation.json') -Raw | ConvertFrom-Json
        $inventory = Get-Content -LiteralPath (Join-Path $projectRoot 'reports\first_audio_validation.json') -Raw -Encoding UTF8 | ConvertFrom-Json
        $inputAudio = $inventory.records[0].audio
        $offsetSeconds = 0.0
    }
    else {
        # 第三首《我不难过》跨歌曲验证：修改UTF-8清单读取，避免PowerShell默认编码损坏中文路径；原代码保留。
        # $sample = Get-Content -LiteralPath (Join-Path $projectRoot 'reports\sample_manifest.json') -Raw | ConvertFrom-Json
        $sample = Get-Content -LiteralPath (Join-Path $projectRoot 'reports\sample_manifest.json') -Raw -Encoding UTF8 | ConvertFrom-Json
        $inputAudio = $sample.sample
        $offsetSeconds = $sample.start_seconds_in_song
    }
    # 兼容性与样曲验证：新增 Demucs GPU 分离及单独报告，失败即停止后续转录。
    $separatedDir = Join-Path $outputDir 'separated'
    $demucsReport = Join-Path $reportDir 'demucs.json'
    & $pythonPath (Join-Path $projectRoot 'tools\check_environment.py') --audio $inputAudio --report $demucsReport --output-dir $separatedDir
    if ($LASTEXITCODE -ne 0) { throw ('人声分离失败，报告：' + $demucsReport) }
    # 第二首《渴》跨歌曲验证：新增分离完成留痕，原素材文件保持。
    "模型验证 $runId：$Song 人声分离完成；下一步ROSVOT/RMVPE整曲转录。" | Add-Content -LiteralPath (Join-Path $reportDir 'stages.log') -Encoding UTF8
    # 兼容性与样曲验证：新增 ROSVOT 单进程转录，歌词尚未对齐的状态由模型报告明确记录。
    $transcriptionDir = Join-Path $outputDir 'transcription'
    & $pythonPath (Join-Path $projectRoot 'tools\rosvot_smoke.py') --input (Join-Path $separatedDir 'vocals.wav') --output-dir $transcriptionDir --source-offset-seconds $offsetSeconds
    if ($LASTEXITCODE -ne 0) { throw ('音符转录失败，证据目录：' + $transcriptionDir) }
    # 兼容性与样曲验证：新增运行清单，保留源选择、偏移、输出与已有阶段范围。
    # 第二首《渴》跨歌曲验证：修改报告输出，原扁平报告行注释保留，新增可直接传入制谱的完整模型报告。
    # [pscustomobject]@{ run_id = $runId; full_song = [bool]$Full; input = $inputAudio; source_offset_seconds = $offsetSeconds; demucs_report = $demucsReport; transcription_summary = (Join-Path $transcriptionDir 'summary.json'); status = '模型兼容性流程通过；歌词对齐、节奏制谱和质量验收另行验证' } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $reportDir 'run.json') -Encoding utf8
    $modelRun = [pscustomobject]@{
        run_id = $runId; full_song = [bool]$Full; input = $inputAudio; selected_song = $Song
        input_audio_sha256 = (Get-FileHash -LiteralPath $inputAudio -Algorithm SHA256).Hash
        source_offset_seconds = $offsetSeconds; demucs_report = $demucsReport
        transcription_summary = (Join-Path $transcriptionDir 'summary.json')
        status = '模型兼容性流程通过；歌词对齐、节奏制谱和质量验收另行验证'
    }
    $modelRun | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath (Join-Path $reportDir 'run.json') -Encoding UTF8
    $modelReportPath = Join-Path $reportDir 'integrated_pipeline.json'
    [pscustomobject]@{
        wall_clock_seconds = $modelWatch.Elapsed.TotalSeconds
        scope = '素材核查/GPU核查/已缓存权重加载/Demucs分离/ROSVOT转录与模型输出，不含ASR/TIFA/制谱或人工听审'
        run = $modelRun
    } | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $modelReportPath -Encoding UTF8
    # 第二首《渴》跨歌曲验证：新增最新指针，保留先前integrated_pipeline.full.json用于首曲回归。
    Copy-Item -LiteralPath $modelReportPath -Destination (Join-Path $projectRoot 'reports\integrated_pipeline.latest.json')
    "模型验证 $runId：$Song 原始转录完成；制谱输入为 $modelReportPath。" | Add-Content -LiteralPath (Join-Path $reportDir 'stages.log') -Encoding UTF8
    Write-Output ('可直接制谱的模型报告：' + $modelReportPath)
    Write-Output ('验证完成，报告目录：' + $reportDir)
}
finally {
    # 兼容性与样曲验证：新增调用者环境恢复，不持久修改系统环境。
    $env:PYTHONIOENCODING = $previousEncoding
    $env:TORCH_HOME = $previousTorchHome
    $modelWatch.Stop() # 第二首《渴》跨歌曲验证：新增计时器停止，不改变其他系统设置。
}
