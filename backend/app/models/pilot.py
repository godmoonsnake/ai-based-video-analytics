"""Single-camera pilot rules and durable guard tasks; no identity inference."""

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.db.session import Base, Scoped, JSONBType


class PilotRule(Scoped, Base):
    __tablename__ = "pilot_rule"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    camera_id: Mapped[str] = mapped_column(ForeignKey("camera.id"))
    zone_name: Mapped[str] = mapped_column(String)
    post_id: Mapped[str] = mapped_column(ForeignKey("security_post.id"))
    schedule: Mapped[dict] = mapped_column(JSONBType)
    instruction: Mapped[str] = mapped_column(Text)
    acknowledgement_seconds: Mapped[int] = mapped_column(Integer)
    priority: Mapped[str] = mapped_column(String, default="high")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    version: Mapped[int] = mapped_column(Integer, default=1)


class PilotContact(Scoped, Base):
    __tablename__ = "pilot_contact"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    subject: Mapped[str] = mapped_column(String, index=True)
    channel: Mapped[str] = mapped_column(String)
    destination: Mapped[str] = mapped_column(String)
    last_registered_at: Mapped[float | None] = mapped_column(Float)


class PilotCase(Scoped, Base):
    __tablename__ = "pilot_case"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    incident_id: Mapped[int] = mapped_column(ForeignKey("incident.id"), index=True)
    rule_id: Mapped[str] = mapped_column(ForeignKey("pilot_rule.id"))
    rule_snapshot: Mapped[dict] = mapped_column(JSONBType)
    trigger_event_id: Mapped[str] = mapped_column(ForeignKey("event.id"))
    source_instance: Mapped[str] = mapped_column(String)
    track_local_id: Mapped[str] = mapped_column(String)
    owner: Mapped[str | None] = mapped_column(String)
    state: Mapped[str] = mapped_column(String, default="open")
    created_at: Mapped[float] = mapped_column(Float)
    acknowledgement_deadline: Mapped[float] = mapped_column(Float)
    acknowledged_at: Mapped[float | None] = mapped_column(Float)
    first_presented_at: Mapped[float | None] = mapped_column(Float)
    outcome: Mapped[str | None] = mapped_column(String)
    outcome_note: Mapped[str | None] = mapped_column(Text)
    outcome_actor: Mapped[str | None] = mapped_column(String)
    resolved_at: Mapped[float | None] = mapped_column(Float)
    label_verified_at: Mapped[float | None] = mapped_column(Float)


class PilotNotice(Scoped, Base):
    __tablename__ = "pilot_notice"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    case_id: Mapped[str | None] = mapped_column(ForeignKey("pilot_case.id"), index=True)
    camera_id: Mapped[str | None] = mapped_column(String)
    recipient: Mapped[str] = mapped_column(String)
    channel: Mapped[str] = mapped_column(String)
    destination: Mapped[str] = mapped_column(String)
    reason: Mapped[str] = mapped_column(String)
    message: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String, default="queued")
    created_at: Mapped[float] = mapped_column(Float)
    accepted_at: Mapped[float | None] = mapped_column(Float)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    failure_class: Mapped[str | None] = mapped_column(String)


class PilotMaintenance(Scoped, Base):
    __tablename__ = "pilot_maintenance"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    camera_id: Mapped[str | None] = mapped_column(String)
    last_run_at: Mapped[float] = mapped_column(Float)
