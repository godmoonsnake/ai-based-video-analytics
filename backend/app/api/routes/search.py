"""Investigation search API.

- POST /search           : structured filter OR {q: "<natural language>"}.
- GET  /search/similar   : semantic appearance search from a reference track.

Deterministic structured search is the baseline; NL is parsed deterministically
(optionally enhanced by a local LLM). Every response is flagged for human review
— the system provides decision support, not verdicts.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.search.filters import SearchFilter, run_search
from app.search.nl_query import parse_nl
from app.search.semantic import similar_to_track

router = APIRouter(prefix="/search", tags=["search"])


class SearchQuery(BaseModel):
    q: str | None = None  # natural language
    # structured fields (optional)
    camera_id: str | None = None
    event_type: str | None = None
    label: str | None = None
    sub_label: str | None = None
    zone: str | None = None
    status: str | None = None
    priority: str | None = None
    time_start: float | None = None
    time_end: float | None = None


@router.post("")
def search(body: SearchQuery, db: Session = Depends(get_db)) -> dict:
    if body.q:
        f = parse_nl(db, body.q)
    else:
        f = SearchFilter(
            camera_id=body.camera_id, event_type=body.event_type, label=body.label,
            sub_label=body.sub_label, zone=body.zone, status=body.status,
            priority=body.priority, time_start=body.time_start, time_end=body.time_end,
        )
    results = run_search(db, f)
    return {
        "query": body.q,
        "parsed_filter": results.filter,
        "events": results.events,
        "incidents": results.incidents,
        "human_review_required": results.human_review_required,
    }


@router.get("/similar")
def semantic_similar(camera_id: str, track_local_id: str, top_k: int = 5,
                     db: Session = Depends(get_db)) -> dict:
    hits = similar_to_track(db, camera_id, track_local_id, top_k=top_k)
    return {"reference": {"camera_id": camera_id, "track_local_id": track_local_id},
            "similar": hits, "human_review_required": True}
