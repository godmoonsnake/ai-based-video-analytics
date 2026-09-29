import { useMemo, useState } from "react";
import type { GraphEdge, GraphNode, IncidentGraph as GraphData } from "../../types/incident";

interface Props {
  graph: GraphData;
}

// Layered layout: node types are placed in fixed columns so the graph reads as
// incident -> track -> camera -> zone -> event (the reconstruction hierarchy).
const COLUMN_ORDER: GraphNode["type"][] = ["incident", "track", "camera", "zone", "event"];
const COL_X: Record<string, number> = {
  incident: 90,
  track: 260,
  camera: 430,
  zone: 600,
  event: 780,
};
const NODE_COLOR: Record<string, string> = {
  incident: "#b00020",
  track: "#6a1b9a",
  camera: "#1565c0",
  zone: "#00838f",
  event: "#2e7d32",
};
const EDGE_COLOR: Record<string, string> = {
  incident_membership: "#b00020",
  event_to_track: "#90a4ae",
  track_to_camera: "#90a4ae",
  event_to_zone: "#90a4ae",
  temporal: "#455a64",
  sequence: "#e65100",
  correlation: "#6a1b9a",
  movement: "#1565c0",
};

interface Positioned {
  node: GraphNode;
  x: number;
  y: number;
}

const ROW_H = 46;
const R = 9;

export function IncidentGraph({ graph }: Props) {
  const [hover, setHover] = useState<GraphEdge | null>(null);

  const { positioned, byKey, height } = useMemo(() => {
    const byCol: Record<string, GraphNode[]> = {};
    for (const n of graph.nodes) (byCol[n.type] ||= []).push(n);
    const positioned: Positioned[] = [];
    const byKey = new Map<string, Positioned>();
    let maxRows = 0;
    for (const type of COLUMN_ORDER) {
      const nodes = byCol[type] ?? [];
      maxRows = Math.max(maxRows, nodes.length);
      nodes.forEach((node, i) => {
        const p = { node, x: COL_X[type] ?? 780, y: 40 + i * ROW_H };
        positioned.push(p);
        byKey.set(`${node.type}:${node.ref_id}`, p);
      });
    }
    return { positioned, byKey, height: Math.max(160, 40 + maxRows * ROW_H) };
  }, [graph]);

  function endpoint(end: GraphEdge["source"]): Positioned | undefined {
    if (!end) return undefined;
    return byKey.get(`${end.type}:${end.ref_id}`);
  }

  return (
    <div className="graph-wrap">
      <svg
        className="incident-graph"
        viewBox={`0 0 900 ${height}`}
        role="img"
        aria-label="Incident reconstruction graph"
        data-testid="incident-graph-svg"
      >
        {/* column headers */}
        {COLUMN_ORDER.map((t) => (
          <text key={t} x={COL_X[t]} y={20} className="graph-col-head" textAnchor="middle">
            {t}
          </text>
        ))}

        {/* edges */}
        {graph.edges.map((e) => {
          const s = endpoint(e.source);
          const t = endpoint(e.target);
          if (!s || !t) return null;
          const isHover = hover?.id === e.id;
          return (
            <line
              key={e.id}
              x1={s.x}
              y1={s.y}
              x2={t.x}
              y2={t.y}
              stroke={EDGE_COLOR[e.type] ?? "#b0bec5"}
              strokeWidth={isHover ? 3 : 1.4}
              strokeOpacity={hover && !isHover ? 0.2 : 0.85}
              onMouseEnter={() => setHover(e)}
              onMouseLeave={() => setHover(null)}
            />
          );
        })}

        {/* nodes */}
        {positioned.map((p) => (
          <g key={`${p.node.type}:${p.node.ref_id}`} transform={`translate(${p.x},${p.y})`}>
            <circle r={R} fill={NODE_COLOR[p.node.type] ?? "#607d8b"} />
            <text x={R + 4} y={4} className="graph-node-label">
              {nodeLabel(p.node)}
            </text>
          </g>
        ))}
      </svg>

      {/* hovered edge evidence */}
      <div className="graph-edge-info" data-testid="graph-edge-info">
        {hover ? (
          <>
            <strong>{hover.type}</strong>
            {hover.confidence != null && <span> · confidence {hover.confidence.toFixed(3)}</span>}
            {Object.keys(hover.evidence ?? {}).length > 0 && (
              <pre>{JSON.stringify(hover.evidence, null, 2)}</pre>
            )}
          </>
        ) : (
          <span className="muted">Hover an edge to see its typed evidence.</span>
        )}
      </div>

      <ul className="graph-legend">
        {Object.entries(NODE_COLOR).map(([t, c]) => (
          <li key={t}>
            <span className="legend-dot" style={{ background: c }} /> {t}
          </li>
        ))}
      </ul>
    </div>
  );
}

function nodeLabel(n: GraphNode): string {
  if (n.type === "event") {
    const et = (n.attributes?.event_type as string) ?? "event";
    const cam = (n.attributes?.camera_id as string) ?? "";
    return cam ? `${et}@${cam}` : et;
  }
  if (n.type === "incident") return `#${n.ref_id}`;
  if (n.type === "track") return `track ${n.ref_id}`;
  return n.ref_id;
}
