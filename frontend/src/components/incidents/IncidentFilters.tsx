export interface Filters {
  status: string;
  priority: string;
}

interface Props {
  filters: Filters;
  onChange: (f: Filters) => void;
  types: string[]; // distinct priorities present in the data
}

const STATES = ["", "open", "triage", "confirmed", "dismissed"];

/** Filter controls for the incident list: lifecycle state + incident type. */
export function IncidentFilters({ filters, onChange, types }: Props) {
  return (
    <div className="filters" role="group" aria-label="Incident filters">
      <label>
        State
        <select
          value={filters.status}
          onChange={(e) => onChange({ ...filters, status: e.target.value })}
          aria-label="Filter by state"
        >
          {STATES.map((s) => (
            <option key={s || "all"} value={s}>
              {s || "All"}
            </option>
          ))}
        </select>
      </label>
      <label>
        Type
        <select
          value={filters.priority}
          onChange={(e) => onChange({ ...filters, priority: e.target.value })}
          aria-label="Filter by type"
        >
          <option value="">All</option>
          {types.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
      </label>
    </div>
  );
}
