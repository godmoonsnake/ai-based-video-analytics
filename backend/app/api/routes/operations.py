import time
import csv
import io
import json
import hashlib
import uuid
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from app.db.session import get_db
from app.config import get_settings
from app.models.entities import Incident, AuditLog, IncidentNode
from app.models.operations import (
    SOP,
    SOPStep,
    SLAPolicy,
    IncidentAction,
    ResponseEpisode,
    SecurityPost,
    Shift,
    SLAEscalation,
    SLANotification,
    IncidentExport,
    CameraHealthCurrent,
)
from app.models.security import Principal, PrincipalScope
from app.operations.service import (
    apply_action,
    latest_episode,
    response_view,
    assert_assignee,
)
from app.security.auth import require_role, MEDIA_ROLES
from app.processing.jobs import digest, enqueue
from app.operations.notifications import acknowledge
from app.evidence.storage import ObjectStore
from app.evidence.policy import held
from app.models.evidence import EvidenceObject, IncidentEvidence
from app.models.processing import ProcessingJob, SourceLease

router = APIRouter(prefix="/api/v1", tags=["response"])


def _redact(value):
    if isinstance(value, dict):
        return {
            k: _redact(v)
            for k, v in value.items()
            if not any(
                token in k.lower()
                for token in (
                    "raw",
                    "url",
                    "secret",
                    "password",
                    "authorization",
                    "object_key",
                    "path",
                )
            )
        }
    if isinstance(value, list):
        return [_redact(v) for v in value]
    if isinstance(value, str) and (
        value.startswith("http://") or value.startswith("https://")
    ):
        return "[redacted source URL]"
    return value


class ExportIn(BaseModel):
    format: Literal["pdf", "zip"]
    expected_version: int = Field(ge=1)
    idempotency_key: str = Field(min_length=8, max_length=128)


@router.get("/operations/overview")
def operations_overview(db=Depends(get_db)):
    scope = require_role(db, MEDIA_ROLES)
    now = time.time()
    incidents = db.scalars(
        select(Incident).where(Incident.status.in_(["open", "triage"]))
    ).all()
    episodes = db.scalars(
        select(ResponseEpisode).where(ResponseEpisode.state != "resolved")
    ).all()
    active_ids = {ep.incident_id for ep in episodes}
    breaches = db.scalars(
        select(SLAEscalation).where(SLAEscalation.status == "open")
    ).all()
    pending_evidence = (
        db.scalar(
            select(func.count())
            .select_from(EvidenceObject)
            .where(EvidenceObject.status.in_(["requested", "pending"]))
        )
        or 0
    )
    leases = db.scalars(select(SourceLease)).all()
    camera_health = db.scalars(select(CameraHealthCurrent)).all()
    pending_jobs = (
        db.scalar(
            select(func.count())
            .select_from(ProcessingJob)
            .where(ProcessingJob.status.in_(["pending", "running"]))
        )
        or 0
    )
    return {
        "tenant_id": scope.tenant,
        "site_id": scope.site,
        "demo_mode": get_settings().environment != "production" and not get_settings().pilot_mode,
        "active_incidents": len(incidents),
        "unassigned_incidents": sum(1 for i in incidents if i.id not in active_ids),
        "oldest_age_minutes": round(
            max((now - (i.start_time or i.created_at.timestamp())) for i in incidents)
            / 60,
            1,
        )
        if incidents
        else 0,
        "open_sla_breaches": len(breaches),
        "pending_evidence": pending_evidence,
        "source_stale": sum(
            1 for item in leases if not item.last_seen or now - item.last_seen > 60
        ),
        "source_count": len(leases),
        "camera_offline": sum(
            1 for item in camera_health if item.stream_state == "offline"
        ),
        "camera_degraded": sum(
            1 for item in camera_health if item.video_state == "degraded"
        ),
        "recording_gaps": sum(
            1 for item in camera_health if item.recording_state == "degraded"
        ),
        "evidence_degraded": sum(
            1 for item in camera_health if item.evidence_state == "degraded"
        ),
        "pending_work": pending_jobs,
        "checked_at": now,
    }


