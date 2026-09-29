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

router = APIRouter(prefix="/api/v1/incidents", tags=["incidents-v1"])


def _summary(db: Session, inc: Incident) -> dict:
    cams = db.execute(
        select(IncidentCamera).where(IncidentCamera.incident_id == inc.id)
    ).scalars().all()
    return {
        "id": inc.id,
        "status": inc.status,
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
    limit: int = Query(200, le=1000),
) -> list[dict]:
    stmt = select(Incident).order_by(Incident.start_time)
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
    return inc


@router.get("/{incident_id}")
def incident_detail(incident_id: int, db: Session = Depends(get_db)) -> dict:
    """Full incident view: summary + tracks/events + explanation/evidence."""
    inc = _get_incident_or_404(db, incident_id)
    nodes = db.execute(
        select(IncidentNode).where(IncidentNode.incident_id == incident_id)
    ).scalars().all()

    tracks = [n.ref_id for n in nodes if n.node_type == "track"]
    events = [
        {"event_id": n.ref_id, **(n.attributes or {})}
        for n in nodes if n.node_type == "event"
    ]
    events.sort(key=lambda e: (e.get("ts") is None, e.get("ts")))

    detail = _summary(db, inc)
    detail.update({
        "tracks": tracks,
        "events": events,
        "explanation": build_explanation(db, incident_id),
    })
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
