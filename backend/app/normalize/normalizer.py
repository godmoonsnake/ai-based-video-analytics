"""Normalizer: raw source events -> CanonicalEvent.

- Frigate: maps the `after` object of a `frigate/events` message.
- Mock: maps our own scenario event dicts (already close to canonical).

Both produce an identical CanonicalEvent so downstream stages never branch on
the source type.
"""
from __future__ import annotations

import uuid
from typing import Any

from app.config import get_settings
from app.schemas.event import (
    CanonicalEvent,
    EventEvidence,
    EventSourceRef,
    EventSpatial,
    EventTime,
    EventTrack,
    EventType,
    SourceType,
)

_settings = get_settings()


def _derive_event_type(zones_current: list[str], zones_entered: list[str], stationary: bool,
                       motionless_count: int) -> EventType:
    """Infer a canonical event_type from Frigate zone/motion signals."""
    if stationary or motionless_count >= 30:
        # A long-motionless object is a dwell; loiter is a softer variant.
        return EventType.dwell if motionless_count >= 60 else EventType.loiter
    if zones_current:
        return EventType.zone_enter
    return EventType.detection


def normalize_frigate_event(msg: dict[str, Any], api_base: str | None = None) -> CanonicalEvent:
    """Map a Frigate `frigate/events` message to a CanonicalEvent.

    Accepts either the full message ({type, before, after}) or a bare `after`
    object. Uses `after` when present since it is the most recent state.
    """
    after = msg.get("after") or msg.get("before") or msg
    api_base = api_base or _settings.frigate_api_base

    source_event_id = after.get("id")
    current_zones = after.get("current_zones") or []
    entered_zones = after.get("entered_zones") or []
    stationary = bool(after.get("stationary", False))
    motionless = int(after.get("motionless_count", 0) or 0)

    has_snapshot = bool(after.get("has_snapshot", False))
    has_clip = bool(after.get("has_clip", False))
    # Evidence base: prefer the browser-facing public base (e.g. "/frigate" behind
    # the reverse proxy) so the URL is reachable from the browser at the single
    # proxy origin. Fall back to the (Docker-internal) api_base for dev/tests.
    evidence_base = (_settings.frigate_public_base or "").rstrip("/") or api_base
    snapshot_url = (
        f"{evidence_base}/api/events/{source_event_id}/snapshot.jpg" if has_snapshot else None
    )
    clip_url = f"{evidence_base}/api/events/{source_event_id}/clip.mp4" if has_clip else None

    return CanonicalEvent(
        event_id=str(uuid.uuid4()),
        source=EventSourceRef(type=SourceType.frigate, source_event_id=source_event_id,
                              instance=_settings.source_instance,
                              event_kind=msg.get("type", "observation"),
                              revision=str(after.get("frame_time") or after.get("end_time")
                                           or after.get("start_time"))),
        camera_id=after.get("camera"),
        track=EventTrack(local_id=source_event_id),
        event_type=_derive_event_type(current_zones, entered_zones, stationary, motionless),
        label=after.get("label"),
        sub_label=_flatten_sub_label(after.get("sub_label")),
        confidence=after.get("score") or after.get("top_score"),
        time=EventTime(
            start=after.get("start_time"),
            end=after.get("end_time"),
            observed=after.get("frame_time") or after.get("start_time"),
        ),
        spatial=EventSpatial(
            bbox=after.get("box"),
            region=after.get("region"),
            # entered_zones is historical. An empty current_zones means the
            # object is outside every zone, not still inside an earlier zone.
            zones=current_zones,
            velocity_angle=after.get("velocity_angle"),
            avg_speed=after.get("average_estimated_speed"),
        ),
        evidence=EventEvidence(
            has_clip=has_clip,
            has_snapshot=has_snapshot,
            snapshot_url=snapshot_url,
            clip_url=clip_url,
        ),
        raw_json=msg,
    )


def _flatten_sub_label(sub_label: Any) -> str | None:
    """Frigate sub_label may be a [name, score] pair or a plain string."""
    if isinstance(sub_label, (list, tuple)) and sub_label:
        return str(sub_label[0])
    if isinstance(sub_label, str):
        return sub_label
    return None


def normalize_mock_event(evt: dict[str, Any]) -> CanonicalEvent:
    """Map a mock scenario event dict to a CanonicalEvent.

    Mock events use canonical-ish field names; missing pieces are defaulted.
    When has_clip/has_snapshot are set without explicit URLs, synthesize a
    stable mock evidence URL so Incident -> Event -> Camera -> Evidence
    traceability is demonstrable in the offline demo.
    """
    track_local_id = evt["track_local_id"]
    has_clip = evt.get("has_clip", False)
    has_snapshot = evt.get("has_snapshot", False)
    snapshot_url = evt.get("snapshot_url")
    clip_url = evt.get("clip_url")
    if has_snapshot and not snapshot_url:
        snapshot_url = f"/mock-evidence/{evt['camera_id']}/{track_local_id}/snapshot.jpg"
    if has_clip and not clip_url:
        clip_url = f"/mock-evidence/{evt['camera_id']}/{track_local_id}/clip.mp4"

    return CanonicalEvent(
        event_id=evt.get("event_id") or str(uuid.uuid4()),
        source=EventSourceRef(
            type=SourceType.mock,
            source_event_id=evt.get("source_event_id") or track_local_id,
        ),
        camera_id=evt["camera_id"],
        track=EventTrack(local_id=track_local_id),
        event_type=EventType(evt.get("event_type", "detection")),
        label=evt.get("label"),
        sub_label=evt.get("sub_label"),
        confidence=evt.get("confidence"),
        time=EventTime(
            start=evt.get("start_time"),
            end=evt.get("end_time"),
            observed=evt.get("ts") or evt.get("observed") or evt["start_time"],
        ),
        spatial=EventSpatial(
            bbox=evt.get("bbox"),
            region=evt.get("region"),
            zones=evt.get("zones", []),
            velocity_angle=evt.get("velocity_angle"),
            avg_speed=evt.get("avg_speed"),
        ),
        evidence=EventEvidence(
            has_clip=has_clip,
            has_snapshot=has_snapshot,
            snapshot_url=snapshot_url,
            clip_url=clip_url,
        ),
        raw_json=evt,
    )
