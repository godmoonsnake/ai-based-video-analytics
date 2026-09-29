# Reproducible DARSON full-stack demo (Windows PowerShell).
#
# MODES
#   .\scripts\demo.ps1            deterministic MOCK scenario (default)
#   .\scripts\demo.ps1 real       REAL prerecorded video through Frigate
#   .\scripts\demo.ps1 down       stop + remove the stack
#   .\scripts\demo.ps1 reset      stop + remove volumes (wipe Postgres + media)
param([string]$Command = "mock")

$ErrorActionPreference = "Stop"
$origin = if ($env:DARSON_ORIGIN) { $env:DARSON_ORIGIN } else { "http://localhost:8080" }
Set-Location (Join-Path $PSScriptRoot "..")

if ($Command -eq "down")  { docker compose down; exit $LASTEXITCODE }
if ($Command -eq "reset") { docker compose down -v; exit $LASTEXITCODE }

function Wait-Healthy([string[]]$ComposeArgs) {
    Write-Host "==> Waiting for all services to report healthy..."
    $deadline = (Get-Date).AddSeconds(300)
    while ($true) {
        $status = & docker @ComposeArgs ps --format '{{.Service}} {{.Health}}'
        if (-not ($status | Where-Object { $_ -notmatch 'healthy$' })) { Write-Host "    all healthy."; break }
        if ((Get-Date) -ge $deadline) { Write-Host "!! Timeout:"; & docker @ComposeArgs ps; exit 1 }
        Start-Sleep -Seconds 5
    }
}

if ($Command -eq "real") {
    $c = @("compose","-f","docker-compose.yml","-f","docker-compose.real-video.yml")
    Write-Host "==> REAL-VIDEO demo. Fetching CC-BY-4.0 sample videos (gitignored)..."
    powershell -ExecutionPolicy Bypass -File scripts\fetch_test_videos.ps1
    Write-Host "==> Starting the stack with the real-video Frigate source..."
    & docker @c up -d --build
    Wait-Healthy $c
    Write-Host "==> Letting Frigate detect people and the backend ingest events (60s)..."
    Start-Sleep -Seconds 60
    Write-Host "==> Correlating + building incidents on REAL events..."
    docker exec darson-intel-backend-1 python -c "from app.db.session import SessionLocal; from app.adapters.mock_source import load_topology, SCENARIOS_DIR; from app.adapters.ingestion import seed_embeddings; from app.pipeline.correlator import correlate; from app.pipeline.incident_builder import build_incidents; db=SessionLocal(); load_topology(db, SCENARIOS_DIR/'topology_real.json'); seed_embeddings(db); correlate(db); print('  incidents:', build_incidents(db)); db.close()"
} else {
    Write-Host "==> MOCK deterministic demo."
    docker compose up -d --build
    Wait-Healthy @("compose")
    Write-Host "==> Seeding the deterministic pipeline via the reverse proxy ($origin)..."
    Invoke-RestMethod -Method POST -Uri "$origin/events/ingest/mock" | Out-Null
    Invoke-RestMethod -Method POST -Uri "$origin/tracks/correlate"   | Out-Null
    Write-Host "    incidents/build -> $((Invoke-RestMethod -Method POST -Uri "$origin/incidents/build") | ConvertTo-Json -Compress)"
}

Write-Host "==> Incidents via v1 API: $((Invoke-RestMethod -Uri "$origin/api/v1/incidents") | ConvertTo-Json -Compress)"
Write-Host ""
Write-Host "Demo ready. Open the dashboard at:  $origin"
Write-Host "Stop:  .\scripts\demo.ps1 down     Reset (wipe DB):  .\scripts\demo.ps1 reset"
