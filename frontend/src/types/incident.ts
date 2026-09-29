// TypeScript types mirroring the DARSON v1 incident API responses.
// These correspond 1:1 to backend/app/api/routes/v1_incidents.py — do not add
// fields the backend does not return.

export type ConfidenceBand = "high" | "medium" | "low" | "unknown";
export type LifecycleState = "open" | "triage" | "confirmed" | "dismissed";
export type LifecycleAction = "start_triage" | "confirm" | "dismiss" | "reopen";

export interface EvidenceRef {
  snapshot_url?: string | null;
  clip_url?: string | null;
}

export interface IncidentSummary {
  id: number;
  status: string;
  priority: string | null;
  confidence: number | null;
  confidence_band: ConfidenceBand;
  start_time: number | null;
  end_time: number | null;
  cameras: string[];
  summary_text: string | null;
}

export interface IncidentEvent {
  event_id: string;
  event_type?: string;
  camera_id?: string;
  track_local_id?: string;
  ts?: number | null;
  zones?: string[];
  zone_kinds?: string[];
  label?: string | null;
  sub_label?: string | null;
  has_snapshot?: boolean;
  has_clip?: boolean;
  evidence_ref?: EvidenceRef;
}

export interface Correlation {
  confidence: number | null;
  s_time?: number;
  s_motion?: number;
  s_appearance?: number;
  combined_score?: number;
  temporal_gap_seconds?: number;
  topology_transition?: string;
  from_track?: string;
  to_track?: string;
}

export interface BehaviourSignal {
  event_id: string | null;
  risk_contribution: number | null;
  event_type: string | null;
  confidence: number | null;
}

export interface Explanation {
  incident_id: number;
  why_created: string[];
  supporting_tracks: string[];
  supporting_events: string[];
  cameras: string[];
  correlations: Correlation[];
  behaviour_signals: BehaviourSignal[];
  confidence: number | null;
  confidence_band: ConfidenceBand;
}

export interface IncidentDetail extends IncidentSummary {
  state: string;
  allowed_actions: string[];
  tracks: string[];
  events: IncidentEvent[];
  explanation: Explanation;
}

export interface TimelineStep {
  event_id: string;
  ts: number | null;
  camera_id: string | null;
  track_local_id: string | null;
  event_type: string | null;
  zones: string[];
  zone_kinds: string[];
  evidence: EvidenceRef;
}

export interface TimelineResponse {
  incident_id: number;
  timeline: TimelineStep[];
}

export type GraphNodeType = "incident" | "track" | "camera" | "zone" | "event";
export type GraphEdgeType =
  | "incident_membership"
  | "event_to_track"
  | "track_to_camera"
  | "event_to_zone"
  | "temporal"
  | "sequence"
  | "correlation"
  | "movement";

export interface GraphNode {
  id: number;
  type: GraphNodeType;
  ref_id: string;
  attributes: Record<string, unknown>;
}

export interface GraphEdgeEnd {
  type: GraphNodeType;
  ref_id: string;
}

export interface GraphEdge {
  id: number;
  type: GraphEdgeType;
  source: GraphEdgeEnd | null;
  target: GraphEdgeEnd | null;
  confidence: number | null;
  evidence: Record<string, unknown>;
}

export interface IncidentGraph {
  incident_id: number;
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface StateResponse {
  incident_id: number;
  state: string;
  allowed_actions: string[];
}

export interface TransitionResult {
  incident_id: number;
  from_state: string | null;
  state: string;
  action: string;
  allowed_actions: string[];
}

export interface StateTransition {
  from_state: string | null;
  to_state: string;
  action: string;
  reviewer: string | null;
  note: string | null;
  created_at: string | null;
}

export interface StateHistoryResponse {
  incident_id: number;
  history: StateTransition[];
}
