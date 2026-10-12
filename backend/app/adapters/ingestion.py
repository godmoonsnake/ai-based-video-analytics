"""Ingestion: persist CanonicalEvents into the event table.

Kept deliberately simple and idempotent-ish (dedup on source_event_id+ts). The
adapter (mock/frigate) produces CanonicalEvents; ingestion is the single write
path so downstream stages always read consistent rows.
"""
from __future__ import annotations

import json
import time

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


def ingest_event(db: Session, evt: CanonicalEvent, enqueue_pipeline: bool = True,
                 enqueue_evidence: bool = True) -> Event:
    from sqlalchemy import select
    from app.processing.jobs import digest, enqueue, insert_once
    scope = db.info["scope"]
    if evt.tenant_id not in (None, scope.tenant) or evt.site_id not in (None, scope.site):
        raise PermissionError("event scope mismatch")
    payload = evt.model_dump(mode="json", exclude={"event_id", "tenant_id", "site_id"})
    payload_hash = digest(payload)
    revision = evt.source.revision or str(evt.time.observed)
    key = digest([scope.tenant, scope.site, evt.source.type.value, evt.source.instance,
                  evt.source.source_event_id, evt.camera_id, revision,
                  evt.source.event_kind, evt.event_type.value])
    row = _to_row(evt)
    values = {c.name: getattr(row, c.name) for c in Event.__table__.columns
              if c.name not in {"created_at", "schema_version"}}
    values.update(id=key, dedup_key=key, tenant_id=scope.tenant, site_id=scope.site,
                  source_instance=evt.source.instance, source_revision=revision,
                  event_kind=evt.source.event_kind, payload_digest=payload_hash,
                  received_at=time.time(), schema_version=evt.schema_version)
    from app.config import get_settings
    if get_settings().pilot_mode:
        # Keep provenance, not optional identity attributes or full raw payloads.
        values.update(raw_json=None, sub_label=None)
    insert_once(db, Event, values, key="dedup_key")
    existing = db.scalar(select(Event).where(Event.dedup_key == key))
    if existing is None or existing.payload_digest != payload_hash:
        db.rollback()
        raise ValueError("conflicting source revision")
    if enqueue_pipeline:
        enqueue(db, "pipeline", key, {"event_id": existing.id})
    from app.evidence.capture import request_capture
    if not get_settings().pilot_mode:
        request_capture(db, existing, enqueue_job=enqueue_evidence)
    db.commit()
    return existing


def ingest_source(db: Session, source: EventSource, limit: int | None = None,
                  enqueue_pipeline: bool = True, enqueue_evidence: bool = True) -> int:
    """Drain a source into the DB. Returns number of events ingested."""
    count = 0
    for evt in source.stream():
        ingest_event(db, evt, enqueue_pipeline=enqueue_pipeline, enqueue_evidence=enqueue_evidence)
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
        from app.models.entities import TrackEmbedding
        if db.scalar(_select(TrackEmbedding.id).where(
                TrackEmbedding.camera_id == e.camera_id,
                TrackEmbedding.track_local_id == e.track_local_id).limit(1)):
            continue
        seed = e.sub_label or e.label or "unknown"
        add_embedding(db, e.camera_id, e.track_local_id, seed=seed, event_id=e.id)
        made += 1
    return made
