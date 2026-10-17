param([int]$Port = 8770)
$ErrorActionPreference = 'Stop'
$python = "$HOME\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    $command = Get-Command python -ErrorAction SilentlyContinue
    if ($command) { $python = $command.Source }
}
if (-not (Test-Path -LiteralPath $python)) { throw 'Python was not found. Install Python 3.11+ or configure the bundled Codex runtime.' }
Write-Host "Starting draft-only Dreamina executor on http://127.0.0.1:$Port (Ctrl+C to stop)." -ForegroundColor Cyan
& $python "$PSScriptRoot\service.py" --host 127.0.0.1 --port $Port
exit $LASTEXITCODE
