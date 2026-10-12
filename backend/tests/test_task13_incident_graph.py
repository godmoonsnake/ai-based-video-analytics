"""Task 13 verification: source-agnostic Incident Graph.

Ten deterministic scenarios, no live CCTV. Events are inserted programmatically
(source-agnostic canonical rows) so each scenario's graph outcome is exact:

  1. isolated event                -> no incident
  2. behaviour signal              -> candidate incident (restricted dwell)
  3. correlated tracks             -> same incident
  4. unrelated tracks              -> separate incidents
  5. multi-camera chain            -> one connected incident
  6. incident merge                -> triggers on one movement => one incident
  7. timeline reconstruction       -> graph-membership derived, ordered
  8. evidence propagation          -> correlation sub-scores stored on edges
  9. confidence propagation        -> min(correlation, behaviour) + bands
 10. idempotent incident rebuild   -> rebuild replaces, no duplicate graph
"""
from __future__ import annotations

import json
import uuid

from fastapi.testclient import TestClient

from app.db.session import SessionLocal
from app.main import app
from app.models.entities import (
    Camera,
    CameraEdge,
    Event,
    IncidentGraphEdge,
    IncidentNode,
    Zone,
)
from app.pipeline.correlator import correlate
from app.pipeline.incident_builder import build_incidents
from app.pipeline.incident_graph import (
    build_explanation,
    confidence_band,
    graph_as_dict,
    graph_timeline,
)
from app.pipeline.reid_service import add_embedding

client = TestClient(app)

BASE = 1_700_000_000.0


def _cam(db, cid):
    if db.get(Camera, cid) is None:
        db.add(Camera(id=cid, name=cid))


def _topology(db):
    """Linear topology cam_a -> cam_b -> cam_c with generous walk windows."""
    _cam(db, "cam_a")
    _cam(db, "cam_b")
    _cam(db, "cam_c")
    _cam(db, "cam_x")  # isolated camera, no edges
    db.add(CameraEdge(from_camera_id="cam_a", to_camera_id="cam_b",
                      walk_seconds_min=2, walk_seconds_max=40, bidirectional=True))
    db.add(CameraEdge(from_camera_id="cam_b", to_camera_id="cam_c",
                      walk_seconds_min=2, walk_seconds_max=40, bidirectional=True))
    # restricted zone lives on cam_c
    db.add(Zone(camera_id="cam_c", name="restricted", kind="restricted"))
    db.add(Zone(camera_id="cam_a", name="entry", kind="entry"))
    db.add(Zone(camera_id="cam_b", name="transit", kind="transit"))
    db.add(Zone(camera_id="cam_x", name="lobby", kind="entry"))
    db.commit()


def _event(db, camera, track, etype, ts, *, start=None, end=None, zones=None,
           angle=90.0, has_clip=True):
    eid = str(uuid.uuid4())
    db.add(Event(
        id=eid, source_event_id=eid, source_type="mock",
        camera_id=camera, track_local_id=track, event_type=etype,
        label="person", sub_label="red_bag", confidence=0.9,
        start_time=start if start is not None else ts,
        end_time=end if end is not None else ts,
        ts=ts,
        zones_json=json.dumps(zones or []),
        velocity_angle=angle, avg_speed=1.2,
        has_snapshot=True, has_clip=has_clip,
        evidence_ref_json=json.dumps({
            "snapshot_url": f"http://frigate:5000/api/events/{eid}/snapshot.jpg",
            "clip_url": f"http://frigate:5000/api/events/{eid}/clip.mp4" if has_clip else None,
        }),
    ))
    db.commit()
    return eid


def _seed_identity(db, camera, track, seed="red_bag"):
    add_embedding(db, camera, track, seed=seed)


