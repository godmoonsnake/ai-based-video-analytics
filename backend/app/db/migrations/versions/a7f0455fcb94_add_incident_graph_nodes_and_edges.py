"""add incident graph nodes and edges

Adds the normalized incident graph layer:
  - incident_node        (typed heterogeneous nodes: event|track|camera|zone|incident)
  - incident_graph_edge  (typed, explainable edges with confidence + JSONB evidence)

This migration is ADDITIVE ONLY. It does not alter or drop any existing table,
so the existing incident / event / track / correlation schema is untouched.

`evidence`/`attributes` use PostgreSQL JSONB in production and generic JSON on
SQLite (portable variant), matching app.db.session.JSONBType.

Revision ID: a7f0455fcb94
Revises:
Create Date: 2026-09-29 14:39:40.534683
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "a7f0455fcb94"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def _jsonb():
    """JSONB on Postgres, generic JSON elsewhere (SQLite)."""
    return sa.JSON().with_variant(JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "incident_node",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("incident_id", sa.Integer(), nullable=False),
        sa.Column("node_type", sa.String(), nullable=False),
        sa.Column("ref_id", sa.String(), nullable=False),
        sa.Column("attributes", _jsonb(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["incident_id"], ["incident.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_incident_node_incident_id", "incident_node", ["incident_id"])
    op.create_index("ix_incident_node_type_ref", "incident_node", ["node_type", "ref_id"])

    op.create_table(
        "incident_graph_edge",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("incident_id", sa.Integer(), nullable=False),
        sa.Column("source_node_id", sa.Integer(), nullable=False),
        sa.Column("target_node_id", sa.Integer(), nullable=False),
        sa.Column("edge_type", sa.String(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("evidence", _jsonb(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["incident_id"], ["incident.id"]),
        sa.ForeignKeyConstraint(["source_node_id"], ["incident_node.id"]),
        sa.ForeignKeyConstraint(["target_node_id"], ["incident_node.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_incident_graph_edge_incident_id", "incident_graph_edge", ["incident_id"]
    )
    op.create_index(
        "ix_incident_graph_edge_type", "incident_graph_edge", ["edge_type"]
    )


def downgrade() -> None:
    op.drop_index("ix_incident_graph_edge_type", table_name="incident_graph_edge")
    op.drop_index("ix_incident_graph_edge_incident_id", table_name="incident_graph_edge")
    op.drop_table("incident_graph_edge")
    op.drop_index("ix_incident_node_type_ref", table_name="incident_node")
    op.drop_index("ix_incident_node_incident_id", table_name="incident_node")
    op.drop_table("incident_node")
