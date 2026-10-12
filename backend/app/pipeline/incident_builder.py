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
import time

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models.entities import (
    Event,
    GlobalTrack,
    GlobalTrackMember,
    Incident,
    IncidentCamera,
    IncidentEdge,
    IncidentEvent,
)
from app.pipeline.incident_graph import build_graph
from app.pipeline.sequence_analyzer import analyze_events, _zone_kind_map

# Priority mapping from the strongest zone kind touched + anomaly.
_ZONE_PRIORITY = {"restricted": "high", "transit": "low", "entry": "low", "exit": "low"}


def _zone_kinds_for_event(e: Event, kind_map: dict[tuple[str, str], str]) -> list[str]:
    zones = json.loads(e.zones_json) if e.zones_json else []
    return [kind_map.get((e.camera_id, z), "unknown") for z in zones]


def find_triggers(db: Session) -> list[Event]:
    """Trigger events inside a restricted zone.

    Two restricted-zone signals seed an incident:
      - dwell/loiter (the strongest signal: lingering in a restricted area), and
      - entry/presence (zone_enter/detection in a restricted zone) — a person
        entering a restricted area is itself a reviewable event and is what real
        pedestrian footage typically produces.
    At most one trigger per (camera, track) is returned (dwell preferred over
    entry) so one movement does not seed duplicate incidents.
    """
    kind_map = _zone_kind_map(db)
    dwell_by_key: dict[tuple[str, str], Event] = {}
    entry_by_key: dict[tuple[str, str], Event] = {}
    for e in db.execute(select(Event)).scalars().all():
        if e.label != "person":
            continue
        if "restricted" not in _zone_kinds_for_event(e, kind_map):
            continue
        key = (e.camera_id, e.track_local_id)
        if e.event_type in ("dwell", "loiter"):
            dwell_by_key.setdefault(key, e)
        elif e.event_type in ("zone_enter", "detection"):
            entry_by_key.setdefault(key, e)
    triggers: list[Event] = list(dwell_by_key.values())
    triggers += [e for key, e in entry_by_key.items() if key not in dwell_by_key]
    return triggers


