"""Ingestion: persist CanonicalEvents into the event table.

Kept deliberately simple and idempotent-ish (dedup on source_event_id+ts). The
adapter (mock/frigate) produces CanonicalEvents; ingestion is the single write
path so downstream stages always read consistent rows.
"""
from __future__ import annotations

import json

from sqlalchemy.orm import Session

from app.adapters.base import EventSource
from app.models.entities import Event
from app.schemas.event import CanonicalEvent


def _to_row(evt: CanonicalEvent) -> Event:
    return Event(
        id=evt.event_id,
        source_event_id=evt.source.source_event_id,
        source_type=evt.source.type.value,
        camera_id=evt.camera_id,
        track_local_id=evt.track.local_id,
        event_type=evt.event_type.value,
        label=evt.label,
        sub_label=evt.sub_label,
        confidence=evt.confidence,
        start_time=evt.time.start,
        end_time=evt.time.end,
        ts=evt.time.observed,
        bbox_json=json.dumps(evt.spatial.bbox) if evt.spatial.bbox is not None else None,
        region_json=json.dumps(evt.spatial.region) if evt.spatial.region is not None else None,
        zones_json=json.dumps(evt.spatial.zones),
        velocity_angle=evt.spatial.velocity_angle,
        avg_speed=evt.spatial.avg_speed,
        has_snapshot=evt.evidence.has_snapshot,
        has_clip=evt.evidence.has_clip,
        evidence_ref_json=json.dumps(
            {"snapshot_url": evt.evidence.snapshot_url, "clip_url": evt.evidence.clip_url}
        ),
        raw_json=json.dumps(evt.raw_json) if evt.raw_json is not None else None,
    )


def ingest_event(db: Session, evt: CanonicalEvent) -> Event:
    row = _to_row(evt)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def ingest_source(db: Session, source: EventSource, limit: int | None = None) -> int:
    """Drain a source into the DB. Returns number of events ingested."""
    count = 0
    for evt in source.stream():
        ingest_event(db, evt)
        count += 1
        if limit is not None and count >= limit:
            break
    return count


def seed_embeddings(db: Session) -> int:
    """Create appearance embeddings for every (camera, track) from an identity seed.

    Identity seed = sub_label when present (mock scenario uses 'red_bag' across
    cameras so the same person clusters), else label. In the real Frigate path
    this is replaced by OSNet features over snapshot crops. Appearance-only; no
    identity DB, no PII.
    """
    from app.models.entities import Event
    from app.pipeline.reid_service import add_embedding
    from sqlalchemy import select as _select

    rows = db.execute(_select(Event)).scalars().all()
    seen: set[tuple[str, str]] = set()
    made = 0
    for e in rows:
        key = (e.camera_id, e.track_local_id)
        if key in seen:
            continue
        seen.add(key)
        seed = e.sub_label or e.label or "unknown"
        add_embedding(db, e.camera_id, e.track_local_id, seed=seed, event_id=e.id)
        made += 1
    return made
