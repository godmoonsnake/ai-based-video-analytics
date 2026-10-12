"""Incident Graph construction, confidence propagation, timeline & explanation.

This module builds a normalized, explainable graph for an incident on top of the
existing domain entities (Event, GlobalTrack/GlobalTrackMember, Camera, Zone) and
the existing intelligence stages (correlator sub-scores, behavioural sequence).

It is completely SOURCE-AGNOSTIC: it consumes canonical Event rows and existing
intelligence objects only. There is no Frigate / MQTT / adapter knowledge here.

GRAPH SHAPE
-----------
Nodes (incident_node), heterogeneous, referencing existing entities:
  incident : the root node (ref_id = str(incident.id))
  track    : a GlobalTrack participating in the incident (ref_id = str(gt.id))
  camera   : a camera the incident touches (ref_id = camera.id)
  zone     : a zone touched (ref_id = "<camera_id>:<zone_name>")
  event    : a canonical Event (ref_id = event.id)

Typed edges (incident_graph_edge) with confidence + JSONB evidence:
  incident_membership : incident -> track           (structural)
  track_to_camera     : track    -> camera          (structural)
  event_to_track      : event    -> track           (structural)
  event_to_zone       : event    -> zone            (structural)
  temporal            : event    -> event           (chronological continuity)
  sequence            : event    -> event           (behavioural step; risk evidence)
  correlation         : track    -> track           (appearance/topology/time sub-scores)
  movement            : camera   -> camera           (topology transition)

Every INFERRED edge (temporal, sequence, correlation, movement) carries a
`confidence` in [0,1] and an `evidence` object of the signals that justify it,
so the edge is explainable from stored data alone.

CONFIDENCE PROPAGATION (deterministic, documented)
---------------------------------------------------
An incident requires TWO independent pillars of evidence:
  1. CORRELATION continuity  — the observations are genuinely one movement.
     correlation_confidence = mean of the combined correlation scores of the
     `correlation` edges along the track chain (the supporting path). A single
     -track incident has no correlation edges -> correlation_confidence = 1.0
     (nothing to stitch, so continuity is not a limiting factor).
  2. BEHAVIOUR significance  — the movement is actually noteworthy.
     behaviour_confidence = the behavioural sequence anomaly_score in [0,1].

We combine them with the MINIMUM (weakest-required-pillar) rule:

     incident_confidence = round(min(correlation_confidence, behaviour_confidence), 3)

Rationale: both pillars are REQUIRED, so the incident can be no more trustworthy
than its weakest required pillar. This is conservative, monotonic, fully
deterministic, uses only the existing correlator/behaviour signals (no invented
formula), and is easy for an operator to reason about. Confidence bands:
     >= 0.66 high | >= 0.33 medium | else low.
"""
from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import (
    Event,
    GlobalTrack,
    GlobalTrackMember,
    IncidentGraphEdge,
    IncidentNode,
)
from app.pipeline.correlator import TrackSpan, score_pair
from app.pipeline.sequence_analyzer import _zone_kind_map, analyze_events

CONFIDENCE_BANDS = ((0.66, "high"), (0.33, "medium"), (0.0, "low"))


def confidence_band(value: float | None) -> str:
    if value is None:
        return "unknown"
    for threshold, label in CONFIDENCE_BANDS:
        if value >= threshold:
            return label
    return "low"


def _span_for_track(events: list[Event]) -> TrackSpan:
    """Build a TrackSpan (as the correlator sees it) for one track's events."""
    starts = [e.start_time if e.start_time is not None else e.ts for e in events]
    ends = [e.end_time if e.end_time is not None else e.ts for e in events]
    angles = [e.velocity_angle for e in events if e.velocity_angle is not None]
    return TrackSpan(
        camera_id=events[0].camera_id,
        track_local_id=events[0].track_local_id,
        start=min(starts),
        end=max(ends),
        exit_angle=angles[-1] if angles else None,
        entry_angle=angles[0] if angles else None,
    )


