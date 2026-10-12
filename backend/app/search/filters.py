"""Structured investigation filters over events and incidents.

Deterministic first: an operator (or the NL parser) supplies a structured
filter dict and gets matching events/incidents back. Results are for human
review — the system never issues a verdict.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import Event, Incident, IncidentCamera, IncidentEvent
from app.models.evidence import EvidenceObject


@dataclass
class SearchFilter:
    camera_id: str | None = None
    event_type: str | None = None
    label: str | None = None
    sub_label: str | None = None
    zone: str | None = None
    time_start: float | None = None
    time_end: float | None = None
    status: str | None = None       # incident status
    priority: str | None = None     # incident priority
    text: str | None = None         # free text over label/sub_label

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if v is not None}


@dataclass
class SearchResults:
    filter: dict
    events: list[dict] = field(default_factory=list)
    incidents: list[dict] = field(default_factory=list)
    human_review_required: bool = True  # explicit: no autonomous verdict


def search_events(db: Session, f: SearchFilter) -> list[Event]:
    stmt = select(Event).order_by(Event.ts)
    if f.camera_id:
        stmt = stmt.where(Event.camera_id == f.camera_id)
    if f.event_type:
        stmt = stmt.where(Event.event_type == f.event_type)
    if f.label:
        stmt = stmt.where(Event.label == f.label)
    if f.sub_label:
        stmt = stmt.where(Event.sub_label == f.sub_label)
    if f.time_start is not None:
        stmt = stmt.where(Event.ts >= f.time_start)
    if f.time_end is not None:
        stmt = stmt.where(Event.ts <= f.time_end)
    rows = db.execute(stmt).scalars().all()

    # Post-filter zone / free text (stored as JSON / spread across columns).
    out = []
    for e in rows:
        if f.zone:
            zones = json.loads(e.zones_json) if e.zones_json else []
            if f.zone not in zones:
                continue
        if f.text:
            hay = f"{e.label or ''} {e.sub_label or ''}".lower()
            if f.text.lower() not in hay:
                continue
        out.append(e)
    return out


def search_incidents(db: Session, f: SearchFilter) -> list[Incident]:
    stmt = select(Incident).order_by(Incident.start_time)
    if f.status:
        stmt = stmt.where(Incident.status == f.status)
    if f.priority:
        stmt = stmt.where(Incident.priority == f.priority)
    if f.time_start is not None:
        stmt = stmt.where(Incident.end_time >= f.time_start)
    if f.time_end is not None:
        stmt = stmt.where(Incident.start_time <= f.time_end)
    incidents = db.execute(stmt).scalars().all()

    if f.camera_id:
        keep = []
        for inc in incidents:
            cams = db.execute(
                select(IncidentCamera).where(IncidentCamera.incident_id == inc.id)
            ).scalars().all()
            if any(c.camera_id == f.camera_id for c in cams):
                keep.append(inc)
        incidents = keep
    return incidents


def run_search(db: Session, f: SearchFilter) -> SearchResults:
    events = search_events(db, f)
    incidents = search_incidents(db, f)
    if any((f.event_type, f.label, f.sub_label, f.zone, f.text)):
        matched = {event.id for event in events}
        related = set(db.scalars(select(IncidentEvent.incident_id).where(
            IncidentEvent.event_id.in_(matched))).all()) if matched else set()
        incidents = [incident for incident in incidents if incident.id in related]
    vault = {}
    if events:
        for obj in db.scalars(select(EvidenceObject).where(
                EvidenceObject.event_id.in_([event.id for event in events]))):
            vault.setdefault(obj.event_id, {})[obj.kind] = obj

    def evidence_ref(event: Event) -> dict:
        records = vault.get(event.id, {})
        return {kind: {
            "status": item.status if item else "not-requested",
            "content_url": f"/api/v1/evidence/{item.id}/content" if item and item.status == "available" else None,
        } for kind, item in (("snapshot", records.get("snapshot")), ("clip", records.get("clip")))}

    return SearchResults(
        filter=f.to_dict(),
        events=[
            {
                "event_id": e.id, "camera_id": e.camera_id, "event_type": e.event_type,
                "label": e.label, "sub_label": e.sub_label, "ts": e.ts,
                "evidence": evidence_ref(e),
            }
            for e in events
        ],
        incidents=[
            {
                "id": inc.id, "status": inc.status, "priority": inc.priority,
                "summary_text": inc.summary_text,
            }
            for inc in incidents
        ],
    )
