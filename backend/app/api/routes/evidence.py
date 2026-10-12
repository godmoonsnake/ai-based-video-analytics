import hashlib
import time
import uuid
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from app.db.session import get_db
from app.models.entities import Incident
from app.models.evidence import EvidenceObject, IncidentEvidence, RetentionHold
from app.models.operations import ResponseEpisode
from app.evidence.storage import ObjectStore
from app.evidence.policy import audit, held
from app.security.auth import require_role, MEDIA_ROLES

router = APIRouter(prefix="/api/v1", tags=["evidence"])


def object_for_access(db, identifier):
    require_role(db, MEDIA_ROLES)
    obj = db.scalar(select(EvidenceObject).where(EvidenceObject.id == identifier).with_for_update())
    if obj is None:
        raise HTTPException(404, "evidence not found")
    scope = db.info["scope"]
    if scope.role == "responder":
        allowed = db.scalar(select(IncidentEvidence.id).join(ResponseEpisode,
            ResponseEpisode.incident_id == IncidentEvidence.incident_id).where(
                IncidentEvidence.evidence_id == identifier, ResponseEpisode.owner == scope.actor,
                ResponseEpisode.state != "resolved").limit(1))
        if not allowed:
            from app.models.pilot import PilotCase
            allowed = db.scalar(select(IncidentEvidence.id).join(PilotCase,
                PilotCase.incident_id == IncidentEvidence.incident_id).where(
                    IncidentEvidence.evidence_id == identifier, PilotCase.owner == scope.actor,
                    PilotCase.state != "resolved").limit(1))
        if not allowed:
            raise HTTPException(404, "evidence not found")
    return obj


@router.get("/incidents/{incident_id}/evidence")
def evidence_list(incident_id: int, db=Depends(get_db)):
    require_role(db, MEDIA_ROLES)
    incident = db.get(Incident, incident_id)
    if not incident:
        raise HTTPException(404, "incident not found")
    scope = db.info["scope"]
    if scope.role == "responder":
        from app.models.pilot import PilotCase
        allowed = db.scalar(select(ResponseEpisode.id).where(
            ResponseEpisode.incident_id == incident_id, ResponseEpisode.owner == scope.actor,
            ResponseEpisode.state != "resolved").limit(1)) or db.scalar(select(PilotCase.id).where(
                PilotCase.incident_id == incident_id, PilotCase.owner == scope.actor,
                PilotCase.state != "resolved").limit(1))
        if not allowed:
            raise HTTPException(404, "incident not found")
    objects = db.scalars(select(EvidenceObject).join(IncidentEvidence,
        IncidentEvidence.evidence_id == EvidenceObject.id).where(IncidentEvidence.incident_id == incident_id)).all()
    return [{"id": o.id, "kind": o.kind, "status": o.status, "error": o.error,
             "sha256": o.sha256, "size": o.size, "mime": o.mime, "manifest": o.manifest,
             "held": held(db, o.id), "content_url": f"/api/v1/evidence/{o.id}/content"
             if o.status == "available" else None} for o in objects]


@router.get("/evidence/{identifier}/content")
def content(identifier: str, db=Depends(get_db)):
    obj = object_for_access(db, identifier)
    if obj.status != "available" or (obj.expires_at <= time.time() and not held(db, obj.id)):
        raise HTTPException(410, "evidence unavailable or retention expired")
    try:
        data = ObjectStore().read(db.info["scope"], obj.object_key)
        if len(data) != obj.size or hashlib.sha256(data).hexdigest() != obj.sha256:
            raise ValueError("integrity mismatch")
    except Exception:
        obj.status, obj.error = "integrity-failed", "stored_object_verification_failed"
        audit(db, obj.id, "integrity_failure")
        db.commit()
        raise HTTPException(409, "evidence failed integrity verification") from None
    audit(db, obj.id, "content_read")
    db.commit()
    return Response(data, media_type=obj.mime, headers={"Cache-Control": "no-store",
                    "Content-Disposition": f'inline; filename="{obj.id}.{ "jpg" if obj.mime == "image/jpeg" else "png" if obj.mime == "image/png" else "mp4"}"'})


class HoldIn(BaseModel):
    reason: str = Field(min_length=3, max_length=1000)


@router.post("/evidence/{identifier}/holds")
def hold(identifier: str, body: HoldIn, db=Depends(get_db)):
    scope = require_role(db, {"supervisor"})
    object_for_access(db, identifier)
    hold = RetentionHold(id=uuid.uuid4().hex, evidence_id=identifier, actor=scope.actor,
                         reason=body.reason, created_at=time.time())
    db.add(hold)
    audit(db, identifier, "hold_created", body.reason)
    db.commit()
    return {"id": hold.id}


@router.post("/evidence/{identifier}/holds/{hold_id}/release")
def release(identifier: str, hold_id: str, body: HoldIn, db=Depends(get_db)):
    require_role(db, {"supervisor"})
    object_for_access(db, identifier)
    row = db.get(RetentionHold, hold_id)
    if not row or row.evidence_id != identifier:
        raise HTTPException(404, "hold not found")
    if row.released_at is None:
        row.released_at = time.time()
        audit(db, identifier, "hold_released", body.reason)
        db.commit()
    return {"id": hold_id, "released": True}
