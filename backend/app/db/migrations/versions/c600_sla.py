"""Frozen additive migration; review generated DDL before applying."""
from alembic import op

revision = 'c600_sla'
down_revision = 'c500_response'
branch_labels = depends_on = None

DDL = {'sqlite': ['\nCREATE TABLE sla_escalation (\n\tid VARCHAR NOT NULL, \n\tepisode_id VARCHAR NOT NULL, \n\tincident_id INTEGER NOT NULL, \n\tstage VARCHAR NOT NULL, \n\tdeadline_at FLOAT NOT NULL, \n\trecorded_at FLOAT NOT NULL, \n\towner_at_deadline VARCHAR, \n\tstatus VARCHAR NOT NULL, \n\ttenant_id VARCHAR NOT NULL, \n\tsite_id VARCHAR NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT fk_sla_escalation_site FOREIGN KEY(tenant_id, site_id) REFERENCES site (tenant_id, id), \n\tCONSTRAINT uq_sla_escalation_scope UNIQUE (id, tenant_id, site_id), \n\tFOREIGN KEY(episode_id) REFERENCES response_episode (id), \n\tFOREIGN KEY(incident_id) REFERENCES incident (id)\n)\n\n', 'CREATE INDEX ix_sla_escalation_episode_id ON sla_escalation (episode_id)', 'CREATE INDEX ix_sla_escalation_incident_id ON sla_escalation (incident_id)', 'CREATE INDEX ix_sla_escalation_site_id ON sla_escalation (site_id)', 'CREATE INDEX ix_sla_escalation_tenant_id ON sla_escalation (tenant_id)'], 'postgresql': ['\nCREATE TABLE sla_escalation (\n\tid VARCHAR NOT NULL, \n\tepisode_id VARCHAR NOT NULL, \n\tincident_id INTEGER NOT NULL, \n\tstage VARCHAR NOT NULL, \n\tdeadline_at FLOAT NOT NULL, \n\trecorded_at FLOAT NOT NULL, \n\towner_at_deadline VARCHAR, \n\tstatus VARCHAR NOT NULL, \n\ttenant_id VARCHAR NOT NULL, \n\tsite_id VARCHAR NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT fk_sla_escalation_site FOREIGN KEY(tenant_id, site_id) REFERENCES site (tenant_id, id), \n\tCONSTRAINT uq_sla_escalation_scope UNIQUE (id, tenant_id, site_id), \n\tFOREIGN KEY(episode_id) REFERENCES response_episode (id), \n\tFOREIGN KEY(incident_id) REFERENCES incident (id)\n)\n\n', 'CREATE INDEX ix_sla_escalation_episode_id ON sla_escalation (episode_id)', 'CREATE INDEX ix_sla_escalation_incident_id ON sla_escalation (incident_id)', 'CREATE INDEX ix_sla_escalation_site_id ON sla_escalation (site_id)', 'CREATE INDEX ix_sla_escalation_tenant_id ON sla_escalation (tenant_id)']}
TABLES = ['sla_escalation']

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
