// Centralized API client for the DARSON v1 incident API.
//
// All frontend data access goes through this module. The frontend never touches
// PostgreSQL directly and holds no Frigate credentials — it consumes only the
// backend HTTP API.
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

export const API_BASE: string =
  (import.meta.env?.VITE_API_BASE as string | undefined) ?? "http://localhost:8000";

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
    res = await fetch(`${API_BASE}${path}`, {
      headers: { "Content-Type": "application/json" },
      ...init,
    });
  } catch (e) {
    throw new ApiError(
      `Network error contacting the backend at ${API_BASE}`,
      0,
      e instanceof Error ? e.message : String(e),
    );
  }

  if (!res.ok) {
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

export const api = {
  base: API_BASE,

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

  // Deterministic demo pipeline (legacy endpoints, still valid). Used only by the
  // "Run demo" affordance to seed mock data + build incidents.
  runDemoPipeline(): Promise<unknown> {
    return request("/events/ingest/mock", { method: "POST" })
      .then(() => request("/tracks/correlate", { method: "POST" }))
      .then(() => request("/incidents/build", { method: "POST" }));
  },
};
