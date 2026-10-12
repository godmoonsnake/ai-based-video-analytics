"""Parking visit rules over registered detector signals, not identity recognition."""
from __future__ import annotations

import time
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select

from app.api.routes.case_studies import ObservationIn, _id, _ingest_observation
from app.case_studies.service import _driver_grant, _policies
from app.config import get_settings
from app.db.session import get_db
from app.models.case_studies import CaseObservation, CaseSource, ParkingSession
from app.models.entities import AuditLog
from app.processing.jobs import digest
from app.security.auth import require_role

router = APIRouter(prefix="/api/v1/parking", tags=["parking"])
SESSION_SECONDS = 12 * 3600
COMPARISON_QUALITY_MIN = 0.8  # Intake gate only; site calibration remains required.
ALERT_ACTIONS = {"door_tamper", "trunk_tamper", "forced_entry", "damage", "object_removal"}
CONDITIONAL_ACTIONS = {"door_handle", "trunk_handle", "loitering"}


class ArrivalIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_event_id: str = Field(min_length=1, max_length=128)
    source_instance: str = Field(min_length=1, max_length=100)
    camera_id: str = Field(min_length=1, max_length=100)
    zone: str = Field(min_length=1, max_length=100)
    observed_at: float = Field(gt=0)
    plate: str = Field(min_length=4, max_length=30)
    vehicle_type: Literal["car", "bike"]
    plate_confidence: float = Field(ge=0, le=1)


class ParkingSignalIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_event_id: str = Field(min_length=1, max_length=128)
    source_instance: str = Field(min_length=1, max_length=100)
    camera_id: str = Field(min_length=1, max_length=100)
    observed_at: float = Field(gt=0)
    kind: Literal["exit", "approach", "interaction", "departure"]
    person_ref: str | None = Field(default=None, max_length=100)
    appearance_match: Literal["same", "different", "unknown"] | None = None
    comparison_quality: float | None = Field(default=None, ge=0, le=1)
    action: Literal["door_handle", "trunk_handle", "door_tamper", "trunk_tamper",
                    "forced_entry", "damage", "object_removal", "loitering"] | None = None
    duration_seconds: float | None = Field(default=None, ge=0, le=3600)

    @model_validator(mode="after")
    def required_fields(self):
        if self.kind != "departure" and not self.person_ref:
            raise ValueError("person_ref is required for person observations")
        if self.kind == "approach" and self.appearance_match is None:
            raise ValueError("approach requires an appearance comparison result")
        if self.kind == "interaction" and self.action is None:
            raise ValueError("interaction requires a configured action")
        if self.action == "loitering" and self.duration_seconds is None:
            raise ValueError("loitering requires a measured duration")
        return self


class AuthorizationIn(BaseModel):
    """Trusted credential-to-camera-track link supplied by an access system."""
    model_config = ConfigDict(extra="forbid")
    source_event_id: str = Field(min_length=1, max_length=128)
    source_instance: str = Field(min_length=1, max_length=100)
    observed_at: float = Field(gt=0)
    person_ref: str = Field(min_length=1, max_length=100)
    principal_ref: str = Field(min_length=1, max_length=100)


def _source(db, source_type: str, instance: str):
    scope = require_role(db, {"operator", "supervisor", "configuration_admin"})
    row = db.get(CaseSource, _id(scope, f"source:{source_type}:{instance}"))
    if not row or not row.enabled or row.actor != scope.actor:
        raise HTTPException(403, "registered detector source required")
    return scope


def _view(row: ParkingSession):
    return {"id": row.id, "plate": row.plate, "vehicle_type": row.vehicle_type,
            "camera_id": row.camera_id, "zone": row.zone,
            "arrived_at": row.arrived_at, "expires_at": row.expires_at,
            "departed_at": row.departed_at, "exit_count": len(row.exit_refs),
            "yellow_count": len(row.flagged_refs),
            "credential_link_count": len(row.authorized_refs),
            "state": "departed" if row.departed_at else "active" if row.expires_at > time.time() else "expired",
            "identity_verified": False}