class ActionIn(BaseModel):
    action: Literal[
        "assign",
        "acknowledge",
        "respond",
        "complete_step",
        "resolve",
        "override_resolve",
        "handover",
        "reassign",
        "reopen_response",
    ]
    expected_version: int = Field(ge=1)
    idempotency_key: str = Field(min_length=8, max_length=128)
    assignee: str | None = None
    post_id: str | None = None
    shift_id: str | None = None
    step_id: str | None = None
    reason: str = Field(default="", max_length=2000)


@router.post("/incidents/{incident_id}/assignments")
def assign(incident_id: int, body: ActionIn, db=Depends(get_db)):
    if body.action not in {"assign", "reassign", "handover"}:
        raise HTTPException(422, "assignment action required")
    return apply_action(db, incident_id, body)


@router.post("/incidents/{incident_id}/actions")
@router.post("/operations/incidents/{incident_id}/actions")
def action(incident_id: int, body: ActionIn, db=Depends(get_db)):
    return apply_action(db, incident_id, body)


@router.get("/incidents/{incident_id}/actions")
def actions(incident_id: int, db=Depends(get_db)):
    require_role(db, MEDIA_ROLES - {"responder", "client_viewer"})
    if not db.get(Incident, incident_id):
        raise HTTPException(404, "incident not found")
    return [
        {
            "id": a.id,
            "action": a.action,
            "actor": a.actor,
            "at": a.at,
            "detail": a.detail,
            "result": a.result,
        }
        for a in db.scalars(
            select(IncidentAction)
            .where(IncidentAction.incident_id == incident_id)
            .order_by(IncidentAction.at, IncidentAction.id)
        )
    ]


@router.get("/incidents/{incident_id}/response")
def response(incident_id: int, db=Depends(get_db)):
    scope = require_role(db, MEDIA_ROLES - {"client_viewer"})
    inc = db.get(Incident, incident_id)
    if not inc:
        raise HTTPException(404, "incident not found")
    if scope.role == "responder":
        ep = latest_episode(db, incident_id)
        if not ep or ep.owner != scope.actor or ep.state == "resolved":
            raise HTTPException(404, "incident not assigned")
    return response_view(db, inc)


@router.get("/incidents/{incident_id}/sla")
def sla_status(incident_id: int, db=Depends(get_db)):
    require_role(db, MEDIA_ROLES - {"responder", "client_viewer"})
    if not db.get(Incident, incident_id):
        raise HTTPException(404, "incident not found")
    return [
        {
            "stage": x.stage,
            "deadline_at": x.deadline_at,
            "recorded_at": x.recorded_at,
            "owner_at_deadline": x.owner_at_deadline,
            "status": x.status,
            "notifications": [
                {
                    "id": n.id,
                    "provider": n.provider,
                    "status": n.status,
                    "attempted_at": n.attempted_at,
                    "accepted_at": n.accepted_at,
                    "acknowledged_at": n.acknowledged_at,
                    "retry_count": n.retry_count,
                    "failure_class": n.failure_class,
                }
                for n in db.scalars(
                    select(SLANotification).where(SLANotification.escalation_id == x.id)
                )
            ],
        }
        for x in db.scalars(
            select(SLAEscalation)
            .where(SLAEscalation.incident_id == incident_id)
            .order_by(SLAEscalation.deadline_at, SLAEscalation.stage)
        )
    ]


