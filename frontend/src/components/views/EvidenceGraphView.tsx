import { useEffect, useMemo, useRef, useState } from "react";
import type { GraphNode, IncidentGraph } from "../../types/incident";
import { camLabel, fmtClock } from "../../lib/format";
import { IconRadar } from "../icons";

/**
 * Evidence graph — bespoke force-directed layout in plain SVG.
 * No viz library: the typed edges and instrument styling ARE the brand.
 *
 * Node types: incident (hex, pinned) · track (ringed disc) · camera (rounded
 * square) · zone (diamond) · event (snapshot disc). Edge types are styled per
 * the legend; correlation edges flow (animated dashes).
 */

interface SimNode {
  key: string;
  type: string;
  ref: string;
  label: string;
  attrs: Record<string, unknown>;
  x: number;
  y: number;
  vx: number;
  vy: number;
  pinned: boolean;
  snap: string | null;
}

interface SimEdge {
  key: string;
  type: string;
  source: string;
  target: string;
  confidence: number | null;
  evidence: Record<string, unknown>;
  rest: number;
}

const nodeKey = (type: string, ref: string) => `${type}:${ref}`;

function restLength(type: string): number {
  switch (type) {
    case "correlation":
      return 175;
    case "movement":
      return 250;
    case "temporal":
      return 115;
    case "sequence":
      return 105;
    case "track_to_camera":
      return 250; // cameras live on the outer ring
    case "event_to_zone":
      return 55;
    case "event_to_track":
      return 70;
    case "incident_membership":
      return 60;
    default:
      return 72;
  }
}

function buildSim(graph: IncidentGraph) {
  const nodes = new Map<string, SimNode>();
  const R = 265;

  // Deterministic seed layout: cameras on a ring, others near their camera.
  const cameraNodes = graph.nodes.filter((n) => n.type === "camera");
  const cameraAngle = new Map<string, number>();
  cameraNodes.forEach((n, i) => {
    cameraAngle.set(n.ref_id, (i / Math.max(1, cameraNodes.length)) * Math.PI * 2 - Math.PI / 2);
  });

  const add = (n: GraphNode, x: number, y: number, pinned = false) => {
    const key = nodeKey(n.type, n.ref_id);
    if (nodes.has(key)) return;
    const attrs = n.attributes ?? {};
    let label = n.ref_id;
    let snap: string | null = null;
    if (n.type === "event") {
      const ev = attrs as Record<string, unknown>;
      label = `${(ev.event_type as string) ?? "event"}`;
      const er = ev.evidence_ref as { snapshot_url?: string | null } | undefined;
      snap = er?.snapshot_url ?? null;
    } else if (n.type === "camera") {
      label = n.ref_id;
    } else if (n.type === "zone") {
      label = (attrs.kind as string) ?? n.ref_id;
    } else if (n.type === "track") {
      label = `track ${n.ref_id}`;
    } else if (n.type === "incident") {
      label = `incident #${n.ref_id}`;
    }
    nodes.set(key, {
      key,
      type: n.type,
      ref: n.ref_id,
      label,
      attrs,
      x,
      y,
      vx: 0,
      vy: 0,
      pinned,
      snap,
    });
  };

  for (const n of graph.nodes) {
    if (n.type === "incident") add(n, 0, 0, true);
    else if (n.type === "track") add(n, 0, 40);
    else if (n.type === "camera") {
      const a = cameraAngle.get(n.ref_id) ?? 0;
      add(n, R * Math.cos(a), R * Math.sin(a));
    } else if (n.type === "zone") {
      const camId = (n.attributes?.camera_id as string) ?? "";
      const a = (cameraAngle.get(camId) ?? 0) + 0.55;
      add(n, (R - 95) * Math.cos(a), (R - 95) * Math.sin(a));
    } else if (n.type === "event") {
      const camId = (n.attributes?.camera_id as string) ?? "";
      const a = (cameraAngle.get(camId) ?? 0) - 0.55;
      add(n, (R - 145) * Math.cos(a), (R - 145) * Math.sin(a));
    }
  }

  const edges: SimEdge[] = graph.edges.map((e) => ({
    key: `e${e.id}`,
    type: e.type,
    source: nodeKey(e.source?.type ?? "", e.source?.ref_id ?? ""),
    target: nodeKey(e.target?.type ?? "", e.target?.ref_id ?? ""),
    confidence: e.confidence,
    evidence: e.evidence ?? {},
    rest: restLength(e.type),
  }));

  // adjacency for springs
  const adjacency = new Map<string, { to: string; rest: number; type: string }[]>();
  for (const e of edges) {
    if (!adjacency.has(e.source)) adjacency.set(e.source, []);
    if (!adjacency.has(e.target)) adjacency.set(e.target, []);
    adjacency.get(e.source)!.push({ to: e.target, rest: e.rest, type: e.type });
    adjacency.get(e.target)!.push({ to: e.source, rest: e.rest, type: e.type });
  }

  return { nodes, edges, adjacency };
}

