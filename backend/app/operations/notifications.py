"""Provider-neutral, restart-safe SLA notification delivery.

The local provider intentionally records/suppresses delivery and never sends an
external message. Production adapters must be explicitly approved and configured.
"""
from dataclasses import dataclass
import time
import uuid
from fastapi import HTTPException
from sqlalchemy import select
from app.config import get_settings
from app.models.operations import SLANotification, SLANotificationAttempt


@dataclass(frozen=True)
class DeliveryResult:
    accepted: bool
    suppressed: bool = False


class LocalNoopProvider:
    name = "local"

    def deliver(self, notification: SLANotification) -> DeliveryResult:
        # Development/demo safety: acknowledge durable handling, never contact a
        # person or external service. status remains suppressed, not accepted.
        return DeliveryResult(accepted=False, suppressed=True)


def _provider(name):
    if name == "local":
        return LocalNoopProvider()
    raise RuntimeError("notification provider is not installed or approved")


def deliver(db, notification_id, provider=None):
    row = db.scalar(select(SLANotification).where(SLANotification.id == notification_id).with_for_update())
    if not row:
        return
    if row.status in {"accepted", "acknowledged", "suppressed"}:
        return
    provider = provider or _provider(get_settings().notification_provider)
    now = time.time()
    row.provider = provider.name
    row.attempted_at = now
    row.retry_count += 1
    attempt = SLANotificationAttempt(id=uuid.uuid4().hex, notification_id=row.id, at=now,
        provider=provider.name, result="started")
    db.add(attempt)
    db.flush()
    try:
        result = provider.deliver(row)
        if result.accepted:
            row.status, row.accepted_at, row.failure_class = "accepted", now, None
            attempt.result = "accepted"
        elif result.suppressed:
            row.status, row.failure_class = "suppressed", None
            attempt.result = "suppressed"
        else:
            raise RuntimeError("provider did not accept notification")
        db.commit()
    except Exception as exc:
        db.rollback()
        row = db.get(SLANotification, notification_id)
        if row:
            row.attempted_at = now
            row.retry_count += 1
            row.status = "retrying"
            row.failure_class = type(exc).__name__
            db.add(SLANotificationAttempt(id=uuid.uuid4().hex, notification_id=row.id,
                at=now, provider=provider.name, result="failed", failure_class=type(exc).__name__))
            db.commit()
        raise


def acknowledge(db, notification_id):
    row = db.scalar(select(SLANotification).where(SLANotification.id == notification_id).with_for_update())
    if not row:
        raise HTTPException(404, "notification not found")
    row.acknowledged_at = row.acknowledged_at or time.time()
    row.status = "acknowledged"
    db.commit()
    return {"id": row.id, "status": row.status, "acknowledged_at": row.acknowledged_at}