class _NodeRegistry:
    """Creates/deduplicates IncidentNodes for one incident and flushes ids."""

    def __init__(self, db: Session, incident_id: int):
        self.db = db
        self.incident_id = incident_id
        self._by_key: dict[tuple[str, str], IncidentNode] = {}

    def get(self, node_type: str, ref_id: str, attributes: dict | None = None) -> IncidentNode:
        key = (node_type, ref_id)
        node = self._by_key.get(key)
        if node is not None:
            return node
        node = IncidentNode(
            incident_id=self.incident_id,
            node_type=node_type,
            ref_id=ref_id,
            attributes=attributes or {},
        )
        self.db.add(node)
        self.db.flush()  # assign id
        self._by_key[key] = node
        return node


def clear_graph(db: Session, incident_id: int) -> None:
    """Remove any existing graph for an incident (idempotent rebuild)."""
    db.query(IncidentGraphEdge).filter(
        IncidentGraphEdge.incident_id == incident_id
    ).delete()
    db.query(IncidentNode).filter(
        IncidentNode.incident_id == incident_id
    ).delete()
    db.flush()


def build_graph(
    db: Session,
    incident_id: int,
    events: list[Event],
    global_track_ids: list[int],
) -> dict:
    """Build the normalized graph for one incident from its member events.

    `events` are all events belonging to the incident (already gathered by the
    IncidentBuilder from the incident's global track(s)). `global_track_ids` are
    the GlobalTracks the incident spans (>1 => multi-track incident).

    Returns a dict with the derived incident confidence and its components so the
    caller (IncidentBuilder) can persist it on the Incident row.
    """
    clear_graph(db, incident_id)
    reg = _NodeRegistry(db, incident_id)
    kind_map = _zone_kind_map(db)

    events = sorted(events, key=lambda e: e.ts)

    # --- root incident node -------------------------------------------------
    incident_node = reg.get("incident", str(incident_id), {"role": "root"})

    # --- track / camera / event / zone nodes + structural edges ------------
    # Group events by their global track so we can build per-track chains.
    members_by_gt: dict[int, set[tuple[str, str]]] = {}
    for gt_id in global_track_ids:
        rows = db.execute(
            select(GlobalTrackMember).where(GlobalTrackMember.global_track_id == gt_id)
        ).scalars().all()
        members_by_gt[gt_id] = {(m.camera_id, m.track_local_id) for m in rows}

    def _gt_for_event(e: Event) -> int | None:
        for gt_id, keys in members_by_gt.items():
            if (e.camera_id, e.track_local_id) in keys:
                return gt_id
        return None

    for gt_id in global_track_ids:
        gt = db.get(GlobalTrack, gt_id)
        track_node = reg.get(
            "track",
            str(gt_id),
            {
                "first_seen": gt.first_seen if gt else None,
                "last_seen": gt.last_seen if gt else None,
                "correlation_confidence": gt.confidence if gt else None,
            },
        )
        # incident -> track (membership)
        _add_edge(db, incident_id, incident_node, track_node, "incident_membership")

    for e in events:
        gt_id = _gt_for_event(e)
        zones = json.loads(e.zones_json) if e.zones_json else []
        kinds = [kind_map.get((e.camera_id, z), "unknown") for z in zones]
        evidence_ref = json.loads(e.evidence_ref_json) if e.evidence_ref_json else {}

        event_node = reg.get(
            "event",
            e.id,
            {
                "event_type": e.event_type,
                "camera_id": e.camera_id,
                "track_local_id": e.track_local_id,
                "ts": e.ts,
                "zones": zones,
                "zone_kinds": kinds,
                "label": e.label,
                "sub_label": e.sub_label,
                "has_snapshot": e.has_snapshot,
                "has_clip": e.has_clip,
                "evidence_ref": evidence_ref,
            },
        )
        camera_node = reg.get("camera", e.camera_id, {"camera_id": e.camera_id})

        # event -> track
        if gt_id is not None:
            track_node = reg.get("track", str(gt_id))
            _add_edge(db, incident_id, event_node, track_node, "event_to_track")
            # track -> camera
            _add_edge(db, incident_id, track_node, camera_node, "track_to_camera")

        # event -> zone (one edge per zone touched)
        for z, kind in zip(zones, kinds):
            zone_node = reg.get(
                "zone", f"{e.camera_id}:{z}",
                {"camera_id": e.camera_id, "zone": z, "kind": kind},
            )
            _add_edge(
                db, incident_id, event_node, zone_node, "event_to_zone",
                evidence={"zone": z, "kind": kind},
            )

    # --- temporal + sequence edges between consecutive events --------------
    seq = analyze_events(events, f"incident:{incident_id}", kind_map)
    risk_by_event = _risk_by_event(seq)
    for prev, cur in zip(events, events[1:]):
        prev_node = reg.get("event", prev.id)
        cur_node = reg.get("event", cur.id)
        delta = round(cur.ts - prev.ts, 2)
        # temporal continuity: closer in time -> higher confidence (bounded).
        temporal_conf = round(max(0.0, 1.0 - min(delta, 300.0) / 300.0), 3)
        _add_edge(
            db, incident_id, prev_node, cur_node, "temporal",
            confidence=temporal_conf,
            evidence={"delta_seconds": delta},
        )
        # sequence edge carries the behavioural risk contributed at `cur`.
        risk = risk_by_event.get(cur.id)
        if risk is not None:
            _add_edge(
                db, incident_id, prev_node, cur_node, "sequence",
                confidence=round(min(risk, 1.0), 3),
                evidence={"risk_contribution": risk, "event_type": cur.event_type},
            )

    # --- correlation + movement edges between consecutive tracks -----------
    correlation_scores = _build_track_and_movement_edges(
        db, incident_id, reg, events, global_track_ids, members_by_gt
    )

    # --- confidence propagation --------------------------------------------
    correlation_confidence = (
        round(sum(correlation_scores) / len(correlation_scores), 3)
        if correlation_scores else 1.0  # single-track: continuity not limiting
    )
    behaviour_confidence = round(seq.anomaly_score, 3)
    incident_confidence = round(min(correlation_confidence, behaviour_confidence), 3)

    db.flush()
    return {
        "incident_confidence": incident_confidence,
        "correlation_confidence": correlation_confidence,
        "behaviour_confidence": behaviour_confidence,
        "band": confidence_band(incident_confidence),
        "sequence": seq,
    }


