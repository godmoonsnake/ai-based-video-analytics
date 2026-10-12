"""Pilot case study policies, observation intake and alert status."""
from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select

from app.db.session import get_db
from app.models.case_studies import CaseAlert, CaseObservation, CasePolicy, CaseSource
from app.models.entities import AuditLog, Event, Incident, IncidentCamera, IncidentEvent
from app.models.evidence import EvidenceObject
from app.processing.jobs import enqueue
from app.pipeline.incident_graph import build_graph
from app.security.auth import require_role
from app.case_studies.service import decide, policy_snapshot
from app.config import get_settings
from app.evidence.capture import attach_evidence, request_capture, store_capture, validate_media
from app.processing.jobs import digest

router = APIRouter(prefix="/api/v1/case-studies", tags=["case-studies"])
MANAGERS = {"supervisor", "configuration_admin"}
OPERATORS = MANAGERS | {"operator"}
POLICY_KINDS = {"material", "material_access", "asset", "asset_transfer",
                "prohibited_activity", "restricted_zone", "area_access", "vehicle"}
OBSERVATION_KINDS = {"restricted_reading", "material_change", "smoking", "drinking",
                     "restricted_entry", "vehicle_plate", "parking_exit", "parking_approach",
                     "parking_interaction", "parking_departure", "parking_authorization"}
EXTERNAL_SOURCES = {"camera_detector", "access_control", "document_access",
                    "asset_custody", "vehicle_anpr"}


class SourceIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_type: Literal["camera_detector", "access_control", "document_access",
                         "asset_custody", "vehicle_anpr"]
    instance: str = Field(min_length=1, max_length=100)
    actor: str = Field(min_length=1, max_length=100)
    enabled: bool = True


class PolicyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=100)
    kind: str
    subject: str = Field(min_length=1, max_length=100)
    zone: str | None = Field(default=None, max_length=100)
    principal: str | None = Field(default=None, max_length=100)
    allowed: bool = True
    valid_from: float | None = None
    valid_until: float | None = None


class ObservationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_event_id: str = Field(min_length=1, max_length=128)
    kind: str
    camera_id: str = Field(min_length=1, max_length=100)
    zone: str = Field(min_length=1, max_length=100)
    observed_at: float = Field(gt=0)
    source_type: Literal["camera_detector", "access_control", "document_access",
                         "asset_custody", "vehicle_anpr", "operator"] = "operator"
    source_instance: str = Field(default="manual", min_length=1, max_length=100)
    source_revision: str = Field(default="1", min_length=1, max_length=100)
    principal_ref: str | None = Field(default=None, max_length=100)
    track_ref: str | None = Field(default=None, max_length=100)
    item_id: str | None = Field(default=None, max_length=100)
    action: str | None = None
    plate: str | None = Field(default=None, max_length=30)
    vehicle_type: Literal["car", "bike"] | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    duration_seconds: float | None = Field(default=None, ge=0, le=3600)
    media_source: Literal["none", "frigate"] = "none"
    has_snapshot: bool = False
    has_clip: bool = False

    @model_validator(mode="after")
    def required_case_fields(self):
        if self.kind == "restricted_reading" and not self.item_id:
            raise ValueError("restricted reading requires item_id")
        if self.kind == "material_change" and (not self.item_id or self.action not in {"removed", "replaced"}):
            raise ValueError("material change requires item_id and removed/replaced action")
        if self.kind == "vehicle_plate" and (not self.plate or not self.vehicle_type):
            raise ValueError("vehicle plate requires plate and car/bike vehicle_type")
        return self


def _id(scope, source_event_id: str) -> str:
    return hashlib.sha256(json.dumps([scope.tenant, scope.site, source_event_id],
                                  separators=(",", ":")).encode()).hexdigest()


def _observation_view(row):
    return {"id": row.id, "kind": row.kind, "camera_id": row.camera_id,
            "zone": row.zone, "observed_at": row.observed_at,
            "source_type": row.source_type, "source_instance": row.source_instance,
            "source_revision": row.source_revision, "policy_version": row.policy_version,
            "policy_ids": row.policy_snapshot.get("matched_policy_ids", []),
            "synthetic": row.synthetic,
            "decision": row.decision, "reason": row.reason,
            "incident_id": row.incident_id}


