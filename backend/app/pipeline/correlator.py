"""Cross-Camera Correlator + Global Track builder.

The CORRELATION stage. Given per-camera (local) tracks, decide whether two
observations on different cameras belong to the same real-world movement, and
stitch them into a GlobalTrack.

Scoring (all sub-scores in [0,1], fully explainable):
  score = w_t*s_time + w_m*s_motion + w_a*s_appearance

Gates (hard requirements before scoring):
  1. A topology edge must exist from A's camera to B's camera.
  2. The transit gap (B.start - A.end) must fall within the edge's
     [walk_seconds_min, walk_seconds_max] window.

Sub-scores:
  s_time       triangular peak at the middle of the walk window.
  s_motion     velocity_angle continuity between A's exit and B's entry.
  s_appearance cosine similarity of mean OSNet track embeddings.

Merge when score >= tau (config corr_merge_threshold). Every merge stores its
component sub-scores in `method` for operator explainability. No identity, no
PII — appearance is a similarity signal only.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.entities import (
    CameraEdge,
    Event,
    GlobalTrack,
    GlobalTrackMember,
)
from app.pipeline.reid_service import cosine, mean_track_vector

_settings = get_settings()


@dataclass
class TrackSpan:
    camera_id: str
    track_local_id: str
    start: float
    end: float
    exit_angle: float | None
    entry_angle: float | None


@dataclass
class PairScore:
    from_track: tuple[str, str]
    to_track: tuple[str, str]
    s_time: float
    s_motion: float
    s_appearance: float
    score: float
    gap: float

    def method_str(self) -> str:
        return (
            f"time={self.s_time:.2f} motion={self.s_motion:.2f} "
            f"appearance={self.s_appearance:.2f} gap={self.gap:.1f}s"
        )


def compute_spans(db: Session) -> list[TrackSpan]:
    """Compute a time span + motion angles for each (camera, track_local_id)."""
    events = db.execute(select(Event).order_by(Event.ts)).scalars().all()
    grouped: dict[tuple[str, str], list[Event]] = {}
    for e in events:
        grouped.setdefault((e.camera_id, e.track_local_id), []).append(e)

    spans: list[TrackSpan] = []
    for (cam, trk), evs in grouped.items():
        starts = [e.start_time if e.start_time is not None else e.ts for e in evs]
        ends = [e.end_time if e.end_time is not None else e.ts for e in evs]
        angles = [e.velocity_angle for e in evs if e.velocity_angle is not None]
        spans.append(TrackSpan(
            camera_id=cam, track_local_id=trk,
            start=min(starts), end=max(ends),
            exit_angle=angles[-1] if angles else None,
            entry_angle=angles[0] if angles else None,
        ))
    return spans


def _edge_window(db: Session, cam_a: str, cam_b: str) -> tuple[float, float] | None:
    """Return (min,max) walk seconds if a topology edge cam_a->cam_b exists."""
    edges = db.execute(select(CameraEdge)).scalars().all()
    for e in edges:
        if e.from_camera_id == cam_a and e.to_camera_id == cam_b:
            return (e.walk_seconds_min, e.walk_seconds_max)
        if e.bidirectional and e.from_camera_id == cam_b and e.to_camera_id == cam_a:
            return (e.walk_seconds_min, e.walk_seconds_max)
    return None


def _s_time(gap: float, window: tuple[float, float]) -> float:
    lo, hi = window
    if gap < lo or gap > hi:
        return 0.0
    mid = (lo + hi) / 2.0
    half = (hi - lo) / 2.0 or 1.0
    return max(0.0, 1.0 - abs(gap - mid) / half)


def _s_motion(exit_angle: float | None, entry_angle: float | None) -> float:
    """Directional continuity: 1 when angles align, 0 when opposite."""
    if exit_angle is None or entry_angle is None:
        return 0.5  # neutral when unknown
    diff = abs(exit_angle - entry_angle) % 360
    if diff > 180:
        diff = 360 - diff
    return max(0.0, 1.0 - diff / 180.0)


def _s_appearance(db: Session, a: TrackSpan, b: TrackSpan) -> float:
    va = mean_track_vector(db, a.camera_id, a.track_local_id)
    vb = mean_track_vector(db, b.camera_id, b.track_local_id)
    if va is None or vb is None:
        return 0.0
    return max(0.0, cosine(va, vb))


def score_pair(db: Session, a: TrackSpan, b: TrackSpan) -> PairScore | None:
    """Score a directed pair a->b, or None if the topology/time gates fail."""
    window = _edge_window(db, a.camera_id, b.camera_id)
    if window is None:
        return None
    gap = b.start - a.end
    s_time = _s_time(gap, window)
    if s_time == 0.0:
        return None  # out of temporal window -> reject
    s_motion = _s_motion(a.exit_angle, b.entry_angle)
    s_appearance = _s_appearance(db, a, b)
    score = (
        _settings.corr_weight_time * s_time
        + _settings.corr_weight_motion * s_motion
        + _settings.corr_weight_appearance * s_appearance
    )
    return PairScore((a.camera_id, a.track_local_id), (b.camera_id, b.track_local_id),
                     s_time, s_motion, s_appearance, score, gap)


class _DSU:
    """Union-Find to merge stitched tracks into connected global tracks."""

    def __init__(self):
        self.parent: dict[tuple[str, str], tuple[str, str]] = {}

    def find(self, x):
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def correlate(db: Session, tau: float | None = None) -> list[dict]:
    """Run correlation over all tracks; persist GlobalTracks. Returns summaries."""
    tau = tau if tau is not None else _settings.corr_merge_threshold
    spans = compute_spans(db)

    # Clear prior global tracks (idempotent for re-runs / demo).
    db.query(GlobalTrackMember).delete()
    db.query(GlobalTrack).delete()
    db.commit()

    dsu = _DSU()
    accepted: list[PairScore] = []
    # Directed pairs ordered by time: a ends before b starts.
    for a in spans:
        for b in spans:
            if a is b or a.camera_id == b.camera_id:
                continue
            if b.start < a.end:
                continue
            ps = score_pair(db, a, b)
            if ps and ps.score >= tau:
                dsu.union(ps.from_track, ps.to_track)
                accepted.append(ps)

    # Build groups; include singletons so every track maps to a global track.
    groups: dict[tuple[str, str], list[tuple[str, str]]] = {}
    for s in spans:
        key = (s.camera_id, s.track_local_id)
        root = dsu.find(key)
        groups.setdefault(root, []).append(key)

    span_by_key = {(s.camera_id, s.track_local_id): s for s in spans}
    method_by_edge = {(p.from_track, p.to_track): p for p in accepted}

    summaries: list[dict] = []
    for members in groups.values():
        members_sorted = sorted(members, key=lambda k: span_by_key[k].start)
        gt = GlobalTrack(
            first_seen=min(span_by_key[k].start for k in members_sorted),
            last_seen=max(span_by_key[k].end for k in members_sorted),
            confidence=(
                round(sum(method_by_edge[e].score for e in method_by_edge
                          if e[0] in members and e[1] in members)
                      / max(1, len(members_sorted) - 1), 3)
                if len(members_sorted) > 1 else None
            ),
        )
        db.add(gt)
        db.flush()

        prev = None
        for key in members_sorted:
            edge = method_by_edge.get((prev, key)) if prev else None
            db.add(GlobalTrackMember(
                global_track_id=gt.id,
                camera_id=key[0], track_local_id=key[1],
                join_score=round(edge.score, 3) if edge else None,
                method=edge.method_str() if edge else "seed",
            ))
            prev = key

        summaries.append({
            "global_track_id": gt.id,
            "members": [{"camera_id": k[0], "track_local_id": k[1]} for k in members_sorted],
            "confidence": gt.confidence,
        })
    db.commit()
    return summaries
