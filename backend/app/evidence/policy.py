import time
import uuid
from sqlalchemy import select
from app.models.evidence import EvidenceAccess, EvidenceObject, RetentionHold


def audit(db, evidence_id, action, detail=None):
    db.add(EvidenceAccess(id=uuid.uuid4().hex, evidence_id=evidence_id,
        actor=db.info["scope"].actor, action=action, at=time.time(), detail=detail))


def held(db, identifier):
    return db.scalar(select(RetentionHold.id).where(RetentionHold.evidence_id == identifier,
                                                  RetentionHold.released_at.is_(None))) is not None


def retention_sweep(db, now=None):
    from app.evidence.storage import ObjectStore
    now = time.time() if now is None else now
    deleted = []
    for obj in db.scalars(select(EvidenceObject).where(EvidenceObject.expires_at <= now,
            EvidenceObject.status.in_(["available", "requested", "pending", "deletion-failed"])).with_for_update()):
        if held(db, obj.id):
            continue
        # Shared incident references point to one object; only its global expiry
        # is applied. Any hold on the object protects every linked case.
        if obj.object_key:
            try:
                ObjectStore().delete(db.info["scope"], obj.object_key)
            except FileNotFoundError:
                pass  # Already absent; expiry still gets its deletion audit.
            except Exception as exc:
                obj.status, obj.error = "deletion-failed", "retention_delete_failed"
                audit(db, obj.id, "retention_delete_failed", type(exc).__name__)
                continue
        obj.status, obj.error = "unavailable", "retention_expired"
        audit(db, obj.id, "retention_delete")
        deleted.append(obj.id)
    db.commit()
    return deleted