function tick(
  nodes: Map<string, SimNode>,
  adjacency: Map<string, { to: string; rest: number; type: string }[]>,
  alpha: number,
) {
  const arr = [...nodes.values()];
  // repulsion
  for (let i = 0; i < arr.length; i++) {
    for (let j = i + 1; j < arr.length; j++) {
      const a = arr[i];
      const b = arr[j];
      let dx = b.x - a.x;
      let dy = b.y - a.y;
      let d2 = dx * dx + dy * dy;
      if (d2 < 1) {
        dx = Math.random() - 0.5;
        dy = Math.random() - 0.5;
        d2 = dx * dx + dy * dy;
      }
      const d = Math.sqrt(d2);
      const f = (9500 / d2) * alpha;
      const fx = (dx / d) * f;
      const fy = (dy / d) * f;
      if (!a.pinned) {
        a.vx -= fx;
        a.vy -= fy;
      }
      if (!b.pinned) {
        b.vx += fx;
        b.vy += fy;
      }
    }
  }
  // springs
  for (const n of arr) {
    for (const link of adjacency.get(n.key) ?? []) {
      const m = nodes.get(link.to);
      if (!m) continue;
      const dx = m.x - n.x;
      const dy = m.y - n.y;
      const d = Math.sqrt(dx * dx + dy * dy) || 0.01;
      const tight =
        link.type === "event_to_track" ||
        link.type === "event_to_zone" ||
        link.type === "incident_membership";
      const k = (tight ? 0.05 : 0.018) * alpha;
      const f = (d - link.rest) * k;
      const fx = (dx / d) * f;
      const fy = (dy / d) * f;
      if (!n.pinned) {
        n.vx += fx;
        n.vy += fy;
      }
      if (!m.pinned) {
        m.vx -= fx;
        m.vy -= fy;
      }
    }
    // gravity to center (weak — keeps the constellation from drifting off)
    if (!n.pinned) {
      n.vx -= n.x * 0.0011 * alpha * 40;
      n.vy -= n.y * 0.0011 * alpha * 40;
    }
  }
  // integrate
  for (const n of arr) {
    if (n.pinned) {
      n.vx = 0;
      n.vy = 0;
      continue;
    }
    n.vx *= 0.82;
    n.vy *= 0.82;
    n.x += Math.max(-14, Math.min(14, n.vx));
    n.y += Math.max(-14, Math.min(14, n.vy));
  }
}

interface Props {
  graph: IncidentGraph | null;
}

