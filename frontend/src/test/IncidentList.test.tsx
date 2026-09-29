import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { IncidentList } from "../components/incidents/IncidentList";
import { ConfidenceBadge } from "../components/incidents/Badges";
import { summary } from "../test/fixtures";

describe("IncidentList", () => {
  it("renders incident rows with type, state, confidence and camera count", () => {
    render(<IncidentList incidents={[summary]} selectedId={null} onSelect={() => {}} />);
    expect(screen.getByTestId("incident-row-1")).toBeInTheDocument();
    expect(screen.getByText("#1")).toBeInTheDocument();
    expect(screen.getByText("high")).toBeInTheDocument(); // type/priority
    expect(screen.getByText("open")).toBeInTheDocument(); // state
    expect(screen.getByText("3")).toBeInTheDocument(); // camera count
  });

  it("marks the selected row and calls onSelect", async () => {
    const onSelect = vi.fn();
    render(<IncidentList incidents={[summary]} selectedId={1} onSelect={onSelect} />);
    const row = screen.getByTestId("incident-row-1");
    expect(row.className).toContain("selected");
    row.click();
    expect(onSelect).toHaveBeenCalledWith(1);
  });
});

describe("ConfidenceBadge", () => {
  it("shows numeric confidence and band", () => {
    render(<ConfidenceBadge confidence={0.6} band="medium" />);
    expect(screen.getByText("0.60")).toBeInTheDocument();
    expect(screen.getByText("medium")).toBeInTheDocument();
  });

  it("shows n/a when confidence is null", () => {
    render(<ConfidenceBadge confidence={null} band="unknown" />);
    expect(screen.getByText("n/a")).toBeInTheDocument();
  });
});
