import type { IncidentSummary } from "../../types/incident";
import { fmtTime, incidentType, priorityClass } from "../../lib/format";
import { ConfidenceBadge, StateBadge } from "./Badges";

interface Props {
  incidents: IncidentSummary[];
  selectedId: number | null;
  onSelect: (id: number) => void;
}

/**
 * Operator incident list. Columns: id, start, end, type (priority/severity),
 * confidence + band, lifecycle state, involved camera count.
 * Track count is not part of the list API payload and is shown in the detail
 * view (which returns supporting tracks) rather than fabricated here.
 */
export function IncidentList({ incidents, selectedId, onSelect }: Props) {
  return (
    <table className="incident-table" aria-label="Incidents">
      <thead>
        <tr>
          <th>ID</th>
          <th>Type</th>
          <th>State</th>
          <th>Confidence</th>
          <th>Cameras</th>
          <th>Start</th>
          <th>End</th>
        </tr>
      </thead>
      <tbody>
        {incidents.map((inc) => (
          <tr
            key={inc.id}
            className={inc.id === selectedId ? "selected" : ""}
            onClick={() => onSelect(inc.id)}
            data-testid={`incident-row-${inc.id}`}
          >
            <td>#{inc.id}</td>
            <td>
              <span className={`type-pill ${priorityClass(inc.priority)}`}>
                {incidentType(inc.priority)}
              </span>
            </td>
            <td>
              <StateBadge state={inc.status} />
            </td>
            <td>
              <ConfidenceBadge confidence={inc.confidence} band={inc.confidence_band} />
            </td>
            <td>
              <span title={inc.cameras.join(", ")}>{inc.cameras.length}</span>
            </td>
            <td className="ts">{fmtTime(inc.start_time)}</td>
            <td className="ts">{fmtTime(inc.end_time)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
