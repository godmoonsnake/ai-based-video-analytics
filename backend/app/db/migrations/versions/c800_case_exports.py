"""Frozen additive migration; review generated DDL before applying."""
from alembic import op

revision = 'c800_case_exports'
down_revision = 'c700_sla_notifications'
branch_labels = depends_on = None

DDL = {'sqlite': ['\nCREATE TABLE incident_export (\n\tid VARCHAR NOT NULL, \n\tincident_id INTEGER NOT NULL, \n\tcase_version INTEGER NOT NULL, \n\tformat VARCHAR NOT NULL, \n\trequested_by VARCHAR NOT NULL, \n\tidempotency_key VARCHAR NOT NULL, \n\tsnapshot JSON NOT NULL, \n\tstatus VARCHAR NOT NULL, \n\tobject_key VARCHAR, \n\tsha256 VARCHAR, \n\tsize INTEGER, \n\trequested_at FLOAT NOT NULL, \n\tcompleted_at FLOAT, \n\texpires_at FLOAT NOT NULL, \n\tfailure_class VARCHAR, \n\ttenant_id VARCHAR NOT NULL, \n\tsite_id VARCHAR NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT fk_incident_export_site FOREIGN KEY(tenant_id, site_id) REFERENCES site (tenant_id, id), \n\tCONSTRAINT uq_incident_export_scope UNIQUE (id, tenant_id, site_id), \n\tFOREIGN KEY(incident_id) REFERENCES incident (id), \n\tUNIQUE (idempotency_key)\n)\n\n', 'CREATE INDEX ix_incident_export_incident_id ON incident_export (incident_id)', 'CREATE INDEX ix_incident_export_site_id ON incident_export (site_id)', 'CREATE INDEX ix_incident_export_tenant_id ON incident_export (tenant_id)'], 'postgresql': ['\nCREATE TABLE incident_export (\n\tid VARCHAR NOT NULL, \n\tincident_id INTEGER NOT NULL, \n\tcase_version INTEGER NOT NULL, \n\tformat VARCHAR NOT NULL, \n\trequested_by VARCHAR NOT NULL, \n\tidempotency_key VARCHAR NOT NULL, \n\tsnapshot JSONB NOT NULL, \n\tstatus VARCHAR NOT NULL, \n\tobject_key VARCHAR, \n\tsha256 VARCHAR, \n\tsize INTEGER, \n\trequested_at FLOAT NOT NULL, \n\tcompleted_at FLOAT, \n\texpires_at FLOAT NOT NULL, \n\tfailure_class VARCHAR, \n\ttenant_id VARCHAR NOT NULL, \n\tsite_id VARCHAR NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT fk_incident_export_site FOREIGN KEY(tenant_id, site_id) REFERENCES site (tenant_id, id), \n\tCONSTRAINT uq_incident_export_scope UNIQUE (id, tenant_id, site_id), \n\tFOREIGN KEY(incident_id) REFERENCES incident (id), \n\tUNIQUE (idempotency_key)\n)\n\n', 'CREATE INDEX ix_incident_export_incident_id ON incident_export (incident_id)', 'CREATE INDEX ix_incident_export_site_id ON incident_export (site_id)', 'CREATE INDEX ix_incident_export_tenant_id ON incident_export (tenant_id)']}
TABLES = ['incident_export']

def upgrade():
    dialect = op.get_bind().dialect.name
    for statement in DDL[dialect]:
        op.execute(statement)
    if dialect == "postgresql":
        for table in TABLES:
            op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
            op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
            expr = "tenant_id=current_setting('app.tenant_id',true) AND site_id=current_setting('app.site_id',true)"
            op.execute(f'CREATE POLICY site_scope ON "{table}" USING ({expr}) WITH CHECK ({expr})')

def downgrade():
    for table in reversed(TABLES):
        op.drop_table(table)
