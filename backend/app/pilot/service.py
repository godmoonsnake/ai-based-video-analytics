"""Incremental zone evaluation, desk tasks, shift routing and escalation."""

from datetime import datetime, timezone
import json
import time

from fastapi import HTTPException
from sqlalchemy import select, update, text

from app.config import get_settings
from app.models.entities import Event, Incident, IncidentCamera, IncidentEvent, AuditLog
from app.models.operations import Shift, CameraHealthCurrent
from app.models.security import Site
from app.models.pilot import (
    PilotRule,
    PilotCase,
    PilotContact,
    PilotNotice,
    PilotMaintenance,
)
from app.operations.service import assert_assignee
from app.pilot.schedule import active_at
from app.processing.jobs import digest, enqueue, insert_once
from app.evidence.capture import request_capture, attach_evidence


def _lock(db):
    if db.bind.dialect.name == "postgresql":
        scope = db.info["scope"]
        db.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:scope))"),
            {"scope": f"pilot:{scope.tenant}:{scope.site}"},
        )


def contact_for(db, subject):
    return db.scalar(select(PilotContact).where(PilotContact.subject == subject))


def marker_key(db, name, camera_id=None):
    scope = db.info["scope"]
    return digest([scope.tenant, scope.site, name, camera_id])


def notice(db, case, recipient, reason, now, message=None, camera_id=None, key=None):
    scope = db.info["scope"]
    identifier = digest(
        [
            scope.tenant,
            scope.site,
            key or (case.id if case else camera_id),
            recipient,
            reason,
        ]
    )
    contact = contact_for(db, recipient)
    insert_once(
        db,
        PilotNotice,
        dict(
            id=identifier,
            tenant_id=scope.tenant,
            site_id=scope.site,
            case_id=case.id if case else None,
            camera_id=camera_id,
            recipient=recipient,
            channel=contact.channel if contact else "unconfigured",
            destination=contact.destination if contact else "",
            reason=reason,
            message=message
            or f"DARSON task #{case.incident_id}: {case.rule_snapshot['zone_name']} — {reason}. Open the guard desk to acknowledge.",
            status="queued" if contact else "failed",
            created_at=now,
            attempts=0,
            failure_class=None if contact else "missing_contact",
        ),
    )
    if contact:
        enqueue(db, "pilot_notice", identifier, {"notice_id": identifier})


def escalate(db, case, reason, now):
    # Empty configuration is an explicit failed notice shown on the desk.
    recipient = get_settings().pilot_supervisor_subject or "unconfigured-supervisor"
    notice(db, case, recipient, reason, now)


def process_event(db, event_id, now=None):
    now = time.time() if now is None else now
    settings, scope = get_settings(), db.info["scope"]
    event = db.get(Event, event_id)
    if not event:
        return
    _lock(db)
    # Late lifecycle messages may provide evidence for an already opened task.
    existing = db.scalars(
        select(PilotCase).where(
            PilotCase.source_instance == (event.source_instance or ""),
            PilotCase.track_local_id == event.track_local_id,
        )
    ).all()
    existing = [
        case for case in existing if case.rule_snapshot["camera_id"] == event.camera_id
    ]
    for case in existing:
        if not db.scalar(
            select(IncidentEvent.id).where(
                IncidentEvent.incident_id == case.incident_id,
                IncidentEvent.event_id == event.id,
            )
        ):
            db.add(
                IncidentEvent(
                    incident_id=case.incident_id, event_id=event.id, role="evidence"
                )
            )
        if case.state != "resolved":
            request_capture(db, event)
        db.flush()
        attach_evidence(db, case.incident_id, [event.id])
    # Never turn delayed replay data or a completed track into a fresh emergency.
    if (
        event.label != "person"
        or event.event_kind == "end"
        or not 0 <= now - event.ts <= settings.pilot_max_event_age_seconds
        or (settings.environment == "production" and event.source_type != "frigate")
    ):
        db.commit()
        return
    zones = json.loads(event.zones_json or "[]")
    site = db.get(Site, (scope.tenant, scope.site))
    for rule in db.scalars(
        select(PilotRule).where(
            PilotRule.enabled.is_(True), PilotRule.camera_id == event.camera_id
        )
    ):
        if rule.zone_name not in zones or not active_at(
            rule.schedule, event.ts, site.timezone
        ):
            continue
        # One case per source track/rule, even after acknowledgement or restart.
        identifier = digest(
            [
                scope.tenant,
                scope.site,
                rule.id,
                event.source_instance,
                event.camera_id,
                event.track_local_id,
            ]
        )
        if db.get(PilotCase, identifier):
            continue
        snapshot = {
            "camera_id": rule.camera_id,
            "zone_name": rule.zone_name,
            "post_id": rule.post_id,
            "version": rule.version,
            "schedule": rule.schedule,
            "timezone": site.timezone,
            "instruction": rule.instruction,
        }
        incident = Incident(
            category="restricted_entry",
            status="open",
            start_time=event.ts,
            priority=rule.priority,
            confidence=event.confidence,
            dedup_key=identifier,
            created_at=datetime.fromtimestamp(now, timezone.utc),
            summary_text=f"Person observed in {rule.zone_name} during restricted hours.",
        )
        db.add(incident)
        db.flush()
        db.add(IncidentCamera(incident_id=incident.id, camera_id=event.camera_id))
        db.add(
            IncidentEvent(incident_id=incident.id, event_id=event.id, role="trigger")
        )
        # Use current on-duty shift, not a guessed physical nearest guard.
        shifts = db.scalars(
            select(Shift)
            .where(
                Shift.post_id == rule.post_id,
                Shift.cancelled_at.is_(None),
                Shift.starts_at <= now,
                Shift.ends_at > now,
            )
            .order_by(Shift.starts_at.desc(), Shift.id)
        ).all()
        owner = None
        for shift in shifts:
            try:
                assert_assignee(db, shift.subject)
                owner = shift.subject
                break
            except HTTPException:
                continue
        case = PilotCase(
            id=identifier,
            incident_id=incident.id,
            rule_id=rule.id,
            rule_snapshot=snapshot,
            trigger_event_id=event.id,
            source_instance=event.source_instance or "",
            track_local_id=event.track_local_id,
            owner=owner,
            state="open",
            created_at=now,
            acknowledgement_deadline=now + rule.acknowledgement_seconds,
        )
        db.add(case)
        db.flush()
        request_capture(db, event)
        attach_evidence(db, incident.id, [event.id])
        if owner:
            notice(db, case, owner, "assigned_guard", now)
            if contact_for(db, owner) is None:
                escalate(db, case, "guard_delivery_failed", now)
        else:
            escalate(db, case, "no_guard_on_shift", now)
        if rule.priority == "critical" and settings.pilot_critical_copy_supervisor:
            escalate(db, case, "critical_event", now)
        db.add(
            AuditLog(
                actor=scope.actor,
                action="pilot_task_created",
                target=f"incident:{incident.id}",
            )
        )
    db.commit()


