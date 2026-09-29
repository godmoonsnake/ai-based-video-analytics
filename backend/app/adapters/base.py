"""EventSource interface.

Both the mock generator and the Frigate adapter implement this. Downstream
ingestion consumes a stream of CanonicalEvents without knowing the source.
"""
from __future__ import annotations

import abc
from collections.abc import Iterator

from app.schemas.event import CanonicalEvent


class EventSource(abc.ABC):
    """Abstract source of canonical events."""

    name: str = "base"

    @abc.abstractmethod
    def stream(self) -> Iterator[CanonicalEvent]:
        """Yield CanonicalEvents. May be finite (mock replay) or long-lived (frigate)."""
        raise NotImplementedError
