import hashlib
import json
import time
from sqlalchemy import and_, or_, select, update

from app.models.processing import ProcessingJob, SourceLease


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def insert_once(db, model, values, key="id"):
    if db.bind.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    return db.execute(insert(model).values(**values).on_conflict_do_nothing(index_elements=[key]))


def enqueue(db, kind: str, semantic_key: str, payload: dict, now=None):
    scope = db.info["scope"]
    identifier = digest([scope.tenant, scope.site, kind, semantic_key])
    insert_once(db, ProcessingJob, dict(id=identifier, tenant_id=scope.tenant, site_id=scope.site,
                kind=kind, payload=payload, status="pending", attempt_count=0, next_retry=0,
                created_at=time.time() if now is None else now))
    return identifier


def claim(db, owner: str, now=None, lease_seconds=120):
    now = time.time() if now is None else now
    eligible = or_(and_(ProcessingJob.status == "pending", ProcessingJob.next_retry <= now),
                   and_(ProcessingJob.status == "running", ProcessingJob.lease_expiry <= now))
    stmt = select(ProcessingJob.id).where(eligible).order_by(ProcessingJob.created_at).limit(1)
    if db.bind.dialect.name == "postgresql":
        stmt = stmt.with_for_update(skip_locked=True)
    identifier = db.scalar(stmt)
    if not identifier:
        return None
    result = db.execute(update(ProcessingJob).where(ProcessingJob.id == identifier, eligible).values(
        status="running", lease_owner=owner, lease_expiry=now + lease_seconds,
        attempt_count=ProcessingJob.attempt_count + 1))
    db.commit()
    return db.get(ProcessingJob, identifier) if result.rowcount else None


def finish(db, identifier, owner, error=None, now=None):
    now = time.time() if now is None else now
    job = db.get(ProcessingJob, identifier)
    if not job or job.lease_owner != owner or job.status != "running" or job.lease_expiry <= now:
        return False
    status = "done" if error is None else ("quarantined" if job.attempt_count >= 5 else "pending")
    result = db.execute(update(ProcessingJob).where(
        ProcessingJob.id == identifier, ProcessingJob.lease_owner == owner,
        ProcessingJob.status == "running", ProcessingJob.lease_expiry > now).values(
            status=status, error_class=type(error).__name__ if error else None,
            next_retry=now + min(300, 2 ** job.attempt_count), lease_owner=None, lease_expiry=None,
            completed_at=now if status == "done" else None))
    db.commit()
    return result.rowcount == 1


def source_lease(db, source, owner, now=None, seconds=30):
    now = time.time() if now is None else now
    scope = db.info["scope"]
    identifier = digest([scope.tenant, scope.site, source])
    insert_once(db, SourceLease, dict(id=identifier, tenant_id=scope.tenant, site_id=scope.site,
                                    owner=owner, expires_at=0))
    result = db.execute(update(SourceLease).where(SourceLease.id == identifier,
        or_(SourceLease.expires_at <= now, SourceLease.owner == owner)).values(
            owner=owner, expires_at=now + seconds))
    db.commit()
    return identifier if result.rowcount else None
