# DARSON Intelligence Layer

An AI-based video-analytics **intelligence layer that sits ABOVE an existing VMS**
(e.g. Katomaran, Frigate). It does not replace a VMS. It turns raw
detections/events into contextual intelligence:

```
EVENT -> CONTEXT -> CORRELATION -> INCIDENT -> HISTORY -> INVESTIGATION
```

## Guardrails (hard constraints)
- Human-in-the-loop decision support only.
- **No** facial recognition, **no** gait recognition, **no** PII database.
- **No** autonomous crime/threat verdicts, **no** automated physical response.

## Capabilities
1. Event normalization (source-agnostic canonical schema)
2. Behavioural sequence analysis (per-track state machine)
3. Cross-camera correlation (topology + time-window + motion + OSNet appearance embeddings)
4. Incident graph + chronological cross-camera timeline reconstruction
5. Historical pattern intelligence (recurring paths/locations/time-windows/hotspots/anomalies)
6. Investigation (deterministic structured search first; optional local LLM for NL + summaries)
7. Evidence traceability: Incident -> Event -> Camera -> Evidence
8. Operator dashboard

## Inputs (pluggable behind one EventSource interface)
- **Mock Event Source** — scripted offline scenarios (default demo path).
- **Frigate Adapter** — read-only: subscribes to `frigate/events` (MQTT) and fetches
  evidence via Frigate's HTTP API. We consume Frigate; we do not fork it.

## Tech stack
- Backend: Python + FastAPI + SQLAlchemy
- DB: PostgreSQL + pgvector (SQLite fallback for offline tests/demo)
- Re-ID embeddings: OSNet / TorchReID (512-d)
- Frontend: React + Vite + TypeScript

## Full-stack demo (Docker · PostgreSQL + pgvector · single origin)

### 1. Prerequisites
- Docker + Docker Compose v2 (tested with Docker 29 / Compose v2).
- ~2 GB free RAM and disk for the Frigate + Postgres images.
- For local (non-Docker) dev/tests: Python 3.12 and Node 20+.

### 2. Environment variables (set by compose; override as needed)
| Variable | Purpose | Compose value |
|---|---|---|
| `DARSON_DATABASE_URL` | Backend DB DSN | `postgresql+psycopg2://darson:darson@db:5432/darson` |
| `DARSON_EVENT_SOURCE` | `mock` (deterministic) or `frigate` | `mock` |
| `DARSON_FRIGATE_MQTT_HOST` | Broker host for the adapter | `mosquitto` |
| `DARSON_FRIGATE_API_BASE` | Server-side Frigate API (internal) | `http://frigate:5000` |
| `DARSON_FRIGATE_PUBLIC_BASE` | Browser-facing evidence base (via proxy) | `/frigate` |
| `VITE_API_BASE` | Frontend API base (build-time) | *empty* → same-origin |
No secrets are passed to the browser; Frigate/DB credentials stay server-side.

### 3 & 4. First startup / full-stack startup
```
docker compose up -d --build     # db + mosquitto + frigate + backend + frontend + proxy
docker compose ps                # wait until every service shows "healthy"
```
The stack is migration-driven on Postgres (Alembic `upgrade head` runs on boot;
the pgvector extension is created automatically).

### 5. Demo command (reproducible, one command)
```
./scripts/demo.sh                # macOS/Linux
.\scripts\demo.ps1               # Windows PowerShell
```
It builds + starts the stack, waits for all healthchecks, seeds the deterministic
demo pipeline **through the reverse proxy** (mock scenario → correlate → build
incident, persisted in PostgreSQL), and prints the browser URL.

### 6. Browser URL
Open **http://localhost:8080** — the single reverse-proxy origin:
- `/` → dashboard, `/api/...`, `/events`, `/tracks`, `/incidents`, … → backend,
  `/frigate/...` → Frigate media/API (browser-reachable evidence snapshots).

