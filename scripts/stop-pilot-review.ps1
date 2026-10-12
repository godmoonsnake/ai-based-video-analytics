$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$logRoot = Join-Path $projectRoot 'backend\var\pilot-review-logs'
$expectedCommands = @{
    api = '-m uvicorn app.main:app --host 127.0.0.1 --port 8011'
    web = 'node_modules/vite/bin/vite.js --host 127.0.0.1'
    worker = '-m app.processing.worker jobs'
}
foreach ($role in $expectedCommands.Keys) {
    $record = Join-Path $logRoot "$role.pid"
    if (-not (Test-Path -LiteralPath $record)) { continue }
    $recordedPid = [int](Get-Content -LiteralPath $record -Raw)
    if ($recordedPid -le 0) { continue }
    $process = Get-CimInstance Win32_Process -Filter "ProcessId=$recordedPid" -ErrorAction SilentlyContinue
    if (-not $process) { continue }
    $pidTime = (Get-Item -LiteralPath $record).LastWriteTime
    if ($process.CommandLine -notlike "*$($expectedCommands[$role])*" -or $process.CreationDate -gt $pidTime.AddSeconds(2)) {
        throw "Recorded $role PID no longer matches this review; refusing to stop it."
    }
    Stop-Process -Id $recordedPid -ErrorAction Stop
    Set-Content -LiteralPath $record -Value 0
}
Write-Host 'Stopped only the recorded simulated review helpers.'