# ---------------------------------------------------------------------------
# 1. isolated event -> no incident
# ---------------------------------------------------------------------------
def test_isolated_event_creates_no_incident():
    db = SessionLocal()
    try:
        _topology(db)
        # A lone detection in a non-restricted lobby: no dwell/loiter trigger.
        _event(db, "cam_x", "loner", "detection", BASE, zones=["lobby"])
        _seed_identity(db, "cam_x", "loner")
        correlate(db)
        ids = build_incidents(db)
        assert ids == []
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 2. behaviour signal -> candidate incident
# ---------------------------------------------------------------------------
def test_behaviour_signal_creates_candidate_incident():
    db = SessionLocal()
    try:
        _topology(db)
        # Single-camera restricted dwell = behavioural trigger, no correlation.
        _event(db, "cam_c", "t1", "dwell", BASE + 5,
               start=BASE, end=BASE + 90, zones=["restricted"], angle=0.0)
        _seed_identity(db, "cam_c", "t1")
        correlate(db)
        ids = build_incidents(db)
        assert len(ids) == 1
        # graph has the incident + track + event + camera + zone nodes
        g = graph_as_dict(db, ids[0])
        types = {n["type"] for n in g["nodes"]}
        assert {"incident", "track", "event", "camera", "zone"} <= types
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 3. correlated tracks -> same incident (one connected movement)
# ---------------------------------------------------------------------------
def test_correlated_tracks_same_incident():
    db = SessionLocal()
    try:
        _topology(db)
        _event(db, "cam_a", "a1", "detection", BASE + 1, start=BASE, end=BASE + 5,
               zones=["entry"])
        _event(db, "cam_b", "b1", "detection", BASE + 12, start=BASE + 10,
               end=BASE + 15, zones=["transit"])
        _event(db, "cam_c", "c1", "dwell", BASE + 25, start=BASE + 20, end=BASE + 110,
               zones=["restricted"], angle=0.0)
        for cam, trk in (("cam_a", "a1"), ("cam_b", "b1"), ("cam_c", "c1")):
            _seed_identity(db, cam, trk)
        correlate(db)
        ids = build_incidents(db)
        assert len(ids) == 1
        # one track node (single stitched global track) spanning 3 cameras
        g = graph_as_dict(db, ids[0])
        cameras = {n["ref_id"] for n in g["nodes"] if n["type"] == "camera"}
        assert cameras == {"cam_a", "cam_b", "cam_c"}
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 4. unrelated tracks -> separate incidents
# ---------------------------------------------------------------------------
def test_unrelated_tracks_separate_incidents():
    db = SessionLocal()
    try:
        _topology(db)
        # Two independent restricted dwells with DIFFERENT identities, far apart
        # in time and not connected by any correlated movement.
        _event(db, "cam_c", "dweller1", "dwell", BASE + 5, start=BASE, end=BASE + 90,
               zones=["restricted"], angle=0.0)
        _seed_identity(db, "cam_c", "dweller1", seed="red_bag")
        _event(db, "cam_c", "dweller2", "dwell", BASE + 5000,
               start=BASE + 4990, end=BASE + 5090, zones=["restricted"], angle=0.0)
        _seed_identity(db, "cam_c", "dweller2", seed="blue_coat")
        correlate(db)
        ids = build_incidents(db)
        assert len(ids) == 2  # two distinct movements -> two incidents
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 5. multi-camera chain -> one connected incident
# ---------------------------------------------------------------------------
def test_multi_camera_chain_one_incident():
    db = SessionLocal()
    try:
        _topology(db)
        _event(db, "cam_a", "a1", "detection", BASE + 1, start=BASE, end=BASE + 5,
               zones=["entry"])
        _event(db, "cam_b", "b1", "zone_enter", BASE + 12, start=BASE + 10,
               end=BASE + 15, zones=["transit"])
        _event(db, "cam_c", "c1", "dwell", BASE + 25, start=BASE + 20, end=BASE + 110,
               zones=["restricted"], angle=0.0)
        for cam, trk in (("cam_a", "a1"), ("cam_b", "b1"), ("cam_c", "c1")):
            _seed_identity(db, cam, trk)
        correlate(db)
        ids = build_incidents(db)
        assert len(ids) == 1
        # movement edges chain the cameras a->b->c
        g = graph_as_dict(db, ids[0])
        moves = [e for e in g["edges"] if e["type"] == "movement"]
        transitions = {e["evidence"]["topology_transition"] for e in moves}
        assert "cam_a -> cam_b" in transitions
        assert "cam_b -> cam_c" in transitions
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 6. incident merge -> two triggers on one movement => one incident
# ---------------------------------------------------------------------------
def test_incident_merge_two_triggers_one_movement():
    db = SessionLocal()
    try:
        _topology(db)
        # Same identity, TWO restricted dwells on the same stitched movement
        # (cam_b then cam_c). Both are triggers, but they belong to one global
        # track -> justified merge into ONE incident.
        db.add(Zone(camera_id="cam_b", name="restricted_b", kind="restricted"))
        db.commit()
        _event(db, "cam_a", "a1", "detection", BASE + 1, start=BASE, end=BASE + 5,
               zones=["entry"])
        _event(db, "cam_b", "b1", "dwell", BASE + 15, start=BASE + 10, end=BASE + 40,
               zones=["restricted_b"], angle=0.0)
        _event(db, "cam_c", "c1", "dwell", BASE + 55, start=BASE + 50, end=BASE + 140,
               zones=["restricted"], angle=0.0)
        for cam, trk in (("cam_a", "a1"), ("cam_b", "b1"), ("cam_c", "c1")):
            _seed_identity(db, cam, trk)
        correlate(db)
        ids = build_incidents(db)
        assert len(ids) == 1  # merged, not two
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 7. timeline reconstruction (graph-membership derived, ordered, with evidence)
# ---------------------------------------------------------------------------
def test_timeline_reconstruction_from_graph():
    db = SessionLocal()
    try:
        _topology(db)
        _event(db, "cam_a", "a1", "detection", BASE + 1, start=BASE, end=BASE + 5,
               zones=["entry"])
        _event(db, "cam_b", "b1", "zone_enter", BASE + 12, start=BASE + 10,
               end=BASE + 15, zones=["transit"])
        _event(db, "cam_c", "c1", "dwell", BASE + 25, start=BASE + 20, end=BASE + 110,
               zones=["restricted"], angle=0.0)
        for cam, trk in (("cam_a", "a1"), ("cam_b", "b1"), ("cam_c", "c1")):
            _seed_identity(db, cam, trk)
        correlate(db)
        inc_id = build_incidents(db)[0]
        tl = graph_timeline(db, inc_id)
        assert [t["camera_id"] for t in tl] == ["cam_a", "cam_b", "cam_c"]
        # every item retains event id, camera, ts, zones, evidence ref
        for item in tl:
            assert item["event_id"] and item["camera_id"] and item["ts"] is not None
        assert all(t["evidence"]["clip_url"] is None for t in tl)
        assert all(t["evidence"]["clip_status"] == "not-requested" for t in tl)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 8. evidence propagation -> correlation sub-scores stored on graph edges
