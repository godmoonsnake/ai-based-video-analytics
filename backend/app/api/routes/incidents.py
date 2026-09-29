"""Incidents API: build incidents, list, detail (graph + timeline), feedback."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.entities import (
    AuditLog,
    Incident,
    IncidentCamera,
    IncidentEdge,
    IncidentEvent,
    OperatorFeedback,
)
from app.pipeline.incident_builder import build_incidents, reconstruct_timeline

router = APIRouter(prefix="/incidents", tags=["incidents"])


@router.post("/build")
def build(db: Session = Depends(get_db)) -> dict:
    ids = build_incidents(db)
    return {"built": len(ids), "incident_ids": ids}


@router.get("")
def list_incidents(db: Session = Depends(get_db), status: str | None = None,
                   priority: str | None = None) -> list[dict]:
    stmt = select(Incident).order_by(Incident.start_time)
    if status:
        stmt = stmt.where(Incident.status == status)
    if priority:
        stmt = stmt.where(Incident.priority == priority)
    incidents = db.execute(stmt).scalars().all()
    out = []
    for inc in incidents:
        cams = db.execute(
            select(IncidentCamera).where(IncidentCamera.incident_id == inc.id)
        ).scalars().all()
        out.append({
            "id": inc.id,
            "status": inc.status,
            "priority": inc.priority,
            "confidence": inc.confidence,
            "start_time": inc.start_time,
            "end_time": inc.end_time,
            "cameras": [c.camera_id for c in cams],
            "summary_text": inc.summary_text,
        })
    return out


@router.get("/{incident_id}")
def incident_detail(incident_id: int, db: Session = Depends(get_db)) -> dict:
    inc = db.get(Incident, incident_id)
    if inc is None:
        raise HTTPException(status_code=404, detail="incident not found")

    cams = db.execute(
        select(IncidentCamera).where(IncidentCamera.incident_id == inc.id)
    ).scalars().all()
    nodes = db.execute(
        select(IncidentEvent).where(IncidentEvent.incident_id == inc.id)
    ).scalars().all()
    edges = db.execute(
        select(IncidentEdge).where(IncidentEdge.incident_id == inc.id)
    ).scalars().all()

    return {
        "id": inc.id,
        "status": inc.status,
        "priority": inc.priority,
        "confidence": inc.confidence,
        "start_time": inc.start_time,
        "end_time": inc.end_time,
        "summary_text": inc.summary_text,
        "cameras": [c.camera_id for c in cams],
        "graph": {
            "nodes": [{"event_id": n.event_id, "role": n.role} for n in nodes],
            "edges": [
                {
                    "from": e.from_event_id,
                    "to": e.to_event_id,
                    "relation": e.relation,
                    "delta_seconds": e.delta_seconds,
                }
                for e in edges
            ],
        },
        "timeline": reconstruct_timeline(db, inc.id),
    }


class FeedbackIn(BaseModel):
    action: str  # confirm | dismiss | note
    note: str | None = None


@router.post("/{incident_id}/feedback")
def submit_feedback(incident_id: int, body: FeedbackIn,
                    db: Session = Depends(get_db)) -> dict:
    """Lightweight human-in-the-loop feedback (no RBAC)."""
    inc = db.get(Incident, incident_id)
    if inc is None:
        raise HTTPException(status_code=404, detail="incident not found")

    db.add(OperatorFeedback(incident_id=incident_id, action=body.action, note=body.note))
    if body.action == "confirm":
        inc.status = "confirmed"
    elif body.action == "dismiss":
        inc.status = "dismissed"
    db.add(AuditLog(actor="operator", action=f"feedback:{body.action}",
                    target=f"incident:{incident_id}"))
    db.commit()
    return {"incident_id": incident_id, "status": inc.status}
