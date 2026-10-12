"""Database session, engine, and a portable Vector column type.

The prototype targets PostgreSQL + pgvector in production but must also run on
SQLite for offline tests/demos. `Vector` uses pgvector's native type on
Postgres and falls back to JSON-encoded float lists on SQLite.
"""
from __future__ import annotations

import json
from typing import Iterator

from sqlalchemy import JSON, String, TypeDecorator, create_engine, event, text
from sqlalchemy import ForeignKeyConstraint, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker, Mapped, mapped_column
from sqlalchemy.orm import declared_attr, with_loader_criteria

from app.config import get_settings

settings = get_settings()

_connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=_connect_args, future=True)

class ScopedSession(Session):
    def __init__(self, *args, **kwargs):
        from app.security.context import session_scope
        super().__init__(*args, **kwargs)
        self.info["scope"] = session_scope()


SessionLocal = sessionmaker(bind=engine, class_=ScopedSession, autoflush=False,
                            autocommit=False, future=True)


class Base(DeclarativeBase):
    pass


class Scoped:
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    site_id: Mapped[str] = mapped_column(String, nullable=False, index=True)

    @declared_attr.directive
    def __table_args__(cls):
        return (
            ForeignKeyConstraint(["tenant_id", "site_id"], ["site.tenant_id", "site.id"],
                                 name=f"fk_{cls.__tablename__}_site"),
            UniqueConstraint("id", "tenant_id", "site_id", name=f"uq_{cls.__tablename__}_scope"),
        )


@event.listens_for(ScopedSession, "do_orm_execute")
def filter_scope(state):
    scope = state.session.info["scope"]
    tenant, site = scope.tenant, scope.site
    if state.is_select or state.is_update or state.is_delete:
        state.statement = state.statement.options(with_loader_criteria(
            Scoped, lambda cls: (cls.tenant_id == tenant) & (cls.site_id == site),
            include_aliases=True))


@event.listens_for(ScopedSession, "after_begin")
def transaction_scope(session, transaction, connection):
    if connection.dialect.name == "postgresql":
        scope = session.info["scope"]
        connection.execute(text("SELECT set_config('app.tenant_id', :tenant, true), "
                                "set_config('app.site_id', :site, true)"),
                           {"tenant": scope.tenant, "site": scope.site})


@event.listens_for(ScopedSession, "before_flush")
def enforce_writes(session, flush_context, instances):
    scope = session.info["scope"]
    for row in session.new | session.dirty | session.deleted:
        if isinstance(row, Scoped):
            if row in session.new:
                row.tenant_id = row.tenant_id or scope.tenant
                row.site_id = row.site_id or scope.site
            if (row.tenant_id, row.site_id) != (scope.tenant, scope.site):
                raise PermissionError("cross-scope write denied")
            # Existing single-ID references remain compatible; every ORM write
            # also verifies that its parent belongs to this immutable session scope.
            for fk in row.__table__.foreign_keys:
                parent = next((m.class_ for m in Base.registry.mappers
                               if m.local_table is fk.column.table), None)
                value = getattr(row, fk.parent.name)
                if value is None or parent is None or not issubclass(parent, Scoped):
                    continue
                pending = any(isinstance(p, parent) and getattr(p, fk.column.name) == value
                              for p in session.new)
                if not pending and session.get(parent, value) is None:
                    raise PermissionError("parent reference outside scope or missing")


#: Portable JSON column. Uses PostgreSQL JSONB (indexable, binary) in production
#: and falls back to the generic JSON type on SQLite for offline tests/demos.
#: Declared as a module-level variant so ORM models can share one definition.
def _portable_jsonb():
    from sqlalchemy.dialects.postgresql import JSONB

    return JSON().with_variant(JSONB(), "postgresql")


JSONBType = _portable_jsonb()


class Vector(TypeDecorator):
    """Fixed-dim float vector. pgvector on Postgres, JSON text on SQLite."""

    impl = String
    cache_ok = True

    def __init__(self, dim: int, *args, **kwargs):
        self.dim = dim
        super().__init__(*args, **kwargs)

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            from pgvector.sqlalchemy import Vector as PGVector

            return dialect.type_descriptor(PGVector(self.dim))
        return dialect.type_descriptor(String())

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if dialect.name == "postgresql":
            return list(value)
        return json.dumps(list(value))

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if dialect.name == "postgresql":
            return list(value)
        return json.loads(value)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
