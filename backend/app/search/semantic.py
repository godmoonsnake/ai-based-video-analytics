"""Semantic (appearance) search over track embeddings.

Reuses the Re-ID embedding store: given a reference (camera, track), return the
most visually similar tracks across cameras. Appearance-only similarity — no
identity, no PII. Useful for 'find other sightings that look like this'.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.pipeline.reid_service import mean_track_vector, query_similar


def similar_to_track(db: Session, camera_id: str, track_local_id: str,
                     top_k: int = 5) -> list[dict]:
    vec = mean_track_vector(db, camera_id, track_local_id)
    if vec is None:
        return []
    hits = query_similar(db, vec, top_k=top_k, exclude=(camera_id, track_local_id))
    return [
        {"camera_id": h.camera_id, "track_local_id": h.track_local_id, "score": round(h.score, 4)}
        for h in hits
    ]