@router.post("/incidents/{incident_id}/exports", status_code=202)
def create_export(incident_id: int, body: ExportIn, db=Depends(get_db)):
    scope = require_role(db, MEDIA_ROLES - {"responder"})
    inc = db.get(Incident, incident_id)
    if not inc:
        raise HTTPException(404, "incident not found")
    if inc.version != body.expected_version:
        raise HTTPException(409, "case version changed; refresh before exporting")
    key = digest(
        [scope.tenant, scope.site, scope.actor, incident_id, body.idempotency_key]
    )
    prior = db.scalar(
        select(IncidentExport).where(IncidentExport.idempotency_key == key)
    )
    if prior:
        if prior.case_version != body.expected_version or prior.format != body.format:
            raise HTTPException(
                409, "export idempotency key reused with different input"
            )
        return {
            "id": prior.id,
            "status": prior.status,
            "case_version": prior.case_version,
        }
    from app.api.routes.v1_incidents import _summary
    from app.pipeline.incident_graph import (
        build_explanation,
        graph_as_dict,
        graph_timeline,
    )
    from app.models.security import Site, Tenant
    from app.models.entities import GlobalTrack, IncidentNode
    from app.models.lineage import CorrelationRun, CorrelationHypothesis

    now = time.time()
    summary = _summary(db, inc)
    from app.models.case_studies import CaseObservation
    observation = db.scalar(select(CaseObservation).where(CaseObservation.incident_id == inc.id))
    summary["category"] = observation.kind if observation else "security observation"
    actions = db.scalars(
        select(IncidentAction)
        .where(IncidentAction.incident_id == inc.id)
        .order_by(IncidentAction.at, IncidentAction.id)
    ).all()
    response_data = response_view(db, inc)
    sla = []
    for breach in db.scalars(
        select(SLAEscalation).where(SLAEscalation.incident_id == inc.id)
    ):
        sla.append(
            {
                "stage": breach.stage,
                "deadline_at": breach.deadline_at,
                "recorded_at": breach.recorded_at,
                "status": breach.status,
                "notifications": [
                    {
                        "provider": n.provider,
                        "status": n.status,
                        "attempted_at": n.attempted_at,
                        "accepted_at": n.accepted_at,
                        "acknowledged_at": n.acknowledged_at,
                        "retry_count": n.retry_count,
                        "failure_class": n.failure_class,
                    }
                    for n in db.scalars(
                        select(SLANotification).where(
                            SLANotification.escalation_id == breach.id
                        )
                    )
                ],
            }
        )
    evidence_rows = db.scalars(
        select(EvidenceObject)
        .join(IncidentEvidence, IncidentEvidence.evidence_id == EvidenceObject.id)
        .where(IncidentEvidence.incident_id == inc.id)
    ).all()
    evidence = [
        {
            "id": item.id,
            "kind": item.kind,
            "status": item.status
            if item.expires_at > now or held(db, item.id)
            else "expired",
            "sha256": item.sha256,
            "mime": item.mime,
            "size": item.size,
            "object_key": item.object_key
            if item.expires_at > now or held(db, item.id)
            else None,
            "manifest": _redact(item.manifest or {}),
        }
        for item in evidence_rows
    ]
    site = db.get(Site, (scope.tenant, scope.site))
    tenant = db.get(Tenant, scope.tenant)
    summary["tenant_label"] = tenant.name if tenant else scope.tenant
    summary["site_label"] = site.name if site else scope.site
    track_ids = [
        int(node.ref_id)
        for node in db.scalars(
            select(IncidentNode).where(
                IncidentNode.incident_id == inc.id, IncidentNode.node_type == "track"
            )
        )
        if node.ref_id.isdigit()
    ]
    run_ids = (
        sorted(
            {
                track.run_id
                for track in db.scalars(
                    select(GlobalTrack).where(GlobalTrack.id.in_(track_ids))
                )
                if track.run_id
            }
        )
        if track_ids
        else []
    )
    runs = (
        db.scalars(select(CorrelationRun).where(CorrelationRun.id.in_(run_ids))).all()
        if run_ids
        else []
    )
    correlation_runs = [
        {
            "run_id": run.id,
            "policy_version": run.policy_version,
            "model_version": run.model_version,
        }
        for run in runs
    ]
    hypotheses = (
        db.scalars(
            select(CorrelationHypothesis).where(
                CorrelationHypothesis.run_id.in_(run_ids)
            )
        ).all()
        if run_ids
        else []
    )
    explanation = build_explanation(db, inc.id)
    case = {
        "case_version": inc.version,
        "incident": summary,
        "case_study": {
            "source_type": observation.source_type,
            "source_instance": observation.source_instance,
            "source_revision": observation.source_revision,
            "decision": observation.decision,
            "reason": observation.reason,
            "zone": observation.zone,
            "policy_version": observation.policy_version,
            "policy_ids": observation.policy_snapshot.get("matched_policy_ids", []),
            "synthetic": observation.synthetic,
        } if observation else None,
        "timezone": site.timezone if site else "UTC",
        "explanation": explanation,
        "behaviour_signals": explanation.get("behaviour_signals", []),
        "graph": graph_as_dict(db, inc.id),
        "timeline": graph_timeline(db, inc.id),
        "actions": [
            {
                "actor": a.actor,
                "action": a.action,
                "at": a.at,
                "detail": _redact(a.detail or {}),
                "result": _redact(a.result or {}),
            }
            for a in actions
        ],
        "response": response_data,
        "sla": sla,
        "review_state": inc.status,
        "correlation_runs": correlation_runs,
        "correlation_hypotheses": [
            {
                "from": item.from_key,
                "to": item.to_key,
                "signals": item.signals,
                "score": item.score,
                "disposition": item.disposition,
            }
            for item in hypotheses
        ],
        "model_version": correlation_runs,
    }
    snapshot = _redact(
        {
            "case": case,
            "evidence": evidence,
            "generated_by": scope.actor,
            "generated_at": now,
            "case_version": inc.version,
        }
    )
    # Keep storage keys only in the private database job snapshot. They are
    # omitted from the exported manifest, report and all API responses.
    for evidence_snapshot, original in zip(snapshot["evidence"], evidence):
        evidence_snapshot["object_key"] = original["object_key"]
    export_id = digest(
        [
            scope.tenant,
            scope.site,
            scope.actor,
            incident_id,
            body.idempotency_key,
            body.format,
        ]
    )
    row = IncidentExport(
        id=export_id,
        incident_id=inc.id,
        case_version=inc.version,
        format=body.format,
        requested_by=scope.actor,
        idempotency_key=key,
        snapshot=snapshot,
        status="queued",
        requested_at=now,
        expires_at=now + 86400,
    )
    db.add(row)
    db.flush()
    snapshot["export_id"] = row.id
    row.snapshot = snapshot
    enqueue(db, "export", row.id, {"export_id": row.id})
    db.add(
        AuditLog(
            actor=scope.actor,
            action=f"case_export_requested:{body.format}",
            target=f"incident:{inc.id}:v{inc.version}",
        )
    )
    db.commit()
    return {"id": row.id, "status": row.status, "case_version": row.case_version}


