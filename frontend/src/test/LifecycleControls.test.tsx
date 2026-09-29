import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { LifecycleControls } from "../components/lifecycle/LifecycleControls";
import { api, ApiError } from "../services/api";

describe("LifecycleControls", () => {
  beforeEach(() => vi.restoreAllMocks());

  it("renders only the backend-provided allowed actions", () => {
    render(
      <LifecycleControls
        incidentId={1}
        state="open"
        allowedActions={["start_triage", "dismiss"]}
        onTransitioned={() => {}}
      />,
    );
    expect(screen.getByTestId("action-start_triage")).toBeInTheDocument();
    expect(screen.getByTestId("action-dismiss")).toBeInTheDocument();
    // confirm is NOT allowed from open -> must not render
    expect(screen.queryByTestId("action-confirm")).not.toBeInTheDocument();
  });

  it("applies a transition and notifies the parent to refresh", async () => {
    const spy = vi.spyOn(api, "transition").mockResolvedValue({
      incident_id: 1,
      from_state: "open",
      state: "triage",
      action: "start_triage",
      allowed_actions: ["confirm", "dismiss"],
    });
    const onTransitioned = vi.fn();
    render(
      <LifecycleControls
        incidentId={1}
        state="open"
        allowedActions={["start_triage"]}
        onTransitioned={onTransitioned}
      />,
    );
    await userEvent.click(screen.getByTestId("action-start_triage"));
    await waitFor(() => expect(spy).toHaveBeenCalledWith(1, "start_triage", { reviewer: undefined }));
    expect(onTransitioned).toHaveBeenCalled();
  });

  it("surfaces a 409 invalid-transition rejection without crashing", async () => {
    vi.spyOn(api, "transition").mockRejectedValue(
      new ApiError("conflict", 409, "cannot 'confirm' from state 'open'"),
    );
    render(
      <LifecycleControls
        incidentId={1}
        state="open"
        allowedActions={["confirm"]}
        onTransitioned={() => {}}
      />,
    );
    await userEvent.click(screen.getByTestId("action-confirm"));
    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent(/Transition rejected/),
    );
  });
});
