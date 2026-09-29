#!/usr/bin/env bash
# Reproducible DARSON full-stack demo.
#
# Brings up the hardened compose stack (PostgreSQL + pgvector, Mosquitto,
# Frigate, backend, frontend, reverse proxy), waits for every service to become
# healthy, then runs the deterministic demo pipeline through the SAME origin the
# browser uses (the reverse proxy) so the incident is built and persisted in
# PostgreSQL. Finally it prints the browser URL.
#
# Usage:  ./scripts/demo.sh          (bring up + seed)
#         ./scripts/demo.sh down     (stop + remove the stack)
#         ./scripts/demo.sh reset    (stop + remove volumes = wipe Postgres)
set -euo pipefail

ORIGIN="${DARSON_ORIGIN:-http://localhost:8080}"
COMPOSE="docker compose"

cd "$(dirname "$0")/.."

case "${1:-up}" in
  down)  exec $COMPOSE down ;;
  reset) exec $COMPOSE down -v ;;
esac

echo "==> Building and starting the full stack (this pulls images on first run)…"
$COMPOSE up -d --build

echo "==> Waiting for all services to report healthy…"
deadline=$(( $(date +%s) + 240 ))
while true; do
  # Every service with a healthcheck must be 'healthy'.
  unhealthy=$($COMPOSE ps --format '{{.Service}} {{.Health}}' | grep -Ev 'healthy$' || true)
  if [ -z "$unhealthy" ]; then
    echo "    all services healthy."
    break
  fi
  if [ "$(date +%s)" -ge "$deadline" ]; then
    echo "!! Timed out waiting for services. Current status:"
    $COMPOSE ps
    exit 1
  fi
  sleep 5
done

echo "==> Seeding the deterministic demo pipeline via the reverse proxy origin ($ORIGIN)…"
curl -fsS -X POST "$ORIGIN/events/ingest/mock"   >/dev/null
curl -fsS -X POST "$ORIGIN/tracks/correlate"     >/dev/null
built=$(curl -fsS -X POST "$ORIGIN/incidents/build")
echo "    incidents/build -> $built"

echo "==> Confirming the incident persisted in PostgreSQL (via v1 API)…"
incidents=$(curl -fsS "$ORIGIN/api/v1/incidents")
echo "    /api/v1/incidents -> $incidents"

echo
echo "Demo ready. Open the dashboard at:  $ORIGIN"
echo "Stop with:  ./scripts/demo.sh down     Reset (wipe DB) with:  ./scripts/demo.sh reset"
