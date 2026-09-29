"""Historical Pattern Miner (batch).

The HISTORY stage. Mines spatial/temporal/behavioural patterns over the stored
events and global tracks. Explicitly NO identity and NO PII — patterns are about
places, times, paths, and densities, not people.

Pattern types produced (persisted to historical_pattern):
- recurring_path      : frequent camera sequences across global tracks (n-grams)
- recurring_location  : zone kinds by frequency of events
- recurring_timewindow: (camera, hour-of-day) event frequency
- hotspot             : event density per camera
- anomaly             : a global-track path seen only once vs the common paths
"""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import (
    Event,
    GlobalTrack,
    GlobalTrackMember,
    HistoricalPattern,
    Zone,
)


def _global_track_camera_sequences(db: Session) -> list[list[str]]:
    """Ordered camera sequence for each global track (by member start time)."""
    seqs: list[list[str]] = []
    for gt in db.execute(select(GlobalTrack)).scalars().all():
        members = db.execute(
            select(GlobalTrackMember).where(GlobalTrackMember.global_track_id == gt.id)
        ).scalars().all()
        if len(members) < 2:
            continue
        # order members by the earliest event ts of each member track
        def _start(m):
            ev = db.execute(
                select(Event).where(
                    Event.camera_id == m.camera_id,
                    Event.track_local_id == m.track_local_id,
                ).order_by(Event.ts)
            ).scalars().first()
            return ev.ts if ev else 0.0

        ordered = sorted(members, key=_start)
        seqs.append([m.camera_id for m in ordered])
    return seqs


def mine_patterns(db: Session, min_path_count: int = 2) -> list[HistoricalPattern]:
    """Run all miners; replace prior patterns; return the new rows."""
    db.query(HistoricalPattern).delete()
    db.commit()

    events = db.execute(select(Event)).scalars().all()
    zone_kind = {(z.camera_id, z.name): z.kind for z in db.execute(select(Zone)).scalars().all()}
    now = datetime.now(timezone.utc).timestamp()
    out: list[HistoricalPattern] = []

    # 1) recurring paths from global-track camera sequences.
    seqs = _global_track_camera_sequences(db)
    path_counter = Counter(tuple(s) for s in seqs)
    for path, count in path_counter.items():
        ptype = "recurring_path" if count >= min_path_count else "anomaly"
        out.append(HistoricalPattern(
            pattern_type=ptype,
            key_json=json.dumps({"path": list(path)}),
            count=count, first_seen=now, last_seen=now,
            score=round(min(1.0, count / max(1, len(seqs))), 3),
        ))

    # 2) recurring locations by zone kind.
    zone_counter: Counter = Counter()
    for e in events:
        zones = json.loads(e.zones_json) if e.zones_json else []
        for z in zones:
            zone_counter[(e.camera_id, z, zone_kind.get((e.camera_id, z), "unknown"))] += 1
    for (cam, zone, kind), count in zone_counter.items():
        out.append(HistoricalPattern(
            pattern_type="recurring_location",
            key_json=json.dumps({"camera_id": cam, "zone": zone, "kind": kind}),
            count=count, first_seen=now, last_seen=now,
            score=round(min(1.0, count / max(1, len(events))), 3),
        ))

    # 3) recurring time windows: (camera, hour-of-day).
    tw_counter: Counter = Counter()
    for e in events:
        hour = datetime.fromtimestamp(e.ts, tz=timezone.utc).hour
        tw_counter[(e.camera_id, hour)] += 1
    for (cam, hour), count in tw_counter.items():
        out.append(HistoricalPattern(
            pattern_type="recurring_timewindow",
            key_json=json.dumps({"camera_id": cam, "hour_of_day": hour}),
            count=count, first_seen=now, last_seen=now,
            score=round(min(1.0, count / max(1, len(events))), 3),
        ))

    # 4) hotspots: event density per camera.
    cam_counter = Counter(e.camera_id for e in events)
    total = sum(cam_counter.values()) or 1
    for cam, count in cam_counter.items():
        out.append(HistoricalPattern(
            pattern_type="hotspot",
            key_json=json.dumps({"camera_id": cam}),
            count=count, first_seen=now, last_seen=now,
            score=round(count / total, 3),
        ))

    for row in out:
        db.add(row)
    db.commit()
    return out
