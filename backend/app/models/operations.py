from sqlalchemy import Boolean, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from app.db.session import Base, Scoped, JSONBType


class SecurityPost(Scoped, Base):
    __tablename__ = "security_post"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    instructions: Mapped[str] = mapped_column(String)
    floor: Mapped[str | None] = mapped_column(String)
    block: Mapped[str | None] = mapped_column(String)


class Shift(Scoped, Base):
    __tablename__ = "shift"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    post_id: Mapped[str] = mapped_column(ForeignKey("security_post.id"))
    subject: Mapped[str] = mapped_column(String)
    starts_at: Mapped[float] = mapped_column(Float)
    ends_at: Mapped[float] = mapped_column(Float)
    label: Mapped[str] = mapped_column(String, default="custom")
    cancelled_at: Mapped[float | None] = mapped_column(Float)


class SOP(Scoped, Base):
    __tablename__ = "sop"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    version: Mapped[int] = mapped_column(Integer)


class SOPStep(Scoped, Base):
    __tablename__ = "sop_step"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    sop_id: Mapped[str] = mapped_column(ForeignKey("sop.id"))
    ordinal: Mapped[int] = mapped_column(Integer)
    instruction: Mapped[str] = mapped_column(String)
    required: Mapped[bool] = mapped_column(Boolean, default=True)


class SLAPolicy(Scoped, Base):
    __tablename__ = "sla_policy"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    sop_id: Mapped[str] = mapped_column(ForeignKey("sop.id"))
    name: Mapped[str] = mapped_column(String)
    version: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[float] = mapped_column(Float)
    approved_for_use: Mapped[bool] = mapped_column(Boolean, default=False)
    definition: Mapped[dict] = mapped_column(JSONBType)


class ResponseEpisode(Scoped, Base):
    __tablename__ = "response_episode"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    incident_id: Mapped[int] = mapped_column(ForeignKey("incident.id"), index=True)
    state: Mapped[str] = mapped_column(String, default="unassigned")
    owner: Mapped[str | None] = mapped_column(String)
    post_id: Mapped[str | None] = mapped_column(ForeignKey("security_post.id"))
    shift_id: Mapped[str | None] = mapped_column(ForeignKey("shift.id"))
    policy_id: Mapped[str] = mapped_column(ForeignKey("sla_policy.id"))
    policy_snapshot: Mapped[dict] = mapped_column(JSONBType)
    steps_done: Mapped[list] = mapped_column(JSONBType, default=list)
    created_at: Mapped[float] = mapped_column(Float)
    acknowledged_at: Mapped[float | None] = mapped_column(Float)
    responded_at: Mapped[float | None] = mapped_column(Float)
    resolved_at: Mapped[float | None] = mapped_column(Float)


class IncidentAssignment(Scoped, Base):
    __tablename__ = "incident_assignment"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    incident_id: Mapped[int] = mapped_column(ForeignKey("incident.id"), index=True)
    episode_id: Mapped[str] = mapped_column(ForeignKey("response_episode.id"))
    actor: Mapped[str] = mapped_column(String)
    previous_owner: Mapped[str | None] = mapped_column(String)
    owner: Mapped[str] = mapped_column(String)
    reason: Mapped[str] = mapped_column(String)
    at: Mapped[float] = mapped_column(Float)


class IncidentAction(Scoped, Base):
    __tablename__ = "incident_action"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    incident_id: Mapped[int] = mapped_column(ForeignKey("incident.id"), index=True)
    episode_id: Mapped[str | None] = mapped_column(ForeignKey("response_episode.id"))
    actor: Mapped[str] = mapped_column(String)
    action: Mapped[str] = mapped_column(String)
    at: Mapped[float] = mapped_column(Float)
    request_digest: Mapped[str] = mapped_column(String)
    detail: Mapped[dict] = mapped_column(JSONBType)
    result: Mapped[dict] = mapped_column(JSONBType)


class SLAEscalation(Scoped, Base):
    """Durable, idempotent record that an operational deadline was missed."""
    __tablename__ = "sla_escalation"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    episode_id: Mapped[str] = mapped_column(ForeignKey("response_episode.id"), index=True)
    incident_id: Mapped[int] = mapped_column(ForeignKey("incident.id"), index=True)
    stage: Mapped[str] = mapped_column(String)
    deadline_at: Mapped[float] = mapped_column(Float)
    recorded_at: Mapped[float] = mapped_column(Float)
    owner_at_deadline: Mapped[str | None] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="open")


