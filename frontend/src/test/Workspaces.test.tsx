import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { api } from "../services/api";
import { ServiceAssurance } from "../components/app/ServiceAssurance";
import { InvestigationWorkspace } from "../components/app/InvestigationWorkspace";

vi.mock("../services/api", () => ({ api: {
  listCameras: vi.fn(), getCameraHealth: vi.fn(), getHealthMetrics: vi.fn(), getMyTasks: vi.fn(),
  getPatterns: vi.fn(), searchInvestigation: vi.fn(), minePatterns: vi.fn(),
} }));

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.listCameras).mockResolvedValue([{ id: "gate_3", name: "Gate 3", site_id: "site_a", x: null, y: null }]);
  vi.mocked(api.getCameraHealth).mockResolvedValue([]);
  vi.mocked(api.getHealthMetrics).mockResolvedValue({ window_hours: 24, unavailable_camera_minutes: 0,
    recording_gap_minutes: 0, evidence_capture_success_rate: null, source_to_darson_lag_seconds: null,
    event_to_incident_latency_seconds: null, samples: 0 });
  vi.mocked(api.getMyTasks).mockResolvedValue([]);
  vi.mocked(api.getPatterns).mockResolvedValue([]);
});

describe("integrated workspaces", () => {
  it("does not present an unprobed camera as healthy", async () => {
    render(<ServiceAssurance onOpenCase={vi.fn()} canSeeTasks />);
    expect(await screen.findByText("Gate 3")).toBeInTheDocument();
    expect(screen.getByText("Not monitored")).toBeInTheDocument();
    expect(screen.getByText(/No health samples are recorded yet/)).toBeInTheDocument();
    expect(screen.getByText(/No cases are currently assigned/)).toBeInTheDocument();
  });

  it("shows search matches and opens the matching case", async () => {
    const openCase = vi.fn();
    vi.mocked(api.searchInvestigation).mockResolvedValue({ query: "Gate 3", parsed_filter: { camera_id: "gate_3" },
      human_review_required: true,
      events: [{ event_id: "event-1", camera_id: "gate_3", event_type: "zone_enter", label: "person",
        ts: 1_700_000_000, evidence: { snapshot: { status: "available", content_url: "/api/v1/evidence/abc/content" },
          clip: { status: "unavailable", content_url: null } } }],
      incidents: [{ id: 7, status: "open", priority: "high", summary_text: "Restricted area observation" }] });
    render(<InvestigationWorkspace onOpenCase={openCase} canMine={false} />);
    fireEvent.change(screen.getByLabelText("Search observations and cases"), { target: { value: "Gate 3" } });
    fireEvent.click(screen.getByRole("button", { name: "Search" }));
    expect(await screen.findByText("Restricted area observation")).toBeInTheDocument();
    expect(screen.getByText(/camera_id: gate_3/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /CASE #7/ }));
    expect(openCase).toHaveBeenCalledWith(7);
    await waitFor(() => expect(api.searchInvestigation).toHaveBeenCalledWith("Gate 3"));
  });
});
