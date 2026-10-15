$ErrorActionPreference = 'Stop'
if ($env:DARSON_ENVIRONMENT -eq 'production') { throw 'Synthetic review is forbidden in a production environment.' }
$projectRoot = Split-Path -Parent $PSScriptRoot
$backendRoot = Join-Path $projectRoot 'backend'
$frontendRoot = Join-Path $projectRoot 'frontend'
$logRoot = Join-Path $backendRoot 'var\pilot-review-logs'
New-Item -ItemType Directory -Force -Path $logRoot | Out-Null

# Use the installed Python with existing local libraries when the old venv's
# interpreter path is stale. Never rewrite or remove an existing environment.
$pythonCommand = Get-Command python -ErrorAction Stop
$runtime = $pythonCommand.Source
$localPackages = Join-Path $backendRoot '.venv-local\Lib\site-packages'
if (Test-Path -LiteralPath $localPackages) { $env:PYTHONPATH = $localPackages }
& $runtime -c 'import fastapi, sqlalchemy, uvicorn'
if ($LASTEXITCODE -ne 0) { throw 'Install backend requirements in a working Python environment first.' }
$node = (Get-Command node -ErrorAction Stop).Source
if (-not (Test-Path -LiteralPath (Join-Path $frontendRoot 'node_modules\vite\bin\vite.js'))) {
    throw 'Run npm ci in frontend first.'
}

$env:DARSON_ENVIRONMENT = 'development'
$env:DARSON_AUTH_MODE = 'development'
$env:DARSON_PILOT_MODE = 'true'
$env:DARSON_NOTIFICATION_PROVIDER = 'local'
$env:DARSON_DATABASE_URL = 'sqlite:///./var/pilot-review-v2.db'
$env:DARSON_EVIDENCE_ROOT = './var/pilot-review-evidence'
$env:DARSON_PILOT_SUPERVISOR_SUBJECT = 'development-operator'
$env:DARSON_DEV_PROXY_TARGET = 'http://127.0.0.1:8011'
$env:DARSON_DEV_PORT = '8081'

if (Get-NetTCPConnection -State Listen -LocalPort 8011,8081 -ErrorAction SilentlyContinue) {
    throw 'Ports 8011 or 8081 are already in use. Reuse the existing review or stop its own recorded processes first.'
}
& $runtime (Join-Path $PSScriptRoot 'seed-pilot-review.py')
if ($LASTEXITCODE -ne 0) { throw 'Synthetic pilot seed failed.' }
$apiProcess = Start-Process -FilePath $runtime -ArgumentList @('-m','uvicorn','app.main:app','--host','127.0.0.1','--port','8011') `
    -WorkingDirectory $backendRoot -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput (Join-Path $logRoot 'api.out.log') -RedirectStandardError (Join-Path $logRoot 'api.err.log')
$webProcess = Start-Process -FilePath $node -ArgumentList @('node_modules/vite/bin/vite.js','--host','127.0.0.1') `
    -WorkingDirectory $frontendRoot -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput (Join-Path $logRoot 'web.out.log') -RedirectStandardError (Join-Path $logRoot 'web.err.log')
$workerProcess = Start-Process -FilePath $runtime -ArgumentList @('-m','app.processing.worker','jobs') `
    -WorkingDirectory $backendRoot -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput (Join-Path $logRoot 'worker.out.log') -RedirectStandardError (Join-Path $logRoot 'worker.err.log')
Set-Content -LiteralPath (Join-Path $logRoot 'api.pid') -Value $apiProcess.Id
Set-Content -LiteralPath (Join-Path $logRoot 'web.pid') -Value $webProcess.Id
Set-Content -LiteralPath (Join-Path $logRoot 'worker.pid') -Value $workerProcess.Id
Write-Host 'SIMULATED pilot review: http://127.0.0.1:8081'
Write-Host 'No recorder is connected; external messages are suppressed. Existing databases are preserved.'
