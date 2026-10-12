"""SQLAlchemy ORM models for the DARSON intelligence layer.

Schema covers: cameras + topology + zones, canonical events, track embeddings,
global (cross-camera) tracks, incidents + graph edges, behavioural sequences,
historical patterns, and lightweight feedback/audit (no RBAC/compliance).
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.config import get_settings
from app.db.session import Base, JSONBType, Vector, Scoped

_EMB_DIM = get_settings().embedding_dim


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Camera(Scoped, Base):
    __tablename__ = "camera"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    x: Mapped[float | None] = mapped_column(Float, nullable=True)
    y: Mapped[float | None] = mapped_column(Float, nullable=True)
    fov_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    zones: Mapped[list["Zone"]] = relationship(back_populates="camera")


class CameraEdge(Scoped, Base):
    """Topology edge: expected walking transit between two cameras."""

    __tablename__ = "camera_edge"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    from_camera_id: Mapped[str] = mapped_column(ForeignKey("camera.id"), nullable=False)
    to_camera_id: Mapped[str] = mapped_column(ForeignKey("camera.id"), nullable=False)
    walk_seconds_min: Mapped[float] = mapped_column(Float, nullable=False)
    walk_seconds_max: Mapped[float] = mapped_column(Float, nullable=False)
    bidirectional: Mapped[bool] = mapped_column(Boolean, default=True)


class Zone(Scoped, Base):
    __tablename__ = "zone"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    camera_id: Mapped[str] = mapped_column(ForeignKey("camera.id"), nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    kind: Mapped[str] = mapped_column(String, nullable=False)  # restricted|transit|entry|exit
    polygon_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    camera: Mapped[Camera] = relationship(back_populates="zones")


class Event(Scoped, Base):
    """Canonical normalized event (source-agnostic)."""

    __tablename__ = "event"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # our event_id (uuid)
    source_event_id: Mapped[str | None] = mapped_column(String, index=True)
    source_type: Mapped[str] = mapped_column(String, nullable=False)  # mock|frigate
    camera_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    track_local_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    label: Mapped[str | None] = mapped_column(String)
    sub_label: Mapped[str | None] = mapped_column(String)
    confidence: Mapped[float | None] = mapped_column(Float)
    start_time: Mapped[float | None] = mapped_column(Float)
    end_time: Mapped[float | None] = mapped_column(Float)
    ts: Mapped[float] = mapped_column(Float, index=True, nullable=False)  # observed time
    bbox_json: Mapped[str | None] = mapped_column(Text)
    region_json: Mapped[str | None] = mapped_column(Text)
    zones_json: Mapped[str | None] = mapped_column(Text)
    velocity_angle: Mapped[float | None] = mapped_column(Float)
    avg_speed: Mapped[float | None] = mapped_column(Float)
    has_snapshot: Mapped[bool] = mapped_column(Boolean, default=False)
    has_clip: Mapped[bool] = mapped_column(Boolean, default=False)
    evidence_ref_json: Mapped[str | None] = mapped_column(Text)
    raw_json: Mapped[str | None] = mapped_column(Text)
    dedup_key: Mapped[str | None] = mapped_column(String, unique=True)
    source_instance: Mapped[str | None] = mapped_column(String)
    source_revision: Mapped[str | None] = mapped_column(String)
    event_kind: Mapped[str | None] = mapped_column(String)
    payload_digest: Mapped[str | None] = mapped_column(String)
    received_at: Mapped[float | None] = mapped_column(Float)
    schema_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class TrackEmbedding(Scoped, Base):
    __tablename__ = "track_embedding"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str | None] = mapped_column(ForeignKey("event.id"), nullable=True)
    camera_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    track_local_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    vector: Mapped[list[float]] = mapped_column(Vector(_EMB_DIM), nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class GlobalTrack(Scoped, Base):
    __tablename__ = "global_track"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    first_seen: Mapped[float | None] = mapped_column(Float)
    last_seen: Mapped[float | None] = mapped_column(Float)
    confidence: Mapped[float | None] = mapped_column(Float)
    fingerprint: Mapped[str | None] = mapped_column(String, unique=True)
    run_id: Mapped[str | None] = mapped_column(String)
    current: Mapped[bool] = mapped_column(Boolean, default=True)

    members: Mapped[list["GlobalTrackMember"]] = relationship(back_populates="global_track")


class GlobalTrackMember(Scoped, Base):
    __tablename__ = "global_track_member"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    global_track_id: Mapped[int] = mapped_column(ForeignKey("global_track.id"), nullable=False)
    camera_id: Mapped[str] = mapped_column(String, nullable=False)
    track_local_id: Mapped[str] = mapped_column(String, nullable=False)
    join_score: Mapped[float | None] = mapped_column(Float)
    method: Mapped[str | None] = mapped_column(String)  # explainability: how it was merged

    global_track: Mapped[GlobalTrack] = relationship(back_populates="members")


class Incident(Scoped, Base):
    __tablename__ = "incident"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    status: Mapped[str] = mapped_column(String, default="open")  # open|confirmed|dismissed
    category: Mapped[str] = mapped_column(String, default="review")
    start_time: Mapped[float | None] = mapped_column(Float)
    end_time: Mapped[float | None] = mapped_column(Float)
    priority: Mapped[str | None] = mapped_column(String)  # low|medium|high|critical
    confidence: Mapped[float | None] = mapped_column(Float)
    primary_global_track_id: Mapped[int | None] = mapped_column(
        ForeignKey("global_track.id"), nullable=True
    )
    summary_text: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, default=1)
    dedup_key: Mapped[str | None] = mapped_column(String, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    cameras: Mapped[list["IncidentCamera"]] = relationship(back_populates="incident")
    events: Mapped[list["IncidentEvent"]] = relationship(back_populates="incident")
    edges: Mapped[list["IncidentEdge"]] = relationship(back_populates="incident")
    nodes: Mapped[list["IncidentNode"]] = relationship(back_populates="incident")
    graph_edges: Mapped[list["IncidentGraphEdge"]] = relationship(back_populates="incident")
    state_transitions: Mapped[list["IncidentStateTransition"]] = relationship(
        back_populates="incident"
    )


class IncidentCamera(Scoped, Base):
    __tablename__ = "incident_camera"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    incident_id: Mapped[int] = mapped_column(ForeignKey("incident.id"), nullable=False)
    camera_id: Mapped[str] = mapped_column(String, nullable=False)

    incident: Mapped[Incident] = relationship(back_populates="cameras")


class IncidentEvent(Scoped, Base):
    __tablename__ = "incident_event"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    incident_id: Mapped[int] = mapped_column(ForeignKey("incident.id"), nullable=False)
    event_id: Mapped[str] = mapped_column(ForeignKey("event.id"), nullable=False)
    role: Mapped[str] = mapped_column(String, nullable=False)  # trigger|context|evidence

    incident: Mapped[Incident] = relationship(back_populates="events")


class IncidentEdge(Scoped, Base):
    __tablename__ = "incident_edge"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    incident_id: Mapped[int] = mapped_column(ForeignKey("incident.id"), nullable=False)
    from_event_id: Mapped[str] = mapped_column(ForeignKey("event.id"), nullable=False)
    to_event_id: Mapped[str] = mapped_column(ForeignKey("event.id"), nullable=False)
    relation: Mapped[str] = mapped_column(String, nullable=False)  # temporal_next|same_track|zone_transition
    delta_seconds: Mapped[float | None] = mapped_column(Float)

    incident: Mapped[Incident] = relationship(back_populates="edges")


class IncidentNode(Scoped, Base):
    """A typed node in an incident's evidence graph.

    Heterogeneous node referencing an existing domain entity. `ref_id` is the
    string identity of the referenced entity, interpreted per `node_type`:
      - event    -> Event.id (uuid string)
      - track    -> GlobalTrack.id (as string)
      - camera   -> Camera.id
      - zone     -> "<camera_id>:<zone_name>"
      - incident -> Incident.id (as string); the graph root node
    Nodes are scoped to one incident so the graph is self-contained and a rebuild
    can replace an incident's graph atomically. `attributes` holds a small,
    display-ready JSON snapshot (e.g. event_type, ts, zone kind) so the UI/API
    need not re-join every source table.
    """

    __tablename__ = "incident_node"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    incident_id: Mapped[int] = mapped_column(
        ForeignKey("incident.id"), index=True, nullable=False
    )
    node_type: Mapped[str] = mapped_column(String, nullable=False)  # event|track|camera|zone|incident
    ref_id: Mapped[str] = mapped_column(String, nullable=False)
    attributes: Mapped[dict | None] = mapped_column(JSONBType, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    incident: Mapped[Incident] = relationship(back_populates="nodes")


class IncidentGraphEdge(Scoped, Base):
    """A typed, explainable edge between two IncidentNodes.

    edge_type is one of:
      event_to_track | track_to_camera | event_to_zone | temporal |
      movement | correlation | sequence | incident_membership
    `confidence` is populated for inferred edges (correlation/movement/sequence);
    structural edges (membership/containment) leave it null. `evidence` is a JSONB
    object of the signals that justify the edge (topology transition, temporal
    gap, appearance similarity, correlation sub-scores, behaviour risk, etc.) so
    every inferred edge is explainable from stored data.
    """

    __tablename__ = "incident_graph_edge"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    incident_id: Mapped[int] = mapped_column(
        ForeignKey("incident.id"), index=True, nullable=False
    )
    source_node_id: Mapped[int] = mapped_column(
        ForeignKey("incident_node.id"), nullable=False
    )
    target_node_id: Mapped[int] = mapped_column(
        ForeignKey("incident_node.id"), nullable=False
    )
    edge_type: Mapped[str] = mapped_column(String, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    evidence: Mapped[dict | None] = mapped_column(JSONBType, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    incident: Mapped[Incident] = relationship(back_populates="graph_edges")
    source_node: Mapped[IncidentNode] = relationship(foreign_keys=[source_node_id])
    target_node: Mapped[IncidentNode] = relationship(foreign_keys=[target_node_id])


class IncidentStateTransition(Scoped, Base):
    """Append-only history of incident lifecycle state changes.

    Records every accepted transition of an incident through the human-in-the-loop
    lifecycle (open -> triage -> confirmed|dismissed). This table is the audit
    trail for review decisions; it is never mutated in place. `reviewer` is a
    free-form operator handle/role label (e.g. "operator", "shift_lead"), NOT a
    person's identity — no PII beyond an optional handle is stored.
    """

    __tablename__ = "incident_state_transition"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    incident_id: Mapped[int] = mapped_column(
        ForeignKey("incident.id"), index=True, nullable=False
    )
    from_state: Mapped[str | None] = mapped_column(String, nullable=True)
    to_state: Mapped[str] = mapped_column(String, nullable=False)
    action: Mapped[str] = mapped_column(String, nullable=False)  # start_triage|confirm|dismiss|reopen
    reviewer: Mapped[str | None] = mapped_column(String, nullable=True)  # handle/role only, no PII
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    incident: Mapped[Incident] = relationship(back_populates="state_transitions")


class BehaviouralSequence(Scoped, Base):
    __tablename__ = "behavioural_sequence"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    global_track_id: Mapped[int | None] = mapped_column(ForeignKey("global_track.id"), nullable=True)
    pattern_signature: Mapped[str | None] = mapped_column(String)
    steps_json: Mapped[str | None] = mapped_column(Text)
    anomaly_score: Mapped[float | None] = mapped_column(Float)


class HistoricalPattern(Scoped, Base):
    __tablename__ = "historical_pattern"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pattern_type: Mapped[str] = mapped_column(String, nullable=False)
    key_json: Mapped[str | None] = mapped_column(Text)
    count: Mapped[int] = mapped_column(Integer, default=0)
    first_seen: Mapped[float | None] = mapped_column(Float)
    last_seen: Mapped[float | None] = mapped_column(Float)
    score: Mapped[float | None] = mapped_column(Float)


class OperatorFeedback(Scoped, Base):
    """Lightweight human-in-the-loop feedback (no RBAC)."""

    __tablename__ = "operator_feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    incident_id: Mapped[int] = mapped_column(ForeignKey("incident.id"), nullable=False)
    action: Mapped[str] = mapped_column(String, nullable=False)  # confirm|dismiss|note
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class AuditLog(Scoped, Base):
    """Lightweight audit trail (no compliance/enterprise features)."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor: Mapped[str] = mapped_column(String, default="operator")
    action: Mapped[str] = mapped_column(String, nullable=False)
    target: Mapped[str | None] = mapped_column(String)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