### 7. Backend tests
```
cd backend
python -m pip install -r requirements-dev.txt
python -m pytest -q              # 74 tests (SQLite; fast, deterministic)
python -m ruff check .
```

### 8. Frontend tests
```
cd frontend
npm install
npm test                         # 15 Vitest component + API-client tests
npm run build                    # type-check + production build
```

### 9. Playwright browser E2E (against the running stack)
```
# with the full stack up (docker compose up -d):
cd frontend
npm run e2e:install              # one-time: install the chromium browser
DARSON_ORIGIN=http://localhost:8080 npm run e2e
```
This is a true browser → proxy → frontend/backend → **PostgreSQL** flow (no
mocking): it opens the incident, verifies timeline/graph/correlation/evidence,
runs the lifecycle (start triage → confirm), reloads, and asserts the confirmed
state persisted; it also asserts an invalid transition is rejected (409).

### 10. Stop / reset
```
docker compose down              # stop + remove containers (keeps DB volume)
docker compose down -v           # also wipe the PostgreSQL + Frigate volumes
./scripts/demo.sh down | reset   # convenience wrappers
```

### 11. Current Frigate synthetic-source limitation
The bundled Frigate dev config (`deploy/frigate-config.yml`) uses a synthetic
`lavfi testsrc` pattern — it exercises the **infrastructure/MQTT path** (Frigate
publishes `frigate/*`, the adapter consumes them) but the test pattern contains
**no people, so it produces no person detections and no `frigate/events`**.
Repeatable **intelligence** behaviour is demonstrated with the deterministic mock
scenario (and captured Frigate payload fixtures in the tests). A real deployment
requires real camera/video feeding Frigate to generate detections and real
snapshot/clip media.

## Real-video validation (genuine person detection, no camera)

