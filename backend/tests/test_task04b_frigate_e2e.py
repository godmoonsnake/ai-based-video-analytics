"""Task 4b verification: Frigate END-TO-END integration through the real pipeline.

Proves the milestone data flow with a captured, docs-faithful Frigate 0.18
`frigate/events` payload — no live broker, no camera, no CCTV credentials:

    Frigate payload (frigate/events)
        -> FrigateAdapter (FrigateReplaySource + normalizer)
        -> CanonicalEvent (the source-agnostic "EventCreate")
        -> existing ingestion pipeline (single write path)
        -> cross-camera correlation (topology + time + motion + appearance)
        -> incident graph + chronological cross-camera timeline w/ evidence

The SAME downstream pipeline used by the mock source is exercised here with
ZERO Frigate-specific branching, demonstrating source-agnostic design.
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.adapters.frigate_source import FrigateReplaySource
from app.adapters.ingestion import ingest_source, seed_embeddings
from app.adapters.mock_source import load_topology
from app.db.session import SessionLocal
from app.main import app
from app.models.entities import Event
from app.pipeline.correlator import correlate
from app.pipeline.incident_builder import build_incidents, reconstruct_timeline
from app.schemas.event import SourceType

E2E_STREAM = Path(__file__).parent / "fixtures" / "frigate_e2e_stream.json"
client = TestClient(app)


def _messages() -> list[dict]:
    return json.loads(E2E_STREAM.read_text())


def test_frigate_payload_maps_to_canonical_eventcreate():
    """Step 1-2: raw Frigate payloads -> FrigateAdapter -> CanonicalEvents.

    Only the four legitimate terminal objects survive; the false_positive ghost
    is dropped by the adapter (source-specific filtering, not pipeline logic)."""
    src = FrigateReplaySource(_messages(), api_base="http://frigate:5000")
    events = list(src.stream())

    assert len(events) == 4  # ghost false-positive filtered out
    assert all(e.source.type == SourceType.frigate for e in events)
    assert {e.camera_id for e in events} == {
        "gate_3", "corridor_1", "restricted_2", "exit_4"
    }
    # Evidence URLs resolve to Frigate's documented HTTP API media endpoints.
    rest = next(e for e in events if e.camera_id == "restricted_2")
    assert rest.sub_label == "red_bag"
    assert rest.evidence.clip_url == (
        "http://frigate:5000/api/events/1700000026.30-rest/clip.mp4"
    )


def test_frigate_events_ingest_through_pipeline_direct():
    """Step 3-5 (direct): ingest Frigate CanonicalEvents, then run the SAME
    correlation + incident builder the mock path uses."""
    db = SessionLocal()
    try:
        load_topology(db)
        ingested = ingest_source(db, FrigateReplaySource(_messages()))
        assert ingested == 4

        rows = db.execute(select(Event)).scalars().all()
        assert len(rows) == 4
        assert all(r.source_type == "frigate" for r in rows)

        seed_embeddings(db)

        # CORRELATION: the four same-identity Frigate objects stitch into one
        # cross-camera global track spanning the full topology.
        summaries = correlate(db)
        big = max(summaries, key=lambda s: len(s["members"]))
        assert {m["camera_id"] for m in big["members"]} == {
            "gate_3", "corridor_1", "restricted_2", "exit_4"
        }

        # INCIDENT: a chronological cross-camera timeline is reconstructed with
        # Frigate evidence URLs attached (traceability Incident->Event->Evidence).
        ids = build_incidents(db)
        assert len(ids) == 1
        timeline = reconstruct_timeline(db, ids[0])
        assert [t["camera_id"] for t in timeline] == [
            "gate_3", "corridor_1", "restricted_2", "exit_4"
        ]
        assert any(
            t["evidence"].get("clip_url", "").startswith("http")
            and "/api/events/" in t["evidence"]["clip_url"]
            for t in timeline
        )
    finally:
        db.close()


def test_frigate_events_ingest_through_pipeline_via_api():
    """Step 3-5 (API): the /events/ingest/frigate/replay endpoint with
    prepare_pipeline drives the identical source-agnostic pipeline over HTTP."""
    resp = client.post(
        "/events/ingest/frigate/replay?prepare_pipeline=true", json=_messages()
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ingested"] == 4
    assert body["source"] == "frigate"
    assert body["embeddings"] == 4

    # Correlate + build incident via the same endpoints the mock demo uses.
    assert client.post("/tracks/correlate").status_code == 200
    gts = client.get("/tracks/global").json()
    big = max(gts, key=lambda g: len(g["members"]))
    assert {m["camera_id"] for m in big["members"]} == {
        "gate_3", "corridor_1", "restricted_2", "exit_4"
    }

    build = client.post("/incidents/build").json()
    assert build["built"] == 1
    detail = client.get(f"/incidents/{build['incident_ids'][0]}").json()
    assert [t["camera_id"] for t in detail["timeline"]] == [
        "gate_3", "corridor_1", "restricted_2", "exit_4"
    ]
    # Behavioural analysis flags the restricted-zone dwell (source-agnostic).
    assert detail["priority"] in ("high", "critical")