def _authorized_export(db, export_id):
    scope = require_role(db, MEDIA_ROLES - {"responder"})
    row = db.get(IncidentExport, export_id)
    if not row or (
        row.requested_by != scope.actor and scope.role not in {"supervisor", "auditor"}
    ):
        raise HTTPException(404, "export not found")
    return scope, row


@router.get("/exports/{export_id}")
def export_status(export_id: str, db=Depends(get_db)):
    _, row = _authorized_export(db, export_id)
    return {
        "id": row.id,
        "status": row.status,
        "format": row.format,
        "case_version": row.case_version,
        "expires_at": row.expires_at,
        "download_url": f"/api/v1/exports/{row.id}/download"
        if row.status == "ready"
        else None,
        "failure_class": row.failure_class,
    }


@router.get("/exports/{export_id}/download")
def download_export(export_id: str, db=Depends(get_db)):
    scope, row = _authorized_export(db, export_id)
    if row.status != "ready" or row.expires_at <= time.time():
        raise HTTPException(410, "export is not ready or has expired")
    try:
        content = ObjectStore().read(scope, row.object_key)
    except Exception:
        raise HTTPException(409, "export object unavailable") from None
    if hashlib.sha256(content).hexdigest() != row.sha256:
        row.status = "integrity-failed"
        db.add(
            AuditLog(
                actor=scope.actor, action="export_integrity_failure", target=row.id
            )
        )
        db.commit()
        raise HTTPException(409, "export integrity check failed")
    db.add(
        AuditLog(
            actor=scope.actor,
            action="case_export_downloaded",
            target=f"{row.id}:v{row.case_version}",
        )
    )
    db.commit()
    ext, mime = (
        ("pdf", "application/pdf")
        if row.format == "pdf"
        else ("zip", "application/zip")
    )
    return Response(
        content,
        media_type=mime,
        headers={
            "Cache-Control": "no-store",
            "Content-Disposition": f'attachment; filename="darson-case-{row.incident_id}-v{row.case_version}.{ext}"',
        },
    )


