import time
import uuid
from fastapi import HTTPException
from sqlalchemy import select, update
from app.config import get_settings
from app.models.entities import Incident
from app.models.operations import ResponseEpisode, IncidentAction, IncidentAssignment, SLAPolicy, SOPStep, Shift, SecurityPost
from app.models.security import Principal, PrincipalScope
from app.processing.jobs import digest, enqueue
from app.security.auth import require_role


def latest_episode(db, incident_id):
    return db.scalar(select(ResponseEpisode).where(ResponseEpisode.incident_id == incident_id)
                     .order_by(ResponseEpisode.created_at.desc(), ResponseEpisode.id.desc()).limit(1))


def response_view(db, inc):
    ep = latest_episode(db, inc.id)
    return {"incident_id": inc.id, "version": inc.version, "review_state": inc.status,
        "response_state": ep.state if ep else "unassigned", "owner": ep.owner if ep else None,
        "episode_id": ep.id if ep else None, "post_id": ep.post_id if ep else None,
        "shift_id": ep.shift_id if ep else None, "policy": ep.policy_snapshot if ep else None,
        "steps_done": ep.steps_done if ep else [], "acknowledged_at": ep.acknowledged_at if ep else None,
        "responded_at": ep.responded_at if ep else None, "resolved_at": ep.resolved_at if ep else None}


def assert_assignee(db, subject):
    scope = db.info["scope"]
    if get_settings().auth_mode == "development" and subject == scope.actor:
        return
    principal = db.get(Principal, subject)
    grant = db.scalar(select(PrincipalScope).where(PrincipalScope.subject == subject,
        PrincipalScope.tenant_id == scope.tenant, PrincipalScope.site_id == scope.site,
        PrincipalScope.role.in_(["operator", "supervisor", "responder"])))
    if not principal or not principal.enabled or not grant:
        raise HTTPException(422, "assignee has no active responder grant at this site")


def apply_action(db, incident_id, body):
    scope = require_role(db, {"supervisor", "operator", "responder"})
    inc = db.get(Incident, incident_id)
    if not inc:
        raise HTTPException(404, "incident not found")
    from app.models.pilot import PilotCase
    if db.scalar(select(PilotCase.id).where(PilotCase.incident_id == incident_id)):
        raise HTTPException(409, "use the guard desk actions for this pilot task")
    data = body.model_dump()
    fingerprint = digest(data)
    identifier = digest([scope.tenant, scope.site, scope.actor, incident_id, body.idempotency_key])
    prior = db.get(IncidentAction, identifier)
    if prior:
        if prior.request_digest != fingerprint:
            raise HTTPException(409, "idempotency key reused with different input")
        return prior.result
    if inc.version != body.expected_version:
        raise HTTPException(409, "stale incident version; refresh before retry")
    ep = latest_episode(db, inc.id)
    now = time.time()
    action = body.action
    if action in {"assign", "handover", "reassign", "reopen_response"}:
        require_role(db, {"supervisor", "operator"})
        if action in {"handover", "reassign", "reopen_response"} and len(body.reason.strip()) < 3:
            raise HTTPException(422, "handover/reassignment/reopen requires a reason")
        if ep and ep.state == "resolved" and action != "reopen_response":
            raise HTTPException(409, "create a new response episode to reopen")
        if action == "reopen_response":
            if not ep or ep.state != "resolved":
                raise HTTPException(409, "only a resolved response may reopen")
            ep = None
        subject = body.assignee or scope.actor
        assert_assignee(db, subject)
        if body.post_id and not db.get(SecurityPost, body.post_id):
            raise HTTPException(422, "post not found in site")
        if body.shift_id:
            shift = db.get(Shift, body.shift_id)
            if not shift or shift.cancelled_at is not None or shift.subject != subject or shift.post_id != body.post_id or not shift.starts_at <= now < shift.ends_at:
                raise HTTPException(422, "shift does not cover assignee/post/current time")
        if ep is None:
            policy = db.scalar(select(SLAPolicy).order_by(SLAPolicy.created_at.desc()).limit(1))
            if not policy or (get_settings().environment == "production" and not policy.approved_for_use):
                raise HTTPException(409, "configure an approved response policy first")
            steps = db.scalars(select(SOPStep).where(SOPStep.sop_id == policy.sop_id).order_by(SOPStep.ordinal)).all()
            incident_clock = inc.start_time or inc.created_at.timestamp()
            ep = ResponseEpisode(id=uuid.uuid4().hex, incident_id=inc.id, state="unassigned", owner=None,
                policy_id=policy.id, created_at=incident_clock, steps_done=[],
                policy_snapshot={**policy.definition, "id": policy.id, "version": policy.version,
                    "approved_for_use": policy.approved_for_use,
                    "steps": [{"id": s.id, "instruction": s.instruction, "required": s.required} for s in steps]})
            db.add(ep)
        previous = ep.owner
        ep.owner = subject
        ep.post_id, ep.shift_id = body.post_id, body.shift_id
        if ep.state == "unassigned":
            ep.state = "assigned"
        # Handover preserves original deadlines and acknowledgement timestamps.
        db.add(IncidentAssignment(id=uuid.uuid4().hex, incident_id=inc.id, episode_id=ep.id,
            actor=scope.actor, previous_owner=previous, owner=subject, reason=body.reason, at=now))
    else:
        if ep is None:
            raise HTTPException(409, "assign the incident first")
        if scope.actor != ep.owner and scope.role != "supervisor":
            raise HTTPException(403, "only assigned responder or supervisor may act")
        if action == "acknowledge" and ep.state == "assigned":
            ep.state, ep.acknowledged_at = "acknowledged", now
        elif action == "respond" and ep.state == "acknowledged":
            if len(body.reason.strip()) < 3:
                raise HTTPException(422, "response observation required")
            ep.state, ep.responded_at = "responding", now
        elif action == "complete_step" and ep.state in {"acknowledged", "responding"}:
            steps = ep.policy_snapshot["steps"]
            step = next((s for s in steps if s["id"] == body.step_id), None)
            if not step:
                raise HTTPException(422, "step does not belong to this SOP version")
            for prior_step in steps[:steps.index(step)]:
                if prior_step["required"] and prior_step["id"] not in ep.steps_done:
                    raise HTTPException(409, "complete preceding required SOP step first")
            ep.steps_done = list(dict.fromkeys([*ep.steps_done, body.step_id]))
        elif action in {"resolve", "override_resolve"} and ep.state == "responding":
            require_role(db, {"supervisor"})
            missing = [s for s in ep.policy_snapshot["steps"] if s["required"] and s["id"] not in ep.steps_done]
            if missing and action != "override_resolve":
                raise HTTPException(409, "required SOP steps remain")
            if len(body.reason.strip()) < 3:
                raise HTTPException(422, "resolution or override reason required")
            ep.state, ep.resolved_at = "resolved", now
        else:
            raise HTTPException(409, "invalid response transition")
    # Optimistic CAS protects all episode/assignment/action changes in this transaction.
    changed = db.execute(update(Incident).where(Incident.id == inc.id, Incident.version == body.expected_version)
                         .values(version=body.expected_version + 1))
    if changed.rowcount != 1:
        db.rollback()
        raise HTTPException(409, "another operator changed this incident")
    db.flush()
    result = response_view(db, inc)
    db.add(IncidentAction(id=identifier, incident_id=inc.id, episode_id=ep.id, actor=scope.actor,
        action=action, at=now, request_digest=fingerprint, detail=data, result=result))
    enqueue(db, "sla", identifier, {"episode_id": ep.id})
    db.commit()
    return result
