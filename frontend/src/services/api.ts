// Centralized API client for the DARSON v1 incident API.
//
// All frontend data access goes through this module. The frontend never touches
// PostgreSQL directly and holds no Frigate credentials — it consumes only the
// backend HTTP API. The base defaults to "" (same-origin): behind the reverse
// proxy the browser talks to a single origin, so requests are relative
// (/api/v1/...). VITE_API_BASE can override for split deployments.
import type {
  IncidentDetail,
  IncidentGraph,
  IncidentSummary,
  LifecycleAction,
  StateHistoryResponse,
  StateResponse,
  TimelineResponse,
  TransitionResult,
} from "../types/incident";
import type { Camera, HealthStatus } from "../types/system";
import { currentAccessToken, expireAuth } from "./auth";

export const API_BASE: string =
  (import.meta.env?.VITE_API_BASE as string | undefined)?.replace(/\/$/, "") ?? "";

/** A structured API error distinguishing HTTP status from network failure. */
export class ApiError extends Error {
  status: number; // 0 => network/transport failure
  detail?: string;
  constructor(message: string, status: number, detail?: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
  get isNetwork(): boolean {
    return this.status === 0;
  }
  get isClient(): boolean {
    return this.status >= 400 && this.status < 500;
  }
  get isServer(): boolean {
    return this.status >= 500;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    const token = currentAccessToken();
    res = await fetch(`${API_BASE}${path}`, {
      headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      ...init,
    });
  } catch (e) {
    throw new ApiError(
      `Network error contacting the backend at ${API_BASE || "same origin"}`,
      0,
      e instanceof Error ? e.message : String(e),
    );
  }

  if (!res.ok) {
    if (res.status === 401) expireAuth();
    let detail: string | undefined;
    try {
      const body = await res.json();
      detail = typeof body?.detail === "string" ? body.detail : JSON.stringify(body);
    } catch {
      detail = undefined;
    }
    throw new ApiError(`${init?.method ?? "GET"} ${path} failed (${res.status})`, res.status, detail);
  }

  return (await res.json()) as T;
}

async function download(path: string, fallbackName: string): Promise<void> {
  const token = currentAccessToken();
  const response = await fetch(`${API_BASE}${path}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!response.ok) {
    if (response.status === 401) expireAuth();
    throw new ApiError(`Download failed (${response.status})`, response.status);
  }
  const blob = await response.blob();
  const name = response.headers.get("content-disposition")?.match(/filename="?([^";]+)"?/i)?.[1] ?? fallbackName;
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  document.body.append(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export const api = {
  base: API_BASE,

  getPilotStatus(): Promise<PilotStatus> { return request("/api/v1/pilot/status"); },
  getPilotTasks(includeResolved = false): Promise<PilotTask[]> {
    return request(`/api/v1/pilot/tasks?include_resolved=${includeResolved}`);
  },
  getPilotNotices(): Promise<PilotNotice[]> { return request("/api/v1/pilot/notices"); },
  markPilotPresented(id: string): Promise<unknown> {
    return request(`/api/v1/pilot/tasks/${encodeURIComponent(id)}/presented`, { method: "POST" });
  },
  pilotAction(id: string, expectedVersion: number, action: "claim" | "acknowledge" | "outcome", data: Record<string, unknown> = {}): Promise<unknown> {
    return request(`/api/v1/pilot/tasks/${encodeURIComponent(id)}/actions`, { method: "POST",
      body: JSON.stringify({ action, expected_version: expectedVersion, ...data }) });
  },
  verifyPilotLabel(id: string): Promise<unknown> {
    return request(`/api/v1/pilot/tasks/${encodeURIComponent(id)}/verify-label`, { method: "POST" });
  },
  retryPilotNotice(id: string): Promise<unknown> {
    return request(`/api/v1/pilot/notices/${encodeURIComponent(id)}/retry`, { method: "POST" });
  },

  listIncidents(params?: { status?: string; priority?: string }): Promise<IncidentSummary[]> {
    const qs = new URLSearchParams();
    if (params?.status) qs.set("status", params.status);
    if (params?.priority) qs.set("priority", params.priority);
    const q = qs.toString();
    return request<IncidentSummary[]>(`/api/v1/incidents${q ? `?${q}` : ""}`);
  },

  getIncident(id: number): Promise<IncidentDetail> {
    return request<IncidentDetail>(`/api/v1/incidents/${id}`);
  },

  getTimeline(id: number): Promise<TimelineResponse> {
    return request<TimelineResponse>(`/api/v1/incidents/${id}/timeline`);
  },

  getGraph(id: number): Promise<IncidentGraph> {
    return request<IncidentGraph>(`/api/v1/incidents/${id}/graph`);
  },

  getState(id: number): Promise<StateResponse> {
    return request<StateResponse>(`/api/v1/incidents/${id}/state`);
  },

  getStateHistory(id: number): Promise<StateHistoryResponse> {
    return request<StateHistoryResponse>(`/api/v1/incidents/${id}/state/history`);
  },

  transition(
    id: number,
    action: LifecycleAction,
    opts?: { reviewer?: string; note?: string },
  ): Promise<TransitionResult> {
    return request<TransitionResult>(`/api/v1/incidents/${id}/state`, {
      method: "POST",
      body: JSON.stringify({ action, reviewer: opts?.reviewer, note: opts?.note }),
    });
  },

  listCameras(): Promise<Camera[]> {
    return request<Camera[]>("/cameras");
  },

  getHealth(): Promise<HealthStatus> {
    return request<HealthStatus>("/health");
  },

  getOperationsOverview(): Promise<{ demo_mode: boolean; active_incidents: number; unassigned_incidents: number;
    oldest_age_minutes: number; open_sla_breaches: number; pending_evidence: number; source_stale: number;
    source_count: number; camera_offline: number; camera_degraded: number; recording_gaps: number;
    evidence_degraded: number; pending_work: number; checked_at: number }> {
    return request("/api/v1/operations/overview");
  },

  getReviewManifest(): Promise<ReviewManifest> {
    return request("/api/v1/demo/manifest");
  },

  replayReview(): Promise<ReviewManifest> {
    return request("/api/v1/demo/replay", { method: "POST" });
  },

  loadCaseStudyDemo(): Promise<{ synthetic: boolean; observations: Array<{ incident_id: number | null }> }> {
    return request("/api/v1/case-studies/demo", { method: "POST" });
  },

  getCameraHealth(): Promise<CameraHealth[]> {
    return request("/api/v1/health/cameras");
  },

  getHealthMetrics(): Promise<HealthMetrics> {
    return request("/api/v1/health/metrics?hours=24");
  },

  getMyTasks(): Promise<ResponseTask[]> {
    return request("/api/v1/operations/tasks");
  },

  searchInvestigation(query: string): Promise<InvestigationResults> {
    return request("/search", { method: "POST", body: JSON.stringify({ q: query }) });
  },

  getPatterns(): Promise<HistoricalPattern[]> {
    return request("/patterns");
  },

  minePatterns(): Promise<{ mined: number }> {
    return request("/patterns/mine", { method: "POST" });
  },

  getResponse(id: number): Promise<any> {
    return request(`/api/v1/incidents/${id}/response`);
  },

  getSla(id: number): Promise<Array<{ stage: string; deadline_at: number; status: string; owner_at_deadline: string | null }>> {
    return request(`/api/v1/incidents/${id}/sla`);
  },

  responseAction(id: number, action: string, expectedVersion: number, data: Record<string, unknown> = {}): Promise<any> {
    return request(`/api/v1/incidents/${id}/actions`, { method: "POST", body: JSON.stringify({
      action, expected_version: expectedVersion, idempotency_key: crypto.randomUUID(), ...data,
    }) });
  },

  exportIncident(id: number, format: "json" | "csv"): string {
    return `${API_BASE}/api/v1/incidents/${id}/export?format=${format}`;
  },

  downloadIncident(id: number, format: "json" | "csv"): Promise<void> {
    return download(`/api/v1/incidents/${id}/export?format=${format}`, `darson-case-${id}.${format}`);
  },

  downloadExport(path: string, format: "pdf" | "zip"): Promise<void> {
    if (!/^\/api\/v1\/exports\/[a-f0-9]+\/download$/.test(path)) throw new Error("Invalid export path");
    return download(path, `darson-case.${format}`);
  },

  async createExport(id: number, format: "pdf" | "zip", version: number): Promise<{id: string; status: string}> {
    return request(`/api/v1/incidents/${id}/exports`, { method: "POST", body: JSON.stringify({
      format, expected_version: version, idempotency_key: crypto.randomUUID(),
    }) });
  },

  getExport(id: string): Promise<{status: string; download_url: string | null; failure_class?: string}> {
    return request(`/api/v1/exports/${encodeURIComponent(id)}`);
  },

  // Deterministic demo pipeline (legacy endpoints, still valid). Used only by
  // the "seed demo data" affordance to ingest the mock scenario and build
  // incidents from it.
  runDemoPipeline(): Promise<unknown> {
    return request("/events/ingest/mock", { method: "POST" })
      .then(() => request("/tracks/correlate", { method: "POST" }))
      .then(() => request("/incidents/build", { method: "POST" }));
  },
};

export interface PilotStatus {
  pilot_mode: boolean; simulated: boolean; site: string; timezone: string;
  rules_configured: number; data_agreement_configured: boolean;
  notification_provider: string; offline_operation_verified: boolean;
  retention_failures?: number;
}
export interface PilotNotice {
  id: string; case_id: string | null; camera_id: string | null; reason: string;
  status: string; created_at: number; failure_class: string | null; attempts: number;
}
export interface PilotTask {
  id: string; incident_id: number; version: number; category: string;
  priority: string; camera_id: string; zone_name: string; instruction: string;
  state: string; owner: string | null; created_at: number; observed_at: number;
  acknowledgement_deadline: number; acknowledged_at: number | null;
  outcome: string | null; outcome_note: string | null; label_verified: boolean;
  evidence: Array<{ id: string; kind: string; status: string; content_url: string | null }>;
  notifications: Array<{ id: string; reason: string; status: string; attempts: number; failure_class: string | null }>;
}

export interface ReviewManifest {
  id: string;
  version: number;
  clock: string;
  synthetic: boolean;
  description: string;
  ready: boolean;
  scenarios: Array<{ id: string; title: string; subtitle: string; talk_track: string; incident_id: number | null }>;
}

export interface CameraHealth {
  camera_id: string;
  state: string;
  stream_state: string;
  video_state: string;
  recording_state: string;
  evidence_state: string;
  maintenance: boolean;
  frame_arrival_fps: number | null;
  last_frame_at: number | null;
  updated_at: number | null;
}

export interface HealthMetrics {
  window_hours: number;
  unavailable_camera_minutes: number;
  recording_gap_minutes: number;
  evidence_capture_success_rate: number | null;
  source_to_darson_lag_seconds: number | null;
  event_to_incident_latency_seconds: number | null;
  samples: number;
}

export interface ResponseTask {
  incident_id: number;
  response_state: string;
  owner: string | null;
  priority: string | null;
  instruction: string;
  location: { site: string };
}

export interface HistoricalPattern {
  id: number;
  pattern_type: string;
  key: Record<string, unknown>;
  count: number;
  score: number | null;
}

export interface InvestigationResults {
  query: string | null;
  parsed_filter: Record<string, unknown>;
  human_review_required: boolean;
  events: Array<{ event_id: string; camera_id: string; event_type: string; label: string | null;
    ts: number; evidence: { snapshot: { status: string; content_url: string | null };
      clip: { status: string; content_url: string | null } } }>;
  incidents: Array<{ id: number; status: string; priority: string | null; summary_text: string | null }>;
}