def _build_track_and_movement_edges(
    db, incident_id, reg, events, global_track_ids, members_by_gt
) -> list[float]:
    """Create correlation (track->track) and movement (camera->camera) edges.

    Correlation edges re-derive the exact correlator sub-scores via score_pair on
    consecutive track spans (deterministic: same inputs -> same output), so the
    edge evidence IS the correlator's own signal. Returns the list of combined
    correlation scores used for confidence propagation.
    """
    # Order tracks within the incident by first-seen time.
    track_events: dict[tuple[str, str], list[Event]] = {}
    for e in events:
        track_events.setdefault((e.camera_id, e.track_local_id), []).append(e)
    spans = [_span_for_track(sorted(evs, key=lambda x: x.ts))
             for evs in track_events.values()]
    spans.sort(key=lambda s: s.start)

    def _gt_id_for_key(cam, trk) -> int | None:
        for gt_id, keys in members_by_gt.items():
            if (cam, trk) in keys:
                return gt_id
        return None

    scores: list[float] = []
    for a, b in zip(spans, spans[1:]):
        gt_a = _gt_id_for_key(a.camera_id, a.track_local_id)
        gt_b = _gt_id_for_key(b.camera_id, b.track_local_id)
        ps = score_pair(db, a, b)
        if ps is None:
            continue
        # correlation edge: track(a) -> track(b), only when they are stitched
        # into the SAME global track (i.e. the correlator merged them).
        if gt_a is not None and gt_b is not None and gt_a == gt_b:
            src = reg.get("track", str(gt_a))
            dst = reg.get("track", str(gt_b))
            evidence = {
                "s_time": round(ps.s_time, 3),
                "s_motion": round(ps.s_motion, 3),
                "s_appearance": round(ps.s_appearance, 3),
                "combined_score": round(ps.score, 3),
                "temporal_gap_seconds": round(ps.gap, 2),
                "topology_transition": f"{a.camera_id} -> {b.camera_id}",
                "from_track": f"{a.camera_id}:{a.track_local_id}",
                "to_track": f"{b.camera_id}:{b.track_local_id}",
            }
            _add_edge(
                db, incident_id, src, dst, "correlation",
                confidence=round(ps.score, 3), evidence=evidence,
            )
            scores.append(ps.score)

        # movement edge: camera(a) -> camera(b) topology transition.
        cam_src = reg.get("camera", a.camera_id)
        cam_dst = reg.get("camera", b.camera_id)
        _add_edge(
            db, incident_id, cam_src, cam_dst, "movement",
            confidence=round(ps.s_time, 3),
            evidence={
                "topology_transition": f"{a.camera_id} -> {b.camera_id}",
                "temporal_gap_seconds": round(ps.gap, 2),
                "s_time": round(ps.s_time, 3),
            },
        )
    return scores


