"""Canonical event schema (source-agnostic).

Both the mock source and the Frigate adapter emit this identical shape so all
downstream stages (sequence analysis, correlation, incidents) are decoupled
from the raw event source.
"""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class EventType(str, Enum):
    detection = "detection"
    zone_enter = "zone_enter"
    zone_exit = "zone_exit"
    loiter = "loiter"
    dwell = "dwell"


class SourceType(str, Enum):
    mock = "mock"
    frigate = "frigate"


class EventSourceRef(BaseModel):
    type: SourceType
    source_event_id: str | None = None


class EventTrack(BaseModel):
    local_id: str


class EventTime(BaseModel):
    start: float | None = None
    end: float | None = None
    observed: float


class EventSpatial(BaseModel):
    bbox: list[float] | None = None
    region: list[float] | None = None
    zones: list[str] = Field(default_factory=list)
    velocity_angle: float | None = None
    avg_speed: float | None = None


class EventEvidence(BaseModel):
    has_clip: bool = False
    has_snapshot: bool = False
    snapshot_url: str | None = None
    clip_url: str | None = None


class CanonicalEvent(BaseModel):
    event_id: str
    source: EventSourceRef
    camera_id: str
    track: EventTrack
    event_type: EventType
    label: str | None = None
    sub_label: str | None = None
    confidence: float | None = None
    time: EventTime
    spatial: EventSpatial = Field(default_factory=EventSpatial)
    evidence: EventEvidence = Field(default_factory=EventEvidence)
    embedding_ref: str | None = None
    raw_json: dict[str, Any] | None = None
