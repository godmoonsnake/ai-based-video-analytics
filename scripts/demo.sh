#!/usr/bin/env bash
# Reproducible DARSON full-stack demo.
#
# MODES
#   ./scripts/demo.sh              deterministic MOCK scenario (default)
#   ./scripts/demo.sh real         REAL prerecorded video through Frigate
#   ./scripts/demo.sh down         stop + remove the stack
#   ./scripts/demo.sh reset        stop + remove volumes (wipe Postgres + media)
#
# Both modes bring up the hardened stack (PostgreSQL + pgvector, Mosquitto,
# Frigate, backend, frontend, reverse proxy), wait for health, then produce an
# incident visible at the reverse-proxy origin. The MOCK path is deterministic
# and fast; the REAL path proves genuine person detection -> MQTT -> adapter ->
# pipeline with real snapshot evidence.
set -euo pipefail

ORIGIN="${DARSON_ORIGIN:-http://localhost:8080}"
cd "$(dirname "$0")/.."
MODE="${1:-mock}"

BASE_COMPOSE=(docker compose)
REAL_COMPOSE=(docker compose -f docker-compose.yml -f docker-compose.real-video.yml)

case "$MODE" in
  down)  exec "${BASE_COMPOSE[@]}" down ;;
  reset) exec "${BASE_COMPOSE[@]}" down -v ;;
esac

wait_healthy() {
  echo "==> Waiting for all services to report healthy…"
  local deadline=$(( $(date +%s) + 300 ))
  while true; do
    local unhealthy
    unhealthy=$("$@" ps --format '{{.Service}} {{.Health}}' | grep -Ev 'healthy$' || true)
    [ -z "$unhealthy" ] && { echo "    all services healthy."; break; }
    [ "$(date +%s)" -ge "$deadline" ] && { echo "!! Timeout:"; "$@" ps; exit 1; }
    sleep 5
  done
}

if [ "$MODE" = "real" ]; then
  echo "==> REAL-VIDEO demo."
  echo "==> Fetching CC-BY-4.0 sample videos (gitignored)…"
  ./scripts/fetch_test_videos.sh
  echo "==> Starting the stack with the real-video Frigate source…"
  "${REAL_COMPOSE[@]}" up -d --build
  wait_healthy "${REAL_COMPOSE[@]}"
  echo "==> Letting Frigate detect people and the backend ingest events (60s)…"
  sleep 60
  echo "==> Seeding topology + embeddings, correlating and building incidents on REAL events…"
  docker exec darson-intel-backend-1 python -c "
from app.db.session import SessionLocal
from app.adapters.mock_source import load_topology, SCENARIOS_DIR
from app.adapters.ingestion import seed_embeddings
from app.pipeline.correlator import correlate
from app.pipeline.incident_builder import build_incidents
db=SessionLocal()
try:
    load_topology(db, SCENARIOS_DIR/'topology_real.json')
    seed_embeddings(db); correlate(db)
    print('  incidents:', build_incidents(db))
finally: db.close()
"
else
  echo "==> MOCK deterministic demo."
  "${BASE_COMPOSE[@]}" up -d --build
  wait_healthy "${BASE_COMPOSE[@]}"
  echo "==> Seeding the deterministic pipeline via the reverse proxy ($ORIGIN)…"
  curl -fsS -X POST "$ORIGIN/events/ingest/mock" >/dev/null
  curl -fsS -X POST "$ORIGIN/tracks/correlate"   >/dev/null
  echo "    incidents/build -> $(curl -fsS -X POST "$ORIGIN/incidents/build")"
fi

echo "==> Incidents now visible via the v1 API:"
curl -fsS "$ORIGIN/api/v1/incidents"
echo
echo "Demo ready. Open the dashboard at:  $ORIGIN"
echo "Stop:  ./scripts/demo.sh down     Reset (wipe DB):  ./scripts/demo.sh reset"
