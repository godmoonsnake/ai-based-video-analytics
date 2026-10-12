"""Tracks API: list track keys and analyze behavioural sequences."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import distinct, select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.entities import BehaviouralSequence, Event
from app.pipeline.sequence_analyzer import analyze_track_local_id

router = APIRouter(prefix="/tracks", tags=["tracks"])


@router.get("")
def list_tracks(db: Session = Depends(get_db)) -> list[dict]:
    rows = db.execute(
        select(distinct(Event.track_local_id), Event.camera_id)
    ).all()
    seen: dict[str, str] = {}
    for track_local_id, camera_id in rows:
        seen.setdefault(track_local_id, camera_id)
    return [{"track_local_id": t, "camera_id": c} for t, c in seen.items()]


@router.get("/{track_local_id}/sequence")
def track_sequence(track_local_id: str, persist: bool = False,
                   db: Session = Depends(get_db)) -> dict:
    result = analyze_track_local_id(db, track_local_id)
    if not result.steps:
        raise HTTPException(status_code=404, detail="track not found")

    if persist:
        db.add(BehaviouralSequence(
            global_track_id=None,
            pattern_signature=result.signature,
            steps_json=json.dumps(result.to_dict()["steps"]),
            anomaly_score=result.anomaly_score,
        ))
        db.commit()
    return result.to_dict()


@router.get("/{camera_id}/{track_local_id}/similar")
def similar_tracks(camera_id: str, track_local_id: str, top_k: int = 5,
                   db: Session = Depends(get_db)) -> list[dict]:
    """Nearest appearance-embedding neighbours to a given (camera, track)."""
    from app.pipeline.reid_service import mean_track_vector, query_similar

    vec = mean_track_vector(db, camera_id, track_local_id)
    if vec is None:
        raise HTTPException(status_code=404, detail="no embedding for track")
    hits = query_similar(db, vec, top_k=top_k, exclude=(camera_id, track_local_id))
    return [
        {"camera_id": h.camera_id, "track_local_id": h.track_local_id, "score": round(h.score, 4)}
        for h in hits
    ]


@router.post("/correlate")
def run_correlation(db: Session = Depends(get_db)) -> dict:
    """Run cross-camera correlation and (re)build global tracks."""
    from app.pipeline.correlator import correlate

    summaries = correlate(db)
    return {"global_tracks": summaries, "count": len(summaries)}


@router.get("/global")
def list_global_tracks(db: Session = Depends(get_db)) -> list[dict]:
    from app.models.entities import GlobalTrack, GlobalTrackMember

    out = []
    for gt in db.execute(select(GlobalTrack).where(GlobalTrack.current.is_(True))).scalars().all():
        members = db.execute(
            select(GlobalTrackMember).where(GlobalTrackMember.global_track_id == gt.id)
        ).scalars().all()
        out.append({
            "global_track_id": gt.id,
            "first_seen": gt.first_seen,
            "last_seen": gt.last_seen,
            "confidence": gt.confidence,
            "track_kind": "correlated_movement" if len(members) > 1 else "single_camera",
            "score_is_probability": False,
            "run_id": gt.run_id,
            "members": [
                {
                    "camera_id": m.camera_id,
                    "track_local_id": m.track_local_id,
                    "join_score": m.join_score,
                    "method": m.method,
                }
                for m in members
            ],
        })
    return out
