"""baseline schema

The initial baseline migration for the DARSON intelligence layer. Creates the
full base schema (cameras/topology/zones, canonical events, embeddings, global
tracks, incidents + legacy incident graph, behavioural sequences, historical
patterns, feedback/audit).

This exists so `alembic upgrade head` produces the SAME schema that the ORM
metadata (Base.metadata.create_all) produces — eliminating the prior divergence
where only the incident-graph tables were migration-managed. The later revision
a7f0455fcb94 adds the normalized incident graph tables on top of this baseline.

The `track_embedding.vector` column uses pgvector on PostgreSQL and a portable
string (JSON-encoded list) on SQLite, matching app.db.session.Vector.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-09-29 14:52:00.000000
"""
from alembic import op
import sqlalchemy as sa

from app.config import get_settings

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None

_EMB_DIM = get_settings().embedding_dim


def _vector_type():
    """pgvector Vector on Postgres, String (JSON list) on SQLite — matches ORM."""
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        from pgvector.sqlalchemy import Vector as PGVector

        return PGVector(_EMB_DIM)
    return sa.String()


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "camera",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("site_id", sa.String(), nullable=True),
        sa.Column("lat", sa.Float(), nullable=True),
        sa.Column("lng", sa.Float(), nullable=True),
        sa.Column("x", sa.Float(), nullable=True),
        sa.Column("y", sa.Float(), nullable=True),
        sa.Column("fov_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "camera_edge",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("from_camera_id", sa.String(), nullable=False),
        sa.Column("to_camera_id", sa.String(), nullable=False),
        sa.Column("walk_seconds_min", sa.Float(), nullable=False),
        sa.Column("walk_seconds_max", sa.Float(), nullable=False),
        sa.Column("bidirectional", sa.Boolean(), nullable=True),
        sa.ForeignKeyConstraint(["from_camera_id"], ["camera.id"]),
        sa.ForeignKeyConstraint(["to_camera_id"], ["camera.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "zone",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("camera_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("polygon_json", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["camera_id"], ["camera.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "event",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("source_event_id", sa.String(), nullable=True),
        sa.Column("source_type", sa.String(), nullable=False),
        sa.Column("camera_id", sa.String(), nullable=False),
        sa.Column("track_local_id", sa.String(), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("label", sa.String(), nullable=True),
        sa.Column("sub_label", sa.String(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("start_time", sa.Float(), nullable=True),
        sa.Column("end_time", sa.Float(), nullable=True),
        sa.Column("ts", sa.Float(), nullable=False),
        sa.Column("bbox_json", sa.Text(), nullable=True),
        sa.Column("region_json", sa.Text(), nullable=True),
        sa.Column("zones_json", sa.Text(), nullable=True),
        sa.Column("velocity_angle", sa.Float(), nullable=True),
        sa.Column("avg_speed", sa.Float(), nullable=True),
        sa.Column("has_snapshot", sa.Boolean(), nullable=True),
        sa.Column("has_clip", sa.Boolean(), nullable=True),
        sa.Column("evidence_ref_json", sa.Text(), nullable=True),
        sa.Column("raw_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_event_source_event_id", "event", ["source_event_id"])
    op.create_index("ix_event_camera_id", "event", ["camera_id"])
    op.create_index("ix_event_track_local_id", "event", ["track_local_id"])
    op.create_index("ix_event_ts", "event", ["ts"])

    op.create_table(
        "track_embedding",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("event_id", sa.String(), nullable=True),
        sa.Column("camera_id", sa.String(), nullable=False),
        sa.Column("track_local_id", sa.String(), nullable=False),
        sa.Column("vector", _vector_type(), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["event_id"], ["event.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_track_embedding_camera_id", "track_embedding", ["camera_id"])
    op.create_index(
        "ix_track_embedding_track_local_id", "track_embedding", ["track_local_id"]
    )

    op.create_table(
        "global_track",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("first_seen", sa.Float(), nullable=True),
        sa.Column("last_seen", sa.Float(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "global_track_member",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("global_track_id", sa.Integer(), nullable=False),
        sa.Column("camera_id", sa.String(), nullable=False),
        sa.Column("track_local_id", sa.String(), nullable=False),
        sa.Column("join_score", sa.Float(), nullable=True),
        sa.Column("method", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(["global_track_id"], ["global_track.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "incident",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("status", sa.String(), nullable=True),
        sa.Column("start_time", sa.Float(), nullable=True),
        sa.Column("end_time", sa.Float(), nullable=True),
        sa.Column("priority", sa.String(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("primary_global_track_id", sa.Integer(), nullable=True),
        sa.Column("summary_text", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["primary_global_track_id"], ["global_track.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "incident_camera",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("incident_id", sa.Integer(), nullable=False),
        sa.Column("camera_id", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["incident_id"], ["incident.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "incident_event",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("incident_id", sa.Integer(), nullable=False),
        sa.Column("event_id", sa.String(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["incident_id"], ["incident.id"]),
        sa.ForeignKeyConstraint(["event_id"], ["event.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "incident_edge",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("incident_id", sa.Integer(), nullable=False),
        sa.Column("from_event_id", sa.String(), nullable=False),
        sa.Column("to_event_id", sa.String(), nullable=False),
        sa.Column("relation", sa.String(), nullable=False),
        sa.Column("delta_seconds", sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(["incident_id"], ["incident.id"]),
        sa.ForeignKeyConstraint(["from_event_id"], ["event.id"]),
        sa.ForeignKeyConstraint(["to_event_id"], ["event.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "behavioural_sequence",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("global_track_id", sa.Integer(), nullable=True),
        sa.Column("pattern_signature", sa.String(), nullable=True),
        sa.Column("steps_json", sa.Text(), nullable=True),
        sa.Column("anomaly_score", sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(["global_track_id"], ["global_track.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "historical_pattern",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("pattern_type", sa.String(), nullable=False),
        sa.Column("key_json", sa.Text(), nullable=True),
        sa.Column("count", sa.Integer(), nullable=True),
        sa.Column("first_seen", sa.Float(), nullable=True),
        sa.Column("last_seen", sa.Float(), nullable=True),
        sa.Column("score", sa.Float(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "operator_feedback",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("incident_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["incident_id"], ["incident.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("actor", sa.String(), nullable=True),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("target", sa.String(), nullable=True),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("audit_log")
    op.drop_table("operator_feedback")
    op.drop_table("historical_pattern")
    op.drop_table("behavioural_sequence")
    op.drop_table("incident_edge")
    op.drop_table("incident_event")
    op.drop_table("incident_camera")
    op.drop_table("incident")
    op.drop_table("global_track_member")
    op.drop_table("global_track")
    op.drop_index("ix_track_embedding_track_local_id", table_name="track_embedding")
    op.drop_index("ix_track_embedding_camera_id", table_name="track_embedding")
    op.drop_table("track_embedding")
    op.drop_index("ix_event_ts", table_name="event")
    op.drop_index("ix_event_track_local_id", table_name="event")
    op.drop_index("ix_event_camera_id", table_name="event")
    op.drop_index("ix_event_source_event_id", table_name="event")
    op.drop_table("event")
    op.drop_table("zone")
    op.drop_table("camera_edge")
    op.drop_table("camera")
