"""Deterministic NL -> structured filter parser.

Maps a natural-language investigation query to a SearchFilter WITHOUT any LLM,
so the prototype is fully offline and reproducible. If a local LLM is enabled
and configured, its parse is merged in as an enhancement — but the deterministic
parser is always the baseline.

Example: "Show incidents involving a red bag near Gate 3 yesterday"
  -> camera_id=gate_3, sub_label=red_bag, time_start/time_end = yesterday window
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.llm import get_provider
from app.models.entities import Camera, Event
from app.search.filters import SearchFilter

_EVENT_TYPES = {"detection", "zone_enter", "zone_exit", "loiter", "dwell"}
_PRIORITIES = {"low", "medium", "high", "critical"}
_STATUSES = {"open", "confirmed", "dismissed"}


def _camera_lookup(db: Session) -> dict[str, str]:
    """Build a phrase->camera_id map from camera ids and names.

    'gate 3' / 'gate_3' / 'Gate 3 (Entry)' all map to camera id 'gate_3'.
    """
    out: dict[str, str] = {}
    for cam in db.execute(select(Camera)).scalars().all():
        out[cam.id.lower()] = cam.id
        out[cam.id.replace("_", " ").lower()] = cam.id
        if cam.name:
            out[cam.name.lower()] = cam.id
    return out


def _sub_label_lookup(db: Session) -> dict[str, str]:
    out: dict[str, str] = {}
    for (sub,) in db.execute(select(Event.sub_label).distinct()).all():
        if sub:
            out[sub.replace("_", " ").lower()] = sub
            out[sub.lower()] = sub
    return out


def _relative_time_window(text: str) -> tuple[float | None, float | None]:
    now = datetime.now(timezone.utc)
    t = text.lower()
    if "yesterday" in t:
        start = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
        return start.timestamp(), end.timestamp()
    if "today" in t:
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return start.timestamp(), (start + timedelta(days=1)).timestamp()
    if "last hour" in t or "past hour" in t:
        return (now - timedelta(hours=1)).timestamp(), now.timestamp()
    m = re.search(r"last (\d+) days?", t)
    if m:
        days = int(m.group(1))
        return (now - timedelta(days=days)).timestamp(), now.timestamp()
    return None, None


def parse_nl(db: Session, query: str) -> SearchFilter:
    """Deterministic parse. Merges optional LLM hints if a provider is enabled."""
    q = query.lower()
    f = SearchFilter()

    # Camera by phrase.
    for phrase, cam_id in sorted(_camera_lookup(db).items(), key=lambda kv: -len(kv[0])):
        if phrase and phrase in q:
            f.camera_id = cam_id
            break

    # Appearance / sub_label (e.g. "red bag" -> red_bag).
    for phrase, sub in sorted(_sub_label_lookup(db).items(), key=lambda kv: -len(kv[0])):
        if phrase and phrase in q:
            f.sub_label = sub
            break

    # Event type keywords.
    for et in _EVENT_TYPES:
        if et.replace("_", " ") in q or et in q:
            f.event_type = et
            break
    if "loiter" in q:
        f.event_type = "loiter"

    # Incident priority / status.
    for p in _PRIORITIES:
        if p in q:
            f.priority = p
            break
    for s in _STATUSES:
        if s in q:
            f.status = s
            break

    # Relative time window.
    ts, te = _relative_time_window(q)
    f.time_start, f.time_end = ts, te

    # Optional LLM enhancement (off by default).
    if get_settings().llm_enabled:
        try:
            hints = get_provider().nl_to_filter(query)
            for k, v in (hints or {}).items():
                if getattr(f, k, None) in (None,) and v is not None:
                    setattr(f, k, v)
        except Exception:  # pragma: no cover - never let LLM break search
            pass

    return f
