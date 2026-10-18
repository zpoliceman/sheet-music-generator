# 兼容性与样曲验证：新增项目内统一验证入口，不修改系统 Python 或系统 PATH。
[CmdletBinding()]
param(
    [ValidateSet('AudioFirst', 'AudioAll', 'Notation', 'GPU')]
    [string]$Stage = 'AudioFirst'
)
$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$projectPython = Join-Path $projectRoot '.venv-gpu\Scripts\python.exe'
# 兼容性与样曲验证：新增项目内运行时回退，仅执行无第三方依赖的素材与格式检查。
if (-not (Test-Path -LiteralPath $projectPython)) {
    $runtimeRoot = Join-Path $projectRoot '.runtime\python'
    $runtimePython = @(Get-ChildItem -LiteralPath $runtimeRoot -Directory -ErrorAction SilentlyContinue | ForEach-Object { Join-Path $_.FullName 'python.exe' } | Where-Object { Test-Path -LiteralPath $_ })
    if ($runtimePython.Count -ne 1) { throw '未找到唯一项目内 Python，请先建立隔离环境。' }
    $projectPython = $runtimePython[0]
}
# 兼容性与样曲验证：新增当前子进程 UTF-8 与项目缓存设置，结束时恢复调用者环境。
$previousEncoding = $env:PYTHONIOENCODING
$previousTorchHome = $env:TORCH_HOME
try {
    $env:PYTHONIOENCODING = 'utf-8'
    $env:TORCH_HOME = Join-Path $projectRoot '.cache\torch'
    # 兼容性与样曲验证：新增按阶段执行，每步检查返回码并保留原素材。
    switch ($Stage) {
        'AudioFirst' { & $projectPython (Join-Path $projectRoot 'tools\audio_inventory.py') --first '孙燕姿 - 遇见.ncm' }
        'AudioAll' { & $projectPython (Join-Path $projectRoot 'tools\audio_inventory.py') --all }
        'Notation' { & $projectPython (Join-Path $projectRoot 'tools\notation_smoke.py') check (Join-Path $projectRoot 'test_outputs\notation\synthetic_vocal.musicxml') --require-match }
        'GPU' { & $projectPython (Join-Path $projectRoot 'tools\check_environment.py') --report (Join-Path $projectRoot 'reports\environment_recheck.json') }
    }
    if ($LASTEXITCODE -ne 0) { throw ('验证阶段失败：' + $Stage + '，返回码 ' + $LASTEXITCODE) }
}
finally {
    # 兼容性与样曲验证：新增调用者环境恢复，避免持久修改。
    $env:PYTHONIOENCODING = $previousEncoding
    $env:TORCH_HOME = $previousTorchHome
}
