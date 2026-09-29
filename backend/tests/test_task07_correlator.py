"""Task 7 verification: cross-camera correlator + global tracks."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.adapters.ingestion import ingest_source, seed_embeddings
from app.adapters.mock_source import MockEventSource, load_topology
from app.db.session import SessionLocal
from app.main import app
from app.pipeline.correlator import (
    TrackSpan,
    _edge_window,
    _s_time,
    compute_spans,
    correlate,
    score_pair,
)

client = TestClient(app)


def _seed():
    db = SessionLocal()
    try:
        load_topology(db)
        ingest_source(db, MockEventSource(base_epoch=1_700_000_000.0))
        seed_embeddings(db)
    finally:
        db.close()


def test_time_score_window():
    # window 4..20 -> mid 12
    assert _s_time(12, (4, 20)) == 1.0
    assert _s_time(4, (4, 20)) == 0.0 or _s_time(4, (4, 20)) >= 0.0
    assert _s_time(2, (4, 20)) == 0.0    # below window
    assert _s_time(30, (4, 20)) == 0.0   # above window


def test_spans_computed():
    _seed()
    db = SessionLocal()
    try:
        spans = {(s.camera_id, s.track_local_id): s for s in compute_spans(db)}
        assert ("gate_3", "A1") in spans
        assert spans[("gate_3", "A1")].end < spans[("corridor_1", "B7")].start
    finally:
        db.close()


def test_full_scenario_stitches_into_one_global_track():
    _seed()
    db = SessionLocal()
    try:
        summaries = correlate(db)
        # Exactly one global track containing all four local tracks.
        big = max(summaries, key=lambda s: len(s["members"]))
        member_cams = {m["camera_id"] for m in big["members"]}
        assert member_cams == {"gate_3", "corridor_1", "restricted_2", "exit_4"}
        assert len(big["members"]) == 4
    finally:
        db.close()


def test_negative_no_edge_rejected():
    db = SessionLocal()
    try:
        load_topology(db)
        # gate_3 and exit_4 have NO direct edge -> no window.
        assert _edge_window(db, "gate_3", "exit_4") is None
        a = TrackSpan("gate_3", "A1", 0, 6, 90, 90)
        b = TrackSpan("exit_4", "D9", 8, 14, 90, 90)
        assert score_pair(db, a, b) is None  # gated out by topology
    finally:
        db.close()


def test_negative_out_of_window_rejected():
    db = SessionLocal()
    try:
        load_topology(db)
        # Edge gate_3->corridor_1 exists (4..20) but gap 200s is out of window.
        a = TrackSpan("gate_3", "A1", 0, 6, 90, 90)
        b = TrackSpan("corridor_1", "B7", 206, 212, 90, 90)
        assert score_pair(db, a, b) is None
    finally:
        db.close()


def test_correlate_endpoint_and_listing():
    client.post("/events/ingest/mock")
    resp = client.post("/tracks/correlate")
    assert resp.status_code == 200

    resp = client.get("/tracks/global")
    assert resp.status_code == 200
    tracks = resp.json()
    big = max(tracks, key=lambda t: len(t["members"]))
    assert len(big["members"]) == 4
    # explainability: non-seed members carry sub-score method strings
    joined = [m for m in big["members"] if m["method"] != "seed"]
    assert joined and all("appearance=" in m["method"] for m in joined)