def _add_edge(
    db: Session,
    incident_id: int,
    source: IncidentNode,
    target: IncidentNode,
    edge_type: str,
    confidence: float | None = None,
    evidence: dict | None = None,
) -> IncidentGraphEdge:
    edge = IncidentGraphEdge(
        incident_id=incident_id,
        source_node_id=source.id,
        target_node_id=target.id,
        edge_type=edge_type,
        confidence=confidence,
        evidence=evidence or {},
    )
    db.add(edge)
    return edge


def _risk_by_event(seq) -> dict[str, float]:
    """Map event_id -> the behavioural risk contribution at that step.

    Deterministically re-derived from the same risk weights the sequence analyzer
    uses, so the sequence-edge confidence matches the analyzer's reasoning.
    """
    from app.pipeline.sequence_analyzer import (
        _RISK_DWELL,
        _RISK_LOITER,
        _RISK_RESTRICTED_DWELL,
        _RISK_RESTRICTED_PRESENCE,
    )

    out: dict[str, float] = {}
    for step in seq.steps:
        in_restricted = "restricted" in step.zone_kinds
        if in_restricted and step.event_type in ("dwell", "loiter"):
            out[step.event_id] = _RISK_RESTRICTED_DWELL
        elif in_restricted:
            out[step.event_id] = _RISK_RESTRICTED_PRESENCE
        elif step.event_type == "loiter":
            out[step.event_id] = _RISK_LOITER
        elif step.event_type == "dwell":
            out[step.event_id] = _RISK_DWELL
    return out


# --------------------------------------------------------------------------
# Graph readers: timeline (from graph membership) + machine-readable explanation
# --------------------------------------------------------------------------

def graph_timeline(db: Session, incident_id: int) -> list[dict]:
    """Chronological timeline derived from the incident graph's event nodes.

    Every item retains: source event id, camera, track, zone(s), event type,
    timestamp, and an evidence reference — all read from the stored graph nodes,
    not re-narrated. No unsupported narrative is generated.
    """
    event_nodes = db.execute(
        select(IncidentNode).where(
            IncidentNode.incident_id == incident_id,
            IncidentNode.node_type == "event",
        )
    ).scalars().all()

    items = []
    from app.models.evidence import EvidenceObject
    event_ids = [n.ref_id for n in event_nodes]
    evidence_rows = db.scalars(select(EvidenceObject).where(EvidenceObject.event_id.in_(event_ids))).all() if event_ids else []
    evidence_by_event = {}
    for item in evidence_rows:
        evidence_by_event.setdefault(item.event_id, {})[item.kind] = item
    for n in event_nodes:
        a = n.attributes or {}
        records = evidence_by_event.get(n.ref_id, {})
        snapshot, clip = records.get("snapshot"), records.get("clip")
        aev = {"snapshot_url": f"/api/v1/evidence/{snapshot.id}/content" if snapshot and snapshot.status == "available" else None,
               "clip_url": f"/api/v1/evidence/{clip.id}/content" if clip and clip.status == "available" else None,
               "snapshot_status": snapshot.status if snapshot else "not-requested",
               "clip_status": clip.status if clip else "not-requested"}
        # Mock assets use the same authorized evidence vault as live sources;
        # an unavailable synthetic asset must not become a broken media URL.
        event = db.get(Event, n.ref_id)
        aev["media_origin"] = "synthetic" if event and event.source_type == "mock" else "source"
        items.append({
            "event_id": n.ref_id,
            "ts": a.get("ts"),
            "camera_id": a.get("camera_id"),
            "track_local_id": a.get("track_local_id"),
            "event_type": a.get("event_type"),
            "zones": a.get("zones", []),
            "zone_kinds": a.get("zone_kinds", []),
            "evidence": aev,
        })
    items.sort(key=lambda i: (i["ts"] is None, i["ts"]))
    return items


