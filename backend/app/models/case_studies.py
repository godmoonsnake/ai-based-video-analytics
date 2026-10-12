"""Site-scoped policies, observations and alert outbox for pilot case studies."""
from sqlalchemy import Boolean, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base, JSONBType, Scoped


class CaseSource(Scoped, Base):
    __tablename__ = "case_source"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    source_type: Mapped[str] = mapped_column(String)
    instance: Mapped[str] = mapped_column(String)
    actor: Mapped[str] = mapped_column(String)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class CasePolicy(Scoped, Base):
    __tablename__ = "case_policy"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    kind: Mapped[str] = mapped_column(String, index=True)
    subject: Mapped[str] = mapped_column(String, index=True)
    zone: Mapped[str | None] = mapped_column(String)
    principal: Mapped[str | None] = mapped_column(String)
    allowed: Mapped[bool] = mapped_column(Boolean, default=True)
    valid_from: Mapped[float | None] = mapped_column(Float)
    valid_until: Mapped[float | None] = mapped_column(Float)


class CaseObservation(Scoped, Base):
    __tablename__ = "case_observation"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    kind: Mapped[str] = mapped_column(String, index=True)
    camera_id: Mapped[str] = mapped_column(String)
    zone: Mapped[str] = mapped_column(String)
    observed_at: Mapped[float] = mapped_column(Float)
    received_at: Mapped[float] = mapped_column(Float)
    source_type: Mapped[str] = mapped_column(String)
    source_instance: Mapped[str] = mapped_column(String)
    source_revision: Mapped[str] = mapped_column(String)
    policy_version: Mapped[str] = mapped_column(String)
    policy_snapshot: Mapped[dict] = mapped_column(JSONBType)
    synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    signal: Mapped[dict] = mapped_column(JSONBType)
    decision: Mapped[str] = mapped_column(String)
    reason: Mapped[str] = mapped_column(String)
    incident_id: Mapped[int | None] = mapped_column(ForeignKey("incident.id"))


class CaseAlert(Scoped, Base):
    __tablename__ = "case_alert"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    incident_id: Mapped[int] = mapped_column(ForeignKey("incident.id"))
    channel: Mapped[str] = mapped_column(String)
    destination: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="queued")
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    accepted_at: Mapped[float | None] = mapped_column(Float)
    last_error: Mapped[str | None] = mapped_column(String)


class ParkingSession(Scoped, Base):
    """Short-lived vehicle visit; refs are detector-local, not person identities."""
    __tablename__ = "parking_session"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    arrival_signal: Mapped[dict] = mapped_column(JSONBType)
    plate: Mapped[str] = mapped_column(String, index=True)
    vehicle_type: Mapped[str] = mapped_column(String)
    camera_id: Mapped[str] = mapped_column(String)
    zone: Mapped[str] = mapped_column(String)
    arrived_at: Mapped[float] = mapped_column(Float)
    expires_at: Mapped[float] = mapped_column(Float)
    departed_at: Mapped[float | None] = mapped_column(Float)
    exit_refs: Mapped[list] = mapped_column(JSONBType, default=list)
    flagged_refs: Mapped[list] = mapped_column(JSONBType, default=list)
    escalated_refs: Mapped[list] = mapped_column(JSONBType, default=list)
    authorized_refs: Mapped[list] = mapped_column(JSONBType, default=list)
