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

## Observation → Correlation → Inference → Incident

The system distinguishes four conceptual layers so that what is *observed* is
never confused with what is *inferred*:

```
OBSERVATION            Camera-local Track
  (single camera)        = all Events sharing (camera_id, track_local_id) on ONE
                           camera. A raw, per-camera observation. NOT an identity.
        │
        ▼
CORRELATION            Cross-Camera Correlator
  (evidence match)       scores directed local-track pairs a→b and MERGES them
                           only when ALL gates pass:
                             1. a topology edge camA→camB exists,
                             2. the transit gap is within [walk_min, walk_max],
                             3. combined score ≥ τ (0.62).
                           score = 0.34·s_time + 0.16·s_motion + 0.50·s_appearance
        │
        ▼
INFERENCE              GlobalTrack  (movement identity, NOT personal identity)
  (movement identity)    a connected set of local tracks the correlator stitched
                           into one movement. confidence = mean of accepted pair
                           scores. Appearance is a *similarity signal only* — no
                           facial/biometric identity is asserted. Unrelated local
                           tracks (no path / out of window / score < τ) stay as
                           separate GlobalTracks.
        │
        ▼
INCIDENT               Incident Graph
  (contextual meaning)   a behavioural trigger (e.g. restricted-zone dwell) seeds
                           an incident; it expands along its GlobalTrack(s) into a
                           normalized graph of typed, explainable nodes/edges with
                           correlation sub-scores and behaviour risk as evidence.
```

### Local Track → GlobalTrack → Incident Graph (data)
- **Local track**: `Event` rows keyed by `(camera_id, track_local_id)`.
- **GlobalTrack / GlobalTrackMember**: the merged movement + its member local
  tracks; each member records `join_score` and a `method` string of the
  correlator sub-scores (`time=… motion=… appearance=… gap=…`) for explainability.
- **Incident graph** (`incident_node` / `incident_graph_edge`): heterogeneous
  nodes (incident/track/camera/zone/event) and typed edges
  (`incident_membership`, `event_to_track`, `track_to_camera`, `event_to_zone`,
  `temporal`, `sequence`, `correlation`, `movement`). Inferred edges carry a
  `confidence` and a JSONB `evidence` object. Incident confidence propagates as
  `min(correlation_confidence, behaviour_confidence)` (weakest required pillar).

## Incident lifecycle (human-in-the-loop)

Incident **status** follows an explicit, persisted state machine. Transitions
are validated (invalid ones rejected), timestamped, and appended to
`incident_state_transition` with an optional reviewer handle/role (no PII). A
transition changes only `Incident.status` — it never mutates the incident graph,
nodes, edges, or evidence.

```
open ──start_triage──▶ triage ──confirm──▶ confirmed
  │                       │
  │                       └──dismiss──▶ dismissed
  └──dismiss──▶ dismissed
confirmed/dismissed ──reopen──▶ open
```

## Database lifecycle (single source of truth)

The schema is defined by the Alembic migration chain
(`0001_baseline` → `a7f0455fcb94` → `b2c1a9d4e7f2`). A consistency test asserts
`alembic upgrade head` produces exactly the same tables as the ORM metadata, so
the bootstrap paths cannot silently diverge.

- **PostgreSQL (deployment)**: schema is migration-driven — `init_db` runs
  `alembic upgrade head` (and ensures the pgvector extension).
- **SQLite (offline dev/tests)**: schema is created via `create_all`, which is
  provably equivalent to the migrations (verified by the consistency test).
- Override with `DARSON_DB_BOOTSTRAP=auto|migrations|create_all`.


## Components
- `app/adapters/` — EventSource interface, mock source, Frigate adapter (read-only), ingestion, factory.
- `app/normalize/` — raw → CanonicalEvent.
- `app/pipeline/` — sequence_analyzer, reid_service, correlator, incident_builder,
  incident_graph (normalized graph + confidence propagation + timeline + explanation),
  incident_lifecycle (state machine).
- `app/analytics/` — pattern_miner.
- `app/search/` — filters, semantic, nl_query; `app/llm/` optional provider.
- `app/api/routes/` — health, events, cameras, tracks, incidents, patterns, search,
  v1_incidents (read-only graph/timeline/explanation + lifecycle state endpoints).
- `app/db/migrations/` — Alembic chain; `init_db` applies migrations (PG) or the
  equivalent create_all (SQLite).

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
