"""Versioned, synthetic review replay through the normal ingest pipeline."""
from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.ingestion import ingest_source, seed_embeddings
from app.adapters.mock_source import MockEventSource, SCENARIOS_DIR, load_topology
from app.config import get_settings
from app.db.session import get_db
from app.models.entities import Camera, Event, IncidentEvent
from app.models.evidence import EvidenceObject
from app.evidence.capture import store_capture
from app.pipeline.correlator import correlate
from app.pipeline.incident_builder import build_incidents

router = APIRouter(prefix="/api/v1/demo", tags=["demo"])
FIXTURE = SCENARIOS_DIR / "review_v1.json"


def _fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _manifest(db: Session) -> dict:
    data = _fixture()
    scenarios = []
    for item in data["scenarios"]:
        ids = db.scalars(select(IncidentEvent.incident_id).join(
            Event, Event.id == IncidentEvent.event_id).where(
            Event.source_event_id.in_(item["source_event_ids"]))).all()
        scenarios.append({**item, "incident_id": min(ids) if ids else None})
    return {"id": data["id"], "version": data["version"], "clock": data["clock"],
            "synthetic": True, "description": data["description"], "scenarios": scenarios,
            "ready": all(item["incident_id"] is not None for item in scenarios)}


@router.get("/manifest")
def manifest(db: Session = Depends(get_db)) -> dict:
    if get_settings().environment == "production":
        raise HTTPException(404, "not found")
    return _manifest(db)


@router.post("/replay")
def replay(db: Session = Depends(get_db)) -> dict:
    if get_settings().environment == "production":
        raise HTTPException(404, "not found")
    current = _manifest(db)
    if current["ready"]:
        return {**current, "ingested": 0, "replayed": False}
    data = _fixture()
    if db.get(Camera, "gate_3") is None:
        load_topology(db)
    epoch = datetime.fromisoformat(data["clock"]).timestamp()
    ingested = ingest_source(db, MockEventSource(FIXTURE, base_epoch=epoch),
                             enqueue_pipeline=False, enqueue_evidence=False)
    seed_embeddings(db)
    correlate(db)
    build_incidents(db)
    # The bundled media is synthetic. Load it into the normal evidence vault,
    # preserving hashes, provenance and authorization checks on reads.
    media_root = FIXTURE.parents[2] / "deploy" / "mock-evidence"
    media_tracks = {"review-gate": ("gate_3", "A1"),
                    "review-corridor": ("corridor_1", "B7"),
                    "review-restricted": ("restricted_2", "C3"),
                    "review-exit": ("exit_4", "D9")}
    for obj in db.scalars(select(EvidenceObject).join(Event, Event.id == EvidenceObject.event_id).where(
            Event.source_event_id.in_(media_tracks), EvidenceObject.status != "available")).all():
        event = db.get(Event, obj.event_id)
        camera, track = media_tracks[event.source_event_id]
        filename = "snapshot.jpg" if obj.kind == "snapshot" else "clip.mp4"
        file_path = media_root / camera / track / filename
        if file_path.is_file():
            store_capture(db, obj, file_path.read_bytes(),
                          "image/jpeg" if obj.kind == "snapshot" else "video/mp4")
    for obj in db.scalars(select(EvidenceObject).join(Event, Event.id == EvidenceObject.event_id).where(
            Event.source_event_id == "review-gap", EvidenceObject.status == "requested")).all():
        obj.status, obj.error = "unavailable", "synthetic_fixture_not_loaded"
    db.commit()
    return {**_manifest(db), "ingested": ingested, "replayed": True}
