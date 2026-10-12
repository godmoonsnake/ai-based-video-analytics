# Start the DARSON review UI without Docker, using an isolated local SQLite database.
# Run from any directory: powershell -ExecutionPolicy Bypass -File scripts\start-local.ps1
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$backendRoot = Join-Path $projectRoot 'backend'
$frontendRoot = Join-Path $projectRoot 'frontend'
$runtime = Join-Path $backendRoot '.venv-local\Scripts\python.exe'
$logRoot = Join-Path $backendRoot 'var\local-web-run'
New-Item -ItemType Directory -Force -Path $logRoot | Out-Null

if (-not (Test-Path -LiteralPath $runtime)) {
    Push-Location $backendRoot
    try { python -m venv .venv-local }
    finally { Pop-Location }
}
& $runtime -c 'import fastapi, sqlalchemy, uvicorn'
if ($LASTEXITCODE -ne 0) {
    & $runtime -m pip install --disable-pip-version-check -r (Join-Path $backendRoot 'requirements.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Backend dependency installation failed.' }
}

$nodeCommand = Get-Command node -ErrorAction SilentlyContinue
$node = if ($nodeCommand) { $nodeCommand.Source } else {
    Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe'
}
if (-not (Test-Path -LiteralPath $node)) { throw 'Node.js is required to run the local frontend.' }
if (-not (Test-Path -LiteralPath (Join-Path $frontendRoot 'node_modules\vite\bin\vite.js'))) {
    throw 'Frontend dependencies are missing. Run npm ci in the frontend directory.'
}

function Test-Port([int]$port) {
    return [bool](Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue)
}
function Wait-Http([string]$url) {
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        try {
            $result = Invoke-WebRequest -Uri $url -TimeoutSec 2 -UseBasicParsing
            if ($result.StatusCode -eq 200) { return }
        } catch { }
        Start-Sleep -Seconds 1
    }
    throw "Service did not become ready at $url. Check $logRoot."
}

if (-not (Test-Port 8000)) {
    $env:DARSON_DATABASE_URL = 'sqlite:///./var/review-demo-v3.db'
    $env:DARSON_EVIDENCE_ROOT = './var/review-demo-v3-evidence'
    $env:DARSON_SPOOL_ROOT = './var/review-demo-v3-spool'
    Start-Process -FilePath $runtime -ArgumentList @('-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8000') `
        -WorkingDirectory $backendRoot -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $logRoot 'api.out.log') `
        -RedirectStandardError (Join-Path $logRoot 'api.err.log') | Out-Null
}
Wait-Http 'http://127.0.0.1:8000/health'

$workerPidPath = Join-Path $logRoot 'worker.pid'
$worker = $null
if (Test-Path -LiteralPath $workerPidPath) {
    $recordedPid = [int](Get-Content -LiteralPath $workerPidPath -Raw)
    $worker = Get-CimInstance Win32_Process -Filter "ProcessId=$recordedPid" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -like '*-m app.processing.worker jobs*' }
}
if (-not $worker) {
    $workerProcess = Start-Process -FilePath $runtime -ArgumentList @('-m', 'app.processing.worker', 'jobs') `
        -WorkingDirectory $backendRoot -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $logRoot 'worker.out.log') `
        -RedirectStandardError (Join-Path $logRoot 'worker.err.log') -PassThru
    Set-Content -LiteralPath $workerPidPath -Value $workerProcess.Id
}

if (-not (Test-Port 8080)) {
    $env:DARSON_DEV_PROXY_TARGET = 'http://127.0.0.1:8000'
    $env:DARSON_DEV_PORT = '8080'
    Start-Process -FilePath $node -ArgumentList @('node_modules/vite/bin/vite.js', '--host', '127.0.0.1') `
        -WorkingDirectory $frontendRoot -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $logRoot 'web.out.log') `
        -RedirectStandardError (Join-Path $logRoot 'web.err.log') | Out-Null
}
Wait-Http 'http://127.0.0.1:8080/'
Write-Host 'DARSON local site is ready: http://127.0.0.1:8080/'
Write-Host 'This uses an isolated development-only SQLite review scope and synthetic replay.'