@router.post("/sources")
def put_source(body: SourceIn, db=Depends(get_db)):
    scope = require_role(db, MANAGERS)
    identifier = _id(scope, f"source:{body.source_type}:{body.instance}")
    row = db.get(CaseSource, identifier)
    if row is None:
        row = CaseSource(id=identifier, source_type=body.source_type,
                         instance=body.instance, actor=body.actor, enabled=body.enabled)
        db.add(row)
    else:
        row.actor, row.enabled = body.actor, body.enabled
    db.add(AuditLog(actor=scope.actor, action="case_source_saved", target=identifier))
    db.commit()
    return {"id": identifier, "source_type": row.source_type,
            "instance": row.instance, "actor": row.actor, "enabled": row.enabled}


@router.get("/sources")
def list_sources(db=Depends(get_db)):
    require_role(db, MANAGERS)
    return [{"id": row.id, "source_type": row.source_type, "instance": row.instance,
             "actor": row.actor, "enabled": row.enabled}
            for row in db.scalars(select(CaseSource).order_by(CaseSource.source_type, CaseSource.instance))]


@router.post("/policies")
def put_policy(body: PolicyIn, db=Depends(get_db)):
    scope = require_role(db, MANAGERS)
    if body.kind not in POLICY_KINDS:
        raise HTTPException(422, "unsupported policy kind")
    if body.valid_from is not None and body.valid_until is not None and body.valid_until < body.valid_from:
        raise HTTPException(422, "invalid validity window")
    if body.kind == "vehicle":
        body.subject = body.subject.upper().replace(" ", "").replace("-", "")
    row = db.get(CasePolicy, body.id)
    if row is None:
        row = CasePolicy(id=body.id, tenant_id=scope.tenant, site_id=scope.site)
        db.add(row)
    for field in ("kind", "subject", "zone", "principal", "allowed", "valid_from", "valid_until"):
        setattr(row, field, getattr(body, field))
    db.add(AuditLog(actor=scope.actor, action="case_policy_saved", target=row.id))
    db.commit()
    return {"id": row.id, "kind": row.kind, "subject": row.subject}


@router.get("/policies")
def list_policies(db=Depends(get_db)):
    require_role(db, OPERATORS)
    return [{"id": p.id, "kind": p.kind, "subject": p.subject, "zone": p.zone,
             "principal": p.principal, "allowed": p.allowed,
             "valid_from": p.valid_from, "valid_until": p.valid_until}
            for p in db.scalars(select(CasePolicy).order_by(CasePolicy.kind, CasePolicy.id))]


@router.post("/observations")
def ingest_observation(body: ObservationIn, db=Depends(get_db)):
    if body.kind.startswith("parking_"):
        raise HTTPException(422, "parking signals require the parking session endpoint")
    return _ingest_observation(body, db)


