"""Task 4 verification: Frigate adapter (offline replay, no broker)."""
from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.adapters.factory import make_event_source
from app.adapters.frigate_source import (
    FrigateReplaySource,
    decode_message,
    is_false_positive,
    is_terminal,
)
from app.adapters.mock_source import MockEventSource
from app.db.session import SessionLocal
from app.main import app
from app.models.entities import Event
from app.schemas.event import EventType, SourceType

STREAM = Path(__file__).parent / "fixtures" / "frigate_stream.json"
EVENT = Path(__file__).parent / "fixtures" / "frigate_event.json"
client = TestClient(app)


def test_decode_single_message_resolves_evidence():
    msgs = json.loads(STREAM.read_text())
    evt = decode_message(msgs[1], api_base="http://frigate:5000")  # the 'update' with clip
    assert evt.source.type == SourceType.frigate
    assert evt.camera_id == "gate_3"
    assert evt.sub_label == "red_bag"
    assert evt.evidence.has_clip is True
    assert evt.evidence.clip_url == "http://frigate:5000/api/events/1700000001.10-aaa/clip.mp4"


def test_terminal_detection():
    msgs = json.loads(STREAM.read_text())
    assert is_terminal(msgs[2]) is True   # type == end
    assert is_terminal(msgs[0]) is False  # type == new


def test_replay_emits_only_terminal_by_default():
    msgs = json.loads(STREAM.read_text())
    src = FrigateReplaySource(msgs, api_base="http://frigate:5000")
    events = list(src.stream())
    # two 'end' messages in the fixture
    assert len(events) == 2
    # the restricted 'end' has motionless_count 95 -> dwell
    dwell = [e for e in events if e.event_type == EventType.dwell]
    assert dwell and dwell[0].camera_id == "restricted_2"


def test_replay_emit_updates():
    msgs = json.loads(STREAM.read_text())
    src = FrigateReplaySource(msgs, emit_updates=True)
    assert len(list(src.stream())) == 4


def test_frigate_replay_ingests_via_api():
    msgs = json.loads(STREAM.read_text())
    resp = client.post("/events/ingest/frigate/replay", json=msgs)
    assert resp.status_code == 200
    assert resp.json() == {"ingested": 2, "source": "frigate"}

    db = SessionLocal()
    try:
        rows = db.execute(select(Event)).scalars().all()
        assert len(rows) == 2
        assert all(r.source_type == "frigate" for r in rows)
    finally:
        db.close()


def test_factory_default_is_mock():
    # default config event_source == mock
    assert isinstance(make_event_source(), MockEventSource)


def test_single_full_message_fixture_maps_after_state():
    """The captured frigate/events message (before+after) maps its `after`
    state: sub_label flattened, zone_enter, snapshot+clip evidence."""
    msg = json.loads(EVENT.read_text())
    evt = decode_message(msg, api_base="http://frigate:5000")
    assert evt.source.type == SourceType.frigate
    assert evt.source.source_event_id == "1607123955.475377-mxklsc"
    assert evt.camera_id == "gate_3"
    assert evt.sub_label == "staff"               # flattened from ["staff", 0.79]
    assert evt.event_type == EventType.zone_enter  # entered_zones present, not stationary
    assert evt.confidence == 0.88                 # score preferred over top_score
    assert evt.evidence.has_snapshot is True
    assert evt.evidence.has_clip is True
    assert evt.evidence.snapshot_url == (
        "http://frigate:5000/api/events/1607123955.475377-mxklsc/snapshot.jpg"
    )
    assert evt.evidence.clip_url == (
        "http://frigate:5000/api/events/1607123955.475377-mxklsc/clip.mp4"
    )


def test_false_positive_detection():
    fp = {"type": "end", "after": {"id": "x", "camera": "c", "false_positive": True}}
    ok = {"type": "end", "after": {"id": "y", "camera": "c", "false_positive": False}}
    assert is_false_positive(fp) is True
    assert is_false_positive(ok) is False


def test_replay_drops_false_positive_messages():
    """A false-positive tracked object must never reach the pipeline, even as a
    terminal 'end' message."""
    msgs = [
        {"type": "end", "after": {
            "id": "real-1", "camera": "gate_3", "label": "person",
            "sub_label": "red_bag", "score": 0.9, "start_time": 1.0,
            "end_time": 6.0, "frame_time": 6.0, "false_positive": False,
            "has_snapshot": True, "has_clip": True,
        }},
        {"type": "end", "after": {
            "id": "ghost-1", "camera": "gate_3", "label": "person",
            "score": 0.3, "start_time": 2.0, "end_time": 2.5, "frame_time": 2.5,
            "false_positive": True,
        }},
    ]
    events = list(FrigateReplaySource(msgs, api_base="http://frigate:5000").stream())
    assert len(events) == 1
    assert events[0].source.source_event_id == "real-1"