def maintenance(db, now=None):
    """Runs under the scoped worker even while its processing queue is busy."""
    now = time.time() if now is None else now
    settings = get_settings()
    _lock(db)
    marker = db.get(PilotMaintenance, marker_key(db, "escalations"))
    if marker and now - marker.last_run_at < settings.maintenance_interval_seconds:
        return
    for case in db.scalars(select(PilotCase).where(PilotCase.state != "resolved")):
        if case.acknowledged_at is None and now >= case.acknowledgement_deadline:
            escalate(db, case, "unacknowledged", now)
    for health in db.scalars(
        select(CameraHealthCurrent).where(
            CameraHealthCurrent.stream_state == "offline",
            CameraHealthCurrent.maintenance.is_(False),
        )
    ):
        # One notice per camera outage episode; recovery permits a new notice.
        marker_id = marker_key(db, "camera-offline", health.camera_id)
        if db.get(PilotMaintenance, marker_id) is None:
            recipient = settings.pilot_supervisor_subject or "unconfigured-supervisor"
            notice(
                db,
                None,
                recipient,
                "camera_offline",
                now,
                camera_id=health.camera_id,
                message=f"DARSON camera {health.camera_id} is offline. Check the on-site desk.",
                key=[marker_id, now],
            )
            db.add(
                PilotMaintenance(
                    id=marker_id,
                    name="camera-offline",
                    camera_id=health.camera_id,
                    last_run_at=now,
                )
            )
    for row in db.scalars(
        select(PilotMaintenance).where(PilotMaintenance.name == "camera-offline")
    ):
        camera = db.scalar(
            select(CameraHealthCurrent).where(
                CameraHealthCurrent.camera_id == row.camera_id
            )
        )
        if camera and camera.stream_state in {"healthy", "online"}:
            db.delete(row)
    if marker:
        marker.last_run_at = now
    else:
        db.add(
            PilotMaintenance(
                id=marker_key(db, "escalations"), name="escalations", last_run_at=now
            )
        )
    db.commit()


def authorize_case(db, identifier):
    case = db.get(PilotCase, identifier)
    scope = db.info["scope"]
    if not case or (scope.role == "responder" and case.owner != scope.actor):
        raise HTTPException(404, "task not found")
    return case


def act(db, identifier, body):
    case = authorize_case(db, identifier)
    scope = db.info["scope"]
    incident = db.get(Incident, case.incident_id)
    if incident.version != body.expected_version:
        raise HTTPException(409, "task changed; refresh before retrying")
    if case.state == "resolved":
        raise HTTPException(409, "task already resolved")
    now = time.time()
    if body.action == "claim":
        if scope.role == "responder":
            raise HTTPException(403, "desk operators assign tasks")
        if case.owner and case.owner != scope.actor:
            raise HTTPException(
                409,
                "task already assigned; use the roster and supervisor handover procedure",
            )
        assert_assignee(db, scope.actor)
        case.owner = scope.actor
    elif body.action == "acknowledge":
        if case.owner is None and scope.role in {"operator", "supervisor"}:
            case.owner = scope.actor
        elif scope.actor != case.owner and scope.role != "supervisor":
            raise HTTPException(
                403, "only assigned guard or supervisor may acknowledge"
            )
        case.acknowledged_at = case.acknowledged_at or now
        case.state = "acknowledged"
    elif body.action == "outcome":
        if scope.actor != case.owner and scope.role != "supervisor":
            raise HTTPException(
                403, "only assigned guard or supervisor may report outcome"
            )
        if case.acknowledged_at is None:
            raise HTTPException(409, "acknowledge before recording an outcome")
        case.outcome, case.outcome_note, case.outcome_actor = (
            body.outcome,
            body.note,
            scope.actor,
        )
        if body.outcome == "need_help":
            case.state = "need_help"
            escalate(db, case, "need_help", now)
        else:
            case.state, case.resolved_at = "resolved", now
            incident.status = (
                "confirmed" if body.outcome == "real_incident" else "dismissed"
            )
    changed = db.execute(
        update(Incident)
        .where(Incident.id == incident.id, Incident.version == body.expected_version)
        .values(version=body.expected_version + 1)
    )
    if changed.rowcount != 1:
        db.rollback()
        raise HTTPException(409, "task changed; refresh before retrying")
    db.add(AuditLog(actor=scope.actor, action=f"pilot:{body.action}", target=case.id))
    db.commit()
    return {"id": case.id, "state": case.state, "version": incident.version}
