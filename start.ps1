param([int]$Port = 8765)
$ErrorActionPreference = 'Stop'
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
# Keep this file ASCII-only: Windows PowerShell 5 reads BOM-less UTF-8 as ANSI.
try {
    $health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 2
    if ($health.application -eq 'dreamina-local-manager' -and $health.workspace -eq $PSScriptRoot) {
        Write-Host "Manager is already running: http://127.0.0.1:$Port"
        exit 0
    }
} catch { }
$bundledPython = Join-Path $HOME '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
if (Test-Path -LiteralPath $bundledPython) { $python = $bundledPython }
elseif (Get-Command python -ErrorAction SilentlyContinue) { $python = (Get-Command python).Source }
else { throw 'Python was not found. Use the Codex bundled runtime or install Python 3.11+.' }
& $python (Join-Path $PSScriptRoot 'manager.py') --port $Port
exit $LASTEXITCODE
