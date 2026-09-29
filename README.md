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

## Attribution
See `NOTICE`. Frigate (MIT) is consumed as an event source; the Detect→Connect→Report
and explainable-incident-card concepts were informed by the SENTINEL-X (MIT) project
and reimplemented here.
