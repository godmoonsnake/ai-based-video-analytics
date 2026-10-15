"""At-least-once outbox: provider acceptance is never guard acknowledgement."""

import time
import json
from pathlib import Path
from threading import Lock
from urllib.parse import quote

import httpx
import jwt
from sqlalchemy import select
from app.config import get_settings
from app.models.pilot import PilotNotice, PilotCase
from app.models.entities import AuditLog
from app.processing.jobs import enqueue
from app.pilot.service import escalate

_fcm_lock = Lock()
_fcm_cached_token = ""
_fcm_token_expires_at = 0.0


def _fcm_credentials():
    path = get_settings().fcm_service_account_file
    if not path:
        raise RuntimeError("FCM service account is not configured")
    credentials = json.loads(Path(path).read_text(encoding="utf-8"))
    if (credentials.get("type") != "service_account" or
            not all(credentials.get(key) for key in ("client_email", "private_key", "project_id"))):
        raise RuntimeError("FCM service account is incomplete")
    return credentials


def _fcm_access_token(credentials):
    global _fcm_cached_token, _fcm_token_expires_at
    with _fcm_lock:
        now = time.time()
        if _fcm_cached_token and now + 60 < _fcm_token_expires_at:
            return _fcm_cached_token
        assertion = jwt.encode({
            "iss": credentials["client_email"],
            "scope": "https://www.googleapis.com/auth/firebase.messaging",
            "aud": "https://oauth2.googleapis.com/token",
            "iat": int(now), "exp": int(now) + 3600,
        }, credentials["private_key"], algorithm="RS256")
        response = httpx.post("https://oauth2.googleapis.com/token", data={
            "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
            "assertion": assertion,
        }, timeout=8)
        response.raise_for_status()
        data = response.json()
        _fcm_cached_token = data["access_token"]
        _fcm_token_expires_at = now + min(int(data.get("expires_in", 3600)), 3600)
        return _fcm_cached_token


def _send_fcm(row):
    credentials = _fcm_credentials()
    project_id = quote(credentials["project_id"], safe="")
    payload = {
        "message": {
            "fid": row.destination,
            # Data-only lets the app create a generic notification with a task deep link.
            # No site, person, footage or instructions leave the server in push data.
            "data": {"task_id": row.case_id or ""},
            "android": {
                "priority": "HIGH", "ttl": "120s",
            },
        }
    }
    response = httpx.post(
        f"https://fcm.googleapis.com/v1/projects/{project_id}/messages:send",
        headers={"Authorization": f"Bearer {_fcm_access_token(credentials)}"},
        json=payload, timeout=8,
    )
    response.raise_for_status()
    if not response.json().get("name"):
        raise RuntimeError("FCM did not accept the message")


def send(row):
    from app.case_studies.alerts import _post

    settings = get_settings()
    if row.channel == "fcm":
        _send_fcm(row)
    elif row.channel == "telegram":
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
        if row.channel == "fcm":
            from app.pilot.service import contact_for
            current = contact_for(db, row.recipient)
            if not current or current.channel != "fcm":
                raise RuntimeError("guard phone is no longer registered")
            if not current.last_registered_at or time.time() - current.last_registered_at > 30 * 86400:
                raise RuntimeError("guard phone registration is stale")
            row.destination = current.destination
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
