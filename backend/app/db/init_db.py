"""Database initialization helpers.

For Postgres we ensure the pgvector extension exists. For both backends we can
create all tables directly (used by tests and the SQLite demo path). Production
Postgres uses Alembic migrations, but create_all is idempotent and safe.
"""
from __future__ import annotations

from sqlalchemy import text

from app.db.session import Base, engine
import app.models  # noqa: F401  ensure models are registered on Base.metadata


def init_db() -> None:
    if engine.dialect.name == "postgresql":
        with engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.create_all(bind=engine)
