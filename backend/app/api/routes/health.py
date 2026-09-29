"""Health endpoint: verifies API is up and DB is reachable."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import get_db

router = APIRouter(tags=["health"])


@router.get("/health")
def health(db: Session = Depends(get_db)) -> dict:
    db_ok = True
    try:
        db.execute(text("SELECT 1"))
    except Exception:  # pragma: no cover - defensive
        db_ok = False
    return {"status": "ok" if db_ok else "degraded", "database": db_ok}
