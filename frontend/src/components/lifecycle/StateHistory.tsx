import type { StateTransition } from "../../types/incident";
import { actionLabel } from "../../lib/format";

interface Props {
  history: StateTransition[];
}

function fmt(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return isNaN(d.getTime()) ? iso : d.toLocaleString();
}

/** Append-only lifecycle transition history (audit trail). */
export function StateHistory({ history }: Props) {
  if (history.length === 0) {
    return <div className="state state-empty">No transitions yet.</div>;
  }
  return (
    <ol className="history" aria-label="Lifecycle history">
      {history.map((h, i) => (
        <li key={i} className="history-item" data-testid="history-item">
          <span className="history-action">{actionLabel(h.action)}</span>
          <span className="history-states">
            {h.from_state ?? "—"} → {h.to_state}
          </span>
          {h.reviewer && <span className="history-reviewer">by {h.reviewer}</span>}
          {h.note && <span className="history-note">“{h.note}”</span>}
          <time className="history-time">{fmt(h.created_at)}</time>
        </li>
      ))}
    </ol>
  );
}
