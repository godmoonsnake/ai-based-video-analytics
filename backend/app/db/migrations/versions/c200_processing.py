"""E2 event envelope and transactional work queue."""
from alembic import op
import sqlalchemy as sa
import hashlib
import json

revision = "c200_processing"
down_revision = "c100_scope_security"
branch_labels = depends_on = None


def scoped_table(name, *columns):
    op.create_table(name, *columns,
        sa.Column("tenant_id", sa.String(), nullable=False),
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
    with op.batch_alter_table("event") as batch:
        for name in ("dedup_key", "source_instance", "source_revision", "event_kind", "payload_digest"):
            batch.add_column(sa.Column(name, sa.String()))
        batch.add_column(sa.Column("received_at", sa.Float()))
        batch.add_column(sa.Column("schema_version", sa.Integer(), nullable=False, server_default="1"))
        batch.create_unique_constraint("uq_event_dedup_key", ["dedup_key"])
    # Historical IDs and incident references are preserved. Legacy observations
    # are assigned a revision key; conflicting duplicates must be adjudicated.
    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT * FROM event")).mappings().all()
    seen = set()
    for row in rows:
        raw = json.loads(row["raw_json"]) if row["raw_json"] else None
        instance = "frigate-local" if row["source_type"] == "frigate" else "default"
        kind = raw.get("type", "observation") if raw and row["source_type"] == "frigate" else "observation"
        rev = str(row["ts"])
        source_revision = rev if row["source_type"] == "frigate" else None
        payload = dict(schema_version=1, source=dict(type=row["source_type"], source_event_id=row["source_event_id"],
            instance=instance, revision=source_revision, event_kind=kind), camera_id=row["camera_id"],
            track={"local_id": row["track_local_id"]}, event_type=row["event_type"], label=row["label"],
            sub_label=row["sub_label"], confidence=row["confidence"],
            time=dict(start=row["start_time"], end=row["end_time"], observed=row["ts"]),
            spatial=dict(bbox=json.loads(row["bbox_json"]) if row["bbox_json"] else None,
                region=json.loads(row["region_json"]) if row["region_json"] else None,
                zones=json.loads(row["zones_json"]) if row["zones_json"] else [],
                velocity_angle=row["velocity_angle"], avg_speed=row["avg_speed"]),
            evidence=dict(has_clip=bool(row["has_clip"]), has_snapshot=bool(row["has_snapshot"]),
                **(json.loads(row["evidence_ref_json"]) if row["evidence_ref_json"] else {"clip_url": None, "snapshot_url": None})),
            embedding_ref=None, raw_json=raw)
        def digest(value):
            return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
        key = digest([row["tenant_id"], row["site_id"], row["source_type"], instance,
                      row["source_event_id"], row["camera_id"], rev, kind, row["event_type"]])
        if key in seen:
            raise RuntimeError("duplicate legacy source revisions require an audited reconciliation")
        seen.add(key)
        bind.execute(sa.text("UPDATE event SET dedup_key=:key, source_instance=:instance, "
            "source_revision=:rev, event_kind=:kind, payload_digest=:digest WHERE id=:id"),
            dict(key=key, instance=instance, rev=rev, kind=kind, digest=digest(payload), id=row["id"]))
    scoped_table("processing_job", sa.Column("id", sa.String(), primary_key=True),
        sa.Column("kind", sa.String(), nullable=False), sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(), nullable=False), sa.Column("lease_owner", sa.String()),
        sa.Column("lease_expiry", sa.Float()), sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("next_retry", sa.Float(), nullable=False), sa.Column("error_class", sa.String()),
        sa.Column("created_at", sa.Float(), nullable=False), sa.Column("completed_at", sa.Float()))
    op.create_index("ix_processing_job_kind", "processing_job", ["kind"])
    op.create_index("ix_processing_job_status", "processing_job", ["status"])
    scoped_table("source_lease", sa.Column("id", sa.String(), primary_key=True),
        sa.Column("owner", sa.String(), nullable=False), sa.Column("expires_at", sa.Float(), nullable=False),
        sa.Column("last_seen", sa.Float()), sa.Column("fault", sa.Text()))


def downgrade():
    op.drop_table("source_lease")
    op.drop_table("processing_job")
    with op.batch_alter_table("event") as batch:
        batch.drop_constraint("uq_event_dedup_key", type_="unique")
        for name in ("dedup_key", "source_instance", "source_revision", "event_kind", "payload_digest",
                     "received_at", "schema_version"):
            batch.drop_column(name)
