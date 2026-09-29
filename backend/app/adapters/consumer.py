"""Background event consumer.

Bridges a live EventSource (the Frigate MQTT adapter) into the single ingestion
write path, running in a daemon thread for the lifetime of the app. This is what
makes REAL Frigate `frigate/events` messages land in the database automatically
(the API `/events/ingest/...` endpoints remain for the mock/replay demo path).

Design:
- Only started when DARSON_EVENT_SOURCE=frigate (see main.lifespan). The default
  mock deployment does not start it.
- Uses its own SessionLocal per ingested event (thread-local safety); the source
  generator blocks on the MQTT queue, so this thread is idle until events arrive.
- Fully additive — no change to the pipeline, adapter, or ingestion contract.
"""
from __future__ import annotations

import logging
import threading

from app.adapters.base import EventSource
from app.adapters.ingestion import ingest_event
from app.db.session import SessionLocal

log = logging.getLogger("darson.consumer")


class BackgroundIngestor:
    """Runs an EventSource.stream() loop in a daemon thread, ingesting events."""

    def __init__(self, source: EventSource):
        self._source = source
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.ingested = 0

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._run, name="darson-frigate-ingestor", daemon=True
        )
        self._thread.start()
        log.info("background ingestor started for source=%s", self._source.name)

    def _run(self) -> None:
        try:
            for evt in self._source.stream():
                if self._stop.is_set():
                    break
                db = SessionLocal()
                try:
                    ingest_event(db, evt)
                    self.ingested += 1
                except Exception:  # pragma: no cover - defensive; never kill thread
                    log.exception("failed to ingest a live event; continuing")
                    db.rollback()
                finally:
                    db.close()
        except Exception:  # pragma: no cover - broker/source failure must not crash app
            log.exception("event source stream terminated")

    def stop(self) -> None:
        self._stop.set()
        stop = getattr(self._source, "stop", None)
        if callable(stop):
            stop()
