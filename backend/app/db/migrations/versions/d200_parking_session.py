"""Short-lived parking vehicle sessions for the pilot rule workflow."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "d200_parking_session"
down_revision = "d100_case_studies"
branch_labels = depends_on = None


def upgrade():
    portable_json = sa.JSON().with_variant(JSONB(), "postgresql")
    op.create_table(
        "parking_session",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("arrival_signal", portable_json, nullable=False),
        sa.Column("plate", sa.String(), nullable=False),
        sa.Column("vehicle_type", sa.String(), nullable=False),
        sa.Column("camera_id", sa.String(), nullable=False),
        sa.Column("zone", sa.String(), nullable=False),
        sa.Column("arrived_at", sa.Float(), nullable=False),
        sa.Column("expires_at", sa.Float(), nullable=False),
        sa.Column("departed_at", sa.Float()),
        sa.Column("exit_refs", portable_json, nullable=False),
        sa.Column("flagged_refs", portable_json, nullable=False),
        sa.Column("escalated_refs", portable_json, nullable=False),
        sa.Column("authorized_refs", portable_json, nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("site_id", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id", "site_id"], ["site.tenant_id", "site.id"],
                                name="fk_parking_session_site"),
        sa.UniqueConstraint("id", "tenant_id", "site_id", name="uq_parking_session_scope"),
    )
    for column in ("plate", "tenant_id", "site_id"):
        op.create_index(f"ix_parking_session_{column}", "parking_session", [column])
    if op.get_bind().dialect.name == "postgresql":
        op.execute('ALTER TABLE "parking_session" ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE "parking_session" FORCE ROW LEVEL SECURITY')
        expr = "tenant_id=current_setting('app.tenant_id',true) AND site_id=current_setting('app.site_id',true)"
        op.execute(f'CREATE POLICY site_scope ON "parking_session" USING ({expr}) WITH CHECK ({expr})')


def downgrade():
    op.drop_table("parking_session")
