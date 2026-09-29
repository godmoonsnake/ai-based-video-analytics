"""Cameras API: list cameras, topology edges, and zones."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.entities import Camera, CameraEdge, Zone

router = APIRouter(prefix="/cameras", tags=["cameras"])


@router.get("")
def list_cameras(db: Session = Depends(get_db)) -> list[dict]:
    cams = db.execute(select(Camera)).scalars().all()
    return [
        {"id": c.id, "name": c.name, "site_id": c.site_id, "x": c.x, "y": c.y}
        for c in cams
    ]


@router.get("/edges")
def list_edges(db: Session = Depends(get_db)) -> list[dict]:
    edges = db.execute(select(CameraEdge)).scalars().all()
    return [
        {
            "from": e.from_camera_id,
            "to": e.to_camera_id,
            "walk_seconds_min": e.walk_seconds_min,
            "walk_seconds_max": e.walk_seconds_max,
            "bidirectional": e.bidirectional,
        }
        for e in edges
    ]


@router.get("/zones")
def list_zones(db: Session = Depends(get_db)) -> list[dict]:
    zones = db.execute(select(Zone)).scalars().all()
    return [{"camera_id": z.camera_id, "name": z.name, "kind": z.kind} for z in zones]
