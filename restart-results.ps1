$ErrorActionPreference='Stop'
$pidFile=Join-Path $PSScriptRoot '.data\canvas-results.pid'
if(Test-Path -LiteralPath $pidFile){
    $servicePid=[int](Get-Content -LiteralPath $pidFile -Raw)
    $process=Get-CimInstance Win32_Process -Filter "ProcessId=$servicePid"
    $expected=Join-Path $PSScriptRoot 'canvas_results.py'
    if($process){
        if(-not $process.CommandLine.Contains($expected)){throw 'PID does not match canvas_results.py; stopped safely'}
        Stop-Process -Id $servicePid
        Start-Sleep -Seconds 1
    }
}
& (Join-Path $PSScriptRoot 'start-results.ps1')
