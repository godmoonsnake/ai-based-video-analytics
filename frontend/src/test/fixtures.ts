import type {
  IncidentDetail,
  IncidentGraph,
  IncidentSummary,
  StateHistoryResponse,
  TimelineResponse,
} from "../types/incident";

export const summary: IncidentSummary = {
  id: 1,
  status: "open",
  category: "restricted_entry",
  priority: "high",
  confidence: 0.6,
  confidence_band: "medium",
  start_time: 1_700_000_000,
  end_time: 1_700_000_120,
  cameras: ["gate_3", "corridor_1", "restricted_2"],
  summary_text: "Track across 3 cameras with restricted dwell.",
};

export const summaryDismissed: IncidentSummary = {
  ...summary,
  id: 2,
  status: "dismissed",
  category: "review",
  priority: "low",
  confidence: 0.31,
  confidence_band: "low",
  summary_text: "Single-camera transit, dismissed by operator.",
};

export const detail: IncidentDetail = {
  ...summary,
  state: "open",
  allowed_actions: ["start_triage", "dismiss"],
  tracks: ["1"],
  events: [
    {
      event_id: "evt-a",
      event_type: "detection",
      camera_id: "gate_3",
      track_local_id: "a1",
      ts: 1_700_000_001,
      zones: ["entry_zone"],
      zone_kinds: ["entry"],
      has_snapshot: true,
      has_clip: true,
      evidence_ref: {
        snapshot_url: "/mock-evidence/gate_3/a1/snapshot.jpg",
        clip_url: "/mock-evidence/gate_3/a1/clip.mp4",
      },
    },
    {
      event_id: "evt-c",
      event_type: "dwell",
      camera_id: "restricted_2",
      track_local_id: "c3",
      ts: 1_700_000_030,
      zones: ["restricted"],
      zone_kinds: ["restricted"],
      has_snapshot: true,
      has_clip: false,
      evidence_ref: { snapshot_url: "/mock-evidence/restricted_2/c3/snapshot.jpg", clip_url: null },
    },
  ],
  explanation: {
    incident_id: 1,
    why_created: [
      "Behavioural anomaly: 1 restricted-zone dwell/loiter step(s) detected.",
      "Cross-camera correlation stitched observations across 3 cameras.",
    ],
    supporting_tracks: ["1"],
    supporting_events: ["evt-a", "evt-c"],
    cameras: ["gate_3", "corridor_1", "restricted_2"],
    correlations: [
      {
        confidence: 0.75,
        s_time: 0.25,
        s_motion: 1.0,
        s_appearance: 1.0,
        combined_score: 0.745,
        temporal_gap_seconds: 6.0,
        topology_transition: "gate_3 -> corridor_1",
        from_track: "gate_3:a1",
        to_track: "corridor_1:b7",
      },
    ],
    behaviour_signals: [
      { event_id: "evt-c", risk_contribution: 0.6, event_type: "dwell", confidence: 0.6 },
    ],
    confidence: 0.6,
    confidence_band: "medium",
  },
};

export const timeline: TimelineResponse = {
  incident_id: 1,
  timeline: [
    {
      event_id: "evt-a",
      ts: 1_700_000_001,
      camera_id: "gate_3",
      track_local_id: "a1",
      event_type: "detection",
      zones: ["entry_zone"],
      zone_kinds: ["entry"],
      evidence: { snapshot_url: "/mock-evidence/gate_3/a1/snapshot.jpg", clip_url: null },
    },
    {
      event_id: "evt-c",
      ts: 1_700_000_030,
      camera_id: "restricted_2",
      track_local_id: "c3",
      event_type: "dwell",
      zones: ["restricted"],
      zone_kinds: ["restricted"],
      evidence: { snapshot_url: null, clip_url: null },
    },
  ],
};

export const graph: IncidentGraph = {
  incident_id: 1,
  nodes: [
    { id: 1, type: "incident", ref_id: "1", attributes: {} },
    { id: 2, type: "track", ref_id: "1", attributes: {} },
    { id: 3, type: "camera", ref_id: "gate_3", attributes: {} },
    {
      id: 4,
      type: "event",
      ref_id: "evt-a",
      attributes: { event_type: "detection", camera_id: "gate_3", ts: 1_700_000_001 },
    },
  ],
  edges: [
    {
      id: 1,
      type: "incident_membership",
      source: { type: "incident", ref_id: "1" },
      target: { type: "track", ref_id: "1" },
      confidence: null,
      evidence: {},
    },
    {
      id: 2,
      type: "event_to_track",
      source: { type: "event", ref_id: "evt-a" },
      target: { type: "track", ref_id: "1" },
      confidence: null,
      evidence: {},
    },
    {
      id: 3,
      type: "correlation",
      source: { type: "track", ref_id: "1" },
      target: { type: "track", ref_id: "1" },
      confidence: 0.745,
      evidence: { combined_score: 0.745, s_time: 0.25 },
    },
  ],
};

export const history: StateHistoryResponse = {
  incident_id: 1,
  history: [
    {
      from_state: "open",
      to_state: "triage",
      action: "start_triage",
      reviewer: "operator",
      note: null,
      created_at: "2026-09-29T10:00:00",
    },
  ],
};