class SLANotification(Scoped, Base):
    __tablename__ = "sla_notification"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    escalation_id: Mapped[str] = mapped_column(ForeignKey("sla_escalation.id"), unique=True)
    incident_id: Mapped[int] = mapped_column(ForeignKey("incident.id"), index=True)
    episode_id: Mapped[str] = mapped_column(ForeignKey("response_episode.id"), index=True)
    escalation_level: Mapped[int] = mapped_column(Integer, default=1)
    provider: Mapped[str] = mapped_column(String)
    destination_ref: Mapped[str | None] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="queued")
    attempted_at: Mapped[float | None] = mapped_column(Float)
    accepted_at: Mapped[float | None] = mapped_column(Float)
    acknowledged_at: Mapped[float | None] = mapped_column(Float)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    failure_class: Mapped[str | None] = mapped_column(String)
    idempotency_key: Mapped[str] = mapped_column(String, unique=True)


class SLANotificationAttempt(Scoped, Base):
    __tablename__ = "sla_notification_attempt"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    notification_id: Mapped[str] = mapped_column(ForeignKey("sla_notification.id"), index=True)
    at: Mapped[float] = mapped_column(Float)
    provider: Mapped[str] = mapped_column(String)
    result: Mapped[str] = mapped_column(String)
    failure_class: Mapped[str | None] = mapped_column(String)


class IncidentExport(Scoped, Base):
    __tablename__ = "incident_export"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    incident_id: Mapped[int] = mapped_column(ForeignKey("incident.id"), index=True)
    case_version: Mapped[int] = mapped_column(Integer)
    format: Mapped[str] = mapped_column(String)
    requested_by: Mapped[str] = mapped_column(String)
    idempotency_key: Mapped[str] = mapped_column(String, unique=True)
    snapshot: Mapped[dict] = mapped_column(JSONBType)
    status: Mapped[str] = mapped_column(String, default="queued")
    object_key: Mapped[str | None] = mapped_column(String)
    sha256: Mapped[str | None] = mapped_column(String)
    size: Mapped[int | None] = mapped_column(Integer)
    requested_at: Mapped[float] = mapped_column(Float)
    completed_at: Mapped[float | None] = mapped_column(Float)
    expires_at: Mapped[float] = mapped_column(Float)
    failure_class: Mapped[str | None] = mapped_column(String)


class CameraHealthCurrent(Scoped, Base):
    __tablename__ = "camera_health_current"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    camera_id: Mapped[str] = mapped_column(ForeignKey("camera.id"), index=True)
    state: Mapped[str] = mapped_column(String, default="unknown")
    stream_state: Mapped[str] = mapped_column(String, default="unknown")
    video_state: Mapped[str] = mapped_column(String, default="unknown")
    recording_state: Mapped[str] = mapped_column(String, default="unknown")
    evidence_state: Mapped[str] = mapped_column(String, default="unknown")
    maintenance: Mapped[bool] = mapped_column(Boolean, default=False)
    frame_arrival_fps: Mapped[float | None] = mapped_column(Float)
    source_to_darson_lag_seconds: Mapped[float | None] = mapped_column(Float)
    event_to_incident_latency_seconds: Mapped[float | None] = mapped_column(Float)
    recording_gap_seconds: Mapped[float | None] = mapped_column(Float)
    evidence_capture_success_rate: Mapped[float | None] = mapped_column(Float)
    last_frame_at: Mapped[float | None] = mapped_column(Float)
    last_recording_at: Mapped[float | None] = mapped_column(Float)
    last_evidence_at: Mapped[float | None] = mapped_column(Float)
    updated_at: Mapped[float] = mapped_column(Float)
    metrics: Mapped[dict] = mapped_column(JSONBType)


class CameraHealthSample(Scoped, Base):
    __tablename__ = "camera_health_sample"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    camera_id: Mapped[str] = mapped_column(ForeignKey("camera.id"), index=True)
    checked_at: Mapped[float] = mapped_column(Float, index=True)
    state: Mapped[str] = mapped_column(String)
    stream_state: Mapped[str] = mapped_column(String)
    video_state: Mapped[str] = mapped_column(String)
    recording_state: Mapped[str] = mapped_column(String)
    evidence_state: Mapped[str] = mapped_column(String)
    maintenance: Mapped[bool] = mapped_column(Boolean, default=False)
    metrics: Mapped[dict] = mapped_column(JSONBType)


class MaintenanceWindow(Scoped, Base):
    __tablename__ = "maintenance_window"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    camera_id: Mapped[str | None] = mapped_column(ForeignKey("camera.id"))
    starts_at: Mapped[float] = mapped_column(Float)
    ends_at: Mapped[float] = mapped_column(Float)
    reason: Mapped[str] = mapped_column(String)
    created_by: Mapped[str] = mapped_column(String)
    created_at: Mapped[float] = mapped_column(Float)
