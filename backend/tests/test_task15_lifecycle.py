"""Task 15: incident lifecycle, local->global boundary, idempotency & evidence.

Covers the cleanup-milestone behaviours:
  - LocalTrack -> GlobalTrack boundary (merge only when justified; separation)
  - lifecycle state transitions (open -> triage -> confirmed|dismissed)
  - invalid transitions rejected
  - transition history recorded
  - repeated incident rebuilds are idempotent (no node/edge duplication)
  - evidence preserved across rebuild AND across lifecycle transitions
All deterministic; no live CCTV.
"""
from __future__ import annotations

import json
import uuid

import pytest
from fastapi.testclient import TestClient

from app.db.session import SessionLocal
from app.main import app
from app.models.entities import (
    Camera,
    CameraEdge,
    Event,
    GlobalTrack,
    GlobalTrackMember,
    Incident,
    IncidentGraphEdge,
    IncidentNode,
    Zone,
)
from app.pipeline.correlator import correlate
from app.pipeline.incident_builder import build_incidents
from app.pipeline.incident_graph import build_graph, graph_as_dict
from app.pipeline.incident_lifecycle import (
    InvalidTransition,
    apply_transition,
    transition_history,
)
from app.pipeline.reid_service import add_embedding

client = TestClient(app)
BASE = 1_700_000_000.0


def _cam(db, cid):
    if db.get(Camera, cid) is None:
        db.add(Camera(id=cid, name=cid))


def _topology(db):
    _cam(db, "cam_a")
    _cam(db, "cam_b")
    _cam(db, "cam_c")
    _cam(db, "cam_iso")
    db.add(CameraEdge(from_camera_id="cam_a", to_camera_id="cam_b",
                      walk_seconds_min=2, walk_seconds_max=40, bidirectional=True))
    db.add(CameraEdge(from_camera_id="cam_b", to_camera_id="cam_c",
                      walk_seconds_min=2, walk_seconds_max=40, bidirectional=True))
    db.add(Zone(camera_id="cam_c", name="restricted", kind="restricted"))
    db.add(Zone(camera_id="cam_a", name="entry", kind="entry"))
    db.add(Zone(camera_id="cam_iso", name="lobby", kind="entry"))
    db.commit()


def _event(db, camera, track, etype, ts, *, start=None, end=None, zones=None,
           angle=90.0):
    eid = str(uuid.uuid4())
    db.add(Event(
        id=eid, source_event_id=eid, source_type="mock",
        camera_id=camera, track_local_id=track, event_type=etype,
        label="person", sub_label="red_bag", confidence=0.9,
        start_time=start if start is not None else ts,
        end_time=end if end is not None else ts, ts=ts,
        zones_json=json.dumps(zones or []), velocity_angle=angle, avg_speed=1.2,
        has_snapshot=True, has_clip=True,
        evidence_ref_json=json.dumps({
            "snapshot_url": f"http://frigate:5000/api/events/{eid}/snapshot.jpg",
            "clip_url": f"http://frigate:5000/api/events/{eid}/clip.mp4",
        }),
    ))
    db.commit()
    return eid


def _chain(db):
    """A correlated 3-camera movement ending in a restricted dwell."""
    _topology(db)
    _event(db, "cam_a", "a1", "detection", BASE + 1, start=BASE, end=BASE + 5,
           zones=["entry"])
    _event(db, "cam_b", "b1", "zone_enter", BASE + 12, start=BASE + 10,
           end=BASE + 15, zones=[])
    _event(db, "cam_c", "c1", "dwell", BASE + 25, start=BASE + 20, end=BASE + 110,
           zones=["restricted"], angle=0.0)
    for cam, trk in (("cam_a", "a1"), ("cam_b", "b1"), ("cam_c", "c1")):
        add_embedding(db, cam, trk, seed="red_bag")
    correlate(db)


# ---------------------------------------------------------------------------
# LocalTrack -> GlobalTrack boundary
# ---------------------------------------------------------------------------
def test_local_track_is_single_camera_observation():
    """A local track is exactly the events sharing (camera_id, track_local_id)."""
    db = SessionLocal()
    try:
        _topology(db)
        _event(db, "cam_a", "a1", "detection", BASE, zones=["entry"])
        _event(db, "cam_a", "a1", "detection", BASE + 2, zones=["entry"])
        add_embedding(db, "cam_a", "a1", seed="red_bag")
        correlate(db)
        # one local track (cam_a,a1) -> exactly one global track membership row
        members = db.query(GlobalTrackMember).filter(
            GlobalTrackMember.camera_id == "cam_a",
            GlobalTrackMember.track_local_id == "a1",
        ).all()
        assert len(members) == 1
    finally:
        db.close()


