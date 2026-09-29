import type { IncidentSummary } from "../api";

interface Props {
  incidents: IncidentSummary[];
  selectedId: number | null;
  onSelect: (id: number) => void;
}

const PRIORITY_COLOR: Record<string, string> = {
  critical: "#b00020",
  high: "#e65100",
  medium: "#f9a825",
  low: "#2e7d32",
};

export function IncidentFeed({ incidents, selectedId, onSelect }: Props) {
  return (
    <div>
      <h2>Incident Feed</h2>
      {incidents.length === 0 && <p className="muted">No incidents yet. Run the pipeline.</p>}
      <ul className="feed">
        {incidents.map((i) => (
          <li
            key={i.id}
            className={i.id === selectedId ? "feed-item selected" : "feed-item"}
            onClick={() => onSelect(i.id)}
          >
            <span
              className="badge"
              style={{ background: PRIORITY_COLOR[i.priority ?? "low"] ?? "#555" }}
            >
              {i.priority ?? "?"}
            </span>
            <span className="incident-id">#{i.id}</span>
            <span className="status">{i.status}</span>
            <span className="cams">{i.cameras.join(" → ")}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
