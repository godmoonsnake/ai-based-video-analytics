// Typed API client for the DARSON intelligence-layer backend.
const BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";

export interface IncidentSummary {
  id: number;
  status: string;
  priority: string | null;
  confidence: number | null;
  start_time: number | null;
  end_time: number | null;
  cameras: string[];
  summary_text: string | null;
}

export interface TimelineStep {
  event_id: string;
  camera_id: string;
  event_type: string;
  ts: number;
  zones: string[];
  role: string | null;
  evidence: { snapshot_url?: string | null; clip_url?: string | null };
}

export interface IncidentDetail extends IncidentSummary {
  summary_text: string | null;
  graph: {
    nodes: { event_id: string; role: string }[];
    edges: { from: string; to: string; relation: string; delta_seconds: number | null }[];
  };
  timeline: TimelineStep[];
}

export interface GlobalTrack {
  global_track_id: number;
  first_seen: number | null;
  last_seen: number | null;
  confidence: number | null;
  members: { camera_id: string; track_local_id: string; join_score: number | null; method: string }[];
}

export interface Pattern {
  id: number;
  pattern_type: string;
  key: Record<string, unknown>;
  count: number;
  score: number | null;
}

export interface Camera {
  id: string;
  name: string;
  x: number | null;
  y: number | null;
}

export interface SearchResponse {
  query: string | null;
  parsed_filter: Record<string, unknown>;
  events: {
    event_id: string;
    camera_id: string;
    event_type: string;
    label: string | null;
    sub_label: string | null;
    ts: number;
    evidence: { snapshot_url?: string | null; clip_url?: string | null };
  }[];
  incidents: { id: number; status: string; priority: string | null; summary_text: string | null }[];
  human_review_required: boolean;
}

async function jget<T>(path: string): Promise<T> {
  const r = await fetch(`${BASE}${path}`);
  if (!r.ok) throw new Error(`GET ${path} -> ${r.status}`);
  return r.json() as Promise<T>;
}

async function jpost<T>(path: string, body?: unknown): Promise<T> {
  const r = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!r.ok) throw new Error(`POST ${path} -> ${r.status}`);
  return r.json() as Promise<T>;
}

export const api = {
  base: BASE,
  health: () => jget<{ status: string; database: boolean }>("/health"),
  cameras: () => jget<Camera[]>("/cameras"),
  incidents: (status?: string) =>
    jget<IncidentSummary[]>(`/incidents${status ? `?status=${status}` : ""}`),
  incident: (id: number) => jget<IncidentDetail>(`/incidents/${id}`),
  globalTracks: () => jget<GlobalTrack[]>("/tracks/global"),
  patterns: (patternType?: string) =>
    jget<Pattern[]>(`/patterns${patternType ? `?pattern_type=${patternType}` : ""}`),
  search: (body: Record<string, unknown>) => jpost<SearchResponse>("/search", body),
  // demo/pipeline helpers
  ingestMock: () => jpost<{ ingested: number }>("/events/ingest/mock"),
  correlate: () => jpost<{ count: number }>("/tracks/correlate"),
  buildIncidents: () => jpost<{ built: number }>("/incidents/build"),
  minePatterns: () => jpost<{ mined: number }>("/patterns/mine"),
  feedback: (id: number, action: string, note?: string) =>
    jpost<{ status: string }>(`/incidents/${id}/feedback`, { action, note }),
};
