# DARSON Intelligence Layer — Architecture

An intelligence layer **above** an existing VMS. It does not ingest raw video or
replace a VMS; it consumes *events* and turns them into contextual intelligence.

```
Event sources (pluggable: EventSource interface)
  ├─ Mock Event Source        (scripted offline scenarios)
  └─ Frigate Adapter (read-only: MQTT frigate/events + HTTP evidence)
        │
        ▼
  Event Normalizer  ──►  CanonicalEvent (source-agnostic)
        │
        ▼  persist
  PostgreSQL (+ pgvector)         SQLite fallback for offline dev/tests
        │
        ├─► Behavioural Sequence Analyzer  (per-track state machine, anomaly score)
        ├─► Re-ID Embedding Service        (OSNet/TorchReID 512-d, pgvector)
        ├─► Cross-Camera Correlator        (topology + time + motion + appearance → global tracks)
        ├─► Incident Graph Builder         (trigger → expand → graph + roles + evidence)
        ├─► Timeline Reconstructor         (chronological cross-camera timeline)
        ├─► Historical Pattern Miner       (paths / locations / time-windows / hotspots)
        └─► Investigation Search           (structured + semantic + NL, optional local LLM)
        │
        ▼
  Operator Dashboard (React) — incident feed, explainable card, timeline,
  topology map, investigation, patterns, confirm/dismiss feedback.
```

## Pipeline stages
EVENT → CONTEXT → CORRELATION → INCIDENT → HISTORY → INVESTIGATION.

## Components
- `app/adapters/` — EventSource interface, mock source, Frigate adapter (read-only), ingestion, factory.
- `app/normalize/` — raw → CanonicalEvent.
- `app/pipeline/` — sequence_analyzer, reid_service, correlator, incident_builder.
- `app/analytics/` — pattern_miner.
- `app/search/` — filters, semantic, nl_query; `app/llm/` optional provider.
- `app/api/routes/` — health, events, cameras, tracks, incidents, patterns, search.

## Guardrails (enforced)
No facial recognition, no gait recognition, no PII database, no autonomous
verdict, no automated physical response. Every search/incident response carries
`human_review_required = true`. A test (`test_task12_e2e.py`) scans the source
to prove none of the forbidden capabilities are present.

## Deployment vs offline dev
- Deployment: `docker compose up` (Postgres+pgvector, Mosquitto, backend, frontend;
  optional `--profile frigate`).
- Offline dev/tests: SQLite + deterministic mock Re-ID backend; `pytest` runs the
  entire pipeline with no external services.
