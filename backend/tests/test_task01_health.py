"""Task 1 verification: health endpoint + schema creation."""
from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import inspect

from app.db.session import engine
from app.main import app

client = TestClient(app)

EXPECTED_TABLES = {
    "camera",
    "camera_edge",
    "zone",
    "event",
    "track_embedding",
    "global_track",
    "global_track_member",
    "incident",
    "incident_camera",
    "incident_event",
    "incident_edge",
    "behavioural_sequence",
    "historical_pattern",
    "operator_feedback",
    "audit_log",
}


def test_health_ok():
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["database"] is True


def test_root_metadata():
    resp = client.get("/")
    assert resp.status_code == 200
    assert resp.json()["human_in_the_loop"] is True


def test_all_tables_created():
    tables = set(inspect(engine).get_table_names())
    missing = EXPECTED_TABLES - tables
    assert not missing, f"missing tables: {missing}"
