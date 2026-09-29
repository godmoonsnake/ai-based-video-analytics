"""Mock event source + topology loader.

The mock source replays a scripted scenario JSON as a stream of CanonicalEvents.
Relative scenario times are shifted by a base epoch so events look real. The
topology loader seeds cameras/edges/zones for correlation and the dashboard.
"""
from __future__ import annotations

import json
import time
from collections.abc import Iterator
from pathlib import Path

from sqlalchemy.orm import Session

from app.adapters.base import EventSource
from app.models.entities import Camera, CameraEdge, Zone
from app.normalize import normalize_mock_event
from app.schemas.event import CanonicalEvent

SCENARIOS_DIR = Path(__file__).resolve().parents[2] / "scenarios"


class MockEventSource(EventSource):
    name = "mock"

    def __init__(self, scenario_path: str | Path | None = None, base_epoch: float | None = None,
                 track_suffix: str = ""):
        self.scenario_path = Path(scenario_path or SCENARIOS_DIR / "scenario_basic.json")
        self.base_epoch = base_epoch if base_epoch is not None else time.time()
        self.track_suffix = track_suffix

    def stream(self) -> Iterator[CanonicalEvent]:
        data = json.loads(self.scenario_path.read_text())
        for evt in data["events"]:
            shifted = dict(evt)
            for key in ("start_time", "end_time", "ts"):
                if shifted.get(key) is not None:
                    shifted[key] = self.base_epoch + shifted[key]
            if self.track_suffix:
                shifted["track_local_id"] = f"{shifted['track_local_id']}{self.track_suffix}"
            yield normalize_mock_event(shifted)


def load_topology(db: Session, topology_path: str | Path | None = None) -> None:
    """Seed cameras, edges, and zones from a topology JSON (idempotent-ish)."""
    path = Path(topology_path or SCENARIOS_DIR / "topology.json")
    data = json.loads(path.read_text())

    for cam in data.get("cameras", []):
        if db.get(Camera, cam["id"]) is None:
            db.add(Camera(id=cam["id"], name=cam["name"], site_id=cam.get("site_id"),
                          x=cam.get("x"), y=cam.get("y"),
                          lat=cam.get("lat"), lng=cam.get("lng")))
    db.commit()

    for edge in data.get("edges", []):
        db.add(CameraEdge(
            from_camera_id=edge["from"], to_camera_id=edge["to"],
            walk_seconds_min=edge["walk_seconds_min"],
            walk_seconds_max=edge["walk_seconds_max"],
            bidirectional=edge.get("bidirectional", True),
        ))
    for zone in data.get("zones", []):
        db.add(Zone(camera_id=zone["camera_id"], name=zone["name"], kind=zone["kind"],
                    polygon_json=json.dumps(zone.get("polygon")) if zone.get("polygon") else None))
    db.commit()
