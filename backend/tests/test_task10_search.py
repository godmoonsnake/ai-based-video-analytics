"""Task 10 verification: investigation search (structured + NL + semantic)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.adapters.ingestion import ingest_source, seed_embeddings
from app.adapters.mock_source import MockEventSource, load_topology
from app.db.session import SessionLocal
from app.main import app
from app.search.nl_query import parse_nl

client = TestClient(app)


def _yesterday_epoch() -> float:
    now = datetime.now(timezone.utc)
    start = (now - timedelta(days=1)).replace(hour=1, minute=0, second=0, microsecond=0)
    return start.timestamp()


def _seed(base_epoch: float):
    db = SessionLocal()
    try:
        load_topology(db)
        ingest_source(db, MockEventSource(base_epoch=base_epoch))
        seed_embeddings(db)
    finally:
        db.close()


def test_nl_parse_red_bag_gate3_yesterday():
    _seed(_yesterday_epoch())
    db = SessionLocal()
    try:
        f = parse_nl(db, "Show incidents involving a red bag near Gate 3 yesterday")
        assert f.camera_id == "gate_3"
        assert f.sub_label == "red_bag"
        assert f.time_start is not None and f.time_end is not None
        # window brackets "yesterday"
        assert f.time_start < _yesterday_epoch() < f.time_end
    finally:
        db.close()


def test_structured_search_endpoint():
    _seed(1_700_000_000.0)
    resp = client.post("/search", json={"event_type": "dwell"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["human_review_required"] is True
    assert len(body["events"]) == 1
    assert body["events"][0]["camera_id"] == "restricted_2"
    assert body["events"][0]["evidence"]["clip"]["content_url"] is None
    assert "/mock-evidence/" not in resp.text


def test_nl_search_endpoint_returns_matches():
    _seed(_yesterday_epoch())
    resp = client.post("/search", json={"q": "red bag near Gate 3 yesterday"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["parsed_filter"].get("camera_id") == "gate_3"
    assert body["parsed_filter"].get("sub_label") == "red_bag"
    # gate_3 has one red_bag event in the scenario
    assert any(e["camera_id"] == "gate_3" for e in body["events"])
    assert body["human_review_required"] is True


def test_semantic_similar_endpoint():
    _seed(1_700_000_000.0)
    resp = client.get("/search/similar", params={"camera_id": "gate_3", "track_local_id": "A1"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["human_review_required"] is True
    assert len(body["similar"]) >= 1
    # same red_bag identity -> high similarity
    assert body["similar"][0]["score"] > 0.5
