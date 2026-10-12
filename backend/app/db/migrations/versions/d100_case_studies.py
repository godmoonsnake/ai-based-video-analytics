"""Pilot case study policies, observations and alert outbox."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "d100_case_studies"
down_revision = "c900_camera_health"
branch_labels = depends_on = None


def _scope(table):
    return [sa.Column("tenant_id", sa.String(), nullable=False),
            sa.Column("site_id", sa.String(), nullable=False),
            sa.ForeignKeyConstraint(["tenant_id", "site_id"],
                                    ["site.tenant_id", "site.id"],
                                    name=f"fk_{table}_site")]


def _secure(table):
    if op.get_bind().dialect.name == "postgresql":
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
        expr = "tenant_id=current_setting('app.tenant_id',true) AND site_id=current_setting('app.site_id',true)"
        op.execute(f'CREATE POLICY site_scope ON "{table}" USING ({expr}) WITH CHECK ({expr})')


def upgrade():
    op.create_table("case_source",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("source_type", sa.String(), nullable=False),
        sa.Column("instance", sa.String(), nullable=False),
        sa.Column("actor", sa.String(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        *_scope("case_source"), sa.UniqueConstraint("id", "tenant_id", "site_id", name="uq_case_source_scope"))
    op.create_table("case_policy",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("subject", sa.String(), nullable=False),
        sa.Column("zone", sa.String()), sa.Column("principal", sa.String()),
        sa.Column("allowed", sa.Boolean(), nullable=False),
        sa.Column("valid_from", sa.Float()), sa.Column("valid_until", sa.Float()),
        *_scope("case_policy"), sa.UniqueConstraint("id", "tenant_id", "site_id", name="uq_case_policy_scope"))
    op.create_table("case_observation",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("camera_id", sa.String(), nullable=False),
        sa.Column("zone", sa.String(), nullable=False),
        sa.Column("observed_at", sa.Float(), nullable=False),
        sa.Column("received_at", sa.Float(), nullable=False),
        sa.Column("source_type", sa.String(), nullable=False),
        sa.Column("source_instance", sa.String(), nullable=False),
        sa.Column("source_revision", sa.String(), nullable=False),
        sa.Column("policy_version", sa.String(), nullable=False),
        sa.Column("policy_snapshot", sa.JSON().with_variant(JSONB(), "postgresql"), nullable=False),
        sa.Column("synthetic", sa.Boolean(), nullable=False),
        sa.Column("signal", sa.JSON().with_variant(JSONB(), "postgresql"), nullable=False),
        sa.Column("decision", sa.String(), nullable=False),
        sa.Column("reason", sa.String(), nullable=False),
        sa.Column("incident_id", sa.Integer(), sa.ForeignKey("incident.id")),
        *_scope("case_observation"), sa.UniqueConstraint("id", "tenant_id", "site_id", name="uq_case_observation_scope"))
    op.create_table("case_alert",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("incident_id", sa.Integer(), sa.ForeignKey("incident.id"), nullable=False),
        sa.Column("channel", sa.String(), nullable=False),
        sa.Column("destination", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("accepted_at", sa.Float()), sa.Column("last_error", sa.String()),
        *_scope("case_alert"), sa.UniqueConstraint("id", "tenant_id", "site_id", name="uq_case_alert_scope"))
    for table in ("case_source", "case_policy", "case_observation", "case_alert"):
        op.create_index(f"ix_{table}_tenant_id", table, ["tenant_id"])
        op.create_index(f"ix_{table}_site_id", table, ["site_id"])
        _secure(table)
    for table, columns in (("case_policy", ("kind", "subject")),
                           ("case_observation", ("kind",))):
        for column in columns:
            op.create_index(f"ix_{table}_{column}", table, [column])


def downgrade():
    for table in ("case_alert", "case_observation", "case_policy", "case_source"):
        op.drop_table(table)
