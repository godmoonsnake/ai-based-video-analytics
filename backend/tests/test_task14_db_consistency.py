"""Task 14: database schema/bootstrap consistency.

Guards against the previously-found divergence where only the incident-graph
tables were migration-managed while create_all built the full schema. Asserts:
  - `alembic upgrade head` from an EMPTY database produces exactly the same
    tables as the ORM metadata (create_all),
  - the migration chain has a single head and is fully reversible,
so the two bootstrap paths in init_db can never silently diverge.
"""
from __future__ import annotations

import os
import tempfile

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect

from app.config import get_settings
from app.db.session import Base
import app.models  # noqa: F401  register models on Base.metadata

_ALEMBIC_INI = os.path.join(os.path.dirname(__file__), "..", "alembic.ini")


def _alembic_cfg(url: str) -> Config:
    cfg = Config(_ALEMBIC_INI)
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


def _tables_via_migrations(url: str) -> set[str]:
    from alembic import command

    command.upgrade(_alembic_cfg(url), "head")
    eng = create_engine(url)
    tables = {t for t in inspect(eng).get_table_names() if t != "alembic_version"}
    eng.dispose()
    return tables


def _tables_via_create_all(url: str) -> set[str]:
    eng = create_engine(url)
    Base.metadata.create_all(bind=eng)
    tables = set(inspect(eng).get_table_names())
    eng.dispose()
    return tables


def test_migrations_match_create_all():
    """alembic upgrade head == ORM create_all (no hidden schema divergence)."""
    f1 = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    f1.close()
    f2 = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    f2.close()
    try:
        migrated = _tables_via_migrations(f"sqlite:///{f1.name}")
        created = _tables_via_create_all(f"sqlite:///{f2.name}")
        assert migrated == created, (
            f"schema divergence: only-migrated={migrated - created} "
            f"only-create_all={created - migrated}"
        )
        # sanity: the core + graph + lifecycle tables are present
        for expected in ("event", "global_track", "incident",
                         "incident_node", "incident_graph_edge",
                         "incident_state_transition"):
            assert expected in migrated
    finally:
        os.unlink(f1.name)
        os.unlink(f2.name)


def test_single_migration_head():
    """The migration graph must have exactly one head (linear, no forks)."""
    script = ScriptDirectory.from_config(_alembic_cfg(get_settings().database_url))
    heads = script.get_heads()
    assert len(heads) == 1, f"expected single head, got {heads}"


def test_pilot_columns_match_migrations(tmp_path):
    from alembic import command
    path = tmp_path / "pilot-schema.db"
    url = f"sqlite:///{path}"
    command.upgrade(_alembic_cfg(url), "head")
    eng = create_engine(url)
    try:
        inspector = inspect(eng)
        for name in ("incident", "pilot_rule", "pilot_case", "pilot_notice", "pilot_contact", "pilot_maintenance"):
            assert {column["name"] for column in inspector.get_columns(name)} == set(Base.metadata.tables[name].columns.keys())
    finally:
        eng.dispose()


def test_migration_chain_is_reversible():
    """upgrade head then downgrade base leaves no application tables."""
    from alembic import command

    f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    f.close()
    url = f"sqlite:///{f.name}"
    try:
        cfg = _alembic_cfg(url)
        command.upgrade(cfg, "head")
        command.downgrade(cfg, "base")
        eng = create_engine(url)
        tables = {t for t in inspect(eng).get_table_names() if t != "alembic_version"}
        eng.dispose()
        assert tables == set(), f"downgrade base left tables: {tables}"
    finally:
        os.unlink(f.name)