def _global_track_for(db: Session, camera_id: str, track_local_id: str) -> GlobalTrack | None:
    member = db.execute(
        select(GlobalTrackMember).where(
            GlobalTrackMember.camera_id == camera_id,
            GlobalTrackMember.track_local_id == track_local_id,
        ).join(GlobalTrack).where(GlobalTrack.current.is_(True))
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
        priority = "high"  # restricted-zone-v1 policy, independent of appearance/anomaly score

    incident = Incident(
        category="restricted_entry",
        dedup_key=_episode_key(db, trigger.camera_id, trigger.track_local_id),
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

    # Legacy event-to-event edges (kept for backward compatibility).
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

    # Normalized incident graph (nodes + typed edges + evidence) and the
    # documented confidence propagation. This is the source-agnostic graph layer.
    gt_ids = [gt.id] if gt is not None else []
    prop = build_graph(db, incident.id, events, gt_ids)
    # Confidence now comes from the documented propagation method (min of the
    # correlation-continuity and behaviour pillars), not the raw track score.
    incident.confidence = prop["incident_confidence"]

    db.commit()
    db.refresh(incident)
    return incident


def build_incidents(db: Session) -> list[int]:
    """Build incidents from connected evidence.

    Triggers that resolve to the SAME global track are merged into ONE incident
    (justified by the existing cross-camera correlation), so a single correlated
    movement never produces duplicate incidents. Triggers on distinct global
    tracks (or with no global track) yield separate incidents. This is the
    multi-track-aware, correlation-justified grouping the milestone requires —
    incidents are built from connected evidence, not per raw detection.
    """
    from app.models.lineage import IncidentEpisode
    from app.processing.jobs import insert_once
    if db.bind.dialect.name == "postgresql":
        scope = db.info["scope"]
        db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:scope))"),
                   {"scope": f"incidents:{scope.tenant}:{scope.site}"})
    ids: list[int] = []
    seen_global_tracks: set[int] = set()
    for trigger in find_triggers(db):
        gt = _global_track_for(db, trigger.camera_id, trigger.track_local_id)
        if gt is not None:
            if gt.id in seen_global_tracks:
                continue  # already covered by an incident for this movement
            seen_global_tracks.add(gt.id)
        events = _events_for_global_track(db, gt.id) if gt else [trigger]
        keys = {_episode_key(db, e.camera_id, e.track_local_id) for e in events}
        existing = set(db.scalars(select(IncidentEpisode.incident_id).where(IncidentEpisode.id.in_(keys))))
        direct = db.scalar(select(Incident).where(Incident.dedup_key == _episode_key(
            db, trigger.camera_id, trigger.track_local_id)))
        if direct:
            existing.add(direct.id)
        # Adopt a historical incident by its immutable event references, not a changing GT ID.
        legacy = set(db.scalars(select(IncidentEvent.incident_id).where(
            IncidentEvent.event_id.in_([e.id for e in events]))))
        existing.update(legacy)
        if len(existing) > 1:
            # Never silently merge two operational cases when new inference links them.
            for identifier in sorted(existing):
                _record_version(db, db.get(Incident, identifier), events, gt, True)
                ids.append(identifier)
            db.commit()
            continue
        inc = db.get(Incident, next(iter(existing))) if existing else build_incident_from_trigger(db, trigger)
        scope = db.info["scope"]
        for key in keys:
            insert_once(db, IncidentEpisode, dict(id=key, incident_id=inc.id,
                        tenant_id=scope.tenant, site_id=scope.site))
        _record_version(db, inc, events, gt, bool(existing))
        from app.evidence.capture import attach_evidence
        attach_evidence(db, inc.id, [e.id for e in events])
        db.commit()
        ids.append(inc.id)
    return sorted(set(ids))


def _episode_key(db, camera, track):
    from app.processing.jobs import digest
    scope = db.info["scope"]
    return digest([scope.tenant, scope.site, "restricted-zone-v1", camera, track])


def _record_version(db, incident, events, gt, proposed):
    from app.models.lineage import IncidentVersion
    from app.processing.jobs import digest
    from app.pipeline.incident_graph import graph_as_dict, graph_timeline
    identifier = digest([incident.id, sorted(e.id for e in events), gt.run_id if gt else None])
    if db.get(IncidentVersion, identifier):
        return
    # Case lineage and response concurrency share the monotonic incident version:
    # newly inferred material invalidates stale operator/export snapshots.
    if proposed:
        incident.version = (incident.version or 1) + 1
    db.add(IncidentVersion(id=identifier, incident_id=incident.id, created_at=time.time(),
        requires_review=proposed, snapshot={
            "incident_id": incident.id, "case_version": incident.version,
            "review_state": incident.status, "priority": incident.priority,
            "priority_policy": "restricted-zone-v1", "priority_reason": "restricted zone observation",
            "event_ids": sorted(e.id for e in events), "run_id": gt.run_id if gt else None,
            "proposed_track_id": gt.id if gt else None, "graph": graph_as_dict(db, incident.id),
            "timeline": graph_timeline(db, incident.id),
            "correlation_score": gt.confidence if gt else None, "score_is_probability": False,
            "track_kind": "correlated_movement" if len({e.camera_id for e in events}) > 1 else "single_camera",
            "detector_confidences": {e.id: e.confidence for e in events},
            "note": "New inference requires review; completed case graph and decisions are preserved."
                    if proposed else "Initial case snapshot."}))


def reconstruct_timeline(db: Session, incident_id: int) -> list[dict]:
    """Chronological cross-camera timeline with evidence refs."""
    from app.pipeline.incident_graph import graph_timeline
    return graph_timeline(db, incident_id)
