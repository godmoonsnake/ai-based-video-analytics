import { render, screen, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { api, ApiError } from "../services/api";
import { IncidentDetailPage } from "../pages/IncidentDetailPage";

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
    globalThis.fetch = vi.fn().mockRejectedValue(new TypeError("failed to fetch")) as unknown as typeof fetch;
    const err = await api.listIncidents().catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.isNetwork).toBe(true);
  });
});

describe("IncidentDetailPage error state", () => {
  beforeEach(() => vi.restoreAllMocks());

  it("shows an error state with retry when detail fails to load", async () => {
    vi.spyOn(api, "getIncident").mockRejectedValue(new ApiError("boom", 500));
    vi.spyOn(api, "getTimeline").mockResolvedValue({ incident_id: 1, timeline: [] });
    vi.spyOn(api, "getGraph").mockResolvedValue({ incident_id: 1, nodes: [], edges: [] });
    vi.spyOn(api, "getStateHistory").mockResolvedValue({ incident_id: 1, history: [] });

    render(<IncidentDetailPage incidentId={1} />);
    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    expect(screen.getByText("Backend error")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /retry/i })).toBeInTheDocument();
  });
});
