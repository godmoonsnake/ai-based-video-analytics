"""E3 immutable correlation runs, hypotheses and case versions."""
from alembic import op
import sqlalchemy as sa

revision = "c300_lineage"
down_revision = "c200_processing"
branch_labels = depends_on = None


def scoped_table(name, *columns):
    """Frozen migration-local scoped table helper; do not import live revisions."""
    op.create_table(name, *columns, sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("site_id", sa.String(), nullable=False),
        sa.UniqueConstraint("id", "tenant_id", "site_id", name=f"uq_{name}_scope"),
        sa.ForeignKeyConstraint(["tenant_id", "site_id"], ["site.tenant_id", "site.id"], name=f"fk_{name}_site"))
    for column in ("tenant_id", "site_id"):
        op.create_index(f"ix_{name}_{column}", name, [column])
    if op.get_bind().dialect.name == "postgresql":
        op.execute(f'ALTER TABLE "{name}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{name}" FORCE ROW LEVEL SECURITY')
        expr = "tenant_id=current_setting('app.tenant_id',true) AND site_id=current_setting('app.site_id',true)"
        op.execute(f'CREATE POLICY site_scope ON "{name}" USING ({expr}) WITH CHECK ({expr})')


def upgrade():
    with op.batch_alter_table("global_track") as batch:
        batch.add_column(sa.Column("fingerprint", sa.String()))
        batch.add_column(sa.Column("run_id", sa.String()))
        batch.add_column(sa.Column("current", sa.Boolean(), nullable=False, server_default=sa.true()))
        batch.create_unique_constraint("uq_global_track_fingerprint", ["fingerprint"])
    with op.batch_alter_table("incident") as batch:
        batch.add_column(sa.Column("version", sa.Integer(), nullable=False, server_default="1"))
        batch.add_column(sa.Column("dedup_key", sa.String()))
        batch.create_unique_constraint("uq_incident_dedup_key", ["dedup_key"])
    scoped_table("correlation_run", sa.Column("id", sa.String(), primary_key=True),
        sa.Column("policy_version", sa.String(), nullable=False), sa.Column("model_version", sa.String(), nullable=False),
        sa.Column("created_at", sa.Float(), nullable=False), sa.Column("supersedes", sa.String()))
    scoped_table("correlation_hypothesis", sa.Column("id", sa.String(), primary_key=True),
        sa.Column("run_id", sa.String(), nullable=False), sa.Column("from_key", sa.JSON(), nullable=False),
        sa.Column("to_key", sa.JSON(), nullable=False), sa.Column("signals", sa.JSON(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False), sa.Column("disposition", sa.String(), nullable=False))
    scoped_table("incident_episode", sa.Column("id", sa.String(), primary_key=True),
        sa.Column("incident_id", sa.Integer(), nullable=False))
    scoped_table("incident_version", sa.Column("id", sa.String(), primary_key=True),
        sa.Column("incident_id", sa.Integer(), nullable=False), sa.Column("created_at", sa.Float(), nullable=False),
        sa.Column("requires_review", sa.Boolean(), nullable=False), sa.Column("snapshot", sa.JSON(), nullable=False))
    for table, column in (("correlation_hypothesis", "run_id"), ("incident_episode", "incident_id"),
                          ("incident_version", "incident_id")):
        op.create_index(f"ix_{table}_{column}", table, [column])


def downgrade():
    for table in ("incident_version", "incident_episode", "correlation_hypothesis", "correlation_run"):
        op.drop_table(table)
    with op.batch_alter_table("incident") as batch:
        batch.drop_constraint("uq_incident_dedup_key", type_="unique")
        batch.drop_column("version")
        batch.drop_column("dedup_key")
    with op.batch_alter_table("global_track") as batch:
        batch.drop_constraint("uq_global_track_fingerprint", type_="unique")
        for column in ("fingerprint", "run_id", "current"):
            batch.drop_column(column)
