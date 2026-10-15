import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { GuardDesk } from "../components/app/GuardDesk";
import { api, ApiError, type PilotTask } from "../services/api";
import { useAuth } from "../services/auth";

vi.mock("../services/api", async importOriginal => {
  const actual = await importOriginal<typeof import("../services/api")>();
  return { ...actual, api: { getPilotStatus: vi.fn(), getPilotTasks: vi.fn(), getCameraHealth: vi.fn(),
    getPilotNotices: vi.fn(), markPilotPresented: vi.fn(), pilotAction: vi.fn(), verifyPilotLabel: vi.fn(), retryPilotNotice: vi.fn(),
    listCameras: vi.fn(), listSecurityPosts: vi.fn(), listGuards: vi.fn(), listGuardShifts: vi.fn() } };
});
vi.mock("../services/auth", () => ({ useAuth: vi.fn(), currentAccessToken: () => null }));
vi.mock("../components/ui/ProtectedMedia", () => ({
  ProtectedImage: ({ fallback }: { fallback: unknown }) => fallback,
  ProtectedVideo: ({ fallback }: { fallback: unknown }) => fallback,
}));

const task: PilotTask = { id: "task-1", incident_id: 8, version: 1, category: "restricted_entry",
  priority: "high", camera_id: "gate", zone_name: "Gate area", instruction: "Check the gate and report.",
  state: "open", owner: "guard", created_at: 1700000000, observed_at: 1700000000,
  acknowledgement_deadline: 1700000020, acknowledged_at: null, outcome: null, outcome_note: null,
  label_verified: false, evidence: [], notifications: [{ id: "notice", reason: "assigned_guard", status: "accepted", attempts: 1, failure_class: null }] };

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(useAuth).mockReturnValue({ enabled: false, token: null, identity: null, login: vi.fn(), logout: vi.fn() });
  vi.mocked(api.getPilotStatus).mockResolvedValue({ pilot_mode: true, simulated: true, site: "Test site",
    timezone: "Asia/Kolkata", rules_configured: 1, data_agreement_configured: false,
    notification_provider: "local", offline_operation_verified: false });
  vi.mocked(api.getPilotTasks).mockResolvedValue([task]);
  vi.mocked(api.getCameraHealth).mockResolvedValue([]);
  vi.mocked(api.listCameras).mockResolvedValue([]);
  vi.mocked(api.listSecurityPosts).mockResolvedValue([]);
  vi.mocked(api.listGuards).mockResolvedValue([]);
  vi.mocked(api.listGuardShifts).mockResolvedValue([]);
  vi.mocked(api.getPilotNotices).mockResolvedValue([]);
  vi.mocked(api.pilotAction).mockResolvedValue({});
  vi.mocked(api.markPilotPresented).mockResolvedValue({});
});

describe("guard desk", () => {
  it("shows separate camera, recorded video, and guard shift views", async () => {
    render(<GuardDesk onOpenSupervisor={vi.fn()} />);
    await screen.findByText("Check the gate and report.");
    fireEvent.click(screen.getByRole("button", { name: "Live cameras" }));
    expect(await screen.findByText("No cameras are registered at this site.", { exact: false })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Video test" }));
    expect(screen.getByText("Person detection: ready to test")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Guard shifts" }));
    expect(await screen.findByRole("heading", { name: "Guard posts & shifts" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Assign guard" })).toBeDisabled();
  });
  it("shows the instruction and acknowledgement even without evidence", async () => {
    render(<GuardDesk onOpenSupervisor={vi.fn()} />);
    expect(await screen.findByText("Check the gate and report.")).toBeInTheDocument();
    expect(screen.getByText(/SIMULATED/)).toBeInTheDocument();
    expect(screen.getByText(/You can still acknowledge/)).toBeInTheDocument();
    expect(screen.getByText("Provider accepted")).toBeInTheDocument();
    expect(screen.queryByText("Real incident")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Acknowledge" }));
    await waitFor(() => expect(api.pilotAction).toHaveBeenCalledWith("task-1", 1, "acknowledge", expect.any(Object)));
  });

  it("requires an observation before an outcome", async () => {
    vi.mocked(api.getPilotTasks).mockResolvedValue([{ ...task, state: "acknowledged", acknowledged_at: 1700000005 }]);
    render(<GuardDesk onOpenSupervisor={vi.fn()} />);
    const outcome = await screen.findByRole("button", { name: "False alarm" });
    expect(outcome).toBeDisabled();
    fireEvent.change(screen.getByLabelText("What did you observe?"), { target: { value: "Shadow on the gate" } });
    fireEvent.click(outcome);
    await waitFor(() => expect(api.pilotAction).toHaveBeenCalledWith("task-1", 1, "outcome", { outcome: "false_alarm", note: "Shadow on the gate" }));
  });

  it("refreshes and explains a stale action instead of reporting success", async () => {
    vi.mocked(api.pilotAction).mockRejectedValue(new ApiError("Conflict", 409, "task changed; refresh before retrying"));
    render(<GuardDesk onOpenSupervisor={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: "Acknowledge" }));
    expect(await screen.findByText(/task changed; refresh before retrying/)).toBeInTheDocument();
    expect(api.getPilotTasks).toHaveBeenCalledTimes(2);
  });

  it("gives responders only their task view", async () => {
    vi.mocked(useAuth).mockReturnValue({ enabled: true, token: "test", identity: { subject: "guard", role: "responder",
      display_name: "Guard", tenant_id: "tenant", site_id: "site" }, login: vi.fn(), logout: vi.fn() });
    render(<GuardDesk onOpenSupervisor={vi.fn()} />);
    await screen.findByText("Check the gate and report.");
    expect(screen.queryByRole("button", { name: "Supervisor review" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Recent outcomes" })).not.toBeInTheDocument();
    expect(api.getPilotNotices).not.toHaveBeenCalled();
  });
});