def _ingest_observation(body: ObservationIn, db, synthetic: bool = False,
                        alert_destinations=None, commit: bool = True):
    scope = require_role(db, OPERATORS)
    if body.kind not in OBSERVATION_KINDS:
        raise HTTPException(422, "unsupported observation kind")
    if not synthetic and body.source_type in EXTERNAL_SOURCES:
        source = db.get(CaseSource, _id(scope, f"source:{body.source_type}:{body.source_instance}"))
        if not source or not source.enabled or source.actor != scope.actor:
            raise HTTPException(403, "source is not registered to this account")
    if body.media_source == "frigate" and (synthetic or body.source_type != "camera_detector"
                                             or body.source_instance != get_settings().source_instance):
        raise HTTPException(422, "Frigate media requires the configured camera source")
    if body.media_source == "none" and (body.has_snapshot or body.has_clip):
        raise HTTPException(422, "media flags require a configured source")
    signal_payload = body.model_dump()
    for optional_field in ("track_ref", "duration_seconds"):
        if signal_payload[optional_field] is None:
            signal_payload.pop(optional_field)
    identifier = _id(scope, body.source_event_id)
    existing = db.get(CaseObservation, identifier)
    if existing:
        if existing.signal != signal_payload:
            raise HTTPException(409, "source event ID already has different content")
        return _observation_view(existing)
    decision, reason, priority = decide(db, body)
    policy = policy_snapshot(db, body)
    received_at = time.time()
    event = Event(id=identifier, source_event_id=body.source_event_id,
                  source_type="frigate" if body.media_source == "frigate" else "case_study",
                  source_instance=body.source_instance, source_revision=body.source_revision,
                  event_kind="observation", received_at=received_at,
                  schema_version=1, payload_digest=digest(signal_payload),
                  camera_id=body.camera_id,
                  track_local_id=body.source_event_id, event_type="case_observation",
                  label=body.kind, confidence=body.confidence,
                  ts=body.observed_at, zones_json=json.dumps([body.zone]),
                  has_snapshot=body.has_snapshot, has_clip=body.has_clip,
                  dedup_key=identifier)
    db.add(event)
    db.flush()
    if body.media_source == "frigate":
        request_capture(db, event)
    incident = None
    if decision == "review":
        incident = Incident(status="open", start_time=body.observed_at,
                            end_time=body.observed_at, priority=priority,
                            summary_text=reason, dedup_key=identifier)
        db.add(incident)
        db.flush()
        db.add(IncidentCamera(incident_id=incident.id, camera_id=body.camera_id))
        db.add(IncidentEvent(incident_id=incident.id, event_id=event.id,
                             role="trigger"))
        db.flush()
        build_graph(db, incident.id, [event], [])
        if body.media_source == "frigate":
            attach_evidence(db, incident.id, [event.id])
    row = CaseObservation(id=identifier, kind=body.kind, camera_id=body.camera_id,
                          zone=body.zone, observed_at=body.observed_at,
                          received_at=received_at, source_type="demo" if synthetic else body.source_type,
                          source_instance=body.source_instance, source_revision=body.source_revision,
                          policy_version=policy["version"], policy_snapshot=policy,
                          synthetic=synthetic,
                          signal=signal_payload,
                          decision=decision, reason=reason,
                          incident_id=incident.id if incident else None)
    db.add(row)
    db.add(AuditLog(actor=scope.actor, action="case_observation_received", target=identifier))
    if incident:
        settings = get_settings()
        destinations = (alert_destinations if alert_destinations is not None else
                        (("telegram", settings.telegram_chat_id),
                         ("whatsapp", settings.whatsapp_recipient))) if not synthetic and settings.environment == "production" else ()
        configured = False
        for channel, destination in destinations:
            if not destination:
                continue
            configured = True
            alert_id = _id(scope, f"alert:{incident.id}:{channel}:{destination}")
            db.add(CaseAlert(id=alert_id, incident_id=incident.id,
                             channel=channel, destination=destination, status="queued"))
            enqueue(db, "case_alert", alert_id, {"alert_id": alert_id})
        if not configured:
            alert_id = _id(scope, f"alert:{incident.id}:local")
            db.add(CaseAlert(id=alert_id, incident_id=incident.id,
                             channel="local", destination="operator_queue", status="queued"))
            enqueue(db, "case_alert", alert_id, {"alert_id": alert_id})
    if commit:
        db.commit()
    else:
        db.flush()
    return _observation_view(row)


@router.put("/observations/{observation_id}/evidence/{kind}")
async def upload_evidence(observation_id: str, kind: Literal["snapshot", "clip"],
                          request: Request, db=Depends(get_db)):
    """Attach bounded detector media to the shared protected evidence vault."""
    require_role(db, {"operator", "supervisor"})
    row = db.get(CaseObservation, observation_id)
    if not row or not row.incident_id:
        raise HTTPException(404, "review incident not found")
    mime = request.headers.get("content-type", "").split(";")[0].lower()
    content = bytearray()
    limit = get_settings().evidence_max_bytes
    async for part in request.stream():
        content.extend(part)
        if len(content) > limit:
            raise HTTPException(413, "evidence exceeds capture limit")
    try:
        validate_media(bytes(content), mime, kind)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    scope = db.info["scope"]
    identifier = digest([scope.tenant, scope.site, observation_id, kind])
    obj = db.get(EvidenceObject, identifier)
    actual_hash = hashlib.sha256(content).hexdigest()
    if obj and obj.status == "available":
        if obj.sha256 != actual_hash:
            raise HTTPException(409, "evidence version already captured")
        return {"id": obj.id, "status": obj.status, "sha256": obj.sha256}
    now = time.time()
    if obj is None:
        obj = EvidenceObject(id=identifier, event_id=observation_id, kind=kind,
                             status="pending", created_at=now,
                             expires_at=now + get_settings().evidence_retention_days * 86400,
                             manifest={"source_instance": row.source_instance,
                                       "source_event": row.signal["source_event_id"],
                                       "source_type": row.source_type,
                                       "camera": row.camera_id,
                                       "source_timestamp": row.observed_at,
                                       "ingest_timestamp": row.received_at,
                                       "policy_version": row.policy_version,
                                       "media_origin": "synthetic" if row.synthetic else "source"})
        db.add(obj)
        db.flush()
    attach_evidence(db, row.incident_id, [observation_id])
    store_capture(db, obj, bytes(content), mime)
    return {"id": obj.id, "status": obj.status, "sha256": obj.sha256}


