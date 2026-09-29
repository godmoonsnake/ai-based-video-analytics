# DARSON demo (PowerShell wrapper).
# Starts the backend (SQLite, mock source) and runs the demo driver.
#
#   ./demo.ps1
#
param([string]$Base = "http://localhost:8000")

Write-Host "Starting DARSON backend (uvicorn)..." -ForegroundColor Cyan
$backend = Start-Process -PassThru -NoNewWindow -FilePath "python" `
    -ArgumentList "-m", "uvicorn", "app.main:app", "--port", "8000" `
    -WorkingDirectory "$PSScriptRoot/backend"

try {
    Start-Sleep -Seconds 3
    Write-Host "Running demo pipeline..." -ForegroundColor Cyan
    python "$PSScriptRoot/demo.py" $Base
}
finally {
    Write-Host "Stopping backend..." -ForegroundColor Cyan
    if ($backend -and -not $backend.HasExited) { Stop-Process -Id $backend.Id -Force }
}
