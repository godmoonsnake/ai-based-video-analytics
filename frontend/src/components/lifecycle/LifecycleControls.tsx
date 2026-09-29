import { useState } from "react";
import { ApiError, api } from "../../services/api";
import type { LifecycleAction } from "../../types/incident";
import { actionLabel } from "../../lib/format";
import { StateBadge } from "../incidents/Badges";

interface Props {
  incidentId: number;
  state: string;
  allowedActions: string[];
  onTransitioned: () => void; // parent refreshes detail + history
}

const ACTION_CLASS: Record<string, string> = {
  confirm: "btn-confirm",
  dismiss: "btn-dismiss",
  start_triage: "btn-primary",
  reopen: "btn-secondary",
};

/**
 * Operator lifecycle controls. Renders ONLY the actions the backend reports as
 * valid from the current state (no client-side guessing). Applies the transition
 * through the lifecycle API, surfaces rejections (409) and errors, and asks the
 * parent to refresh the incident + history on success.
 */
export function LifecycleControls({ incidentId, state, allowedActions, onTransitioned }: Props) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reviewer, setReviewer] = useState("");

  async function run(action: LifecycleAction) {
    setBusy(action);
    setError(null);
    try {
      await api.transition(incidentId, action, { reviewer: reviewer || undefined });
      onTransitioned();
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        setError(`Transition rejected: ${e.detail ?? "invalid for current state"}`);
      } else if (e instanceof ApiError) {
        setError(e.detail ? `${e.message} — ${e.detail}` : e.message);
      } else {
        setError(String(e));
      }
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="lifecycle" data-testid="lifecycle-controls">
      <div className="lifecycle-current">
        Current state: <StateBadge state={state} />
      </div>

      <label className="lifecycle-reviewer">
        Reviewer (optional handle/role)
        <input
          type="text"
          value={reviewer}
          placeholder="e.g. operator, shift_lead"
          onChange={(e) => setReviewer(e.target.value)}
        />
      </label>

      <div className="lifecycle-actions">
        {allowedActions.length === 0 && (
          <span className="muted">No actions available from this state.</span>
        )}
        {allowedActions.map((a) => (
          <button
            key={a}
            className={ACTION_CLASS[a] ?? "btn-primary"}
            disabled={busy !== null}
            onClick={() => run(a as LifecycleAction)}
            data-testid={`action-${a}`}
          >
            {busy === a ? "…" : actionLabel(a)}
          </button>
        ))}
      </div>

      {error && (
        <div className="lifecycle-error" role="alert">
          {error}
        </div>
      )}
    </div>
  );
}
