"""Application configuration for the DARSON intelligence layer.

Settings are environment-driven. For local tests we default to SQLite so the
backend runs without Docker/Postgres; production docker-compose supplies a
Postgres+pgvector DATABASE_URL.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DARSON_", env_file=".env", extra="ignore")

    # Database. SQLite fallback keeps the prototype runnable without Docker.
    database_url: str = "sqlite:///./darson.db"
    environment: str = "development"
    auth_mode: str = "development"
    oidc_issuer: str = ""
    oidc_audience: str = ""
    oidc_jwks_url: str = ""
    oidc_jwks_file: str = ""
    require_mfa: bool = True
    notification_provider: str = "local"
    # Production Compose enables the narrow pilot. Legacy research demos remain opt-in.
    pilot_mode: bool = False
    pilot_data_agreement_ref: str = ""
    pilot_supervisor_subject: str = ""
    pilot_critical_copy_supervisor: bool = False
    pilot_max_event_age_seconds: int = Field(default=30, ge=1, le=300)
    connector_poll_seconds: float = Field(default=0.2, ge=0.05, le=1)
    maintenance_interval_seconds: int = Field(default=15, ge=1, le=60)
    retention_interval_seconds: int = Field(default=300, ge=10, le=3600)
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    parking_security_telegram_chat_id: str = ""
    parking_floor_guard_telegram_chat_id: str = ""
    whatsapp_access_token: str = ""
    whatsapp_phone_number_id: str = ""
    whatsapp_recipient: str = ""
    parking_security_whatsapp_recipient: str = ""
    parking_floor_guard_whatsapp_recipient: str = ""
    parking_loitering_seconds: int = 120
    whatsapp_template_name: str = ""
    whatsapp_template_language: str = "en_US"
    whatsapp_api_version: str = "v21.0"
    evidence_root: str = "./var/evidence"
    evidence_key: str = ""
    evidence_max_bytes: int = 50_000_000
    evidence_retention_days: int = Field(default=3, ge=1, le=365)
    spool_root: str = "./var/spool"
    spool_key: str = ""
    spool_max_bytes: int = 100_000_000
    worker_tenant: str = "development"
    worker_site: str = "site_a"
    source_instance: str = "frigate-local"
    mqtt_username: str = ""
    mqtt_password: str = ""
    mqtt_tls: bool = False
    health_probe_interval_seconds: int = 30
    health_offline_after_seconds: int = 60
    health_freeze_debounce_seconds: int = 120
    health_recording_expected: bool = True
    frigate_api_token: str = ""

    # Event source toggle: "mock" (offline scenarios) or "frigate" (real adapter).
    event_source: str = "mock"

    # Frigate integration (read-only). We CONSUME Frigate; we never write to it.
    #
    # Required subscription: `frigate/events` carries the tracked-object lifecycle
    # (type new/update/end with before/after states) — this is the only topic the
    # DARSON adapter needs to build canonical events. `frigate/reviews` is an
    # optional higher-level stream (detection/alert review items) kept here for
    # forward use; it is NOT required by the current adapter.
    frigate_mqtt_host: str = "localhost"
    frigate_mqtt_port: int = 1883
    frigate_mqtt_topic: str = "frigate/events"
    frigate_mqtt_reviews_topic: str = "frigate/reviews"
    frigate_api_base: str = "http://localhost:5000"
    # Browser-facing base for evidence URLs. When set (e.g. "/frigate" behind the
    # reverse proxy), evidence snapshot/clip URLs are built RELATIVE to this base
    # so they are reachable from the browser at the single proxy origin, instead
    # of the Docker-internal frigate_api_base (e.g. http://frigate:5000) which the
    # browser cannot reach. Empty => fall back to frigate_api_base (dev/tests).
    frigate_public_base: str = ""
    # Ingest a tracked object once it finalizes (type == "end") by default. Set
    # true to emit every new/update message (higher volume, earlier signal).
    # Legacy replay remains terminal-only. The durable live connector consumes
    # all lifecycle updates; production pilot Compose enables adapter updates too.
    frigate_emit_updates: bool = False

    # Cross-camera correlation weights and threshold.
    corr_weight_time: float = 0.34
    corr_weight_motion: float = 0.16
    corr_weight_appearance: float = 0.50
    corr_merge_threshold: float = 0.62

    # Re-ID embedding dimensionality (OSNet default).
    embedding_dim: int = 512

    # Optional local LLM for NL search / summaries. Off by default (deterministic first).
    llm_enabled: bool = False

    @property
    def is_postgres(self) -> bool:
        return self.database_url.startswith("postgresql")


@lru_cache
def get_settings() -> Settings:
    return Settings()