export function EvidenceGraphView({ graph }: Props) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ w: 800, h: 480 });
  const [tickN, setTickN] = useState(0);
  const [hover, setHover] = useState<string | null>(null);
  const [tip, setTip] = useState<{ x: number; y: number; key: string } | null>(null);
  const [hiddenTypes, setHiddenTypes] = useState<Set<string>>(new Set());
  const simRef = useRef<{
    nodes: Map<string, SimNode>;
    edges: SimEdge[];
    adjacency: Map<string, { to: string; rest: number; type: string }[]>;
  } | null>(null);
  const alphaRef = useRef(1);
  const viewRef = useRef({ x: 0, y: 0, k: 1 });
  const dragRef = useRef<{ key: string | null; px: number; py: number; panning: boolean } | null>(
    null,
  );

  // (Re)build simulation when the graph changes.
  useEffect(() => {
    if (!graph) return;
    simRef.current = buildSim(graph);
    alphaRef.current = 1;
    // initial fit: frame the whole constellation in the measured viewport
    const el = wrapRef.current;
    const fit = el
      ? Math.min(1.15, Math.max(0.5, Math.min(el.clientWidth, el.clientHeight) / 780))
      : 1;
    viewRef.current = { x: 0, y: 0, k: fit };
  }, [graph]);

  // Measure wrapper.
  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => {
      setSize({ w: el.clientWidth, h: el.clientHeight });
    });
    ro.observe(el);
    setSize({ w: el.clientWidth, h: el.clientHeight });
    return () => ro.disconnect();
  }, []);

  // Simulation loop.
  useEffect(() => {
    if (!graph) return;
    let raf = 0;
    const loop = () => {
      const sim = simRef.current;
      if (sim && alphaRef.current > 0.02) {
        tick(sim.nodes, sim.adjacency, alphaRef.current);
        alphaRef.current *= 0.9945;
        setTickN((t) => t + 1);
      }
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, [graph]);

  const sim = simRef.current;
  const view = viewRef.current;
  const visibleEdges = useMemo(
    () => sim?.edges.filter((e) => !hiddenTypes.has(edgeClass(e.type))) ?? [],
    [sim, tickN, hiddenTypes],
  );

  // neighbor set for focus dimming
  const neighbors = useMemo(() => {
    if (!hover || !sim) return null;
    const set = new Set<string>([hover]);
    for (const e of sim.edges) {
      if (e.source === hover) set.add(e.target);
      if (e.target === hover) set.add(e.source);
    }
    return set;
  }, [hover, sim]);

  if (!graph || !sim) {
    return (
      <div className="graph-wrap">
        <div className="state-block">
          <div className="radar">
            <span className="sweep" />
          </div>
          <div className="state-sub">BUILDING EVIDENCE GRAPH …</div>
        </div>
      </div>
    );
  }

  const { x: vx, y: vy, k } = view;

  const toGraph = (clientX: number, clientY: number) => {
    const rect = wrapRef.current!.getBoundingClientRect();
    return {
      x: (clientX - rect.left - size.w / 2 - vx) / k,
      y: (clientY - rect.top - size.h / 2 - vy) / k,
    };
  };

  const onWheel = (e: React.WheelEvent) => {
    e.preventDefault();
    const v = viewRef.current;
    const rect = wrapRef.current!.getBoundingClientRect();
    const mx = e.clientX - rect.left - size.w / 2;
    const my = e.clientY - rect.top - size.h / 2;
    const factor = e.deltaY < 0 ? 1.12 : 1 / 1.12;
    const nk = Math.min(3, Math.max(0.35, v.k * factor));
    // keep point under cursor stable
    v.x = mx - ((mx - v.x) * nk) / v.k;
    v.y = my - ((my - v.y) * nk) / v.k;
    v.k = nk;
    setTickN((t) => t + 1);
  };

  const onPointerDown = (e: React.PointerEvent, key: string | null) => {
    (e.target as Element).setPointerCapture?.(e.pointerId);
    dragRef.current = { key, px: e.clientX, py: e.clientY, panning: key == null };
  };

  const onPointerMove = (e: React.PointerEvent) => {
    const drag = dragRef.current;
    if (!drag) return;
    const v = viewRef.current;
    if (drag.key) {
      const n = sim.nodes.get(drag.key);
      if (n) {
        const p = toGraph(e.clientX, e.clientY);
        n.x = p.x;
        n.y = p.y;
        n.vx = 0;
        n.vy = 0;
        alphaRef.current = Math.max(alphaRef.current, 0.55);
        setTickN((t) => t + 1);
      }
    } else if (drag.panning) {
      v.x += e.clientX - drag.px;
      v.y += e.clientY - drag.py;
      drag.px = e.clientX;
      drag.py = e.clientY;
      setTickN((t) => t + 1);
    }
  };

  const endDrag = () => {
    dragRef.current = null;
  };

  const toggleType = (t: string) => {
    setHiddenTypes((prev) => {
      const next = new Set(prev);
      if (next.has(t)) next.delete(t);
      else next.add(t);
      return next;
    });
  };

  const tipNode = tip ? sim.nodes.get(tip.key) : undefined;

  return (
    <div className="graph-wrap" ref={wrapRef}>
      <svg
        className="graph-svg"
        data-testid="incident-graph-svg"
        width={size.w}
        height={size.h}
        onWheel={onWheel}
        onPointerDown={(e) => onPointerDown(e, null)}
        onPointerMove={onPointerMove}
        onPointerUp={endDrag}
        onPointerLeave={endDrag}
      >
        <defs>
          <marker id="g-arrow" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto">
            <path d="M0 0.6 L7.4 4 L0 7.4" fill="context-stroke" stroke="none" />
          </marker>
          <clipPath id="ev-disc">
            <circle cx="0" cy="0" r="13.4" />
          </clipPath>
        </defs>
        <g transform={`translate(${size.w / 2 + vx} ${size.h / 2 + vy}) scale(${k})`}>
          {/* edges */}
          {visibleEdges.map((e) => {
            const s = sim.nodes.get(e.source);
            const t = sim.nodes.get(e.target);
            if (!s || !t) return null;
            const dim =
              neighbors && !(neighbors.has(e.source) && neighbors.has(e.target)) ? 0.12 : undefined;
            if (e.source === e.target) {
              // self-loop (correlation stitched within one global track)
              const r = 17;
              const d = `M ${s.x - 8} ${s.y - 16} A ${r} ${r} 0 1 1 ${s.x + 8} ${s.y - 16}`;
              return (
                <path
                  key={e.key}
                  className={`g-edge ${edgeClass(e.type)}`}
                  data-testid={`graph-edge-${e.type}`}
                  d={d}
                  style={{ opacity: dim }}
                />
              );
            }
            const dx = t.x - s.x;
            const dy = t.y - s.y;
            const len = Math.sqrt(dx * dx + dy * dy) || 1;
            const sx = s.x + (dx / len) * 16;
            const sy = s.y + (dy / len) * 16;
            const tx = t.x - (dx / len) * 18;
            const ty = t.y - (dy / len) * 18;
            const curved = e.type === "movement";
            const d = curved
              ? `M ${sx} ${sy} Q ${(sx + tx) / 2 + (dy / len) * 26} ${(sy + ty) / 2 - (dx / len) * 26} ${tx} ${ty}`
              : `M ${sx} ${sy} L ${tx} ${ty}`;
            return (
              <path
                key={e.key}
                className={`g-edge ${edgeClass(e.type)}`}
                data-testid={`graph-edge-${e.type}`}
                d={d}
                markerEnd={
                  e.type === "movement" || e.type === "sequence" ? "url(#g-arrow)" : undefined
                }
                style={{ opacity: dim }}
              />
            );
          })}

          {/* nodes */}
          {[...sim.nodes.values()].map((n) => {
            const dim = neighbors && !neighbors.has(n.key) && n.key !== hover;
            return (
              <g
                key={n.key}
                transform={`translate(${n.x} ${n.y})`}
                className={`g-node${dim ? " dim" : ""}${hover === n.key ? " focus" : ""}`}
                onPointerDown={(e) => {
                  e.stopPropagation();
                  onPointerDown(e, n.key);
                }}
                onPointerUp={endDrag}
                onPointerEnter={(e) => {
                  setHover(n.key);
                  setTip({ x: e.clientX, y: e.clientY, key: n.key });
                }}
                onPointerMove={(e) => {
                  onPointerMove(e);
                  if (hover === n.key) setTip({ x: e.clientX, y: e.clientY, key: n.key });
                }}
                onPointerLeave={() => {
                  setHover(null);
                  setTip(null);
                }}
              >
                {n.type === "incident" && <IncidentNode />}
                {n.type === "track" && <TrackNode node={n} />}
                {n.type === "camera" && <CameraNode />}
                {n.type === "zone" && <ZoneNode node={n} />}
                {n.type === "event" && <EventNode node={n} />}
                <text className="g-label" y={n.type === "incident" ? -26 : 30}>
                  {n.label}
                </text>
              </g>
            );
          })}
        </g>
      </svg>

      <div className="graph-tools">
        <button
          className="icon-btn"
          title="Reset view"
          onClick={() => {
            viewRef.current = { x: 0, y: 0, k: 1 };
            setTickN((t) => t + 1);
          }}
        >
          <IconRadar />
        </button>
      </div>

      <div className="graph-legend">
        {[
          ["corr", "correlation", true],
          ["movement", "movement", true],
          ["temporal", "temporal", true],
          ["sequence", "sequence", true],
          ["structural", "structural", true],
        ].map(([cls, label, togglable]) => (
          <span
            key={cls as string}
            className="li"
            style={{ cursor: togglable ? "pointer" : "default", opacity: hiddenTypes.has(label as string) ? 0.35 : 1 }}
            onClick={() => togglable && toggleType(label as string)}
            title={togglable ? "Toggle visibility" : undefined}
          >
            <span className={`sw ${cls}`} />
            {label}
          </span>
        ))}
        <span className="li" style={{ color: "var(--ink-faint)" }}>
          drag nodes · wheel zoom · drag pan
        </span>
      </div>

      {tipNode && tip && (
        <div className="graph-tip" style={{ left: tip.x - wrapAbsX() + 14, top: tip.y - wrapAbsY() + 14 }}>
          <NodeTip node={tipNode} />
        </div>
      )}
    </div>
  );

  function wrapAbsX(): number {
    return wrapRef.current?.getBoundingClientRect().left ?? 0;
  }
  function wrapAbsY(): number {
    return wrapRef.current?.getBoundingClientRect().top ?? 0;
  }
}

function edgeClass(type: string): string {
  switch (type) {
    case "correlation":
      return "corr";
    case "movement":
      return "movement";
    case "temporal":
      return "temporal";
    case "sequence":
      return "sequence";
    default:
      return "structural";
  }
}

function IncidentNode() {
  return (
    <>
      <circle className="halo" r="24" fill="none" stroke="#43e0a0" strokeOpacity="0.4" />
      <path
        d={hexPath(15)}
        fill="rgba(67,224,160,0.14)"
        stroke="#43e0a0"
        strokeWidth="1.8"
        style={{ filter: "drop-shadow(0 0 8px rgba(67,224,160,0.5))" }}
      />
      <circle r="3.2" fill="#43e0a0" />
    </>
  );
}

function TrackNode({ node }: { node: SimNode }) {
  const conf = node.attrs.correlation_confidence as number | undefined;
  return (
    <>
      <circle className="halo" r="22" fill="none" stroke="#5ea2f7" strokeOpacity="0.4" />
      <circle r="12" fill="#0a1120" stroke="#5ea2f7" strokeWidth="1.8" />
      <circle r="5" fill="none" stroke="#5ea2f7" strokeWidth="1.4" strokeDasharray={conf != null ? `${Math.max(2, conf * 24)} 24` : undefined} transform="rotate(-90)" />
    </>
  );
}

function CameraNode() {
  return (
    <>
      <rect className="halo" x="-19" y="-19" width="38" height="38" rx="9" fill="none" stroke="#41c4dd" strokeOpacity="0.35" />
      <rect x="-11" y="-11" width="22" height="22" rx="6" fill="#0a1120" stroke="#41c4dd" strokeWidth="1.6" />
      <circle r="3" fill="none" stroke="#41c4dd" strokeWidth="1.4" />
      <circle r="0.8" fill="#41c4dd" />
    </>
  );
}

function ZoneNode({ node }: { node: SimNode }) {
  const kind = (node.attrs.kind as string) ?? "";
  const restricted = kind === "restricted";
  const color = restricted ? "#ff5c5c" : "#b08cff";
  return (
    <>
      <rect
        x="-7.5"
        y="-7.5"
        width="15"
        height="15"
        transform="rotate(45)"
        fill="rgba(176,140,255,0.12)"
        stroke={color}
        strokeWidth="1.5"
      />
      {restricted && <circle className="halo" r="16" fill="none" stroke="#ff5c5c" strokeOpacity="0.4" />}
    </>
  );
}

function EventNode({ node }: { node: SimNode }) {
  return (
    <>
      <circle className="halo" r="22" fill="none" stroke="#8fa0bb" strokeOpacity="0.35" />
      <circle r="14" fill="#0a1120" stroke="#66758f" strokeWidth="1.4" />
      {node.snap ? (
        <image
          href={node.snap}
          x="-13.5"
          y="-13.5"
          width="27"
          height="27"
          clipPath="url(#ev-disc)"
          preserveAspectRatio="xMidYMid slice"
          onError={(e) => {
            e.currentTarget.style.display = "none";
          }}
        />
      ) : (
        <circle r="4" fill="#3d4a63" />
      )}
      <circle r="14" fill="none" stroke="#8fa0bb" strokeWidth="1.1" strokeOpacity="0.8" />
    </>
  );
}

function NodeTip({ node }: { node: SimNode }) {
  const a = node.attrs;
  const rows: [string, string][] = [];
  if (node.type === "event") {
    rows.push(["type", String(a.event_type ?? "—")]);
    rows.push(["camera", camLabel(String(a.camera_id ?? "—"))]);
    rows.push(["zone", ((a.zones as string[]) ?? []).join(", ") || "—"]);
    rows.push(["time", fmtClock(a.ts as number)]);
    if (a.track_local_id) rows.push(["track", String(a.track_local_id)]);
    if (a.sub_label) rows.push(["label", `${a.label ?? ""} · ${a.sub_label}`]);
  } else if (node.type === "camera") {
    rows.push(["camera", camLabel(node.ref)]);
  } else if (node.type === "zone") {
    rows.push(["zone", String(a.zone ?? node.ref)]);
    rows.push(["kind", String(a.kind ?? "—")]);
    rows.push(["camera", camLabel(String(a.camera_id ?? "—"))]);
  } else if (node.type === "track") {
    rows.push(["global track", node.ref]);
    rows.push(["window", `${fmtClock(a.first_seen as number)} → ${fmtClock(a.last_seen as number)}`]);
    if (a.correlation_confidence != null)
      rows.push(["corr. confidence", String(a.correlation_confidence)]);
  } else if (node.type === "incident") {
    rows.push(["root", `incident #${node.ref}`]);
    rows.push(["", "all members hang off this node"]);
  }
  return (
    <>
      <div className="t">
        {node.type} · {node.ref}
      </div>
      {rows.map(([k, v], i) => (
        <div className="row" key={i}>
          <span className="k">{k}</span>
          <span>{v}</span>
        </div>
      ))}
    </>
  );
}

function hexPath(r: number): string {
  return Array.from({ length: 6 }, (_, i) => {
    const a = (i * Math.PI) / 3 - Math.PI / 6;
    return `${i === 0 ? "M" : "L"} ${(r * Math.cos(a)).toFixed(2)} ${(r * Math.sin(a)).toFixed(2)}`;
  }).join(" ");
}
