"""Task 2 verification: canonical schema + normalizer.

Assert that a raw Frigate event and an equivalent mock event normalize to an
identical canonical shape (ignoring the intentionally source-specific fields:
event_id, source.type, source_event_id, raw_json).
"""
from __future__ import annotations

import json
from pathlib import Path

from app.normalize import normalize_frigate_event, normalize_mock_event
from app.schemas.event import CanonicalEvent, EventType

FIXTURE = Path(__file__).parent / "fixtures" / "frigate_event.json"


def _comparable(evt: CanonicalEvent) -> dict:
    d = evt.model_dump()
    # Drop intentionally source-specific fields.
    d.pop("event_id")
    d.pop("raw_json")
    d["source"].pop("type")
    d["source"].pop("source_event_id")
    # Provenance added by the durable ingestion envelope is deliberately
    # source-specific while the canonical observation shape remains stable.
    for key in ("instance", "event_kind", "revision"):
        d["source"].pop(key, None)
    # Evidence URLs are source-specific; compare only the boolean flags.
    d["evidence"].pop("snapshot_url")
    d["evidence"].pop("clip_url")
    return d


def test_frigate_normalizes():
    msg = json.loads(FIXTURE.read_text())
    evt = normalize_frigate_event(msg, api_base="http://frigate:5000")
    assert evt.camera_id == "gate_3"
    assert evt.label == "person"
    assert evt.sub_label == "staff"  # flattened from [name, score]
    assert evt.event_type == EventType.zone_enter
    assert "restricted" in evt.spatial.zones
    assert evt.confidence == 0.88
    assert evt.evidence.has_clip is True
    assert evt.evidence.clip_url == "http://frigate:5000/api/events/1607123955.475377-mxklsc/clip.mp4"


def test_mock_normalizes():
    mock = {
        "camera_id": "gate_3",
        "track_local_id": "t-1",
        "event_type": "zone_enter",
        "label": "person",
        "sub_label": "staff",
        "confidence": 0.88,
        "start_time": 1607123955.475377,
        "ts": 1607123962.082975,
        "bbox": [432, 496, 544, 854],
        "region": [218, 440, 693, 915],
        "zones": ["restricted"],
        "velocity_angle": 180,
        "avg_speed": 1.3,
        "has_snapshot": True,
        "has_clip": True,
    }
    evt = normalize_mock_event(mock)
    assert evt.camera_id == "gate_3"
    assert evt.event_type == EventType.zone_enter


def test_both_sources_identical_canonical_shape():
    frig = normalize_frigate_event(json.loads(FIXTURE.read_text()))
    mock = normalize_mock_event(
        {
            "camera_id": "gate_3",
            "track_local_id": "1607123955.475377-mxklsc",
            "event_type": "zone_enter",
            "label": "person",
            "sub_label": "staff",
            "confidence": 0.88,
            "start_time": 1607123955.475377,
            "end_time": None,
            "ts": 1607123962.082975,
            "bbox": [432, 496, 544, 854],
            "region": [218, 440, 693, 915],
            "zones": ["restricted"],
            "velocity_angle": 180,
            "avg_speed": 1.3,
            "has_snapshot": True,
            "has_clip": True,
        }
    )
    assert _comparable(frig) == _comparable(mock)
