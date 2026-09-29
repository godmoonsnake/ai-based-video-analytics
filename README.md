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

## Quick start (deployment)
```
docker compose up            # db + mosquitto + backend + frontend (mock source)
docker compose --profile frigate up   # additionally run Frigate as a real source
```

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
```
# 1. start the backend (SQLite is fine)
cd backend && uvicorn app.main:app --port 8000
# 2. start the dashboard
cd frontend && npm run dev
# 3. in the dashboard, click "Run demo pipeline"
#    (ingest mock scenario -> correlate -> build incident)
# 4. open the generated incident and review:
#    why -> timeline -> correlations -> graph -> evidence -> change state
```
The same path is exercised headlessly by the backend tests and by
`test_task12_e2e.py`. The demo uses the built-in mock event source and needs no
cameras.

## Current limitations
- The synthetic Frigate development stream (`docker compose --profile frigate up`)
  is an infrastructure/MQTT source only — its test pattern contains no people, so
  it produces **no person detections** and therefore no `frigate/events`. Repeatable
  intelligence behaviour is demonstrated with the deterministic **mock scenario**.
- Evidence snapshot/clip URLs in the mock/dev path point at a Frigate host that is
  not reachable from the browser; the dashboard shows them as labelled references
  and degrades gracefully (no fabricated media). Real snapshots/clips require a
  real Frigate deployment with reachable media endpoints.
- A real deployment requires real camera/video sources feeding Frigate (or another
  `EventSource`).

## Attribution
See `NOTICE`. Frigate (MIT) is consumed as an event source; the Detect→Connect→Report
and explainable-incident-card concepts were informed by the SENTINEL-X (MIT) project
and reimplemented here.
