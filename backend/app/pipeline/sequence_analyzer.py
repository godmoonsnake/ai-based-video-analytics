"""Behavioural Sequence Analyzer.

Turns an ordered list of events (for one track — local or global) into a
behavioural sequence: a compact pattern signature, per-step detail, and an
anomaly score. This is the CONTEXT stage: it understands sequences rather than
isolated alerts (e.g. Entry -> Transit -> Restricted Dwell -> Exit).

Design notes:
- Deterministic and explainable — no black-box model. The anomaly score is a
  transparent sum of interpretable risk contributions so operators can see WHY.
- Zone `kind` (entry/transit/restricted/exit) drives risk; the analyzer accepts
  a mapping of zone-name -> kind so it can label steps semantically.
- No identity, no PII: works purely on event_type/zone/timing.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Iterable

from app.models.entities import Event, Zone
from sqlalchemy import select
from sqlalchemy.orm import Session

# Risk weights per behavioural signal (transparent + tunable).
_RISK_RESTRICTED_DWELL = 0.6
_RISK_RESTRICTED_PRESENCE = 0.3
_RISK_LOITER = 0.25
_RISK_DWELL = 0.15


@dataclass
class SequenceStep:
    camera_id: str
    event_type: str
    zones: list[str]
    zone_kinds: list[str]
    ts: float
    event_id: str
    dwell_seconds: float | None = None


@dataclass
class SequenceResult:
    track_key: str
    signature: str
    steps: list[SequenceStep] = field(default_factory=list)
    anomaly_score: float = 0.0
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "track_key": self.track_key,
            "signature": self.signature,
            "anomaly_score": round(self.anomaly_score, 3),
            "reasons": self.reasons,
            "steps": [
                {
                    "camera_id": s.camera_id,
                    "event_type": s.event_type,
                    "zones": s.zones,
                    "zone_kinds": s.zone_kinds,
                    "ts": s.ts,
                    "event_id": s.event_id,
                    "dwell_seconds": s.dwell_seconds,
                }
                for s in self.steps
            ],
        }


def _zone_kind_map(db: Session) -> dict[tuple[str, str], str]:
    """Map (camera_id, zone_name) -> kind for semantic labelling."""
    rows = db.execute(select(Zone)).scalars().all()
    return {(z.camera_id, z.name): z.kind for z in rows}


def analyze_events(events: Iterable[Event], track_key: str,
                   zone_kinds: dict[tuple[str, str], str] | None = None) -> SequenceResult:
    """Analyze an ordered (by ts) event list into a SequenceResult."""
    zone_kinds = zone_kinds or {}
    ordered = sorted(events, key=lambda e: e.ts)

    steps: list[SequenceStep] = []
    sig_tokens: list[str] = []
    score = 0.0
    reasons: list[str] = []

    for e in ordered:
        zones = json.loads(e.zones_json) if e.zones_json else []
        kinds = [zone_kinds.get((e.camera_id, z), "unknown") for z in zones]
        dwell_seconds = None
        if e.start_time is not None and e.end_time is not None:
            dwell_seconds = round(e.end_time - e.start_time, 2)

        steps.append(SequenceStep(
            camera_id=e.camera_id, event_type=e.event_type, zones=zones,
            zone_kinds=kinds, ts=e.ts, event_id=e.id, dwell_seconds=dwell_seconds,
        ))

        # Signature token: prefer semantic zone kind, else event type.
        token = kinds[0] if kinds and kinds[0] != "unknown" else e.event_type
        sig_tokens.append(token)

        # Transparent risk accumulation.
        in_restricted = "restricted" in kinds
        if in_restricted and e.event_type in ("dwell", "loiter"):
            score += _RISK_RESTRICTED_DWELL
            reasons.append(f"{e.event_type} inside restricted zone on {e.camera_id}")
        elif in_restricted:
            score += _RISK_RESTRICTED_PRESENCE
            reasons.append(f"presence in restricted zone on {e.camera_id}")
        elif e.event_type == "loiter":
            score += _RISK_LOITER
            reasons.append(f"loitering on {e.camera_id}")
        elif e.event_type == "dwell":
            score += _RISK_DWELL
            reasons.append(f"dwell on {e.camera_id}")

    signature = " -> ".join(sig_tokens)
    return SequenceResult(
        track_key=track_key,
        signature=signature,
        steps=steps,
        anomaly_score=min(score, 1.0),
        reasons=reasons,
    )


def analyze_local_track(db: Session, camera_id: str, track_local_id: str) -> SequenceResult:
    """Analyze a single-camera (local) track by its (camera_id, track_local_id)."""
    stmt = (
        select(Event)
        .where(Event.camera_id == camera_id, Event.track_local_id == track_local_id)
        .order_by(Event.ts)
    )
    events = db.execute(stmt).scalars().all()
    key = f"{camera_id}:{track_local_id}"
    return analyze_events(events, key, _zone_kind_map(db))


def analyze_track_local_id(db: Session, track_local_id: str) -> SequenceResult:
    """Analyze all events sharing a track_local_id (may span cameras if reused)."""
    stmt = select(Event).where(Event.track_local_id == track_local_id).order_by(Event.ts)
    events = db.execute(stmt).scalars().all()
    return analyze_events(events, track_local_id, _zone_kind_map(db))