@router.post("/notifications/{notification_id}/acknowledge")
def acknowledge_notification(notification_id: str, db=Depends(get_db)):
    require_role(db, {"supervisor", "operator", "responder"})
    return acknowledge(db, notification_id)


@router.get("/incidents/{incident_id}/export")
def export_case(
    incident_id: int, format: Literal["json", "csv"] = "json", db=Depends(get_db)
):
    scope = require_role(db, MEDIA_ROLES - {"responder", "client_viewer"})
    incident = db.get(Incident, incident_id)
    if not incident:
        raise HTTPException(404, "incident not found")
    from app.api.routes.v1_incidents import _summary
    from app.pipeline.incident_graph import (
        build_explanation,
        graph_as_dict,
        graph_timeline,
    )

    nodes = db.scalars(
        select(IncidentNode).where(IncidentNode.incident_id == incident_id)
    ).all()
    events = [
        {"event_id": n.ref_id, **(n.attributes or {})}
        for n in nodes
        if n.node_type == "event"
    ]
    events.sort(key=lambda e: (e.get("ts") is None, e.get("ts")))
    bundle = {
        "schema_version": 1,
        "incident": _summary(db, incident),
        "events": events,
        "timeline": graph_timeline(db, incident_id),
        "graph": graph_as_dict(db, incident_id),
        "explanation": build_explanation(db, incident_id),
        "exported_at": time.time(),
    }
    db.add(
        AuditLog(
            actor=scope.actor,
            action=f"case_export:{format}",
            target=f"incident:{incident_id}",
        )
    )
    db.commit()
    if format == "json":
        return Response(
            json.dumps(bundle, ensure_ascii=False, default=str),
            media_type="application/json",
            headers={
                "Content-Disposition": f'attachment; filename="darson-case-{incident_id}.json"',
                "Cache-Control": "no-store",
            },
        )
    out = io.StringIO(newline="")
    writer = csv.writer(out)
    writer.writerow(["record_type", "incident_id", "timestamp", "event_id", "details"])

    def safe_cell(value):
        text_value = "" if value is None else str(value)
        return (
            "'" + text_value
            if text_value.lstrip("\t\r\n ").startswith(("=", "+", "-", "@"))
            else text_value
        )

    for event in events:
        details = json.dumps(event, ensure_ascii=False, default=str)
        writer.writerow(
            [
                safe_cell("event"),
                safe_cell(incident_id),
                safe_cell(event.get("ts")),
                safe_cell(event.get("event_id")),
                safe_cell(details),
            ]
        )
    return Response(
        "\ufeff" + out.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="darson-case-{incident_id}.csv"',
            "Cache-Control": "no-store",
        },
    )


@router.get("/operations/tasks")
def tasks(db=Depends(get_db)):
    scope = require_role(db, {"operator", "supervisor", "responder"})
    rows = db.scalars(
        select(Incident)
        .join(ResponseEpisode)
        .where(
            ResponseEpisode.owner == scope.actor, ResponseEpisode.state != "resolved"
        )
        .distinct()
    ).all()
    return [
        {
            **response_view(db, i),
            "location": {"site": i.site_id},
            "priority": i.priority,
            "instruction": "Follow the approved site SOP; use the manual/radio fallback if unavailable.",
        }
        for i in rows
        if latest_episode(db, i.id).owner == scope.actor
    ]


