import type { StateHistoryResponse } from "../../types/incident";
import { StateBadge } from "../ui/Badges";
import { IconArrowRight } from "../icons";
import { actionLabel } from "../../lib/format";

/** Audit trail: the persisted lifecycle history for this incident. */
export function AuditTrail({ history }: { history: StateHistoryResponse | null }) {
  const entries = history?.history ?? [];
  return (
    <div className="audit">
      <div className="lanes-head">
        <span className="micro">Lifecycle audit</span>
        <span className="lanes-caption">
          {entries.length} transition{entries.length === 1 ? "" : "s"} · persisted with reviewer +
          note
        </span>
      </div>
      <div className="panel">
        {entries.length === 0 ? (
          <p className="state-sub" style={{ textAlign: "left" }}>
            No transitions recorded yet. Lifecycle changes made by operators appear here with
            reviewer and note.
          </p>
        ) : (
          <div className="audit-rail">
            {entries.map((h, i) => (
              <div className="history-item" data-testid="history-item" key={i}>
                <div className="hi-row">
                  <span className="hi-action">{actionLabel(h.action)}</span>
                  {h.from_state && (
                    <>
                      <StateBadge state={h.from_state} />
                      <span className="hi-arrow">
                        <IconArrowRight />
                      </span>
                    </>
                  )}
                  <StateBadge state={h.to_state} />
                  {h.reviewer && <span className="chip">reviewer · {h.reviewer}</span>}
                  <span className="hi-time">{fmtAuditTime(h.created_at)}</span>
                </div>
                {h.note && <div className="hi-note">“{h.note}”</div>}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function fmtAuditTime(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString(undefined, {
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}
