"""At-least-once outbox: provider acceptance is never guard acknowledgement."""

import time
from sqlalchemy import select
from app.config import get_settings
from app.models.pilot import PilotNotice, PilotCase
from app.models.entities import AuditLog
from app.processing.jobs import enqueue
from app.pilot.service import escalate


def send(row):
    from app.case_studies.alerts import _post

    settings = get_settings()
    if row.channel == "telegram":
        if not settings.telegram_bot_token:
            raise RuntimeError("Telegram credentials missing")
        result = _post(
            f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage",
            {"chat_id": row.destination, "text": row.message},
        )
        if not result.get("ok"):
            raise RuntimeError("Telegram rejected notification")
    elif row.channel == "whatsapp":
        if not all(
            (
                settings.whatsapp_access_token,
                settings.whatsapp_phone_number_id,
                settings.whatsapp_template_name,
            )
        ):
            raise RuntimeError("WhatsApp credentials/template missing")
        version = settings.whatsapp_api_version
        if not version.startswith("v") or not version[1:].replace(".", "").isdigit():
            raise RuntimeError("invalid WhatsApp API version")
        # Pilot template has ONE text parameter. Configure/approve it before use.
        result = _post(
            f"https://graph.facebook.com/{version}/{settings.whatsapp_phone_number_id}/messages",
            {
                "messaging_product": "whatsapp",
                "to": row.destination,
                "type": "template",
                "template": {
                    "name": settings.whatsapp_template_name,
                    "language": {"code": settings.whatsapp_template_language},
                    "components": [
                        {
                            "type": "body",
                            "parameters": [{"type": "text", "text": row.message}],
                        }
                    ],
                },
            },
            settings.whatsapp_access_token,
        )
        if not result.get("messages"):
            raise RuntimeError("WhatsApp rejected notification")
    else:
        raise RuntimeError("real notification destination is not configured")


def deliver(db, identifier, sender=None):
    row = db.scalar(
        select(PilotNotice).where(PilotNotice.id == identifier).with_for_update()
    )
    if not row or row.status in {"accepted", "suppressed", "cancelled", "failed"}:
        return
    case = db.get(PilotCase, row.case_id) if row.case_id else None
    if case and case.state == "resolved":
        row.status = "cancelled"
        db.commit()
        return
    if get_settings().environment != "production":
        row.status = "suppressed"
        db.add(
            AuditLog(
                actor=db.info["scope"].actor,
                action="pilot_notice_suppressed",
                target=row.id,
            )
        )
        db.commit()
        return
    row.attempts += 1
    db.add(
        AuditLog(
            actor=db.info["scope"].actor,
            action=f"pilot_notice_attempt:{row.attempts}",
            target=row.id,
        )
    )
    db.commit()
    try:
        (sender or send)(row)
        row.status, row.accepted_at, row.failure_class = "accepted", time.time(), None
        db.add(
            AuditLog(
                actor=db.info["scope"].actor,
                action="pilot_notice_accepted",
                target=row.id,
            )
        )
        db.commit()
    except Exception as exc:
        row.status = "failed" if row.attempts >= 5 else "retrying"
        row.failure_class = type(exc).__name__
        db.add(
            AuditLog(
                actor=db.info["scope"].actor,
                action=f"pilot_notice_failed:{row.failure_class}",
                target=row.id,
            )
        )
        if case and row.reason == "assigned_guard":
            escalate(db, case, "guard_delivery_failed", time.time())
        db.commit()
        raise RuntimeError("pilot notification delivery failed") from None


def retry_failed(db, identifier):
    row = db.get(PilotNotice, identifier)
    if not row or row.status != "failed":
        return False
    from app.pilot.service import contact_for

    contact = contact_for(db, row.recipient)
    if not contact:
        return False
    row.channel, row.destination = contact.channel, contact.destination
    row.status, row.attempts, row.failure_class = "queued", 0, None
    enqueue(
        db, "pilot_notice", [row.id, "manual-retry", time.time()], {"notice_id": row.id}
    )
    db.commit()
    return True
