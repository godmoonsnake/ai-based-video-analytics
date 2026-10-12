import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { api, ApiError } from "../services/api";
import { IncidentDetail } from "../components/detail/IncidentDetail";
import { detail, timeline, graph, history } from "./fixtures";

const allSpied = () => {
  vi.spyOn(api, "getIncident").mockResolvedValue(detail);
  vi.spyOn(api, "getTimeline").mockResolvedValue(timeline);
  vi.spyOn(api, "getGraph").mockResolvedValue(graph);
  vi.spyOn(api, "getStateHistory").mockResolvedValue(history);
  vi.spyOn(api, "getResponse").mockResolvedValue({ version: 1, response_state: "unassigned", owner: null, policy: null, steps_done: [] });
};

describe("IncidentDetail (happy path)", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    allSpied();
  });

  it("renders dossier header, why-created reasons and correlation cards", async () => {
    render(<IncidentDetail incidentId={1} tab="case" onTabChange={() => {}} onChanged={() => {}} />);
    await waitFor(() => expect(screen.getByTestId("incident-detail")).toBeInTheDocument());

    // header identity
    expect(screen.getByText("#1")).toBeInTheDocument();
    expect(screen.getByText("high")).toBeInTheDocument(); // priority chip
    expect(screen.getAllByText("open").length).toBeGreaterThan(0); // status and history

    // why-created reasons
    expect(screen.getAllByTestId("why-reason")).toHaveLength(2);

    // correlation card with sub-scores
    expect(screen.getByTestId("correlation-card")).toBeInTheDocument();
    expect(screen.getAllByText("gate_3 -> corridor_1").length).toBeGreaterThan(0);

    // lifecycle shows only backend-allowed actions
    expect(screen.getByTestId("action-start_triage")).toBeInTheDocument();
    expect(screen.getByTestId("action-dismiss")).toBeInTheDocument();
    expect(screen.queryByTestId("action-confirm")).not.toBeInTheDocument();
  });

  it("renders timeline steps and switches tabs on demand", async () => {
    const onTabChange = vi.fn();
    render(
      <IncidentDetail incidentId={1} tab="timeline" onTabChange={onTabChange} onChanged={() => {}} />,
    );
    await waitFor(() => expect(screen.getAllByTestId("timeline-step").length).toBe(2));
  });

  it("renders the evidence graph svg with node labels", async () => {
    render(<IncidentDetail incidentId={1} tab="graph" onTabChange={() => {}} onChanged={() => {}} />);
    await waitFor(() => expect(screen.getByTestId("incident-graph-svg")).toBeInTheDocument());
    // one rendered edge per graph edge (correlation self-loop included)
    await waitFor(() =>
      expect(screen.getAllByTestId(/graph-edge-/).length).toBe(graph.edges.length),
    );
  });

  it("renders audit history items", async () => {
    render(<IncidentDetail incidentId={1} tab="audit" onTabChange={() => {}} onChanged={() => {}} />);
    await waitFor(() => expect(screen.getAllByTestId("history-item").length).toBe(1));
    expect(screen.getByTestId("history-item")).toHaveTextContent(/reviewer · operator/);
  });
});

describe("IncidentDetail (error path)", () => {
  beforeEach(() => vi.restoreAllMocks());

  it("shows a structured backend error with retry", async () => {
    vi.spyOn(api, "getIncident").mockRejectedValue(new ApiError("GET / failed (500)", 500));
    vi.spyOn(api, "getTimeline").mockResolvedValue({ incident_id: 1, timeline: [] });
    vi.spyOn(api, "getGraph").mockResolvedValue({ incident_id: 1, nodes: [], edges: [] });
    vi.spyOn(api, "getStateHistory").mockResolvedValue({ incident_id: 1, history: [] });

    render(<IncidentDetail incidentId={1} tab="case" onTabChange={() => {}} onChanged={() => {}} />);
    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    expect(screen.getByText("Backend error")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /retry/i })).toBeInTheDocument();
  });
});

describe("api client error handling", () => {
  const realFetch = globalThis.fetch;
  beforeEach(() => vi.restoreAllMocks());
  afterEach(() => {
    globalThis.fetch = realFetch;
  });

  it("throws a client ApiError on 4xx with detail", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 404,
      json: async () => ({ detail: "incident not found" }),
    }) as unknown as typeof fetch;
    await expect(api.getIncident(999)).rejects.toMatchObject({
      status: 404,
      detail: "incident not found",
    });
  });

  it("throws a server ApiError on 5xx", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      json: async () => ({}),
    }) as unknown as typeof fetch;
    const err = await api.listIncidents().catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.isServer).toBe(true);
  });

  it("throws a network ApiError (status 0) on transport failure", async () => {
    globalThis.fetch = vi
      .fn()
      .mockRejectedValue(new TypeError("failed to fetch")) as unknown as typeof fetch;
    const err = await api.listIncidents().catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.isNetwork).toBe(true);
  });
});

describe("LifecycleBar within detail", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    allSpied();
  });

  it("applies a transition, toasts and notifies the parent", async () => {
    const spy = vi.spyOn(api, "transition").mockResolvedValue({
      incident_id: 1,
      from_state: "open",
      state: "triage",
      action: "start_triage",
      allowed_actions: ["confirm", "dismiss"],
    });
    const onChanged = vi.fn();
    render(<IncidentDetail incidentId={1} tab="case" onTabChange={() => {}} onChanged={onChanged} />);
    await waitFor(() => expect(screen.getByTestId("action-start_triage")).toBeInTheDocument());
    await userEvent.click(screen.getByTestId("action-start_triage"));
    await waitFor(() => expect(spy).toHaveBeenCalledWith(1, "start_triage", { note: undefined }));
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
  });

  it("surfaces a 409 invalid-transition rejection without crashing", async () => {
    vi.spyOn(api, "transition").mockRejectedValue(
      new ApiError("conflict", 409, "cannot 'confirm' from state 'open'"),
    );
    render(<IncidentDetail incidentId={1} tab="case" onTabChange={() => {}} onChanged={() => {}} />);
    await waitFor(() => expect(screen.getByTestId("action-start_triage")).toBeInTheDocument());
    await userEvent.click(screen.getByTestId("action-start_triage"));
    await waitFor(() =>
      expect(screen.getAllByRole("alert").some((alert) => /Transition rejected/.test(alert.textContent ?? ""))).toBe(true),
    );
  });
});
