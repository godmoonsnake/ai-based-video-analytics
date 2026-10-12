import { useMemo } from "react";
import type { IncidentGraph } from "../../types/incident";
import { api } from "../../services/api";
import { useAsync } from "../../hooks/useAsync";
import { camLabel, fmtSeconds } from "../../lib/format";
import { ErrorPanel } from "../ui/States";
import { camKindChip } from "../../lib/cameraKinds";

/**
 * Site map: cameras at their registered site-plan coordinates (backend
 * /cameras), with the correlated movement path animated in walk order.
 * Topology-aware path — says nothing about identity, and says so.
 */
export function SiteMapView({ graph }: { graph: IncidentGraph | null }) {
  const cameras = useAsync(() => api.listCameras(), []);

  const model = useMemo(() => {
    if (!graph || !cameras.data) return null;
    const camList = cameras.data;

    // movement path from movement edges (walk order = edge order)
    const movements = graph.edges
      .filter((e) => e.type === "movement" && e.source && e.target)
      .map((e) => ({
        from: e.source!.ref_id,
        to: e.target!.ref_id,
        gap: (e.evidence?.temporal_gap_seconds as number | undefined) ?? null,
        conf: e.confidence,
      }));

    const waypoints: string[] = [];
    for (const m of movements) {
      if (waypoints.length === 0) waypoints.push(m.from);
      if (!waypoints.includes(m.to)) waypoints.push(m.to);
    }

    // Projection: world site-plan coords -> a fixed pixel viewBox so node
    // shapes stay a constant size regardless of coordinate magnitude.
    const VW = 1100;
    const VH = 480;
    const MARGIN = 90;
    const pts = camList.filter((c) => c.x != null && c.y != null);
    const allKnown = pts.length === camList.length && pts.length > 0;
    const minX = allKnown ? Math.min(...pts.map((c) => c.x!)) : -5;
    const maxX = allKnown ? Math.max(...pts.map((c) => c.x!)) : 5;
    const minY = allKnown ? Math.min(...pts.map((c) => c.y!)) : -5;
    const maxY = allKnown ? Math.max(...pts.map((c) => c.y!)) : 5;
    const worldW = Math.max(1e-6, maxX - minX);
    const worldH = Math.max(1e-6, maxY - minY);
    const scale = Math.min((VW - MARGIN * 2) / worldW, (VH - MARGIN * 2) / worldH);
    const offX = (VW - worldW * scale) / 2;
    const offY = (VH - worldH * scale) / 2;
    const px = (x: number) => offX + (x - minX) * scale;
    const py = (y: number) => offY + (y - minY) * scale;

    const cams = camList.map((c) => {
      const known = c.x != null && c.y != null;
      // fallback: distribute unknowns on an ellipse
      const idx = camList.indexOf(c);
      const n = camList.length || 1;
      const a = (idx / n) * Math.PI * 2 - Math.PI / 2;
      const x = known ? px(c.x!) : VW / 2 + (VW * 0.36) * Math.cos(a);
      const y = known ? py(c.y!) : VH / 2 + (VH * 0.36) * Math.sin(a);
      return { cam: c, x, y, known };
    });

    const posById = new Map(cams.map((c) => [c.cam.id, { x: c.x, y: c.y }]));
    const path = waypoints.map((w) => posById.get(w)).filter(Boolean) as { x: number; y: number }[];

    // orthogonal-ish path with rounded elbows
    const pathD = path
      .map((p, i) => {
        if (i === 0) return `M ${p.x} ${p.y}`;
        const prev = path[i - 1];
        const r = Math.min(26, Math.abs(p.y - prev.y) / 2, Math.abs(p.x - prev.x) / 2);
        const dirX = p.x > prev.x ? 1 : -1;
        const dirY = p.y > prev.y ? 1 : -1;
        return (
          `L ${prev.x} ${p.y - dirY * r}` +
          ` Q ${prev.x} ${p.y} ${prev.x + dirX * r} ${p.y}` +
          ` L ${p.x} ${p.y}`
        );
      })
      .join(" ");

    const stepPos = waypoints.map((w, i) => ({
      id: w,
      step: i + 1,
      ...posById.get(w)!,
    }));

    const gapChips = movements.map((m, i) => {
      const a = posById.get(m.from)!;
      const b = posById.get(m.to)!;
      return { i, x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 - 14, gap: m.gap };
    });

    return { cams, pathD, stepPos, gapChips, VW, VH, waypoints };
  }, [graph, cameras.data]);

  if (cameras.error) {
    return <ErrorPanel error={cameras.error} onRetry={cameras.reload} />;
  }
  if (!graph || !model) {
    return (
      <div className="map-wrap">
        <div className="state-block">
          <div className="radar">
            <span className="sweep" />
          </div>
          <div className="state-sub">PROJECTING SITE LAYOUT …</div>
        </div>
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12, height: "100%" }}>
      <div className="lanes-head">
        <span className="micro">Site topology</span>
        <span className="lanes-caption">
          registered camera layout · correlated movement path in walk order
        </span>
      </div>
      <div className="map-wrap" style={{ flex: 1 }}>
        <svg
          className="map-svg"
          viewBox={`0 0 ${model.VW} ${model.VH}`}
          preserveAspectRatio="xMidYMid meet"
          role="img"
          aria-label="Site camera topology with movement path"
        >
          <defs>
            <pattern id="map-grid" width="30" height="30" patternUnits="userSpaceOnUse">
              <path d="M 30 0 L 0 0 0 30" fill="none" className="map-grid" />
            </pattern>
          </defs>
          <rect width={model.VW} height={model.VH} fill="url(#map-grid)" />
          {/* site footprint */}
          <rect
            className="map-footprint"
            x={3}
            y={3}
            width={model.VW - 6}
            height={model.VH - 6}
            rx="16"
          />

          {/* movement path */}
          {model.pathD && (
            <path className="map-path" d={model.pathD} markerEnd="url(#map-arrow)" />
          )}
          <marker id="map-arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto">
            <path d="M0 1 L9 5 L0 9" fill="#43e0a0" />
          </marker>

          {/* gap chips on segments */}
          {model.gapChips.map((g) => (
            <text key={g.i} className="map-gaplbl" x={g.x} y={g.y}>
              {g.gap != null ? `+${fmtSeconds(g.gap)}` : ""}
            </text>
          ))}

          {/* step chips */}
          {model.stepPos.map((s) => (
            <g key={`step-${s.id}`} transform={`translate(${s.x + 14} ${s.y - 14})`}>
              <circle className="map-step-chip" r="7.5" />
              <text className="map-step" y="2.6" textAnchor="middle">
                {s.step}
              </text>
            </g>
          ))}

          {/* cameras */}
          {model.cams.map(({ cam, x, y, known }) => {
            const kind = camKindChip(cam.name);
            const restricted = kind === "restricted";
            return (
              <g
                key={cam.id}
                className={`map-cam${restricted ? " restricted" : ""}`}
                transform={`translate(${x} ${y})`}
              >
                {restricted && (
                  <circle r="26" fill="none" stroke="#ff5c5c" strokeOpacity="0.5" strokeDasharray="3 4">
                    <animate attributeName="r" values="24;30;24" dur="2.6s" repeatCount="indefinite" />
                    <animate attributeName="stroke-opacity" values="0.55;0.15;0.55" dur="2.6s" repeatCount="indefinite" />
                  </circle>
                )}
                {restricted && <circle r="21" fill="rgba(255,92,92,0.06)" />}
                <rect className="body" x="-15" y="-10" width="30" height="20" rx="6" />
                {/* camera glyph */}
                <path
                  className="icon"
                  d="M -8 -3 L 2 -6 L 3.4 -0.5 L -6.6 2.4 Z"
                />
                <path className="icon" d="M -3 2.5 L -2 6 M -6 9 L 0 9 L -1.4 6" />
                <text className="lbl" y="24">
                  {camLabel(cam.id)}
                </text>
                <text className="sub" y="-16">
                  {kind}
                  {known ? "" : " · position n/a"}
                </text>
              </g>
            );
          })}
        </svg>
        <div className="map-caption">
          movement correlation via site topology — not identity · source: /cameras registry
        </div>
      </div>
    </div>
  );
}