To validate the pipeline with **real detectable video** — actual people detected
by Frigate's model — without any camera or CCTV credentials, use the real-video
overlay. It runs Frigate against prerecorded pedestrian clips (looped in-process
by Frigate's own ffmpeg) and drains the **live** `frigate/events` MQTT stream
into DARSON via a background ingestor.

```
./scripts/fetch_test_videos.sh          # fetch CC-BY-4.0 sample clips (gitignored)
docker compose -f docker-compose.yml -f docker-compose.real-video.yml up -d --build
# or simply:  ./scripts/demo.sh real     (.\scripts\demo.ps1 real on Windows)
```
Then open **http://localhost:8080**.

- **Test videos**: `intel-iot-devkit/sample-videos` (license **CC-BY-4.0**,
  attribution: Intel IoT DevKit). Fetched on demand into `deploy/videos/` and
  **never committed** (gitignored). Three clips become three cameras
  (`cam_a → cam_b → cam_c`).
- **Frigate config**: `deploy/frigate-config.real.yml` — direct ffmpeg file input
  (`-re -stream_loop -1 -fflags +genpts`), CPU detector, `person` tracking,
  snapshots + recordings for real evidence.
- **Backend**: with `DARSON_EVENT_SOURCE=frigate`, a background ingestor
  subscribes to `frigate/events` and persists real detections; run
  `correlate` + `build_incidents` (the `demo.sh real` flow does this) to produce
  incidents from the real tracks.
- **Evidence**: real snapshots are served browser-reachably at
  `/frigate/api/events/<id>/snapshot.jpg` through the reverse proxy.

### GPU requirements
- The dev setup uses Frigate's **CPU detector** and DARSON's **deterministic mock
  Re-ID backend**, so **no GPU is required** (and none is used in the validated
  dev environment — there is no GPU memory figure to report here).
- Production throughput benefits from a hardware detector (Coral/GPU) for Frigate
  and, if enabled, an OSNet/TorchReID GPU backend for appearance embeddings
  (`backend/requirements-reid.txt`). Those are optional and out of scope for the
  dev validation.

### Tested development behaviour vs intended production vs limitations
- **Tested (dev, this repo)**: real person detection → `frigate/events` (MQTT) →
  FrigateAdapter → CanonicalEvent → PostgreSQL → behaviour → cross-camera
  **movement** correlation → incident graph → timeline → browser-reachable real
  snapshot evidence → lifecycle persistence. Verified on the Docker/PostgreSQL/
  pgvector stack.
- **Intended production**: real cameras/RTSP feeding Frigate, a hardware
  detector, an OSNet Re-ID backend over real snapshot crops, and hardened MQTT
  credentials — all behind the same source-agnostic adapter boundary.
- **Limitations / honest scope**:
  - Cross-camera correlation is **movement** correlation from topology + timing +
    appearance signals; it is **not** a claim of human identity.
  - The Re-ID path in dev is a deterministic mock; **no labeled Re-ID accuracy is
    claimed** — that requires a proper labeled evaluation dataset.
  - The sample clips contain independent pedestrians, so cross-camera "same
    movement" links are illustrative of the mechanism, not ground-truth identity.
  - This is a validated development demonstration; it is **not** presented as
    production-ready.

## Quick start (offline dev, no Docker)
```
cd backend
python -m pip install -r requirements-dev.txt
python -m pytest -q                     # run the test suite (SQLite)
uvicorn app.main:app --reload           # API at http://localhost:8000
```

## Frontend — operator investigation dashboard
A React + TypeScript dashboard that consumes the read-only **v1 incident API**
(`/api/v1/incidents/...`). It walks the operator through the investigation:
incident → why it was created → supporting tracks/events → timeline →
correlations → graph → evidence → lifecycle review.

```
cd frontend
npm install
npm run dev        # dashboard at http://localhost:5173 (expects backend at :8000)
npm test           # component + API-client tests (Vitest)
npm run build      # type-check + production build
```

Point the dashboard at a non-default backend with `VITE_API_BASE`, e.g.
`VITE_API_BASE=http://localhost:8077 npm run dev`. The frontend talks only to the
backend HTTP API — it never accesses PostgreSQL directly and holds no Frigate
credentials.

## Deterministic demo workflow (no CCTV hardware)
Full stack (recommended — verified against PostgreSQL):
```
./scripts/demo.sh            # or  .\scripts\demo.ps1  on Windows
# then open http://localhost:8080 and open the generated incident:
#   why -> timeline -> correlations -> graph -> evidence -> change state
```
Frontend-only against a local backend (SQLite is fine for this path):
```
cd backend && uvicorn app.main:app --port 8000     # terminal 1
cd frontend && npm run dev                          # terminal 2 (http://localhost:5173)
# click "Run demo pipeline" in the dashboard, then open the incident
```
The same path is exercised headlessly by the backend tests, by
`test_task12_e2e.py`, and by the Playwright browser E2E. It uses the built-in
mock event source and needs no cameras.

## Current limitations
- The synthetic Frigate stream (`deploy/frigate-config.yml`) is an
  infrastructure/MQTT source only — its test pattern contains no people, so it
  produces **no person detections** and therefore no `frigate/events`. Repeatable
  intelligence behaviour is demonstrated with the deterministic **mock scenario**
  and captured Frigate payload fixtures in the tests.
- In the full-stack deployment, evidence URLs are built as same-origin
  `/frigate/api/events/<id>/snapshot.jpg` and are **browser-reachable through the
  reverse proxy**. For mock-scenario incidents the evidence references are
  placeholders and the dashboard degrades gracefully (no fabricated media). Real
  snapshots/clips require a real Frigate deployment with detections + media.
- A real deployment requires real camera/video sources feeding Frigate (or another
  `EventSource`).

## Attribution
See `NOTICE`. Frigate (MIT) is consumed as an event source; the Detect→Connect→Report
and explainable-incident-card concepts were informed by the SENTINEL-X (MIT) project
and reimplemented here.