def test_correlated_local_tracks_merge_into_one_global_track():
    """Topology-adjacent, in-window, high-similarity local tracks merge."""
    db = SessionLocal()
    try:
        _chain(db)
        # all three local tracks should share ONE global track
        gts = db.query(GlobalTrack).all()
        big = max(gts, key=lambda g: len(
            db.query(GlobalTrackMember).filter(
                GlobalTrackMember.global_track_id == g.id).all()))
        member_cams = {m.camera_id for m in db.query(GlobalTrackMember).filter(
            GlobalTrackMember.global_track_id == big.id).all()}
        assert member_cams == {"cam_a", "cam_b", "cam_c"}
        # confidence is the mean of accepted pair scores (evidence-derived, not identity)
        assert big.confidence is not None and 0.0 < big.confidence <= 1.0
    finally:
        db.close()


def test_unrelated_local_tracks_stay_separate():
    """No topology edge / out-of-window => distinct global tracks, no merge."""
    db = SessionLocal()
    try:
        _topology(db)
        # cam_a and cam_iso have NO edge -> cannot merge
        _event(db, "cam_a", "a1", "detection", BASE, start=BASE, end=BASE + 5,
               zones=["entry"])
        _event(db, "cam_iso", "z9", "detection", BASE + 8, start=BASE + 7,
               end=BASE + 12, zones=["lobby"])
        add_embedding(db, "cam_a", "a1", seed="red_bag")
        add_embedding(db, "cam_iso", "z9", seed="red_bag")  # same look, but no path
        correlate(db)
        # two singletons -> two distinct global tracks
        gt_of = {}
        for m in db.query(GlobalTrackMember).all():
            gt_of[(m.camera_id, m.track_local_id)] = m.global_track_id
        assert gt_of[("cam_a", "a1")] != gt_of[("cam_iso", "z9")]
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Lifecycle transitions
# ---------------------------------------------------------------------------
def _one_incident(db) -> Incident:
    _chain(db)
    inc_id = build_incidents(db)[0]
    return db.get(Incident, inc_id)


def test_lifecycle_open_triage_confirmed():
    db = SessionLocal()
    try:
        inc = _one_incident(db)
        assert (inc.status or "open") == "open"
        apply_transition(db, inc, "start_triage", reviewer="operator")
        assert inc.status == "triage"
        apply_transition(db, inc, "confirm", reviewer="shift_lead", note="verified")
        assert inc.status == "confirmed"
    finally:
        db.close()


def test_lifecycle_dismiss_from_open():
    db = SessionLocal()
    try:
        inc = _one_incident(db)
        apply_transition(db, inc, "dismiss", reviewer="operator", note="false alarm")
        assert inc.status == "dismissed"
    finally:
        db.close()


def test_invalid_transition_rejected():
    db = SessionLocal()
    try:
        inc = _one_incident(db)
        # cannot confirm directly from open (must triage first)
        with pytest.raises(InvalidTransition):
            apply_transition(db, inc, "confirm")
        # state unchanged after rejected transition
        db.refresh(inc)
        assert inc.status == "open"
        # unknown action rejected too
        with pytest.raises(InvalidTransition):
            apply_transition(db, inc, "nonsense")
    finally:
        db.close()


def test_transition_history_recorded():
    db = SessionLocal()
    try:
        inc = _one_incident(db)
        apply_transition(db, inc, "start_triage", reviewer="op1")
        apply_transition(db, inc, "dismiss", reviewer="op2", note="cleared")
        hist = transition_history(db, inc.id)
        assert [h["action"] for h in hist] == ["start_triage", "dismiss"]
        assert [h["from_state"] for h in hist] == ["open", "triage"]
        assert [h["to_state"] for h in hist] == ["triage", "dismissed"]
        assert hist[0]["reviewer"] == "op1" and hist[1]["reviewer"] == "op2"
        assert all(h["created_at"] for h in hist)
    finally:
        db.close()