# ---------------------------------------------------------------------------
def test_evidence_propagation_on_correlation_edges():
    db = SessionLocal()
    try:
        _topology(db)
        _event(db, "cam_a", "a1", "detection", BASE + 1, start=BASE, end=BASE + 5,
               zones=["entry"])
        _event(db, "cam_c", "c1", "dwell", BASE + 25, start=BASE + 20, end=BASE + 110,
               zones=["restricted"], angle=0.0)
        _event(db, "cam_b", "b1", "detection", BASE + 12, start=BASE + 10,
               end=BASE + 15, zones=["transit"])
        for cam, trk in (("cam_a", "a1"), ("cam_b", "b1"), ("cam_c", "c1")):
            _seed_identity(db, cam, trk)
        correlate(db)
        inc_id = build_incidents(db)[0]
        edges = db.execute(
            IncidentGraphEdge.__table__.select().where(
                IncidentGraphEdge.incident_id == inc_id
            )
        ).mappings().all()
        corr = [e for e in edges if e["edge_type"] == "correlation"]
        assert corr, "expected correlation edges"
        ev = corr[0]["evidence"]
        for key in ("s_time", "s_motion", "s_appearance", "combined_score",
                    "temporal_gap_seconds", "topology_transition"):
            assert key in ev
        # edge confidence equals the combined correlation score
        assert corr[0]["confidence"] == ev["combined_score"]
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 9. confidence propagation -> min(correlation, behaviour) + bands
# ---------------------------------------------------------------------------
def test_confidence_propagation_min_rule_and_bands():
    db = SessionLocal()
    try:
        _topology(db)
        _event(db, "cam_a", "a1", "detection", BASE + 1, start=BASE, end=BASE + 5,
               zones=["entry"])
        _event(db, "cam_b", "b1", "detection", BASE + 12, start=BASE + 10,
               end=BASE + 15, zones=["transit"])
        _event(db, "cam_c", "c1", "dwell", BASE + 25, start=BASE + 20, end=BASE + 110,
               zones=["restricted"], angle=0.0)
        for cam, trk in (("cam_a", "a1"), ("cam_b", "b1"), ("cam_c", "c1")):
            _seed_identity(db, cam, trk)
        correlate(db)
        inc_id = build_incidents(db)[0]
        exp = build_explanation(db, inc_id)
        conf = exp["confidence"]
        # single restricted dwell => behaviour anomaly 0.6; correlation mean >= 0.6
        # here, so min-rule pins incident confidence to the behaviour pillar 0.6.
        assert conf == 0.6
        assert exp["confidence_band"] == confidence_band(conf) == "medium"
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 10. idempotent incident rebuild -> rebuild replaces, no duplicate graph
# ---------------------------------------------------------------------------
def test_idempotent_graph_rebuild():
    db = SessionLocal()
    try:
        _topology(db)
        _event(db, "cam_c", "t1", "dwell", BASE + 5, start=BASE, end=BASE + 90,
               zones=["restricted"], angle=0.0)
        _seed_identity(db, "cam_c", "t1")
        correlate(db)
        inc_id = build_incidents(db)[0]

        n1 = db.query(IncidentNode).filter(IncidentNode.incident_id == inc_id).count()
        e1 = db.query(IncidentGraphEdge).filter(
            IncidentGraphEdge.incident_id == inc_id).count()

        # Rebuild the graph for the same incident from the SAME inputs (same
        # events + same global track). Idempotency = replace, not duplicate.
        from app.models.entities import Event as Ev
        from app.models.entities import Incident
        from app.pipeline.incident_graph import build_graph
        evs = db.query(Ev).filter(Ev.camera_id == "cam_c").all()
        inc = db.get(Incident, inc_id)
        gt_ids = [inc.primary_global_track_id] if inc.primary_global_track_id else []
        build_graph(db, inc_id, evs, gt_ids)
        db.commit()

        n2 = db.query(IncidentNode).filter(IncidentNode.incident_id == inc_id).count()
        e2 = db.query(IncidentGraphEdge).filter(
            IncidentGraphEdge.incident_id == inc_id).count()
        assert n1 == n2 and e1 == e2  # replaced, not duplicated
    finally:
        db.close()


