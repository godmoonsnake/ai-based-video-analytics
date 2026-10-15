"""Cameras API: list cameras, topology edges, and zones."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from urllib.parse import quote, urlparse
import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.entities import Camera, CameraEdge, Zone
from app.config import get_settings
from app.security.auth import require_role

router = APIRouter(prefix="/cameras", tags=["cameras"])


@router.get("")
def list_cameras(db: Session = Depends(get_db)) -> list[dict]:
    cams = db.execute(select(Camera)).scalars().all()
    return [
        {"id": c.id, "name": c.name, "site_id": c.site_id, "x": c.x, "y": c.y}
        for c in cams
    ]


@router.get("/{camera_id}/latest-frame")
def latest_frame(camera_id: str, db: Session = Depends(get_db)):
    """Authenticated, bounded read of Frigate's latest frame; never a claimed live video stream."""
    require_role(db, {"operator", "supervisor"})
    if not db.get(Camera, camera_id):
        raise HTTPException(404, "camera is not registered at this site")
    settings = get_settings()
    if settings.event_source != "frigate":
        raise HTTPException(503, "live source is not configured")
    base = settings.frigate_api_base.rstrip("/")
    parsed = urlparse(base)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.query or parsed.fragment:
        raise HTTPException(503, "live source configuration is invalid")
    headers = {"Cookie": f"frigate_token={settings.frigate_api_token}"} if settings.frigate_api_token else {}
    try:
        with httpx.Client(timeout=5, follow_redirects=False, trust_env=False, headers=headers) as client:
            with client.stream("GET", f"{base}/api/{quote(camera_id, safe='')}/latest.jpg") as source:
                if source.status_code != 200 or source.headers.get("content-type", "").split(";")[0].lower() != "image/jpeg":
                    raise HTTPException(503, "camera frame is unavailable")
                frame = bytearray()
                for chunk in source.iter_bytes():
                    frame.extend(chunk)
                    if len(frame) > 5_000_000:
                        raise HTTPException(503, "camera frame exceeds preview limit")
    except httpx.HTTPError:
        raise HTTPException(503, "camera frame is unavailable") from None
    if not frame.startswith(b"\xff\xd8\xff"):
        raise HTTPException(503, "camera frame is invalid")
    return Response(bytes(frame), media_type="image/jpeg", headers={"Cache-Control": "no-store"})


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
