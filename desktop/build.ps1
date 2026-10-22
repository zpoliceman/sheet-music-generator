[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$compiler = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
if (-not (Test-Path -LiteralPath $compiler -PathType Leaf)) {
    throw '找不到Windows自带的.NET Framework 4编译器。请先安装.NET Framework 4.8。'
}
$source = Join-Path $PSScriptRoot 'SheetMusicApp.cs'
$supervisorSource = Join-Path $PSScriptRoot 'TaskSupervisor.cs'
$manifest = Join-Path $PSScriptRoot 'app.manifest'
$output = Join-Path $projectRoot '弦页制谱.exe'
& $compiler /nologo /target:winexe /platform:x64 /optimize+ /codepage:65001 "/win32manifest:$manifest" "/out:$output" /reference:System.Windows.Forms.dll /reference:System.Drawing.dll /reference:System.Web.Extensions.dll /reference:System.Core.dll $source $supervisorSource
if ($LASTEXITCODE -ne 0) { throw 'EXE编译失败，请查看上面的错误。' }
Write-Output ('已生成：' + $output)
Write-Output '双击该EXE，选择音源、TXT歌词和保存文件夹，即可开始。EXE需与当前项目及已安装环境一起使用。'
