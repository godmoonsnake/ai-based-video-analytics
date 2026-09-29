"""Application configuration for the DARSON intelligence layer.

Settings are environment-driven. For local tests we default to SQLite so the
backend runs without Docker/Postgres; production docker-compose supplies a
Postgres+pgvector DATABASE_URL.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DARSON_", env_file=".env", extra="ignore")

    # Database. SQLite fallback keeps the prototype runnable without Docker.
    database_url: str = "sqlite:///./darson.db"

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
    # Ingest a tracked object once it finalizes (type == "end") by default. Set
    # true to emit every new/update message (higher volume, earlier signal).
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