def test_lifecycle_is_non_destructive_to_graph_and_evidence():
    """A state transition must not mutate graph nodes/edges or evidence."""
    db = SessionLocal()
    try:
        inc = _one_incident(db)
        before = graph_as_dict(db, inc.id)
        n_before = len(before["nodes"])
        e_before = len(before["edges"])
        ev_before = {
            n["ref_id"]: n["attributes"].get("evidence_ref")
            for n in before["nodes"] if n["type"] == "event"
        }
        apply_transition(db, inc, "start_triage")
        apply_transition(db, inc, "confirm")
        after = graph_as_dict(db, inc.id)
        assert len(after["nodes"]) == n_before
        assert len(after["edges"]) == e_before
        ev_after = {
            n["ref_id"]: n["attributes"].get("evidence_ref")
            for n in after["nodes"] if n["type"] == "event"
        }
        assert ev_after == ev_before  # evidence untouched by lifecycle
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Rebuild idempotency + evidence preservation
# ---------------------------------------------------------------------------
def test_repeated_rebuild_is_idempotent():
    db = SessionLocal()
    try:
        inc = _one_incident(db)
        g1 = graph_as_dict(db, inc.id)
        evs = sorted(
            db.query(Event).all(), key=lambda e: e.ts
        )
        gt_ids = [inc.primary_global_track_id] if inc.primary_global_track_id else []
        # rebuild twice from identical inputs
        build_graph(db, inc.id, evs, gt_ids)
        db.commit()
        build_graph(db, inc.id, evs, gt_ids)
        db.commit()
        g2 = graph_as_dict(db, inc.id)
        assert len(g1["nodes"]) == len(g2["nodes"])
        assert len(g1["edges"]) == len(g2["edges"])
        # no orphan duplication in the tables
        assert db.query(IncidentNode).filter(
            IncidentNode.incident_id == inc.id).count() == len(g2["nodes"])
        assert db.query(IncidentGraphEdge).filter(
            IncidentGraphEdge.incident_id == inc.id).count() == len(g2["edges"])
    finally:
        db.close()


def test_evidence_preserved_across_rebuild():
    db = SessionLocal()
    try:
        inc = _one_incident(db)
        g1 = graph_as_dict(db, inc.id)
        corr1 = [e["evidence"] for e in g1["edges"] if e["type"] == "correlation"]
        evs = sorted(db.query(Event).all(), key=lambda e: e.ts)
        gt_ids = [inc.primary_global_track_id] if inc.primary_global_track_id else []
        build_graph(db, inc.id, evs, gt_ids)
        db.commit()
        g2 = graph_as_dict(db, inc.id)
        corr2 = [e["evidence"] for e in g2["edges"] if e["type"] == "correlation"]
        assert corr1 == corr2  # correlator sub-score evidence stable across rebuild
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Lifecycle API
# ---------------------------------------------------------------------------
def test_lifecycle_api_and_readonly_endpoints_coexist():
    db = SessionLocal()
    try:
        inc = _one_incident(db)
        inc_id = inc.id
    finally:
        db.close()

    # read state
    st = client.get(f"/api/v1/incidents/{inc_id}/state").json()
    assert st["state"] == "open"
    assert "start_triage" in st["allowed_actions"]

    # invalid transition -> 409
    bad = client.post(f"/api/v1/incidents/{inc_id}/state", json={"action": "confirm"})
    assert bad.status_code == 409

    # valid path
    r1 = client.post(f"/api/v1/incidents/{inc_id}/state",
                     json={"action": "start_triage", "reviewer": "operator"})
    assert r1.status_code == 200 and r1.json()["state"] == "triage"
    r2 = client.post(f"/api/v1/incidents/{inc_id}/state",
                     json={"action": "confirm", "reviewer": "shift_lead"})
    assert r2.json()["state"] == "confirmed"

    # history
    hist = client.get(f"/api/v1/incidents/{inc_id}/state/history").json()["history"]
    assert [h["action"] for h in hist] == ["start_triage", "confirm"]

    # read-only graph/timeline/explanation still work after transitions
    assert client.get(f"/api/v1/incidents/{inc_id}/graph").json()["nodes"]
    assert client.get(f"/api/v1/incidents/{inc_id}/timeline").json()["timeline"]
    assert client.get(f"/api/v1/incidents/{inc_id}/explanation").json()["why_created"]
