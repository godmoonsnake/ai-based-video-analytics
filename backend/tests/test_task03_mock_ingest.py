"""Task 3 verification: mock event source + ingestion + /events."""
from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.adapters.ingestion import ingest_source
from app.adapters.mock_source import MockEventSource, load_topology
from app.db.session import SessionLocal
from app.main import app
from app.models.entities import Camera, CameraEdge, Event

client = TestClient(app)


def test_mock_source_streams_scenario():
    src = MockEventSource(base_epoch=1_700_000_000.0)
    events = list(src.stream())
    assert len(events) == 4
    cams = [e.camera_id for e in events]
    assert cams == ["gate_3", "corridor_1", "restricted_2", "exit_4"]
    # dwell in restricted zone present
    dwell = [e for e in events if e.event_type.value == "dwell"]
    assert dwell and "restricted" in dwell[0].spatial.zones
    # times were shifted by base epoch
    assert all(e.time.observed >= 1_700_000_000.0 for e in events)


def test_ingestion_persists_rows():
    db = SessionLocal()
    try:
        load_topology(db)
        count = ingest_source(db, MockEventSource(base_epoch=1_700_000_000.0))
        assert count == 4
        rows = db.execute(select(Event).order_by(Event.ts)).scalars().all()
        assert len(rows) == 4
        assert rows[0].camera_id == "gate_3"
        assert db.execute(select(Camera)).scalars().all()  # topology seeded
        assert db.execute(select(CameraEdge)).scalars().all()
    finally:
        db.close()


def test_events_endpoint_lists_scenario():
    resp = client.post("/events/ingest/mock")
    assert resp.status_code == 200
    assert resp.json()["ingested"] == 4

    resp = client.get("/events")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 4
    assert body[0]["camera_id"] == "gate_3"

    # structured filter works
    resp = client.get("/events", params={"event_type": "dwell"})
    assert len(resp.json()) == 1
    assert resp.json()[0]["camera_id"] == "restricted_2"
