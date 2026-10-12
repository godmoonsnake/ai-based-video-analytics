"""Developer utility: emit reviewed, static dialect DDL for NEW tables only.

Generated migrations never import live application models. Existing-table
alterations/backfills require hand-written reviewed migrations.
"""
from pathlib import Path
import sys
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.schema import CreateTable, CreateIndex

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "backend"))
from app.db.session import Base  # noqa: E402
import app.models  # noqa: E402, F401

revision, previous, *names = sys.argv[1:]
tables = [t for t in Base.metadata.sorted_tables if t.name in names]
assert len(tables) == len(names)
ddl = {}
for dialect in (sqlite.dialect(), postgresql.dialect()):
    ddl[dialect.name] = [str(CreateTable(t).compile(dialect=dialect)) for t in tables]
    ddl[dialect.name] += [str(CreateIndex(i).compile(dialect=dialect)) for t in tables
                          for i in sorted(t.indexes, key=lambda i: i.name)]
content = ('"""Frozen additive migration; review generated DDL before applying."""\n'
    'from alembic import op\n\n' + f'revision = {revision!r}\ndown_revision = {previous!r}\n'
    'branch_labels = depends_on = None\n\n' + f'DDL = {ddl!r}\nTABLES = {[t.name for t in tables]!r}\n\n'
    'def upgrade():\n'
    '    dialect = op.get_bind().dialect.name\n'
    '    for statement in DDL[dialect]:\n        op.execute(statement)\n'
    '    if dialect == "postgresql":\n'
    '        for table in TABLES:\n'
    '            op.execute(f\'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY\')\n'
    '            op.execute(f\'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY\')\n'
    '            expr = "tenant_id=current_setting(\'app.tenant_id\',true) AND site_id=current_setting(\'app.site_id\',true)"\n'
    '            op.execute(f\'CREATE POLICY site_scope ON "{table}" USING ({expr}) WITH CHECK ({expr})\')\n\n'
    'def downgrade():\n    for table in reversed(TABLES):\n        op.drop_table(table)\n')
destination = root / "backend/app/db/migrations/versions" / (revision + ".py")
with destination.open("x", encoding="utf-8") as f:
    f.write(content)
print(destination)