class PolicyIn(BaseModel):
    name: str = Field(min_length=3, max_length=100)
    version: int = Field(ge=1)
    timezone: str = "Asia/Kolkata"
    calendar: Literal["24x7"] = "24x7"
    acknowledgement_seconds: int = Field(ge=1, le=86400)
    response_seconds: int = Field(ge=1, le=86400)
    resolution_seconds: int = Field(ge=1, le=604800)
    steps: list[str] = Field(min_length=1, max_length=30)
    approved_for_use: bool = False


@router.post("/config/response-policy")
def create_policy(body: PolicyIn, db=Depends(get_db)):
    scope = require_role(db, {"supervisor", "configuration_admin"})
    try:
        ZoneInfo(body.timezone)
    except ZoneInfoNotFoundError:
        raise HTTPException(422, "unknown timezone") from None
    if any(not step.strip() or len(step) > 1000 for step in body.steps):
        raise HTTPException(422, "each SOP step must contain 1–1000 characters")
    identifier = digest([scope.tenant, scope.site, body.name, body.version])
    if db.get(SLAPolicy, identifier):
        raise HTTPException(409, "policy versions are immutable; create a new version")
    db.add(SOP(id=identifier, name=body.name, version=body.version))
    db.flush()
    for index, instruction in enumerate(body.steps):
        db.add(
            SOPStep(
                id=f"{identifier}:{index}",
                sop_id=identifier,
                ordinal=index,
                instruction=instruction,
                required=True,
            )
        )
    db.add(
        SLAPolicy(
            id=identifier,
            sop_id=identifier,
            name=body.name,
            version=body.version,
            created_at=time.time(),
            approved_for_use=body.approved_for_use,
            definition={
                **body.model_dump(exclude={"steps"}),
                "clock_start": "incident_created",
                "response_definition": "responder reports response started",
                "pause_policy": "no_pauses",
            },
        )
    )
    db.add(
        AuditLog(actor=scope.actor, action="response_policy_created", target=identifier)
    )
    db.commit()
    return {
        "id": identifier,
        "version": body.version,
        "approved_for_use": body.approved_for_use,
    }


class PostIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    instructions: str = Field(min_length=1, max_length=2000)
    floor: str | None = Field(default=None, max_length=80)
    block: str | None = Field(default=None, max_length=80)


@router.get("/config/posts")
def list_posts(db=Depends(get_db)):
    require_role(db, {"supervisor", "operator", "configuration_admin"})
    return [{"id": row.id, "name": row.name, "instructions": row.instructions,
             "floor": row.floor, "block": row.block}
            for row in db.scalars(select(SecurityPost).order_by(SecurityPost.name))]


@router.get("/config/guards")
def list_guards(db=Depends(get_db)):
    scope = require_role(db, {"supervisor", "operator", "configuration_admin"})
    grants = db.scalars(select(PrincipalScope).where(
        PrincipalScope.tenant_id == scope.tenant,
        PrincipalScope.site_id == scope.site,
        PrincipalScope.role == "responder",
    ).order_by(PrincipalScope.subject)).all()
    return [{"subject": row.subject, "demo": row.subject.startswith("demo-")}
            for row in grants if (principal := db.get(Principal, row.subject)) and principal.enabled]


class DemoGuardIn(BaseModel):
    subject: str = Field(pattern=r"^demo-[a-z0-9-]{3,40}$")


@router.post("/demo/guards")
def create_demo_guard(body: DemoGuardIn, db=Depends(get_db)):
    scope = require_role(db, {"supervisor"})
    if get_settings().environment == "production" or get_settings().auth_mode != "development":
        raise HTTPException(404, "demo guard creation is unavailable")
    if db.get(Principal, body.subject):
        raise HTTPException(409, "demo guard ID already exists")
    db.add(Principal(subject=body.subject, enabled=True, tokens_valid_after=0))
    db.flush()
    db.add(PrincipalScope(subject=body.subject, tenant_id=scope.tenant,
                          site_id=scope.site, role="responder"))
    db.add(AuditLog(actor=scope.actor, action="demo_guard_created", target=body.subject))
    db.commit()
    return {"subject": body.subject, "demo": True}


