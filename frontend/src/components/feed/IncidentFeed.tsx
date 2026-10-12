import { useEffect, useMemo, useState } from "react";
import type { IncidentSummary } from "../../types/incident";
import { camLabel, fmtAgo, priorityRank } from "../../lib/format";
import { EmptyBlock, ErrorPanel, LoadingBlock } from "../ui/States";
import { api } from "../../services/api";
import { useToast } from "../ui/Toasts";

interface Props {
  incidents: IncidentSummary[] | null;
  loading: boolean;
  error: Error | null;
  reload: () => void;
  selectedId: number | null;
  onSelect: (id: number) => void;
  onVisibleChange: (ids: number[]) => void;
}

export function IncidentFeed({ incidents, loading, error, reload, selectedId, onSelect, onVisibleChange }: Props) {
  const [state, setState] = useState("all");
  const [type, setType] = useState("all");
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState("recent");
  const toast = useToast();
  const types = useMemo(() => [...new Set((incidents ?? []).map((incident) => incidentType(incident)))].sort(), [incidents]);
  const visible = useMemo(() => {
    const text = query.trim().toLowerCase();
    return [...(incidents ?? [])].filter((incident) =>
      (state === "all" || incident.status === state) &&
      (type === "all" || incidentType(incident) === type) &&
      (!text || [String(incident.id), incident.summary_text ?? "", ...incident.cameras].some((value) => value.toLowerCase().includes(text)))
    ).sort((a, b) => sort === "priority"
      ? priorityRank(b.priority) - priorityRank(a.priority) || (b.start_time ?? 0) - (a.start_time ?? 0)
      : (b.start_time ?? 0) - (a.start_time ?? 0));
  }, [incidents, state, type, query, sort]);
  useEffect(() => { onVisibleChange(visible.map((incident) => incident.id)); }, [visible, onVisibleChange]);

  async function loadReview() {
    try { await api.replayReview(); reload(); toast("success", "Review cases ready", "Synthetic review cases loaded."); }
    catch { toast("error", "Could not load review cases", "Check the backend connection."); }
  }

  return <section className="feed" aria-label="Incidents">
    <div className="feed-head"><div><h2>Incidents</h2><p>{visible.length} of {(incidents ?? []).length} shown</p></div><button className="quiet-button" onClick={reload}>Refresh</button></div>
    <div className="feed-controls">
      <input data-testid="feed-search" aria-label="Search incidents" placeholder="Search incidents or cameras" value={query} onChange={(event) => setQuery(event.target.value)} />
      <label>State<select aria-label="State filter" value={state} onChange={(event) => setState(event.target.value)}><option value="all">All</option><option value="open">Open</option><option value="triage">Triage</option><option value="confirmed">Confirmed</option><option value="dismissed">Dismissed</option></select></label>
      <label>Type<select aria-label="Type filter" value={type} onChange={(event) => setType(event.target.value)}><option value="all">All</option>{types.map((name) => <option key={name} value={name}>{name}</option>)}</select></label>
      <label>Sort<select aria-label="Sort incidents" value={sort} onChange={(event) => setSort(event.target.value)}><option value="recent">Recent</option><option value="priority">Priority</option></select></label>
    </div>
    <div className="feed-scroll" data-testid="incident-list">
      {error && <ErrorPanel error={error} onRetry={reload} />}
      {!error && loading && !incidents && <LoadingBlock label="Loading incidents" />}
      {!error && incidents?.length === 0 && <EmptyBlock title="No incidents" sub="No cases are available in this site."><button className="button" onClick={() => void loadReview()}>Load review cases</button></EmptyBlock>}
      {!error && incidents && incidents.length > 0 && !visible.length && <EmptyBlock title="No matching incidents" sub="Try another search or filter." />}
      {!!visible.length && <div className="incident-table-wrap"><table className="incident-table"><thead><tr><th>ID</th><th>Type</th><th>Camera</th><th>Time</th><th>Priority</th><th>Status</th></tr></thead><tbody>
        {visible.map((incident) => <tr key={incident.id} className={incident.id === selectedId ? "selected" : ""} data-testid={`incident-row-${incident.id}`} onClick={() => onSelect(incident.id)} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); onSelect(incident.id); } }} tabIndex={0} aria-selected={incident.id === selectedId}>
          <td className="incident-id">#{incident.id}</td><td><strong>{incidentType(incident)}</strong><small>{incident.summary_text ?? "No summary"}</small></td><td>{incident.cameras.length ? incident.cameras.map(camLabel).join(", ") : "—"}</td><td title={incident.start_time ? new Date(incident.start_time * 1000).toLocaleString() : ""}>{fmtAgo(incident.start_time)}</td><td><span className={`table-badge priority-${incident.priority ?? "unknown"}`}>{incident.priority ?? "Unknown"}</span></td><td><span className={`table-badge state-${incident.status}`}>{incident.status}</span></td>
        </tr>)}
      </tbody></table></div>}
    </div>
  </section>;
}

function incidentType(incident: IncidentSummary): string {
  const labels: Record<string, string> = {
    restricted_entry: "Restricted zone entry", review: "Review",
    smoking: "Experimental smoking observation", drinking: "Experimental drinking observation",
    restricted_reading: "Experimental reading observation", material_change: "Experimental material observation",
    vehicle_plate: "Experimental plate observation",
  };
  return labels[incident.category ?? "review"] ?? "Review";
}
