from sqlalchemy import Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from app.db.session import Base, Scoped, JSONBType


class EvidenceObject(Scoped, Base):
    __tablename__ = "evidence_object"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    event_id: Mapped[str] = mapped_column(String, index=True)
    kind: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="requested")
    object_key: Mapped[str | None] = mapped_column(String)
    sha256: Mapped[str | None] = mapped_column(String)
    size: Mapped[int | None] = mapped_column(Integer)
    mime: Mapped[str | None] = mapped_column(String)
    manifest: Mapped[dict] = mapped_column(JSONBType)
    created_at: Mapped[float] = mapped_column(Float)
    captured_at: Mapped[float | None] = mapped_column(Float)
    expires_at: Mapped[float] = mapped_column(Float)
    parent_id: Mapped[str | None] = mapped_column(String)
    error: Mapped[str | None] = mapped_column(String)


class IncidentEvidence(Scoped, Base):
    __tablename__ = "incident_evidence"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    incident_id: Mapped[int] = mapped_column(Integer, index=True)
    evidence_id: Mapped[str] = mapped_column(String, index=True)


class EvidenceAccess(Scoped, Base):
    __tablename__ = "evidence_access"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    evidence_id: Mapped[str] = mapped_column(String)
    actor: Mapped[str] = mapped_column(String)
    action: Mapped[str] = mapped_column(String)
    at: Mapped[float] = mapped_column(Float)
    detail: Mapped[str | None] = mapped_column(String)


class RetentionHold(Scoped, Base):
    __tablename__ = "retention_hold"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    evidence_id: Mapped[str] = mapped_column(String, index=True)
    actor: Mapped[str] = mapped_column(String)
    reason: Mapped[str] = mapped_column(String)
    created_at: Mapped[float] = mapped_column(Float)
    released_at: Mapped[float | None] = mapped_column(Float)
