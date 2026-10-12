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

from dataclasses import dataclass, asdict
from collections import Counter, defaultdict
from bisect import bisect_left, bisect_right
import time

from sqlalchemy import select, func, update, text
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
    latest = db.scalar(select(func.max(Event.ts)))
    if latest is None:
        return []
    events = db.execute(select(Event).where(Event.ts >= latest - 86400).order_by(Event.ts)).scalars().all()
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
    if window[0] < 0 or window[1] < window[0] or not window[0] <= gap <= window[1]:
        return None  # out of temporal window -> reject
    s_motion = _s_motion(a.exit_angle, b.entry_angle)
    s_appearance = _s_appearance(db, a, b)
    weights = (_settings.corr_weight_time, _settings.corr_weight_motion, _settings.corr_weight_appearance)
    if min(weights) < 0 or abs(sum(weights) - 1) > 0.000001:
        raise ValueError("correlation weights must be nonnegative and sum to one")
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
    """Append immutable inference runs. Ambiguous branches never become forced matches."""
    from app.models.lineage import CorrelationRun, CorrelationHypothesis
    from app.processing.jobs import digest
    scope = db.info["scope"]
    if db.bind.dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:scope))"),
                   {"scope": f"correlation:{scope.tenant}:{scope.site}"})
    tau = tau if tau is not None else _settings.corr_merge_threshold
    if not 0 <= tau <= 1:
        raise ValueError("threshold must lie in [0,1]")
    spans = compute_spans(db)
    topology = db.scalars(select(CameraEdge).order_by(CameraEdge.id)).all()
    windows = {}
    for edge in topology:
        windows[edge.from_camera_id, edge.to_camera_id] = (edge.walk_seconds_min, edge.walk_seconds_max)
        if edge.bidirectional:
            windows[edge.to_camera_id, edge.from_camera_id] = windows[edge.from_camera_id, edge.to_camera_id]
    from app.pipeline.reid_service import get_backend
    model = type(get_backend()).__name__
    input_ids = list(db.scalars(select(Event.id).order_by(Event.id)))
    run_id = digest([scope.tenant, scope.site, input_ids, [asdict(s) for s in spans],
                     sorted((a, b, lo, hi) for (a, b), (lo, hi) in windows.items()),
                     tau, model, _settings.corr_weight_time, _settings.corr_weight_motion,
                     _settings.corr_weight_appearance, "conservative-path-v1"])
    prior = db.get(CorrelationRun, run_id)
    if prior:
        return _run_summary(db, run_id)
    previous = db.scalar(select(CorrelationRun.id).order_by(CorrelationRun.created_at.desc()).limit(1))
    db.add(CorrelationRun(id=run_id, policy_version="conservative-path-v1", model_version=model,
                         created_at=time.time(), supersedes=previous))
    by_camera = defaultdict(list)
    for span in spans:
        by_camera[span.camera_id].append(span)
    for camera in by_camera:
        by_camera[camera].sort(key=lambda s: (s.start, s.track_local_id))
    starts = {camera: [s.start for s in values] for camera, values in by_camera.items()}
    pairs = []
    for a in spans:
        for (origin, target), (lo, hi) in windows.items():
            if origin != a.camera_id or target == origin or target not in by_camera:
                continue
            left, right = bisect_left(starts[target], a.end + lo), bisect_right(starts[target], a.end + hi)
            for b in by_camera[target][left:right]:
                ps = score_pair(db, a, b)
                if ps:
                    pairs.append(ps)
    eligible = [p for p in pairs if p.score >= tau]
    outgoing = Counter(p.from_track for p in eligible)
    incoming = Counter(p.to_track for p in eligible)
    accepted = []
    for p in pairs:
        disposition = "below_threshold"
        if p.score >= tau:
            disposition = "accepted" if outgoing[p.from_track] == incoming[p.to_track] == 1 else "ambiguous"
        db.add(CorrelationHypothesis(id=digest([run_id, p.from_track, p.to_track]), run_id=run_id,
            from_key=list(p.from_track), to_key=list(p.to_track), signals={
                "time": p.s_time, "motion": p.s_motion, "appearance": p.s_appearance, "gap": p.gap,
                "appearance_backend": model, "identity_probability": False},
            score=p.score, disposition=disposition))
        if disposition == "accepted":
            accepted.append(p)
    successors = {p.from_track: p.to_track for p in accepted}
    predecessors = {p.to_track for p in accepted}
    span_by_key = {(s.camera_id, s.track_local_id): s for s in spans}
    method_by_edge = {(p.from_track, p.to_track): p for p in accepted}
    groups, visited = [], set()
    for key in sorted(span_by_key, key=lambda k: (span_by_key[k].start, k)):
        if key in predecessors or key in visited:
            continue
        group, cursor = [], key
        while cursor is not None and cursor not in visited:
            visited.add(cursor)
            group.append(cursor)
            cursor = successors.get(cursor)
        groups.append(group)
    # Defensive fallback for zero-duration cycles: keep observations as singletons.
    groups.extend([[k] for k in span_by_key if k not in visited])
    db.execute(update(GlobalTrack).values(current=False))
    for members_sorted in groups:
        path_scores = [method_by_edge[a, b].score for a, b in zip(members_sorted, members_sorted[1:])]
        gt = GlobalTrack(
            fingerprint=digest([run_id, members_sorted]), run_id=run_id, current=True,
            first_seen=min(span_by_key[k].start for k in members_sorted),
            last_seen=max(span_by_key[k].end for k in members_sorted),
            confidence=round(min(path_scores), 3) if path_scores else None,
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

    db.commit()
    return _run_summary(db, run_id)


def _run_summary(db, run_id):
    out = []
    for gt in db.scalars(select(GlobalTrack).where(GlobalTrack.run_id == run_id).order_by(GlobalTrack.id)):
        members = db.scalars(select(GlobalTrackMember).where(GlobalTrackMember.global_track_id == gt.id)
                             .order_by(GlobalTrackMember.id)).all()
        out.append({"global_track_id": gt.id, "members": [
            {"camera_id": m.camera_id, "track_local_id": m.track_local_id} for m in members],
            "confidence": gt.confidence, "run_id": run_id,
            "track_kind": "correlated_movement" if len(members) > 1 else "single_camera",
            "score_is_probability": False})
    return out
