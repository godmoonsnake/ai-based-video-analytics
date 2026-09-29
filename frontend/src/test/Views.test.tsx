import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { Timeline } from "../components/timeline/Timeline";
import { Correlations } from "../components/incidents/Correlations";
import { IncidentGraph } from "../components/graph/IncidentGraph";
import { timeline, detail, graph } from "../test/fixtures";

describe("Timeline", () => {
  it("renders a step per event with camera, event type and evidence status", () => {
    render(<Timeline steps={timeline.timeline} />);
    const steps = screen.getAllByTestId("timeline-step");
    expect(steps).toHaveLength(2);
    expect(screen.getByText("gate_3")).toBeInTheDocument();
    expect(screen.getByText("dwell")).toBeInTheDocument();
    expect(screen.getByText("evidence available")).toBeInTheDocument();
    expect(screen.getByText("no evidence")).toBeInTheDocument();
  });
});

describe("Correlations", () => {
  it("shows source/target tracks, transition, gap and all sub-scores", () => {
    render(<Correlations correlations={detail.explanation.correlations} />);
    expect(screen.getByTestId("correlation-card")).toBeInTheDocument();
    expect(screen.getByText("gate_3 -> corridor_1")).toBeInTheDocument();
    expect(screen.getByText(/gate_3:a1/)).toBeInTheDocument();
    expect(screen.getByText("temporal")).toBeInTheDocument();
    expect(screen.getByText("topology / motion")).toBeInTheDocument();
    expect(screen.getByText("appearance")).toBeInTheDocument();
    expect(screen.getByText(/temporal gap: 6s/)).toBeInTheDocument();
  });
});

describe("IncidentGraph", () => {
  it("renders the backend nodes and edges as an SVG", () => {
    render(<IncidentGraph graph={graph} />);
    const svg = screen.getByTestId("incident-graph-svg");
    expect(svg).toBeInTheDocument();
    // one line per edge (3 edges in the fixture)
    expect(svg.querySelectorAll("line")).toHaveLength(3);
    // node labels present
    expect(screen.getByText("#1")).toBeInTheDocument(); // incident node
    expect(screen.getByText(/detection@gate_3/)).toBeInTheDocument(); // event node
  });
});
