param(
    [string]$SourceDir,
    [string]$Manifest,
    [string]$Drama,
    [string]$ProjectId,
    [string]$StateDir,
    [int]$Limit = 3,
    [switch]$PrepareOnly,
    [switch]$Execute,
    [switch]$Resume
)
$ErrorActionPreference = 'Stop'
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
# ASCII-only so Windows PowerShell 5 can launch this without an encoding change.
$python = Join-Path $HOME '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    $python = (Get-Command python -ErrorAction Stop).Source
}
if ((-not $SourceDir -and -not $Manifest) -or ($SourceDir -and $Manifest)) {
    throw 'Supply exactly one of -SourceDir or -Manifest.'
}
if ($PrepareOnly -and $Execute) { throw 'Choose -PrepareOnly or -Execute, not both.' }
$arguments = @((Join-Path $PSScriptRoot 'migrate_haishan.py'), '--limit', [string]$Limit)
if ($SourceDir) { $arguments += @('--source-dir', $SourceDir) }
if ($Manifest) { $arguments += @('--manifest', $Manifest) }
if ($Drama) { $arguments += @('--drama', $Drama) }
if ($ProjectId) { $arguments += @('--project-id', $ProjectId) }
if ($StateDir) { $arguments += @('--state-dir', $StateDir) }
if ($PrepareOnly) { $arguments += '--prepare-only' }
if ($Execute) { $arguments += '--execute' }
if ($Resume) { $arguments += '--resume' }
& $python @arguments
exit $LASTEXITCODE
