"""Frigate adapter (read-only).

Subscribes to `frigate/events` over MQTT, maps each message to a CanonicalEvent
via the normalizer, and resolves evidence URLs against Frigate's HTTP API. We
consume Frigate; we never write to or fork it.

The message-decoding logic (`decode_message`) is separated from the live MQTT
client so it can be unit-tested with recorded fixtures and no broker. A
`FrigateReplaySource` replays a recorded list of messages as an EventSource,
which is what the demo/tests use.
"""
from __future__ import annotations

import json
import queue
import threading
from collections.abc import Iterator
from typing import Any

from app.adapters.base import EventSource
from app.config import get_settings
from app.normalize import normalize_frigate_event
from app.schemas.event import CanonicalEvent

_settings = get_settings()


def decode_message(payload: str | bytes | dict, api_base: str | None = None) -> CanonicalEvent:
    """Decode a single raw `frigate/events` MQTT payload into a CanonicalEvent."""
    if isinstance(payload, (str, bytes)):
        msg = json.loads(payload)
    else:
        msg = payload
    return normalize_frigate_event(msg, api_base=api_base or _settings.frigate_api_base)


def is_terminal(msg: dict[str, Any]) -> bool:
    """True when this Frigate message finalizes a tracked object (type == 'end')."""
    return msg.get("type") == "end"


class FrigateReplaySource(EventSource):
    """Replays a recorded list of Frigate messages (offline, no broker).

    By default only terminal ('end') messages are emitted, mirroring the live
    adapter's default of ingesting a finalized tracked object once. Set
    emit_updates=True to emit every message.
    """

    name = "frigate"

    def __init__(self, messages: list[dict], api_base: str | None = None,
                 emit_updates: bool = False):
        self.messages = messages
        self.api_base = api_base or _settings.frigate_api_base
        self.emit_updates = emit_updates

    def stream(self) -> Iterator[CanonicalEvent]:
        for msg in self.messages:
            if self.emit_updates or is_terminal(msg):
                yield decode_message(msg, api_base=self.api_base)


class FrigateMqttSource(EventSource):
    """Live MQTT source subscribing to `frigate/events`.

    Uses paho-mqtt. Emits finalized tracked objects (type == 'end') by default.
    This is exercised in deployment; tests use FrigateReplaySource.
    """

    name = "frigate"

    def __init__(self, host: str | None = None, port: int | None = None,
                 topic: str | None = None, api_base: str | None = None,
                 emit_updates: bool = False):
        self.host = host or _settings.frigate_mqtt_host
        self.port = port or _settings.frigate_mqtt_port
        self.topic = topic or _settings.frigate_mqtt_topic
        self.api_base = api_base or _settings.frigate_api_base
        self.emit_updates = emit_updates
        self._q: "queue.Queue[CanonicalEvent]" = queue.Queue()
        self._stop = threading.Event()

    def _on_message(self, client, userdata, message):  # pragma: no cover - needs broker
        try:
            msg = json.loads(message.payload)
        except (ValueError, TypeError):
            return
        if self.emit_updates or is_terminal(msg):
            self._q.put(decode_message(msg, api_base=self.api_base))

    def stream(self) -> Iterator[CanonicalEvent]:  # pragma: no cover - needs broker
        import paho.mqtt.client as mqtt

        client = mqtt.Client()
        client.on_message = self._on_message
        client.connect(self.host, self.port)
        client.subscribe(self.topic)
        client.loop_start()
        try:
            while not self._stop.is_set():
                try:
                    yield self._q.get(timeout=1.0)
                except queue.Empty:
                    continue
        finally:
            client.loop_stop()
            client.disconnect()

    def stop(self) -> None:  # pragma: no cover
        self._stop.set()