@router.post("/config/posts")
def create_post(body: PostIn, db=Depends(get_db)):
    scope = require_role(db, {"supervisor", "configuration_admin"})
    identifier = digest([scope.tenant, scope.site, body.name])
    if db.get(SecurityPost, identifier):
        raise HTTPException(409, "post already exists")
    db.add(SecurityPost(id=identifier, **body.model_dump()))
    db.add(AuditLog(actor=scope.actor, action="security_post_created", target=identifier))
    db.commit()
    return {"id": identifier}


class ShiftIn(BaseModel):
    post_id: str
    subject: str
    starts_at: float = Field(allow_inf_nan=False)
    ends_at: float = Field(allow_inf_nan=False)
    label: Literal["day", "night", "custom"] = "custom"


@router.get("/config/shifts")
def list_shifts(db=Depends(get_db)):
    require_role(db, {"supervisor", "operator", "configuration_admin"})
    rows = db.scalars(select(Shift).order_by(Shift.starts_at.desc()).limit(300)).all()
    return [{"id": row.id, "post_id": row.post_id, "subject": row.subject,
             "starts_at": row.starts_at, "ends_at": row.ends_at,
             "label": row.label, "cancelled_at": row.cancelled_at}
            for row in rows]


@router.post("/config/shifts")
def create_shift(body: ShiftIn, db=Depends(get_db)):
    scope = require_role(db, {"supervisor", "configuration_admin"})
    assert_assignee(db, body.subject)
    if body.ends_at <= body.starts_at or not db.get(SecurityPost, body.post_id):
        raise HTTPException(422, "invalid shift interval or post")
    overlap = db.scalar(select(Shift.id).where(
        Shift.subject == body.subject, Shift.cancelled_at.is_(None),
        Shift.starts_at < body.ends_at, Shift.ends_at > body.starts_at,
    ).limit(1))
    if overlap:
        raise HTTPException(409, "guard already has an overlapping shift")
    identifier = uuid.uuid4().hex
    db.add(Shift(id=identifier, **body.model_dump()))
    db.add(AuditLog(actor=scope.actor, action="guard_shift_created", target=identifier))
    db.commit()
    return {"id": identifier}


@router.delete("/config/shifts/{identifier}")
def cancel_shift(identifier: str, db=Depends(get_db)):
    scope = require_role(db, {"supervisor", "configuration_admin"})
    row = db.get(Shift, identifier)
    if not row:
        raise HTTPException(404, "shift not found")
    if row.cancelled_at is None:
        row.cancelled_at = time.time()
        db.add(AuditLog(actor=scope.actor, action="guard_shift_cancelled", target=identifier))
        db.commit()
    return {"id": identifier, "cancelled": True}


class ManualIn(BaseModel):
    summary: str = Field(min_length=5, max_length=2000)
    priority: Literal["low", "medium", "high", "critical"]
    reason: str = Field(min_length=3, max_length=1000)
    idempotency_key: str = Field(min_length=8, max_length=128)


@router.post("/incidents/manual")
def manual(body: ManualIn, db=Depends(get_db)):
    scope = require_role(db, {"supervisor", "operator"})
    key = digest(
        [scope.tenant, scope.site, scope.actor, "manual", body.idempotency_key]
    )
    inc = db.scalar(select(Incident).where(Incident.dedup_key == key))
    if inc:
        if inc.summary_text != body.summary or inc.priority != body.priority:
            raise HTTPException(409, "idempotency input conflict")
        return {"incident_id": inc.id}
    inc = Incident(
        status="open",
        summary_text=body.summary,
        priority=body.priority,
        dedup_key=key,
        start_time=time.time(),
        confidence=None,
    )
    db.add(inc)
    db.flush()
    db.add(
        AuditLog(
            actor=scope.actor,
            action="manual_incident:" + body.reason,
            target=f"incident:{inc.id}",
        )
    )
    db.commit()
    return {"incident_id": inc.id}