@router.post("/sessions")
def arrive(body: ArrivalIn, db=Depends(get_db)):
    scope = _source(db, "vehicle_anpr", body.source_instance)
    if body.plate_confidence < 0.85:
        raise HTTPException(422, "low-confidence plate rejected; manual correction workflow not yet available")
    normalized_plate = "".join(c for c in body.plate.upper() if c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")
    if len(normalized_plate) < 4:
        raise HTTPException(422, "invalid plate")
    identifier = _id(scope, f"parking:{body.source_event_id}")
    existing = db.get(ParkingSession, identifier)
    signal = body.model_dump()
    if existing:
        if existing.arrival_signal != signal:
            raise HTTPException(409, "arrival event ID already has different content")
        return _view(existing)
    row = ParkingSession(id=identifier, arrival_signal=signal, plate=normalized_plate,
                         vehicle_type=body.vehicle_type, camera_id=body.camera_id,
                         zone=body.zone, arrived_at=body.observed_at,
                         expires_at=body.observed_at + SESSION_SECONDS,
                         exit_refs=[], flagged_refs=[], escalated_refs=[], authorized_refs=[])
    db.add(row)
    db.add(AuditLog(actor=scope.actor, action="parking_session_opened", target=identifier))
    db.commit()
    return _view(row)


@router.get("/sessions")
def list_sessions(db=Depends(get_db)):
    require_role(db, {"operator", "supervisor", "configuration_admin"})
    rows = db.scalars(select(ParkingSession).order_by(ParkingSession.arrived_at.desc()).limit(100))
    return [_view(row) for row in rows]


@router.post("/sessions/{session_id}/authorizations")
def authorize(session_id: str, body: AuthorizationIn, db=Depends(get_db)):
    scope = _source(db, "access_control", body.source_instance)
    identifier = _id(scope, body.source_event_id)
    existing = db.get(CaseObservation, identifier)
    if existing:
        if (existing.signal.get("source_revision") != digest(body.model_dump()) or
                existing.signal.get("item_id") != session_id):
            raise HTTPException(409, "source event ID already has different content")
        return {"decision": existing.decision, "linked": existing.decision == "allowed"}
    row = db.scalar(select(ParkingSession).where(ParkingSession.id == session_id).with_for_update())
    if not row:
        raise HTTPException(404, "parking session not found")
    if row.departed_at is not None or not row.arrived_at <= body.observed_at <= row.expires_at:
        raise HTTPException(409, "parking session is closed or credential is outside visit window")
    observation = ObservationIn(
        source_event_id=body.source_event_id, kind="parking_authorization",
        camera_id=row.camera_id, zone=row.zone, observed_at=body.observed_at,
        source_type="access_control", source_instance=body.source_instance,
        source_revision=digest(body.model_dump()), item_id=session_id,
        principal_ref=body.principal_ref, track_ref=body.person_ref,
        plate=row.plate, vehicle_type=row.vehicle_type)
    result = _ingest_observation(observation, db, alert_destinations=(), commit=False)
    link = {"person_ref": body.person_ref, "principal_ref": body.principal_ref}
    if result["decision"] == "allowed" and link not in row.authorized_refs:
        row.authorized_refs = [*row.authorized_refs, link]
    db.add(AuditLog(actor=scope.actor, action="parking_credential_link_received", target=identifier))
    db.commit()
    return {"decision": result["decision"], "linked": result["decision"] == "allowed"}


@router.post("/sessions/{session_id}/signals")
def signal(session_id: str, body: ParkingSignalIn, db=Depends(get_db)):
    scope = _source(db, "camera_detector", body.source_instance)
    identifier = _id(scope, body.source_event_id)
    existing = db.get(CaseObservation, identifier)
    if existing:
        if (existing.signal.get("source_revision") != digest(body.model_dump()) or
                existing.signal.get("item_id") != session_id):
            raise HTTPException(409, "source event ID already has different content")
        session = db.get(ParkingSession, session_id)
        if session is None:
            raise HTTPException(404, "parking session not found")
        return {"session": _view(session), "observation":
                {"id": existing.id, "decision": existing.decision, "incident_id": existing.incident_id}}
    row = db.scalar(select(ParkingSession).where(ParkingSession.id == session_id).with_for_update())
    if not row:
        raise HTTPException(404, "parking session not found")
    if row.departed_at is not None or not row.arrived_at <= body.observed_at <= row.expires_at:
        raise HTTPException(409, "parking session is closed or signal is outside visit window")
    if body.camera_id != row.camera_id:
        raise HTTPException(422, "pilot parking session requires the same camera")

    action = None
    if body.kind == "exit":
        if body.person_ref not in row.exit_refs:
            row.exit_refs = [*row.exit_refs, body.person_ref]
    elif body.kind == "approach":
        registered = any(p.principal for p in _policies(
            db, "vehicle", row.plate, row.zone, body.observed_at))
        authorized = any(link["person_ref"] == body.person_ref and _driver_grant(
            db, row.plate, row.zone, link["principal_ref"], body.observed_at)
            for link in row.authorized_refs)
        if authorized:
            action = "registry_authorized"
        elif body.person_ref in row.exit_refs:
            action = "baseline_only" if registered else "same"
        elif body.appearance_match == "different" and (body.comparison_quality or 0) >= COMPARISON_QUALITY_MIN:
            action = "different"
            if body.person_ref not in row.flagged_refs:
                row.flagged_refs = [*row.flagged_refs, body.person_ref]
        elif body.appearance_match == "same" and (body.comparison_quality or 0) >= COMPARISON_QUALITY_MIN:
            action = "baseline_only" if registered else "same"
        else:
            action = "unknown"
    elif body.kind == "interaction":
        flagged = body.person_ref in row.flagged_refs
        loitered = body.action != "loitering" or (body.duration_seconds or 0) >= max(
            30, get_settings().parking_loitering_seconds)
        eligible = body.action in ALERT_ACTIONS or (flagged and loitered and body.action in CONDITIONAL_ACTIONS)
        action = body.action if eligible and body.person_ref not in row.escalated_refs else "none"
        if action != "none":
            row.escalated_refs = [*row.escalated_refs, body.person_ref]
    else:
        row.departed_at = body.observed_at

    settings = get_settings()
    dispatch = tuple(dict.fromkeys([
        ("telegram", destination) for destination in (
            settings.parking_security_telegram_chat_id,
            settings.parking_floor_guard_telegram_chat_id) if destination
    ] + [
        ("whatsapp", destination) for destination in (
            settings.parking_security_whatsapp_recipient,
            settings.parking_floor_guard_whatsapp_recipient) if destination
    ])) if body.kind == "interaction" and action != "none" else ()
    observation = ObservationIn(
        source_event_id=body.source_event_id,
        kind=f"parking_{body.kind}", camera_id=body.camera_id, zone=row.zone,
        observed_at=body.observed_at, source_type="camera_detector",
        source_instance=body.source_instance, source_revision=digest(body.model_dump()), item_id=session_id,
        track_ref=body.person_ref, action=action, plate=row.plate,
        vehicle_type=row.vehicle_type, confidence=body.comparison_quality,
        duration_seconds=body.duration_seconds)
    result = _ingest_observation(observation, db, alert_destinations=dispatch, commit=False)
    db.add(AuditLog(actor=scope.actor, action="parking_signal_received", target=identifier))
    db.commit()
    return {"session": _view(row), "observation": result,
            "risk": "yellow" if result["decision"] == "review" and body.kind == "approach" else
                    "high" if result["decision"] == "review" and body.kind == "interaction" else "none",
            "external_alerts_queued": bool(dispatch and settings.environment == "production" and
                                           result["decision"] == "review"),
            "identity_verified": False}