def graph_as_dict(db: Session, incident_id: int) -> dict:
    """Serialize the incident graph: nodes + typed edges (with evidence)."""
    nodes = db.execute(
        select(IncidentNode).where(IncidentNode.incident_id == incident_id)
    ).scalars().all()
    edges = db.execute(
        select(IncidentGraphEdge).where(IncidentGraphEdge.incident_id == incident_id)
    ).scalars().all()

    node_ref = {n.id: {"type": n.node_type, "ref_id": n.ref_id} for n in nodes}
    return {
        "nodes": [
            {
                "id": n.id,
                "type": n.node_type,
                "ref_id": n.ref_id,
                "attributes": {k: v for k, v in (n.attributes or {}).items() if k != "evidence_ref"},
            }
            for n in nodes
        ],
        "edges": [
            {
                "id": e.id,
                "type": e.edge_type,
                "source": node_ref.get(e.source_node_id),
                "target": node_ref.get(e.target_node_id),
                "confidence": e.confidence,
                "evidence": e.evidence or {},
            }
            for e in edges
        ],
    }


def build_explanation(db: Session, incident_id: int) -> dict:
    """Machine-readable explanation object derived entirely from stored graph.

    {
      "why_created": [...],
      "supporting_tracks": [...],
      "supporting_events": [...],
      "correlations": [...],
      "behaviour_signals": [...],
      "confidence": <float>,
      "confidence_band": "...",
    }
    """
    from app.models.entities import Incident

    inc = db.get(Incident, incident_id)
    nodes = db.execute(
        select(IncidentNode).where(IncidentNode.incident_id == incident_id)
    ).scalars().all()
    edges = db.execute(
        select(IncidentGraphEdge).where(IncidentGraphEdge.incident_id == incident_id)
    ).scalars().all()

    tracks = [n.ref_id for n in nodes if n.node_type == "track"]
    event_nodes = [n for n in nodes if n.node_type == "event"]
    cameras = sorted({n.ref_id for n in nodes if n.node_type == "camera"})

    correlations = [
        {
            "confidence": e.confidence,
            **(e.evidence or {}),
        }
        for e in edges if e.edge_type == "correlation"
    ]
    behaviour_signals = [
        {
            "event_id": next(
                (nn.ref_id for nn in nodes if nn.id == e.target_node_id), None
            ),
            "risk_contribution": (e.evidence or {}).get("risk_contribution"),
            "event_type": (e.evidence or {}).get("event_type"),
            "confidence": e.confidence,
        }
        for e in edges if e.edge_type == "sequence"
    ]

    why: list[str] = []
    # Behaviour pillar.
    restricted_hits = [
        b for b in behaviour_signals
        if b["event_type"] in ("dwell", "loiter") and (b["risk_contribution"] or 0) >= 0.6
    ]
    if restricted_hits:
        why.append(
            f"Behavioural anomaly: {len(restricted_hits)} restricted-zone "
            f"dwell/loiter step(s) detected."
        )
    elif behaviour_signals:
        why.append("Behavioural risk accumulated across the track sequence.")
    # Correlation pillar. Cross-camera stitching is evidenced by correlation
    # edges (tracks merged into one movement across multiple cameras), not the
    # number of distinct global-track nodes.
    if correlations:
        why.append(
            f"Cross-camera correlation stitched observations across "
            f"{len(cameras)} cameras into one movement via "
            f"{len(correlations)} correlation transition(s)."
        )
    elif len(tracks) > 1:
        why.append(
            f"{len(tracks)} tracks associated across {len(cameras)} cameras."
        )
    elif tracks:
        why.append("Single-camera track (no cross-camera transition required).")
    if correlations:
        strongest = max(correlations, key=lambda c: c.get("combined_score", 0) or 0)
        why.append(
            "Strongest correlation "
            f"{strongest.get('topology_transition')} "
            f"(score {strongest.get('combined_score')}, "
            f"gap {strongest.get('temporal_gap_seconds')}s, "
            f"appearance {strongest.get('s_appearance')})."
        )

    return {
        "incident_id": incident_id,
        "why_created": why,
        "supporting_tracks": tracks,
        "supporting_events": [n.ref_id for n in event_nodes],
        "cameras": cameras,
        "correlations": correlations,
        "behaviour_signals": behaviour_signals,
        "confidence": inc.confidence if inc else None,
        "confidence_band": confidence_band(inc.confidence if inc else None),
    }
