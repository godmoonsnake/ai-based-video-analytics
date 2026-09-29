"""Patterns API: mine and list historical patterns (spatial/temporal only)."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analytics.pattern_miner import mine_patterns
from app.db.session import get_db
from app.models.entities import HistoricalPattern

router = APIRouter(prefix="/patterns", tags=["patterns"])


@router.post("/mine")
def mine(db: Session = Depends(get_db)) -> dict:
    rows = mine_patterns(db)
    return {"mined": len(rows)}


@router.get("")
def list_patterns(db: Session = Depends(get_db), pattern_type: str | None = None) -> list[dict]:
    stmt = select(HistoricalPattern).order_by(HistoricalPattern.count.desc())
    if pattern_type:
        stmt = stmt.where(HistoricalPattern.pattern_type == pattern_type)
    rows = db.execute(stmt).scalars().all()
    return [
        {
            "id": r.id,
            "pattern_type": r.pattern_type,
            "key": json.loads(r.key_json) if r.key_json else {},
            "count": r.count,
            "score": r.score,
        }
        for r in rows
    ]
