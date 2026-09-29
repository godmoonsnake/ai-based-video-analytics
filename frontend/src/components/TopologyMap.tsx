import type { Camera } from "../api";

interface Props {
  cameras: Camera[];
  path?: string[]; // ordered camera ids of the selected incident/global track
}

export function TopologyMap({ cameras, path = [] }: Props) {
  const pts = cameras.filter((c) => c.x != null && c.y != null);
  if (!pts.length) return null;
  const xs = pts.map((c) => c.x as number);
  const ys = pts.map((c) => c.y as number);
  const minX = Math.min(...xs), maxX = Math.max(...xs);
  const minY = Math.min(...ys), maxY = Math.max(...ys);
  const W = 360, H = 160, pad = 30;
  const sx = (x: number) => pad + ((x - minX) / (maxX - minX || 1)) * (W - 2 * pad);
  const sy = (y: number) => pad + ((y - minY) / (maxY - minY || 1)) * (H - 2 * pad);
  const byId = new Map(pts.map((c) => [c.id, c]));

  const pathPoints = path
    .map((id) => byId.get(id))
    .filter((c): c is Camera => !!c)
    .map((c) => `${sx(c.x as number)},${sy(c.y as number)}`);

  return (
    <div>
      <h3>Camera Topology {path.length > 0 && "(track path highlighted)"}</h3>
      <svg width={W} height={H} className="topo">
        {pathPoints.length > 1 && (
          <polyline
            points={pathPoints.join(" ")}
            fill="none"
            stroke="#e65100"
            strokeWidth={2}
            strokeDasharray="4 3"
          />
        )}
        {pts.map((c) => {
          const active = path.includes(c.id);
          return (
            <g key={c.id}>
              <circle
                cx={sx(c.x as number)}
                cy={sy(c.y as number)}
                r={active ? 8 : 6}
                fill={active ? "#e65100" : "#1565c0"}
              />
              <text x={sx(c.x as number) + 10} y={sy(c.y as number) + 4} fontSize={11}>
                {c.id}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}
