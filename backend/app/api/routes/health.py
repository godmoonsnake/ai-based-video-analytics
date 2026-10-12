"""Health endpoint: verifies API is up and DB is reachable."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text, select, func
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.models.operations import (
    CameraHealthCurrent,
    CameraHealthSample,
    MaintenanceWindow,
)
from app.models.entities import Camera, AuditLog
from app.security.auth import require_role, MEDIA_ROLES
from pydantic import BaseModel, Field
import time
import uuid

from app.db.session import engine


def health_db():
    with Session(engine) as db:
        yield db


router = APIRouter(tags=["health"])


@router.get("/health")
def health(db: Session = Depends(health_db)) -> dict:
    db_ok = True
    try:
        db.execute(text("SELECT 1"))
    except Exception:  # pragma: no cover - defensive
        db_ok = False
    return {"status": "ok" if db_ok else "degraded", "database": db_ok}


@router.get("/health/ready")
def readiness(db=Depends(get_db)) -> dict:
    """Operational summary without tenant-specific identifiers or payload data."""
    try:
        from app.models.processing import ProcessingJob, SourceLease
        from app.models.evidence import EvidenceObject

        now = __import__("time").time()
        backlog = (
            db.scalar(
                select(func.count())
                .select_from(ProcessingJob)
                .where(ProcessingJob.status == "pending")
            )
            or 0
        )
        failed = (
            db.scalar(
                select(func.count())
                .select_from(ProcessingJob)
                .where(ProcessingJob.status == "quarantined")
            )
            or 0
        )
        evidence_pending = (
            db.scalar(
                select(func.count())
                .select_from(EvidenceObject)
                .where(EvidenceObject.status == "pending")
            )
            or 0
        )
        sources = db.scalars(select(SourceLease)).all()
        stale_sources = sum(
            1
            for source in sources
            if not source.last_seen or now - source.last_seen > 60
        )
        return {
            "status": "ready",
            "database": True,
            "queues": {
                "pending": backlog,
                "quarantined": failed,
                "evidence_pending": evidence_pending,
            },
            "sources": {"configured": len(sources), "stale": stale_sources},
            "checked_at": now,
        }
    except Exception:
        db.rollback()
        return {"status": "degraded", "database": False}


@router.get("/api/v1/health/cameras")
def camera_health(db=Depends(get_db)):
    require_role(db, MEDIA_ROLES)
    return [
        {
            "camera_id": row.camera_id,
            "state": row.state,
            "stream_state": row.stream_state,
            "video_state": row.video_state,
            "recording_state": row.recording_state,
            "evidence_state": row.evidence_state,
            "maintenance": row.maintenance,
            "frame_arrival_fps": row.frame_arrival_fps,
            "source_to_darson_lag_seconds": row.source_to_darson_lag_seconds,
            "event_to_incident_latency_seconds": row.event_to_incident_latency_seconds,
            "recording_gap_seconds": row.recording_gap_seconds,
            "evidence_capture_success_rate": row.evidence_capture_success_rate,
            "last_frame_at": row.last_frame_at,
            "last_recording_at": row.last_recording_at,
            "last_evidence_at": row.last_evidence_at,
            "updated_at": row.updated_at,
            "metrics": row.metrics,
        }
        for row in db.scalars(
            select(CameraHealthCurrent).order_by(CameraHealthCurrent.camera_id)
        )
    ]


@router.get("/api/v1/health/metrics")
def health_metrics(hours: int = 24, db=Depends(get_db)):
    require_role(db, MEDIA_ROLES)
    hours = max(1, min(hours, 168))
    since = time.time() - hours * 3600
    rows = db.scalars(
        select(CameraHealthSample)
        .where(CameraHealthSample.checked_at >= since)
        .order_by(CameraHealthSample.camera_id, CameraHealthSample.checked_at)
    ).all()
    outages = recording_gaps = 0.0
    lag, latency, evidence = [], [], []
    for current, following in zip(rows, rows[1:]):
        if current.camera_id != following.camera_id:
            continue
        duration = max(0, following.checked_at - current.checked_at)
        if current.stream_state == "offline" and not current.maintenance:
            outages += duration
        if current.recording_state == "degraded" and not current.maintenance:
            recording_gaps += duration
    for row in rows:
        m = row.metrics or {}
        if m.get("source_to_darson_lag_seconds") is not None:
            lag.append(m["source_to_darson_lag_seconds"])
        if m.get("event_to_incident_latency_seconds") is not None:
            latency.append(m["event_to_incident_latency_seconds"])
        if m.get("evidence_capture_success_rate") is not None:
            evidence.append(m["evidence_capture_success_rate"])

    def avg(values):
        return round(sum(values) / len(values), 3) if values else None

    return {
        "window_hours": hours,
        "unavailable_camera_minutes": round(outages / 60, 2),
        "recording_gap_minutes": round(recording_gaps / 60, 2),
        "evidence_capture_success_rate": avg(evidence),
        "source_to_darson_lag_seconds": avg(lag),
        "event_to_incident_latency_seconds": avg(latency),
        "samples": len(rows),
        "checked_at": time.time(),
    }


class MaintenanceIn(BaseModel):
    camera_id: str | None = None
    starts_at: float
    ends_at: float
    reason: str = Field(min_length=3, max_length=500)


@router.post("/api/v1/config/maintenance")
def create_maintenance(body: MaintenanceIn, db=Depends(get_db)):
    scope = require_role(db, {"supervisor", "configuration_admin"})
    if body.ends_at <= body.starts_at or body.ends_at <= time.time():
        from fastapi import HTTPException

        raise HTTPException(
            422, "maintenance window must have a future end after its start"
        )
    if body.camera_id and not db.get(Camera, body.camera_id):
        from fastapi import HTTPException

        raise HTTPException(404, "camera not found")
    row = MaintenanceWindow(
        id=uuid.uuid4().hex,
        camera_id=body.camera_id,
        starts_at=body.starts_at,
        ends_at=body.ends_at,
        reason=body.reason,
        created_by=scope.actor,
        created_at=time.time(),
    )
    db.add(row)
    db.add(
        AuditLog(actor=scope.actor, action="maintenance_window_created", target=row.id)
    )
    db.commit()
    return {"id": row.id, "starts_at": row.starts_at, "ends_at": row.ends_at}


@router.delete("/api/v1/config/maintenance/{window_id}")
def cancel_maintenance(window_id: str, db=Depends(get_db)):
    scope = require_role(db, {"supervisor", "configuration_admin"})
    row = db.get(MaintenanceWindow, window_id)
    if not row:
        from fastapi import HTTPException

        raise HTTPException(404, "maintenance window not found")
    row.ends_at = min(row.ends_at, time.time())
    db.add(
        AuditLog(
            actor=scope.actor, action="maintenance_window_cancelled", target=row.id
        )
    )
    db.commit()
    return {"id": row.id, "cancelled": True}
