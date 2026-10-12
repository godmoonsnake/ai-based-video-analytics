from sqlalchemy import select, func
from app.adapters.mock_source import MockEventSource, load_topology
from app.adapters.ingestion import ingest_source, seed_embeddings
from app.db.session import SessionLocal
from app.models.entities import Incident, GlobalTrack, Event
from app.models.lineage import IncidentVersion, CorrelationHypothesis
from app.pipeline.correlator import correlate, TrackSpan, score_pair
from app.pipeline.incident_builder import build_incidents
from app.pipeline.incident_lifecycle import apply_transition


def seed(db):
    load_topology(db)
    ingest_source(db, MockEventSource(base_epoch=1700000000))
    seed_embeddings(db)


def test_replay_preserves_case_decisions_and_track_references():
    with SessionLocal() as db:
        seed(db)
        first = correlate(db)
        ids = build_incidents(db)
        inc = db.get(Incident, ids[0])
        apply_transition(db, inc, "start_triage")
        apply_transition(db, inc, "confirm")
        original_track = inc.primary_global_track_id
        version = db.scalar(select(IncidentVersion))
        frozen = version.snapshot
        seed(db)
        assert correlate(db) == first
        assert build_incidents(db) == ids
        assert db.scalar(select(func.count()).select_from(Incident)) == 1
        assert inc.status == "confirmed"
        assert db.get(GlobalTrack, original_track) is not None
        assert db.get(IncidentVersion, version.id).snapshot == frozen


def test_branch_ambiguity_and_bounded_scores():
    with SessionLocal() as db:
        seed(db)
        original = db.scalar(select(Event).where(Event.camera_id == "corridor_1"))
        db.add(Event(id="branch", camera_id=original.camera_id, track_local_id="branch",
            source_type="mock", event_type="detection", ts=original.ts,
            start_time=original.start_time, end_time=original.end_time, label="person", sub_label="red_bag"))
        db.commit()
        seed_embeddings(db)
        groups = correlate(db, tau=0.1)
        assert all(g["confidence"] is None or 0 <= g["confidence"] <= 1 for g in groups)
        assert db.scalar(select(CorrelationHypothesis).where(CorrelationHypothesis.disposition == "ambiguous"))
        assert any(g["track_kind"] == "single_camera" for g in groups)


def test_transit_endpoints_are_valid_candidates():
    with SessionLocal() as db:
        load_topology(db)
        a = TrackSpan("gate_3", "a", 0, 6, None, None)
        assert score_pair(db, a, TrackSpan("corridor_1", "b", 10, 12, None, None)) is not None
        assert score_pair(db, a, TrackSpan("corridor_1", "b", 26, 28, None, None)) is not None
