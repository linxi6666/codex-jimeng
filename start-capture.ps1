$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$chrome = 'C:\Program Files\Google\Chrome\Application\chrome.exe'
if (-not (Test-Path -LiteralPath $chrome)) { throw 'Chrome was not found' }
$node = Join-Path $HOME '.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe'
if (-not (Test-Path -LiteralPath $node)) { $node = (Get-Command node -ErrorAction Stop).Source }
$profile = Join-Path $root '.data\capture-chrome-profile'
New-Item -ItemType Directory -Path $profile -Force | Out-Null
try {
    $status = Invoke-RestMethod 'http://127.0.0.1:9230/status' -TimeoutSec 2
    if ($status.running) { Write-Host 'Local capture is already running.'; return }
} catch {}
$arguments = @('--remote-debugging-address=127.0.0.1', '--remote-debugging-port=9227',
    ('--user-data-dir="' + $profile + '"'), '--no-first-run', '--no-default-browser-check',
    'https://jimeng.jianying.com/ai-tool/elements')
# The user explicitly asked for a visible dedicated Chrome window to perform actions.
Start-Process -FilePath $chrome -ArgumentList $arguments | Out-Null
& $node (Join-Path $root 'capture-jimeng.cjs')
