"""Optional local LLM provider interface.

Deterministic search comes FIRST. An LLM is an optional, pluggable enhancement
for (a) parsing free-form NL into a structured filter and (b) drafting an
incident summary. It is OFF by default (settings.llm_enabled=False) and, when
absent, the system falls back to the deterministic parser/template. All output
is advisory and human-reviewed — never an autonomous verdict.
"""
from __future__ import annotations

import abc


class LLMProvider(abc.ABC):
    @abc.abstractmethod
    def nl_to_filter(self, query: str) -> dict:
        """Return a structured filter dict for a natural-language query."""
        raise NotImplementedError

    @abc.abstractmethod
    def summarize_incident(self, context: dict) -> str:
        raise NotImplementedError


class NullLLMProvider(LLMProvider):
    """No-op provider used when no LLM is configured."""

    def nl_to_filter(self, query: str) -> dict:
        return {}

    def summarize_incident(self, context: dict) -> str:
        return ""


_provider: LLMProvider | None = None


def get_provider() -> LLMProvider:
    global _provider
    if _provider is None:
        _provider = NullLLMProvider()
    return _provider


def set_provider(provider: LLMProvider) -> None:
    global _provider
    _provider = provider
