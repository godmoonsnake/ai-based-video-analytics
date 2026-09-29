"""Events API: list canonical events with structured filters; trigger mock ingest."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.ingestion import ingest_source
from app.adapters.mock_source import MockEventSource, load_topology
from app.db.session import get_db
from app.models.entities import Event

router = APIRouter(prefix="/events", tags=["events"])


def _serialize(e: Event) -> dict:
    return {
        "event_id": e.id,
        "source_type": e.source_type,
        "source_event_id": e.source_event_id,
        "camera_id": e.camera_id,
        "track_local_id": e.track_local_id,
        "event_type": e.event_type,
        "label": e.label,
        "sub_label": e.sub_label,
        "confidence": e.confidence,
        "time": {"start": e.start_time, "end": e.end_time, "observed": e.ts},
        "spatial": {
            "bbox": json.loads(e.bbox_json) if e.bbox_json else None,
            "zones": json.loads(e.zones_json) if e.zones_json else [],
            "velocity_angle": e.velocity_angle,
            "avg_speed": e.avg_speed,
        },
        "evidence": json.loads(e.evidence_ref_json) if e.evidence_ref_json else {},
    }


@router.get("")
def list_events(
    db: Session = Depends(get_db),
    camera_id: str | None = None,
    event_type: str | None = None,
    label: str | None = None,
    limit: int = Query(200, le=1000),
) -> list[dict]:
    stmt = select(Event).order_by(Event.ts)
    if camera_id:
        stmt = stmt.where(Event.camera_id == camera_id)
    if event_type:
        stmt = stmt.where(Event.event_type == event_type)
    if label:
        stmt = stmt.where(Event.label == label)
    rows = db.execute(stmt.limit(limit)).scalars().all()
    return [_serialize(e) for e in rows]


@router.post("/ingest/mock")
def ingest_mock(db: Session = Depends(get_db)) -> dict:
    """Seed topology and replay the default mock scenario (demo helper)."""
    from app.adapters.ingestion import seed_embeddings

    load_topology(db)
    count = ingest_source(db, MockEventSource())
    embeddings = seed_embeddings(db)
    return {"ingested": count, "embeddings": embeddings, "source": "mock"}


@router.post("/ingest/frigate/replay")
def ingest_frigate_replay(messages: list[dict], db: Session = Depends(get_db)) -> dict:
    """Replay a recorded list of Frigate `frigate/events` messages (demo helper).

    Proves the Frigate integration path without a live broker: the same messages
    a broker would deliver are mapped to canonical events and ingested.
    """
    from app.adapters.frigate_source import FrigateReplaySource

    count = ingest_source(db, FrigateReplaySource(messages))
    return {"ingested": count, "source": "frigate"}
