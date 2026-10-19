# 无旧目录联接迁移：只解析当前工程配置登记的历史根目录，不改变报告内容。
function Resolve-WorkspaceInput {
    param([Parameter(Mandatory=$true)][string]$Value, [Parameter(Mandatory=$true)][string]$Root)
    $mappingFile = Join-Path $Root 'data/workspace_paths.json'
    if (-not (Test-Path -LiteralPath $mappingFile)) { return $Value }
    $mapping = Get-Content -LiteralPath $mappingFile -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($mapping.version -ne 1) { throw '工作区路径映射配置版本无效。' }
    $absolute = [System.IO.Path]::GetFullPath($Value)
    foreach ($previous in $mapping.historical_roots) {
        $prefix = [System.IO.Path]::GetFullPath([string]$previous).TrimEnd('\')
        if ($absolute.Equals($prefix, [System.StringComparison]::OrdinalIgnoreCase)) { return $Root }
        if ($absolute.StartsWith($prefix + '\', [System.StringComparison]::OrdinalIgnoreCase)) {
            $suffix = $absolute.Substring($prefix.Length + 1)
            return Join-Path $Root $suffix
        }
    }
    return $Value
}
