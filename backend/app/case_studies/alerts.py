"""Telegram and WhatsApp delivery for case study alert outbox."""
from __future__ import annotations

import json
import time
from urllib.request import Request, urlopen

from sqlalchemy import select

from app.case_studies.service import alert_text
from app.config import get_settings
from app.models.case_studies import CaseAlert, CaseObservation
from app.models.entities import Incident


def _post(url: str, payload: dict, token: str | None = None) -> dict:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(url, data=json.dumps(payload).encode(), headers=headers,
                      method="POST")
    with urlopen(request, timeout=10) as response:
        return json.load(response)


def deliver(db, alert_id: str):
    alert = db.scalar(select(CaseAlert).where(CaseAlert.id == alert_id).with_for_update())
    if not alert or alert.status in {"accepted", "suppressed"}:
        return
    incident = db.get(Incident, alert.incident_id)
    observation = db.scalar(select(CaseObservation).where(
        CaseObservation.incident_id == alert.incident_id))
    if not incident or not observation:
        raise RuntimeError("alert case is missing")
    settings = get_settings()
    message = alert_text(incident, observation)
    alert.attempt_count += 1
    try:
        if alert.channel == "local" or observation.synthetic or settings.environment != "production":
            alert.status = "suppressed"
        elif alert.channel == "telegram":
            if not settings.telegram_bot_token:
                raise RuntimeError("Telegram credentials are not configured")
            result = _post(f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage",
                           {"chat_id": alert.destination, "text": message})
            if not result.get("ok"):
                raise RuntimeError("Telegram did not accept the message")
            alert.status = "accepted"
        elif alert.channel == "whatsapp":
            if not all((settings.whatsapp_access_token, settings.whatsapp_phone_number_id,
                        settings.whatsapp_template_name)):
                raise RuntimeError("WhatsApp credentials or template are not configured")
            if not settings.whatsapp_api_version.startswith("v") or not settings.whatsapp_api_version[1:].replace(".", "").isdigit():
                raise RuntimeError("invalid WhatsApp API version")
            result = _post(
                f"https://graph.facebook.com/{settings.whatsapp_api_version}/{settings.whatsapp_phone_number_id}/messages",
                {"messaging_product": "whatsapp", "to": alert.destination,
                 "type": "template", "template": {"name": settings.whatsapp_template_name,
                    "language": {"code": settings.whatsapp_template_language},
                    "components": [{"type": "body", "parameters": [
                        {"type": "text", "text": str(incident.id)},
                        {"type": "text", "text": observation.kind.replace("_", " ")},
                        {"type": "text", "text": observation.zone}]}]}},
                settings.whatsapp_access_token)
            if not result.get("messages"):
                raise RuntimeError("WhatsApp did not accept the message")
            alert.status = "accepted"
        else:
            raise RuntimeError("unsupported alert channel")
        alert.accepted_at = time.time() if alert.status == "accepted" else None
        alert.last_error = None
        db.commit()
    except Exception as exc:
        db.rollback()
        alert = db.get(CaseAlert, alert_id)
        if alert:
            alert.attempt_count += 1
            alert.status = "retrying"
            alert.last_error = type(exc).__name__
            db.commit()
        raise
