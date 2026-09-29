import { render, screen, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { api } from "../services/api";
import { IncidentDetailPage } from "../pages/IncidentDetailPage";
import { detail, timeline, graph, history } from "../test/fixtures";

describe("IncidentDetailPage (happy path)", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(api, "getIncident").mockResolvedValue(detail);
    vi.spyOn(api, "getTimeline").mockResolvedValue(timeline);
    vi.spyOn(api, "getGraph").mockResolvedValue(graph);
    vi.spyOn(api, "getStateHistory").mockResolvedValue(history);
  });

  it("renders header, why-created, timeline and correlations", async () => {
    render(<IncidentDetailPage incidentId={1} />);
    await waitFor(() => expect(screen.getByTestId("incident-detail")).toBeInTheDocument());

    // header
    expect(screen.getByText("Incident #1")).toBeInTheDocument();
    expect(screen.getByText("high")).toBeInTheDocument();
    expect(screen.getByText(/3 cameras · 1 tracks/)).toBeInTheDocument();

    // why-created reasons
    const reasons = screen.getAllByTestId("why-reason");
    expect(reasons.length).toBe(2);

    // timeline steps rendered
    expect(screen.getAllByTestId("timeline-step").length).toBe(2);

    // correlation card present
    expect(screen.getByTestId("correlation-card")).toBeInTheDocument();

    // lifecycle shows only allowed actions from fixture (start_triage, dismiss)
    expect(screen.getByTestId("action-start_triage")).toBeInTheDocument();
    expect(screen.getByTestId("action-dismiss")).toBeInTheDocument();
    expect(screen.queryByTestId("action-confirm")).not.toBeInTheDocument();
  });
});
