# 和弦弹唱与伴奏编配：新增Windows独立入口，复用认可人声及同源分轨，不覆盖原谱。
# 默认入口原曲节拍强制复核：修改，旧只支持新曲源输入的签名保留；新增旧工程参数集，默认一样必须核对原拍。
# param(
#     [Parameter(Mandatory=$true)][string]$VocalProject,
#     [Parameter(Mandatory=$true)][string]$DemucsReport,
[CmdletBinding(DefaultParameterSetName='FromAudio')]
param(
    [Parameter(Mandatory=$true,ParameterSetName='FromAudio')][string]$VocalProject,
    [Parameter(Mandatory=$true,ParameterSetName='FromAudio')][string]$DemucsReport,
    # 默认入口原曲节拍强制复核：新增旧工程直接调用，未经校准输入自动重建，用户无需记额外修复开关。
    [Parameter(Mandatory=$true,ParameterSetName='FromProject')][string]$EditedProject,
    # 吉他编配规则与统一验收修复：新增保留已认可音乐的吉他修订入口，参数只用于已有工程。
    [Parameter(ParameterSetName='FromProject')][switch]$ReadableGuitar,
    [Parameter(ParameterSetName='FromProject')][string]$ReadabilityFeatureCache,
    [Parameter(Mandatory=$true)][string]$Output,
    [string]$AnalysisDir = "test_outputs/accompaniment_runs/current",
    [string[]]$Reference = @(),
    [int]$Capo = -1,
    # 默认入口原曲节拍强制复核：修改，旧末项保留；增加显式独立简谱／重新核准及报告参数。
    # [switch]$SixSources
    [switch]$SixSources,
    [switch]$ExportVocal,
    [switch]$RebuildSourceMeter,
    # 器乐合理分句与十二品硬限制：新增历史吉他另存升级参数；普通重导保留历史音乐。
    [switch]$LowPositionInstrumental,
    # 原声覆盖与选音归属通用修复：新增通用来源绑定认可段落保留入口，参数映射到正式Python生成程序。
    [string]$ApprovedSectionReview,
    [string]$Report
)
# 和弦弹唱与伴奏编配：新增参数数组调用，路径含中文/空格也不拼接为shell代码。
$ErrorActionPreference = 'Stop'
# 默认入口原曲节拍强制复核：修改，旧参数数组保留；按互斥参数集传递，使用统一CLI及项目内独立缓存。
# $accompanimentArguments = @('-X','utf8',(Join-Path $PSScriptRoot 'tools/generate_accompaniment.py'),
#     '--vocal-project',$VocalProject,'--demucs-report',$DemucsReport,'--output',$Output,'--analysis-dir',$AnalysisDir)
$accompanimentArguments = @('-B','-X','utf8',(Join-Path $PSScriptRoot 'tools/generate_accompaniment.py'),
    '--output',$Output,'--analysis-dir',$AnalysisDir)
if ($PSCmdlet.ParameterSetName -eq 'FromProject') {
    $accompanimentArguments += @('--edited-project',$EditedProject)
} else {
    $accompanimentArguments += @('--vocal-project',$VocalProject,'--demucs-report',$DemucsReport)
}
# 默认入口原曲节拍强制复核：新增窄参数映射，不使用拼接Shell字符串，也不暴露跳过检查的开关。
if ($ExportVocal) { $accompanimentArguments += '--export-vocal' }
if ($RebuildSourceMeter) { $accompanimentArguments += '--rebuild-source-meter' }
# 吉他编配规则与统一验收修复：新增直接数组映射，经过Python共用原音／规则验收，仅隔离另存。
if ($ReadableGuitar) { $accompanimentArguments += '--readable-guitar' }
if ($ReadabilityFeatureCache) { $accompanimentArguments += @('--readability-feature-cache',$ReadabilityFeatureCache) }
# 器乐合理分句与十二品硬限制：新增参数数组映射，不拼接Shell代码或提供跳过12品验收的开关。
if ($LowPositionInstrumental) { $accompanimentArguments += '--low-position-instrumental' }
# 原声覆盖与选音归属通用修复：新增数组传参，中文路径和空格不进入动态Shell拼接。
if ($ApprovedSectionReview) { $accompanimentArguments += @('--approved-section-review',$ApprovedSectionReview) }
if ($Report) { $accompanimentArguments += @('--report',$Report) }
foreach ($accompanimentReference in $Reference) { $accompanimentArguments += @('--reference',$accompanimentReference) }
if ($Capo -ge 0) { $accompanimentArguments += @('--capo',[string]$Capo) }
if ($SixSources) { $accompanimentArguments += '--six-sources' }
Push-Location -LiteralPath $PSScriptRoot
try {
    & (Join-Path $PSScriptRoot '.venv-gpu/Scripts/python.exe') @accompanimentArguments
    if ($LASTEXITCODE -ne 0) { throw "伴奏编配退出码：$LASTEXITCODE" }
} finally { Pop-Location }