# ---------------------------------------------------------------------------
# v1 API smoke: endpoints return graph/timeline/explanation
# ---------------------------------------------------------------------------
def test_v1_api_endpoints():
    db = SessionLocal()
    try:
        _topology(db)
        _event(db, "cam_a", "a1", "detection", BASE + 1, start=BASE, end=BASE + 5,
               zones=["entry"])
        _event(db, "cam_c", "c1", "dwell", BASE + 25, start=BASE + 20, end=BASE + 110,
               zones=["restricted"], angle=0.0)
        _event(db, "cam_b", "b1", "detection", BASE + 12, start=BASE + 10,
               end=BASE + 15, zones=["transit"])
        for cam, trk in (("cam_a", "a1"), ("cam_b", "b1"), ("cam_c", "c1")):
            _seed_identity(db, cam, trk)
        correlate(db)
        inc_id = build_incidents(db)[0]
    finally:
        db.close()

    lst = client.get("/api/v1/incidents").json()
    assert any(i["id"] == inc_id for i in lst)
    assert all("confidence_band" in i for i in lst)

    detail = client.get(f"/api/v1/incidents/{inc_id}").json()
    assert detail["explanation"]["why_created"]
    assert detail["tracks"] and detail["events"]

    graph = client.get(f"/api/v1/incidents/{inc_id}/graph").json()
    assert graph["nodes"] and graph["edges"]
    assert any(e["type"] == "correlation" for e in graph["edges"])

    tl = client.get(f"/api/v1/incidents/{inc_id}/timeline").json()
    assert [t["camera_id"] for t in tl["timeline"]] == ["cam_a", "cam_b", "cam_c"]

    exp = client.get(f"/api/v1/incidents/{inc_id}/explanation").json()
    assert exp["confidence"] is not None

    assert client.get("/api/v1/incidents/99999").status_code == 404
