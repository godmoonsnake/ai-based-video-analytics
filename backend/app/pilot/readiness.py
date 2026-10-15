from app.config import get_settings
from pathlib import Path


def validate_configuration():
    settings = get_settings()
    if settings.environment != "production" or not settings.pilot_mode:
        return
    if settings.event_source != "frigate":
        raise RuntimeError("production pilot requires the real Frigate source")
    if not settings.pilot_data_agreement_ref.strip():
        raise RuntimeError(
            "set the approved pilot data/retention agreement reference before collection"
        )
    if settings.notification_provider not in {"telegram", "whatsapp", "fcm"}:
        raise RuntimeError(
            "production pilot requires a real notification provider; local suppression is demo only"
        )
    if not settings.pilot_supervisor_subject:
        raise RuntimeError("production pilot requires a supervisor fallback subject")
    if settings.notification_provider == "telegram" and not settings.telegram_bot_token:
        raise RuntimeError("production pilot requires Telegram credentials")
    if settings.notification_provider == "fcm" and not (
        settings.fcm_service_account_file and Path(settings.fcm_service_account_file).is_file()
    ):
        raise RuntimeError("production pilot requires a mounted FCM service account")
    if settings.notification_provider == "whatsapp" and not all(
        (
            settings.whatsapp_access_token,
            settings.whatsapp_phone_number_id,
            settings.whatsapp_template_name,
        )
    ):
        raise RuntimeError(
            "production pilot requires WhatsApp credentials and an approved one-parameter template"
        )
    if (
        settings.notification_provider == "whatsapp"
        and not settings.whatsapp_api_version
    ):
        raise RuntimeError(
            "set the WhatsApp API version tested with the provider account"
        )
