# Reproducible DARSON full-stack demo (Windows PowerShell).
#
# Mirrors scripts/demo.sh: bring up the hardened compose stack (PostgreSQL +
# pgvector, Mosquitto, Frigate, backend, frontend, reverse proxy), wait for all
# services to become healthy, then seed the deterministic demo pipeline through
# the reverse-proxy origin so the incident persists in PostgreSQL.
#
# Usage:  .\scripts\demo.ps1            (bring up + seed)
#         .\scripts\demo.ps1 down       (stop + remove the stack)
#         .\scripts\demo.ps1 reset      (stop + remove volumes = wipe Postgres)
param([string]$Command = "up")

$ErrorActionPreference = "Stop"
$origin = if ($env:DARSON_ORIGIN) { $env:DARSON_ORIGIN } else { "http://localhost:8080" }
Set-Location (Join-Path $PSScriptRoot "..")

if ($Command -eq "down")  { docker compose down; exit $LASTEXITCODE }
if ($Command -eq "reset") { docker compose down -v; exit $LASTEXITCODE }

Write-Host "==> Building and starting the full stack (first run pulls images)…"
docker compose up -d --build

Write-Host "==> Waiting for all services to report healthy…"
$deadline = (Get-Date).AddSeconds(240)
while ($true) {
    $status = docker compose ps --format '{{.Service}} {{.Health}}'
    $unhealthy = $status | Where-Object { $_ -notmatch 'healthy$' }
    if (-not $unhealthy) { Write-Host "    all services healthy."; break }
    if ((Get-Date) -ge $deadline) {
        Write-Host "!! Timed out waiting for services:"; docker compose ps; exit 1
    }
    Start-Sleep -Seconds 5
}

Write-Host "==> Seeding the deterministic demo pipeline via the reverse proxy ($origin)…"
Invoke-RestMethod -Method POST -Uri "$origin/events/ingest/mock" | Out-Null
Invoke-RestMethod -Method POST -Uri "$origin/tracks/correlate"   | Out-Null
$built = Invoke-RestMethod -Method POST -Uri "$origin/incidents/build"
Write-Host "    incidents/build -> $($built | ConvertTo-Json -Compress)"

Write-Host "==> Confirming the incident persisted in PostgreSQL (via v1 API)…"
$incidents = Invoke-RestMethod -Uri "$origin/api/v1/incidents"
Write-Host "    /api/v1/incidents -> $($incidents | ConvertTo-Json -Compress)"

Write-Host ""
Write-Host "Demo ready. Open the dashboard at:  $origin"
Write-Host "Stop with:  .\scripts\demo.ps1 down    Reset (wipe DB) with:  .\scripts\demo.ps1 reset"
