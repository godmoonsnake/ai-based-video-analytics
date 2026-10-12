"""Read-only Incident Graph API (v1).

Exposes the incident graph, timeline, and machine-readable explanation for the
eventual operator UI. All endpoints are READ-ONLY (GET) — incident construction
and human-in-the-loop feedback live on the existing /incidents routes.

Response shapes are designed so a UI can render, without extra round-trips:
  - incident summary (list)
  - incident detail: cameras, tracks, events, confidence + explanation/evidence
  - timeline (graph-membership derived)
  - graph (nodes + typed edges with evidence)
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.entities import Incident, IncidentCamera, IncidentNode
from app.pipeline.incident_graph import (
    build_explanation,
    confidence_band,
    graph_as_dict,
    graph_timeline,
)
from app.pipeline.incident_lifecycle import (
    InvalidTransition,
    allowed_actions,
    apply_transition,
    transition_history,
)

router = APIRouter(prefix="/api/v1/incidents", tags=["incidents-v1"])


def _summary(db: Session, inc: Incident) -> dict:
    from app.models.pilot import PilotCase
    pilot_task = db.scalar(select(PilotCase.id).where(PilotCase.incident_id == inc.id))
    cams = db.execute(
        select(IncidentCamera).where(IncidentCamera.incident_id == inc.id)
    ).scalars().all()
    return {
        "id": inc.id,
        "version": inc.version,
        "tenant_id": inc.tenant_id,
        "site_id": inc.site_id,
        "track_kind": "correlated_movement" if len(cams) > 1 else "single_camera",
        "score_is_probability": False,
        "status": inc.status,
        "category": inc.category,
        "pilot_task_id": pilot_task,
        "priority": inc.priority,
        "confidence": inc.confidence,
        "confidence_band": confidence_band(inc.confidence),
        "start_time": inc.start_time,
        "end_time": inc.end_time,
        "cameras": [c.camera_id for c in cams],
        "summary_text": inc.summary_text,
    }


@router.get("")
def list_incidents(
    db: Session = Depends(get_db),
    status: str | None = None,
    priority: str | None = None,
    limit: int = Query(200, ge=1, le=1000),
) -> list[dict]:
    from app.security.context import session_scope
    scope = session_scope()
    stmt = select(Incident).order_by(Incident.start_time.desc(), Incident.id.desc())
    if scope.role == "responder":
        from app.models.operations import ResponseEpisode
        stmt = stmt.join(ResponseEpisode, ResponseEpisode.incident_id == Incident.id).where(
            ResponseEpisode.owner == scope.actor, ResponseEpisode.state != "resolved").distinct()
    if status:
        stmt = stmt.where(Incident.status == status)
    if priority:
        stmt = stmt.where(Incident.priority == priority)
    incidents = db.execute(stmt.limit(limit)).scalars().all()
    return [_summary(db, inc) for inc in incidents]


def _get_incident_or_404(db: Session, incident_id: int) -> Incident:
    inc = db.get(Incident, incident_id)
    if inc is None:
        raise HTTPException(status_code=404, detail="incident not found")
    scope = db.info["scope"]
    if scope.role == "responder":
        from app.models.operations import ResponseEpisode
        assigned = db.scalar(select(ResponseEpisode.id).where(ResponseEpisode.incident_id == incident_id,
            ResponseEpisode.owner == scope.actor, ResponseEpisode.state != "resolved").limit(1))
        if not assigned:
            raise HTTPException(status_code=404, detail="incident not found")
    return inc


@router.get("/{incident_id}")
def incident_detail(incident_id: int, db: Session = Depends(get_db)) -> dict:
    """Full incident view: summary + tracks/events + explanation/evidence."""
    inc = _get_incident_or_404(db, incident_id)
    nodes = db.execute(
        select(IncidentNode).where(IncidentNode.incident_id == incident_id)
    ).scalars().all()

    tracks = [n.ref_id for n in nodes if n.node_type == "track"]
    events = [{"event_id": n.ref_id, **{k: v for k, v in (n.attributes or {}).items()
                if k != "evidence_ref"}}
        for n in nodes if n.node_type == "event"]
    events.sort(key=lambda e: (e.get("ts") is None, e.get("ts")))

    detail = _summary(db, inc)
    detail.update({
        "state": inc.status or "open",
        "allowed_actions": allowed_actions(inc.status or "open"),
        "tracks": tracks,
        "events": events,
        "explanation": build_explanation(db, incident_id),
    })
    if detail["pilot_task_id"]:
        detail["allowed_actions"] = []
        from app.models.entities import Event, IncidentEvent
        detail["events"] = [{"event_id": event.id, "camera_id": event.camera_id,
            "event_type": event.event_type, "label": event.label, "ts": event.ts}
            for event in db.scalars(select(Event).join(IncidentEvent,
                IncidentEvent.event_id == Event.id).where(IncidentEvent.incident_id == incident_id).order_by(Event.ts))]
    from app.models.case_studies import CaseObservation
    from app.models.evidence import EvidenceObject

    observation = db.scalar(select(CaseObservation).where(CaseObservation.incident_id == incident_id))
    if observation:
        evidence = db.scalars(select(EvidenceObject).where(EvidenceObject.event_id == observation.id)).all()
        detail["case_study"] = {
            "type": observation.kind,
            "site": observation.site_id,
            "zone": observation.zone,
            "observed_at": observation.observed_at,
            "source": observation.source_type,
            "source_instance": observation.source_instance,
            "source_revision": observation.source_revision,
            "decision": observation.decision,
            "policy_version": observation.policy_version,
            "policy_ids": observation.policy_snapshot.get("matched_policy_ids", []),
            "reason": observation.reason,
            "detector_confidence": observation.signal.get("confidence"),
            "evidence_status": {item.kind: item.status for item in evidence},
            "synthetic": observation.synthetic,
        }
    return detail


@router.get("/{incident_id}/timeline")
def incident_timeline(incident_id: int, db: Session = Depends(get_db)) -> dict:
    """Chronological timeline derived from incident graph membership."""
    _get_incident_or_404(db, incident_id)
    return {"incident_id": incident_id, "timeline": graph_timeline(db, incident_id)}


@router.get("/{incident_id}/graph")
def incident_graph(incident_id: int, db: Session = Depends(get_db)) -> dict:
    """The incident graph: heterogeneous nodes + typed edges with evidence."""
    _get_incident_or_404(db, incident_id)
    g = graph_as_dict(db, incident_id)
    return {"incident_id": incident_id, **g}


@router.get("/{incident_id}/explanation")
def incident_explanation(incident_id: int, db: Session = Depends(get_db)) -> dict:
    """Machine-readable explanation object (why the incident was created)."""
    _get_incident_or_404(db, incident_id)
    return build_explanation(db, incident_id)


# --------------------------------------------------------------------------
# Lifecycle (human-in-the-loop review state)
# --------------------------------------------------------------------------

class TransitionIn(BaseModel):
    action: str  # start_triage | confirm | dismiss | reopen
    reviewer: str | None = None  # operator handle/role only, no PII
    note: str | None = None
    expected_version: int | None = None
    idempotency_key: str | None = None


@router.get("/{incident_id}/state")
def incident_state(incident_id: int, db: Session = Depends(get_db)) -> dict:
    """Current lifecycle state + the actions available from it."""
    inc = _get_incident_or_404(db, incident_id)
    state = inc.status or "open"
    return {
        "incident_id": incident_id,
        "state": state,
        "allowed_actions": allowed_actions(state),
    }


@router.post("/{incident_id}/state")
def change_incident_state(
    incident_id: int, body: TransitionIn, db: Session = Depends(get_db)
) -> dict:
    """Apply a lifecycle transition. Invalid transitions return 409.

    Non-destructive: only the incident status changes and a history row is
    appended — the incident graph, nodes, edges, and evidence are not mutated.
    """
    inc = _get_incident_or_404(db, incident_id)
    from app.security.auth import require_role, REVIEW_ROLES
    from app.config import get_settings
    scope = require_role(db, REVIEW_ROLES)
    if get_settings().environment == "production" and (body.expected_version is None or not body.idempotency_key):
        raise HTTPException(422, "expected_version and idempotency_key are required")
    from app.processing.jobs import digest
    from app.models.operations import IncidentAction
    import time
    import uuid
    data = body.model_dump(exclude={"reviewer", "idempotency_key"})
    key = digest([scope.tenant, scope.site, scope.actor, incident_id, "review", body.idempotency_key or uuid.uuid4().hex])
    prior = db.get(IncidentAction, key)
    if prior:
        if prior.request_digest != digest(data):
            raise HTTPException(409, "idempotency key reused with different input")
        return prior.result
    try:
        t = apply_transition(db, inc, body.action, reviewer=scope.actor, note=body.note,
                             expected_version=body.expected_version, commit=False)
    except InvalidTransition as e:
        raise HTTPException(status_code=409, detail=str(e))
    result = {
        "incident_id": incident_id,
        "from_state": t.from_state,
        "state": t.to_state,
        "action": t.action,
        "allowed_actions": allowed_actions(t.to_state),
    }
    db.add(IncidentAction(id=key, incident_id=inc.id, actor=scope.actor, action="review:" + body.action,
        at=time.time(), request_digest=digest(data), detail=data, result=result))
    db.commit()
    return result


@router.get("/{incident_id}/state/history")
def incident_state_history(incident_id: int, db: Session = Depends(get_db)) -> dict:
    """Ordered lifecycle transition history for an incident."""
    _get_incident_or_404(db, incident_id)
    return {
        "incident_id": incident_id,
        "history": transition_history(db, incident_id),
    }
