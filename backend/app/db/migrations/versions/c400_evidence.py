"""E4 independent evidence and retention ledger."""
from alembic import op
import sqlalchemy as sa

revision = "c400_evidence"
down_revision = "c300_lineage"
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
    scoped_table("evidence_object", sa.Column("id", sa.String(), primary_key=True),
        sa.Column("event_id", sa.String(), nullable=False), sa.Column("kind", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False), sa.Column("object_key", sa.String()),
        sa.Column("sha256", sa.String()), sa.Column("size", sa.Integer()), sa.Column("mime", sa.String()),
        sa.Column("manifest", sa.JSON(), nullable=False), sa.Column("created_at", sa.Float(), nullable=False),
        sa.Column("captured_at", sa.Float()), sa.Column("expires_at", sa.Float(), nullable=False),
        sa.Column("parent_id", sa.String()), sa.Column("error", sa.String()))
    scoped_table("incident_evidence", sa.Column("id", sa.String(), primary_key=True),
        sa.Column("incident_id", sa.Integer(), nullable=False), sa.Column("evidence_id", sa.String(), nullable=False))
    scoped_table("evidence_access", sa.Column("id", sa.String(), primary_key=True),
        sa.Column("evidence_id", sa.String(), nullable=False), sa.Column("actor", sa.String(), nullable=False),
        sa.Column("action", sa.String(), nullable=False), sa.Column("at", sa.Float(), nullable=False),
        sa.Column("detail", sa.String()))
    scoped_table("retention_hold", sa.Column("id", sa.String(), primary_key=True),
        sa.Column("evidence_id", sa.String(), nullable=False), sa.Column("actor", sa.String(), nullable=False),
        sa.Column("reason", sa.String(), nullable=False), sa.Column("created_at", sa.Float(), nullable=False),
        sa.Column("released_at", sa.Float()))
    for table, columns in {"evidence_object": ["event_id"], "incident_evidence": ["incident_id", "evidence_id"],
                           "retention_hold": ["evidence_id"]}.items():
        for column in columns:
            op.create_index(f"ix_{table}_{column}", table, [column])


def downgrade():
    for table in ("retention_hold", "evidence_access", "incident_evidence", "evidence_object"):
        op.drop_table(table)
