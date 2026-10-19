#Requires -Version 5.1
[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$portalRoot = $PSScriptRoot
$portalPython = Join-Path $portalRoot '.venv\Scripts\python.exe'
$portalBasePython = Join-Path $portalRoot '..\.venv-gpu\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $portalBasePython)) {
    $portalPythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
    if (-not $portalPythonCommand) { throw '需要先安装Python 3.11，或准备好主项目的Python环境。' }
    $portalBasePython = $portalPythonCommand.Source
}
$portalPackageTemp = Join-Path $portalRoot 'runtime\package_tmp'
New-Item -ItemType Directory -Path $portalPackageTemp -Force | Out-Null
$portalOriginalTemp = $env:TEMP
$portalOriginalTmp = $env:TMP
try {
    $env:TEMP = $portalPackageTemp
    $env:TMP = $portalPackageTemp
    if (-not (Test-Path -LiteralPath $portalPython)) {
        & $portalBasePython -B -X utf8 -m venv (Join-Path $portalRoot '.venv')
        if ($LASTEXITCODE -ne 0) { throw '网页独立环境创建失败。' }
    }
    & $portalPython -B -X utf8 -m pip install --disable-pip-version-check --no-cache-dir -r (Join-Path $portalRoot 'requirements.lock.txt')
    if ($LASTEXITCODE -ne 0) { throw '网页依赖安装失败。' }
    & $portalPython -B -X utf8 (Join-Path $portalRoot 'scripts\download_share.py')
    if ($LASTEXITCODE -ne 0) { throw '免费分享工具下载或校验失败。' }
    & $portalPython -B -X utf8 (Join-Path $portalRoot 'scripts\check_print_environment.py')
    if ($LASTEXITCODE -ne 0) { throw '网页依赖已经安装；打印环境仍有缺项，请按上方提示处理。' }
    Write-Output '网页环境已准备好。双击本文件夹中的“启动网页.cmd”即可。'
} finally {
    $env:TEMP = $portalOriginalTemp
    $env:TMP = $portalOriginalTmp
}
