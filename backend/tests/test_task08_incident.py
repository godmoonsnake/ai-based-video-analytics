"""Task 8 verification: incident graph + timeline reconstruction."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.adapters.ingestion import ingest_source, seed_embeddings
from app.adapters.mock_source import MockEventSource, load_topology
from app.db.session import SessionLocal
from app.main import app
from app.pipeline.correlator import correlate
from app.pipeline.incident_builder import build_incidents, find_triggers

client = TestClient(app)


def _seed_and_correlate():
    db = SessionLocal()
    try:
        load_topology(db)
        ingest_source(db, MockEventSource(base_epoch=1_700_000_000.0))
        seed_embeddings(db)
        correlate(db)
    finally:
        db.close()


def test_trigger_is_restricted_dwell():
    _seed_and_correlate()
    db = SessionLocal()
    try:
        triggers = find_triggers(db)
        assert len(triggers) == 1
        assert triggers[0].camera_id == "restricted_2"
        assert triggers[0].event_type == "dwell"
    finally:
        db.close()


def test_incident_spans_all_cameras_ordered_with_evidence():
    _seed_and_correlate()
    db = SessionLocal()
    try:
        ids = build_incidents(db)
        assert len(ids) == 1
        inc_id = ids[0]
    finally:
        db.close()

    resp = client.get(f"/incidents/{inc_id}")
    assert resp.status_code == 200
    detail = resp.json()
    # priority high/critical because restricted zone touched
    assert detail["priority"] in ("high", "critical")
    # cameras correct
    assert set(detail["cameras"]) == {"gate_3", "corridor_1", "restricted_2", "exit_4"}
    # timeline ordered across cameras
    cam_order = [t["camera_id"] for t in detail["timeline"]]
    assert cam_order == ["gate_3", "corridor_1", "restricted_2", "exit_4"]
    # Raw source paths are withheld until media reaches the authorized vault.
    assert all(t["evidence"]["clip_url"] is None for t in detail["timeline"])
    assert all(t["evidence"]["clip_status"] == "requested" for t in detail["timeline"])
    # trigger role assigned to the restricted dwell
    trigger_nodes = [n for n in detail["graph"]["nodes"] if n["role"] == "trigger"]
    assert len(trigger_nodes) == 1
    # zone_transition edges exist (cross-camera)
    assert any(e["relation"] == "zone_transition" for e in detail["graph"]["edges"])


def test_incident_endpoints_and_feedback():
    client.post("/events/ingest/mock")
    client.post("/tracks/correlate")
    build = client.post("/incidents/build")
    inc_id = build.json()["incident_ids"][0]

    # list
    lst = client.get("/incidents").json()
    assert any(i["id"] == inc_id for i in lst)

    # feedback confirm -> status changes
    fb = client.post(f"/incidents/{inc_id}/feedback", json={"action": "confirm"})
    assert fb.status_code == 200
    assert fb.json()["status"] == "confirmed"

    # filter by status
    confirmed = client.get("/incidents", params={"status": "confirmed"}).json()
    assert any(i["id"] == inc_id for i in confirmed)

    assert client.get("/incidents/99999").status_code == 404
