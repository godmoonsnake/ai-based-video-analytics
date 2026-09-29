"""Event source factory: selects the source based on config toggle."""
from __future__ import annotations

from app.adapters.base import EventSource
from app.adapters.frigate_source import FrigateMqttSource
from app.adapters.mock_source import MockEventSource
from app.config import get_settings


def make_event_source() -> EventSource:
    """Return the configured live event source (mock | frigate)."""
    settings = get_settings()
    if settings.event_source == "frigate":
        return FrigateMqttSource()
    return MockEventSource()
