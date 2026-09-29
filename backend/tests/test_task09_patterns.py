"""Task 9 verification: historical pattern miner."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.adapters.ingestion import ingest_source, seed_embeddings
from app.adapters.mock_source import MockEventSource, load_topology
from app.analytics.pattern_miner import mine_patterns
from app.db.session import SessionLocal
from app.main import app
from app.pipeline.correlator import correlate

client = TestClient(app)

CAM_PATH = ["gate_3", "corridor_1", "restricted_2", "exit_4"]


def _seed_n_runs(n: int):
    """Ingest the scenario n times with unique track suffixes + time offsets,
    correlating after each run so distinct global tracks form."""
    db = SessionLocal()
    try:
        load_topology(db)
        for i in range(n):
            ingest_source(
                db,
                MockEventSource(base_epoch=1_700_000_000.0 + i * 10_000, track_suffix=f"_r{i}"),
            )
            seed_embeddings(db)
        correlate(db)
    finally:
        db.close()


def test_recurring_path_mined():
    _seed_n_runs(3)
    db = SessionLocal()
    try:
        rows = mine_patterns(db)
        paths = [r for r in rows if r.pattern_type == "recurring_path"]
        assert paths, "expected at least one recurring path"
        top = max(paths, key=lambda r: r.count)
        import json

        assert json.loads(top.key_json)["path"] == CAM_PATH
        assert top.count >= 2
    finally:
        db.close()


def test_hotspot_and_location():
    _seed_n_runs(2)
    db = SessionLocal()
    try:
        rows = mine_patterns(db)
        hotspots = [r for r in rows if r.pattern_type == "hotspot"]
        assert hotspots
        locations = [r for r in rows if r.pattern_type == "recurring_location"]
        # restricted zone must appear as a mined location
        import json

        kinds = [json.loads(r.key_json).get("kind") for r in locations]
        assert "restricted" in kinds
    finally:
        db.close()


def test_patterns_endpoint():
    _seed_n_runs(3)
    resp = client.post("/patterns/mine")
    assert resp.status_code == 200
    assert resp.json()["mined"] > 0

    resp = client.get("/patterns", params={"pattern_type": "recurring_path"})
    assert resp.status_code == 200
    paths = resp.json()
    assert any(p["key"]["path"] == CAM_PATH and p["count"] >= 2 for p in paths)

    hot = client.get("/patterns", params={"pattern_type": "hotspot"}).json()
    assert any(h["key"]["camera_id"] == "restricted_2" for h in hot)
