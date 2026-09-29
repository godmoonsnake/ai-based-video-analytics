"""Incident Graph builder + Timeline reconstructor.

The INCIDENT stage. A trigger event (e.g. dwell/loiter in a restricted zone, or
a high behavioural anomaly) seeds an incident. We expand along the trigger
track's GlobalTrack to gather all related member-track events across cameras,
then build:

- Incident (priority + confidence + summary)
- IncidentEvent nodes with a role: trigger | evidence | context
- IncidentCamera for each distinct camera
- IncidentEdge graph edges (relation: same_track | zone_transition | temporal_next)

Timeline reconstruction returns those events in chronological order with their
evidence references so operators can trace Incident -> Event -> Camera -> Evidence.
Human-in-the-loop: incidents start `open`; no autonomous verdict is issued.
"""
from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import (
    Event,
    GlobalTrack,
    GlobalTrackMember,
    Incident,
    IncidentCamera,
    IncidentEdge,
    IncidentEvent,
    Zone,
)
from app.pipeline.sequence_analyzer import analyze_events, _zone_kind_map

# Priority mapping from the strongest zone kind touched + anomaly.
_ZONE_PRIORITY = {"restricted": "high", "transit": "low", "entry": "low", "exit": "low"}


def _zone_kinds_for_event(e: Event, kind_map: dict[tuple[str, str], str]) -> list[str]:
    zones = json.loads(e.zones_json) if e.zones_json else []
    return [kind_map.get((e.camera_id, z), "unknown") for z in zones]


def find_triggers(db: Session) -> list[Event]:
    """Trigger events: dwell/loiter inside a restricted zone."""
    kind_map = _zone_kind_map(db)
    triggers: list[Event] = []
    for e in db.execute(select(Event)).scalars().all():
        if e.event_type in ("dwell", "loiter"):
            if "restricted" in _zone_kinds_for_event(e, kind_map):
                triggers.append(e)
    return triggers


def _global_track_for(db: Session, camera_id: str, track_local_id: str) -> GlobalTrack | None:
    member = db.execute(
        select(GlobalTrackMember).where(
            GlobalTrackMember.camera_id == camera_id,
            GlobalTrackMember.track_local_id == track_local_id,
        )
    ).scalars().first()
    if member is None:
        return None
    return db.get(GlobalTrack, member.global_track_id)


def _events_for_global_track(db: Session, gt_id: int) -> list[Event]:
    members = db.execute(
        select(GlobalTrackMember).where(GlobalTrackMember.global_track_id == gt_id)
    ).scalars().all()
    keys = {(m.camera_id, m.track_local_id) for m in members}
    events = db.execute(select(Event)).scalars().all()
    picked = [e for e in events if (e.camera_id, e.track_local_id) in keys]
    return sorted(picked, key=lambda e: e.ts)


def build_incident_from_trigger(db: Session, trigger: Event) -> Incident:
    kind_map = _zone_kind_map(db)
    gt = _global_track_for(db, trigger.camera_id, trigger.track_local_id)

    if gt is not None:
        events = _events_for_global_track(db, gt.id)
    else:
        events = sorted(
            db.execute(
                select(Event).where(
                    Event.camera_id == trigger.camera_id,
                    Event.track_local_id == trigger.track_local_id,
                )
            ).scalars().all(),
            key=lambda e: e.ts,
        )

    seq = analyze_events(events, "incident", kind_map)

    # Priority from strongest zone kind + anomaly boost.
    kinds_touched = {k for e in events for k in _zone_kinds_for_event(e, kind_map)}
    priority = "medium"
    if "restricted" in kinds_touched:
        priority = "critical" if seq.anomaly_score >= 0.6 else "high"

    incident = Incident(
        status="open",
        start_time=min(e.ts for e in events),
        end_time=max(e.ts for e in events),
        priority=priority,
        confidence=gt.confidence if gt else None,
        primary_global_track_id=gt.id if gt else None,
        summary_text=(
            f"Track observed across {len({e.camera_id for e in events})} cameras "
            f"with sequence '{seq.signature}'. "
            f"Anomaly score {round(seq.anomaly_score, 2)}."
        ),
    )
    db.add(incident)
    db.flush()

    # Cameras.
    for cam in sorted({e.camera_id for e in events}):
        db.add(IncidentCamera(incident_id=incident.id, camera_id=cam))

    # Event nodes with roles.
    for e in events:
        if e.id == trigger.id:
            role = "trigger"
        elif e.has_clip or e.has_snapshot:
            role = "evidence"
        else:
            role = "context"
        db.add(IncidentEvent(incident_id=incident.id, event_id=e.id, role=role))

    # Graph edges between consecutive events.
    for prev, cur in zip(events, events[1:]):
        if prev.camera_id == cur.camera_id and prev.track_local_id == cur.track_local_id:
            relation = "same_track"
        elif prev.camera_id != cur.camera_id:
            relation = "zone_transition"
        else:
            relation = "temporal_next"
        db.add(IncidentEdge(
            incident_id=incident.id,
            from_event_id=prev.id, to_event_id=cur.id,
            relation=relation, delta_seconds=round(cur.ts - prev.ts, 2),
        ))

    db.commit()
    db.refresh(incident)
    return incident


def build_incidents(db: Session) -> list[int]:
    """Build one incident per trigger. Returns new incident ids."""
    ids: list[int] = []
    for trigger in find_triggers(db):
        inc = build_incident_from_trigger(db, trigger)
        ids.append(inc.id)
    return ids


def reconstruct_timeline(db: Session, incident_id: int) -> list[dict]:
    """Chronological cross-camera timeline with evidence refs."""
    ie_rows = db.execute(
        select(IncidentEvent).where(IncidentEvent.incident_id == incident_id)
    ).scalars().all()
    role_by_event = {r.event_id: r.role for r in ie_rows}
    events = [db.get(Event, r.event_id) for r in ie_rows]
    events = [e for e in events if e is not None]
    events.sort(key=lambda e: e.ts)

    timeline = []
    for e in events:
        evidence = json.loads(e.evidence_ref_json) if e.evidence_ref_json else {}
        timeline.append({
            "event_id": e.id,
            "camera_id": e.camera_id,
            "event_type": e.event_type,
            "ts": e.ts,
            "zones": json.loads(e.zones_json) if e.zones_json else [],
            "role": role_by_event.get(e.id),
            "evidence": evidence,
        })
    return timeline
