"""Database initialization — explicit, non-divergent bootstrap.

The schema has a SINGLE source of truth: the Alembic migration chain
(0001_baseline -> a7f0455fcb94 -> ...). A consistency test
(`test_task14_db_consistency.py`) asserts that `alembic upgrade head` produces
exactly the same tables as the ORM metadata, so the two bootstrap paths below can
never silently diverge.

Bootstrap policy (explicit):
  - PostgreSQL (production/deployment): schema is MIGRATION-DRIVEN. `init_db`
    runs `alembic upgrade head`, which also creates the pgvector extension.
  - SQLite (offline dev/tests): schema is created from the ORM metadata via
    `create_all`. This is intentional and documented — it is provably equivalent
    to the migrations (see the consistency test) and keeps the offline test path
    fast and self-contained without an Alembic run per test.

Override with DARSON_DB_BOOTSTRAP:
  - "auto"       (default) -> policy above (migrations on PG, create_all on SQLite)
  - "migrations" -> always run `alembic upgrade head`
  - "create_all" -> always use ORM create_all
This makes the test/dev behavior explicit and switchable rather than hidden.
"""
from __future__ import annotations

import os
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import text

from app.db.session import Base, engine
import app.models  # noqa: F401  ensure models are registered on Base.metadata

_ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"


def _alembic_config() -> Config:
    cfg = Config(str(_ALEMBIC_INI))
    # env.py already resolves the URL from settings; set it explicitly too so the
    # config is self-describing regardless of how it is invoked.
    from app.config import get_settings

    cfg.set_main_option("sqlalchemy.url", get_settings().database_url)
    return cfg


def run_migrations() -> None:
    """Apply all Alembic migrations up to head (the schema source of truth)."""
    cfg = _alembic_config()
    # Do not let Alembic's fileConfig reconfigure/disable the app+uvicorn loggers
    # when we run migrations programmatically at startup.
    cfg.attributes["configure_logger"] = False
    command.upgrade(cfg, "head")


def _bootstrap_mode() -> str:
    mode = os.environ.get("DARSON_DB_BOOTSTRAP", "auto").lower()
    if mode not in ("auto", "migrations", "create_all"):
        mode = "auto"
    return mode


def init_db() -> None:
    """Initialize the database schema per the explicit bootstrap policy."""
    is_pg = engine.dialect.name == "postgresql"
    mode = _bootstrap_mode()
    from app.config import get_settings
    if get_settings().environment == "production":
        # Migrations are a deployment operation under a separate owner credential.
        if not is_pg or get_settings().auth_mode != "oidc":
            raise RuntimeError("production requires PostgreSQL and OIDC")
        with engine.connect() as conn:
            elevated = conn.scalar(text(
                "SELECT rolsuper OR rolbypassrls OR EXISTS (SELECT 1 FROM pg_tables "
                "WHERE schemaname='public' AND tableowner=current_user) "
                "FROM pg_roles WHERE rolname=current_user"))
            if elevated:
                raise RuntimeError("production runtime must not own tables or bypass RLS")
        return

    if is_pg:
        # pgvector must exist before either path creates the vector column.
        with engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))

    if mode == "migrations" or (mode == "auto" and is_pg):
        run_migrations()
    else:
        # SQLite offline dev/tests (or explicit create_all override).
        Base.metadata.create_all(bind=engine)
        from sqlalchemy.orm import Session
        from app.models.security import Tenant, Site
        with Session(engine) as db:
            if not db.get(Tenant, "development"):
                db.add(Tenant(id="development", name="Development — not a customer"))
                db.flush()
            if not db.get(Site, ("development", "site_a")):
                db.add(Site(tenant_id="development", id="site_a", name="Review demo"))
            db.commit()
