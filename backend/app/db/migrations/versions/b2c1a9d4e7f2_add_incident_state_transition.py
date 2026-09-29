"""add incident state transition history

Adds the incident lifecycle audit table `incident_state_transition` — the
append-only history of open -> triage -> confirmed|dismissed transitions with
reviewer/action metadata (no PII beyond an optional operator handle/role).

Additive only; no existing table is altered.

Revision ID: b2c1a9d4e7f2
Revises: a7f0455fcb94
Create Date: 2026-09-29 14:55:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "b2c1a9d4e7f2"
down_revision = "a7f0455fcb94"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "incident_state_transition",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("incident_id", sa.Integer(), nullable=False),
        sa.Column("from_state", sa.String(), nullable=True),
        sa.Column("to_state", sa.String(), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("reviewer", sa.String(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["incident_id"], ["incident.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_incident_state_transition_incident_id",
        "incident_state_transition",
        ["incident_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_incident_state_transition_incident_id",
        table_name="incident_state_transition",
    )
    op.drop_table("incident_state_transition")
