param([int]$Port = 8769, [string]$ListenAddress = '0.0.0.0')
$ErrorActionPreference='Stop'
$env:PYTHONUTF8='1'
$python=Join-Path $HOME '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
if(-not (Test-Path -LiteralPath $python)){$python=(Get-Command python -ErrorAction Stop).Source}
try{$health=Invoke-RestMethod "http://127.0.0.1:$Port/health" -TimeoutSec 2;if($health.service -eq 'canvas-results'){Write-Host "Already running: http://127.0.0.1:$Port/";exit 0}}catch{}
& $python (Join-Path $PSScriptRoot 'canvas_results.py') --host $ListenAddress --port $Port
