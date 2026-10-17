param([int]$Port = 8768)
$ErrorActionPreference = 'Stop'
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
try {
    $null = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/" -UseBasicParsing -SessionVariable localSession -TimeoutSec 2
    $state = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/session" -WebSession $localSession -TimeoutSec 2
    if ($state.mode -eq 'video-assets-only') {
        Write-Host "Video assets are already running: http://127.0.0.1:$Port/"
        exit 0
    }
} catch { }
$python = Join-Path $HOME '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
if (-not (Test-Path -LiteralPath $python)) { $python = (Get-Command python -ErrorAction Stop).Source }
& $python (Join-Path $PSScriptRoot 'asset_server.py') --port $Port
exit $LASTEXITCODE
