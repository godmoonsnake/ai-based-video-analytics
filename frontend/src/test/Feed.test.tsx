import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi } from "vitest";
import type { ReactElement } from "react";
import { IncidentFeed } from "../components/feed/IncidentFeed";
import { PriorityChip, StateBadge, BandPill } from "../components/ui/Badges";
import { ConfidenceDial } from "../components/ui/ConfidenceDial";
import { summary, summaryDismissed } from "./fixtures";
import { ToastProvider } from "../components/ui/Toasts";

const renderFeed = (ui: ReactElement) => render(<ToastProvider>{ui}</ToastProvider>);

describe("IncidentFeed", () => {
  it("renders incident rows with type, priority, state and cameras", () => {
    renderFeed(
      <IncidentFeed
        incidents={[summary]}
        loading={false}
        error={null}
        reload={() => {}}
        selectedId={null}
        onSelect={() => {}}
        onVisibleChange={() => {}}
      />,
    );
    expect(screen.getByTestId("incident-row-1")).toBeInTheDocument();
    expect(screen.getByText("#1")).toBeInTheDocument();
    expect(screen.getByText("high")).toBeInTheDocument(); // priority chip
    expect(screen.getByText("open")).toBeInTheDocument(); // state badge
    expect(screen.getAllByText("Restricted zone entry").length).toBeGreaterThan(0);
    expect(screen.queryByText("Correlated movement")).not.toBeInTheDocument();
  });

  it("marks the selected row and calls onSelect", async () => {
    const onSelect = vi.fn();
    renderFeed(
      <IncidentFeed
        incidents={[summary]}
        loading={false}
        error={null}
        reload={() => {}}
        selectedId={1}
        onSelect={onSelect}
        onVisibleChange={() => {}}
      />,
    );
    const row = screen.getByTestId("incident-row-1");
    expect(row.className).toContain("selected");
    await userEvent.click(row);
    expect(onSelect).toHaveBeenCalledWith(1);
  });

  it("filters by lifecycle state group", async () => {
    renderFeed(
      <IncidentFeed
        incidents={[summary, summaryDismissed]}
        loading={false}
        error={null}
        reload={() => {}}
        selectedId={null}
        onSelect={() => {}}
        onVisibleChange={() => {}}
      />,
    );
    expect(screen.getByTestId("incident-row-1")).toBeInTheDocument();
    expect(screen.getByTestId("incident-row-2")).toBeInTheDocument();

    await userEvent.selectOptions(screen.getByRole("combobox", { name: "State filter" }), "dismissed");
    expect(screen.queryByTestId("incident-row-1")).not.toBeInTheDocument();
    expect(screen.getByTestId("incident-row-2")).toBeInTheDocument();
  });

  it("shows the designed empty state when the feed is clear", () => {
    renderFeed(
      <IncidentFeed
        incidents={[]}
        loading={false}
        error={null}
        reload={() => {}}
        selectedId={null}
        onSelect={() => {}}
        onVisibleChange={() => {}}
      />,
    );
    expect(screen.getByText("No incidents")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /load review cases/i })).toBeInTheDocument();
  });
});

describe("badges", () => {
  it("priority chip reflects severity", () => {
    render(<PriorityChip priority="critical" />);
    expect(screen.getByText("critical")).toBeInTheDocument();
  });

  it("state badge keeps the state-* class contract", () => {
    render(<StateBadge state="confirmed" />);
    const el = screen.getByText("confirmed");
    expect(el.className).toContain("state-badge");
    expect(el.className).toContain("state-confirmed");
  });

  it("band pill shows numeric confidence", () => {
    render(<BandPill band="medium" confidence={0.6} />);
    expect(screen.getByText("0.60")).toBeInTheDocument();
  });
});

describe("ConfidenceDial", () => {
  it("renders value and band with an accessible label", () => {
    render(<ConfidenceDial confidence={0.6} band="medium" />);
    expect(screen.getByText("0.60")).toBeInTheDocument();
    expect(screen.getByText("medium")).toBeInTheDocument();
    expect(screen.getByRole("img")).toHaveAttribute(
      "aria-label",
      "Confidence 0.60, band medium",
    );
  });

  it("renders n/a when confidence is null", () => {
    render(<ConfidenceDial confidence={null} band="unknown" />);
    expect(screen.getByText("n/a")).toBeInTheDocument();
  });
});
