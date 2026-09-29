import { useMemo, useState } from "react";
import { api } from "../services/api";
import { useAsync } from "../hooks/useAsync";
import type { IncidentSummary } from "../types/incident";
import { Loading, Empty, ErrorState } from "../components/common/States";
import { IncidentList } from "../components/incidents/IncidentList";
import { IncidentFilters, type Filters } from "../components/incidents/IncidentFilters";

interface Props {
  selectedId: number | null;
  onSelect: (id: number) => void;
  refreshKey: number; // bump to force reload after external changes (transitions)
}

export function IncidentListPage({ selectedId, onSelect, refreshKey }: Props) {
  const [filters, setFilters] = useState<Filters>({ status: "", priority: "" });
  const [demoBusy, setDemoBusy] = useState(false);

  const { data, loading, error, reload } = useAsync<IncidentSummary[]>(
    () => api.listIncidents({ status: filters.status || undefined, priority: filters.priority || undefined }),
    [filters.status, filters.priority, refreshKey],
  );

  const types = useMemo(() => {
    const s = new Set<string>();
    (data ?? []).forEach((i) => i.priority && s.add(i.priority));
    return [...s].sort();
  }, [data]);

  async function runDemo() {
    setDemoBusy(true);
    try {
      await api.runDemoPipeline();
      reload();
    } finally {
      setDemoBusy(false);
    }
  }

  return (
    <div className="list-page">
      <div className="list-toolbar">
        <IncidentFilters filters={filters} onChange={setFilters} types={types} />
        <button className="btn-secondary" onClick={runDemo} disabled={demoBusy}>
          {demoBusy ? "Running demo…" : "Run demo pipeline"}
        </button>
      </div>

      {loading ? (
        <Loading label="Loading incidents…" />
      ) : error ? (
        <ErrorState error={error} onRetry={reload} />
      ) : (data?.length ?? 0) === 0 ? (
        <Empty label="No incidents. Run the demo pipeline to generate one." />
      ) : (
        <IncidentList incidents={data!} selectedId={selectedId} onSelect={onSelect} />
      )}
    </div>
  );
}
