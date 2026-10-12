"""E1 scoped data and identity grants; rejects ambiguous legacy sites."""
from alembic import op
import sqlalchemy as sa

revision = "c100_scope_security"
down_revision = "b2c1a9d4e7f2"
branch_labels = depends_on = None

TABLES = (
    "camera", "camera_edge", "zone", "event", "track_embedding", "global_track",
    "global_track_member", "incident", "incident_camera", "incident_event", "incident_edge",
    "incident_node", "incident_graph_edge", "incident_state_transition",
    "behavioural_sequence", "historical_pattern", "operator_feedback", "audit_log",
)


def upgrade():
    bind = op.get_bind()
    sites = set(bind.execute(sa.text("SELECT DISTINCT site_id FROM camera WHERE site_id IS NOT NULL")).scalars())
    if sites - {"site_a"}:
        raise RuntimeError("ambiguous legacy site mapping: provide an audited site migration first")
    op.create_table("tenant", sa.Column("id", sa.String(), primary_key=True),
                    sa.Column("name", sa.String(), nullable=False))
    op.create_table("site", sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenant.id"), primary_key=True),
                    sa.Column("id", sa.String(), primary_key=True),
                    sa.Column("name", sa.String(), nullable=False),
                    sa.Column("timezone", sa.String(), nullable=False))
    op.create_table("building", sa.Column("id", sa.String(), primary_key=True),
                    sa.Column("tenant_id", sa.String(), nullable=False),
                    sa.Column("site_id", sa.String(), nullable=False),
                    sa.Column("name", sa.String(), nullable=False),
                    sa.ForeignKeyConstraint(["tenant_id", "site_id"], ["site.tenant_id", "site.id"]))
    op.create_table("principal", sa.Column("subject", sa.String(), primary_key=True),
                    sa.Column("enabled", sa.Boolean(), nullable=False),
                    sa.Column("tokens_valid_after", sa.Float(), nullable=False))
    op.create_table("principal_scope", sa.Column("id", sa.Integer(), primary_key=True),
                    sa.Column("subject", sa.String(), sa.ForeignKey("principal.subject"), nullable=False),
                    sa.Column("tenant_id", sa.String(), nullable=False),
                    sa.Column("site_id", sa.String(), nullable=False),
                    sa.Column("role", sa.String(), nullable=False),
                    sa.ForeignKeyConstraint(["tenant_id", "site_id"], ["site.tenant_id", "site.id"]),
                    sa.UniqueConstraint("subject", "tenant_id", "site_id"))
    bind.execute(sa.text("INSERT INTO tenant VALUES ('development', 'Development - not a customer')"))
    bind.execute(sa.text("INSERT INTO site VALUES ('development', 'site_a', 'Review demo', 'Asia/Kolkata')"))
    for table in TABLES:
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column("tenant_id", sa.String(), nullable=False, server_default="development"))
            if table != "camera":
                batch.add_column(sa.Column("site_id", sa.String(), nullable=False, server_default="site_a"))
        if table == "camera":
            bind.execute(sa.text("UPDATE camera SET site_id='site_a' WHERE site_id IS NULL"))
        with op.batch_alter_table(table) as batch:
            batch.alter_column("tenant_id", server_default=None)
            batch.alter_column("site_id", nullable=False, server_default=None)
            batch.create_index(f"ix_{table}_tenant_id", ["tenant_id"])
            batch.create_index(f"ix_{table}_site_id", ["site_id"])
            batch.create_unique_constraint(f"uq_{table}_scope", ["id", "tenant_id", "site_id"])
            batch.create_foreign_key(f"fk_{table}_site", "site", ["tenant_id", "site_id"], ["tenant_id", "id"])
        if bind.dialect.name == "postgresql":
            op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
            op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
            expr = "tenant_id=current_setting('app.tenant_id',true) AND site_id=current_setting('app.site_id',true)"
            op.execute(f'CREATE POLICY site_scope ON "{table}" USING ({expr}) WITH CHECK ({expr})')


def downgrade():
    for table in reversed(TABLES):
        if op.get_bind().dialect.name == "postgresql":
            op.execute(f'DROP POLICY site_scope ON "{table}"')
            op.execute(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY')
        with op.batch_alter_table(table) as batch:
            batch.drop_constraint(f"fk_{table}_site", type_="foreignkey")
            batch.drop_constraint(f"uq_{table}_scope", type_="unique")
            batch.drop_index(f"ix_{table}_tenant_id")
            batch.drop_index(f"ix_{table}_site_id")
            batch.drop_column("tenant_id")
            if table != "camera":
                batch.drop_column("site_id")
            else:
                batch.alter_column("site_id", nullable=True)
    for table in ("principal_scope", "principal", "building", "site", "tenant"):
        op.drop_table(table)
