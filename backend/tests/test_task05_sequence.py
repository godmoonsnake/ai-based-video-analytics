"""Task 5 verification: behavioural sequence analyzer."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.adapters.ingestion import ingest_source
from app.adapters.mock_source import MockEventSource, load_topology
from app.db.session import SessionLocal
from app.main import app
from app.models.entities import Event
from app.pipeline.sequence_analyzer import analyze_events

client = TestClient(app)


def _seed():
    db = SessionLocal()
    try:
        load_topology(db)
        ingest_source(db, MockEventSource(base_epoch=1_700_000_000.0))
    finally:
        db.close()


def test_restricted_dwell_flagged():
    _seed()
    db = SessionLocal()
    try:
        # C3 is the restricted_2 dwell track in the scenario.
        events = db.query(Event).filter(Event.track_local_id == "C3").all()
        from app.pipeline.sequence_analyzer import _zone_kind_map

        result = analyze_events(events, "C3", _zone_kind_map(db))
        assert result.anomaly_score >= 0.6
        assert any("restricted" in r for r in result.reasons)
        assert "restricted" in result.signature
    finally:
        db.close()


def test_full_sequence_signature_ordered():
    _seed()
    db = SessionLocal()
    try:
        # Build a synthetic global sequence by relabelling all scenario events
        # to one track key, ordered by ts, to prove Entry->Transit->Restricted->Exit.
        from app.pipeline.sequence_analyzer import _zone_kind_map

        events = db.query(Event).order_by(Event.ts).all()
        result = analyze_events(events, "global-1", _zone_kind_map(db))
        assert result.signature == "entry -> transit -> restricted -> exit"
        assert result.anomaly_score >= 0.6
        assert [s.camera_id for s in result.steps] == [
            "gate_3", "corridor_1", "restricted_2", "exit_4",
        ]
    finally:
        db.close()


def test_sequence_endpoint():
    resp = client.post("/events/ingest/mock")
    assert resp.status_code == 200

    resp = client.get("/tracks/C3/sequence", params={"persist": True})
    assert resp.status_code == 200
    body = resp.json()
    assert body["anomaly_score"] >= 0.6
    assert body["steps"][0]["camera_id"] == "restricted_2"

    # unknown track -> 404
    assert client.get("/tracks/NOPE/sequence").status_code == 404