@router.get("/observations")
def list_observations(db=Depends(get_db)):
    require_role(db, OPERATORS)
    return [_observation_view(row) for row in db.scalars(
        select(CaseObservation).order_by(CaseObservation.observed_at.desc()).limit(100))]


@router.get("/alerts")
def list_alerts(db=Depends(get_db)):
    require_role(db, MANAGERS)
    from app.operations.service import latest_episode
    return [{"id": a.id, "incident_id": a.incident_id, "channel": a.channel,
             "status": a.status, "attempt_count": a.attempt_count,
             "accepted_at": a.accepted_at,
             "human_acknowledged_at": (episode.acknowledged_at if (
                 episode := latest_episode(db, a.incident_id)) else None),
             "last_error": a.last_error}
            for a in db.scalars(select(CaseAlert).order_by(CaseAlert.id).limit(100))]


@router.post("/demo")
def load_demo(db=Depends(get_db)):
    """Create deterministic synthetic examples; disabled outside development."""
    if get_settings().environment == "production":
        raise HTTPException(404, "not found")
    require_role(db, MANAGERS)
    policies = [
        PolicyIn(id="demo-material", kind="material", subject="EXAM-PAPER-7", zone="records_room"),
        PolicyIn(id="demo-asset", kind="asset", subject="FILE-42", zone="records_room"),
        PolicyIn(id="demo-smoking", kind="prohibited_activity", subject="smoking", zone="loading_bay"),
        PolicyIn(id="demo-drinking", kind="prohibited_activity", subject="drinking", zone="control_room"),
        PolicyIn(id="demo-zone", kind="restricted_zone", subject="server_room", zone="server_room"),
        PolicyIn(id="demo-vehicle", kind="vehicle", subject="KA03MN1234", zone="main_gate"),
    ]
    for policy in policies:
        put_policy(policy, db)
    epoch = datetime.fromisoformat("2026-10-07T09:00:00+05:30").timestamp()
    examples = [
        ObservationIn(source_event_id="case-demo-reading", kind="restricted_reading",
                      camera_id="records_cam", zone="records_room", observed_at=epoch,
                      item_id="EXAM-PAPER-7"),
        ObservationIn(source_event_id="case-demo-replacement", kind="material_change",
                      camera_id="records_cam", zone="records_room", observed_at=epoch + 60,
                      item_id="FILE-42", action="replaced"),
        ObservationIn(source_event_id="case-demo-smoking", kind="smoking",
                      camera_id="loading_cam", zone="loading_bay", observed_at=epoch + 120,
                      confidence=0.91),
        ObservationIn(source_event_id="case-demo-drinking", kind="drinking",
                      camera_id="control_cam", zone="control_room", observed_at=epoch + 180,
                      confidence=0.76),
        ObservationIn(source_event_id="case-demo-entry", kind="restricted_entry",
                      camera_id="server_door_cam", zone="server_room", observed_at=epoch + 240),
        ObservationIn(source_event_id="case-demo-unknown-car", kind="vehicle_plate",
                      camera_id="gate_cam", zone="main_gate", observed_at=epoch + 300,
                      plate="KA05AB9999", vehicle_type="car", confidence=0.94),
        ObservationIn(source_event_id="case-demo-authorized-bike", kind="vehicle_plate",
                      camera_id="gate_cam", zone="main_gate", observed_at=epoch + 360,
                      plate="KA03MN1234", vehicle_type="bike", confidence=0.92),
    ]
    return {"synthetic": True, "observations": [_ingest_observation(item, db, synthetic=True) for item in examples]}
