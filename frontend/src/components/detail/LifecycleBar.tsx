import { useState } from "react";
import { api, ApiError } from "../../services/api";
import type { LifecycleAction } from "../../types/incident";
import { actionLabel } from "../../lib/format";
import { useHotkeys } from "../../hooks/useHotkeys";
import { InlineAlert } from "../ui/States";
import { useToast } from "../ui/Toasts";
import { IconCrosshair, IconShieldCheck, IconBan, IconRotate } from "../icons";

const ACTION_ICON: Record<string, React.ReactNode> = {
  start_triage: <IconCrosshair />,
  confirm: <IconShieldCheck />,
  dismiss: <IconBan />,
  reopen: <IconRotate />,
};

/** Keyboard shortcut per action (lowercase event.key). */
const ACTION_KEY: Record<string, string> = {
  start_triage: "t",
  confirm: "c",
  dismiss: "e",
  reopen: "r",
};

const ACTION_CLASS: Record<string, string> = {
  start_triage: "btn-violet",
  confirm: "btn-accent",
  dismiss: "btn-danger",
  reopen: "btn",
};

interface Props {
  incidentId: number;
  state: string;
  allowedActions: string[];
  onTransitioned: () => void;
}

/**
 * Operator lifecycle controls. Renders ONLY the backend-allowed actions
 * (allowed_actions is the source of truth), applies transitions, surfaces
 * 409 rejections inline, and binds single-key shortcuts (T/C/E/R).
 */
export function LifecycleBar({ incidentId, state, allowedActions, onTransitioned }: Props) {
  const [busy, setBusy] = useState(false);
  const [rejected, setRejected] = useState<string | null>(null);
  const [noteOpen, setNoteOpen] = useState(false);
  const [note, setNote] = useState("");
  const toast = useToast();

  const apply = async (action: LifecycleAction | string) => {
    if (busy) return;
    setBusy(true);
    setRejected(null);
    try {
      const res = await api.transition(incidentId, action as LifecycleAction, {
        note: note.trim() || undefined,
      });
      toast(
        "success",
        `#${incidentId} → ${res.state}`,
        `${actionLabel(action)} recorded${note.trim() ? " with note" : ""}.`,
      );
      setNote("");
      setNoteOpen(false);
      onTransitioned();
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        setRejected(`Transition rejected — ${e.detail ?? "not allowed from current state"}`);
      } else if (e instanceof ApiError && e.isNetwork) {
        toast("error", "Backend unreachable", "Change not applied.");
        setRejected("Network error — change not applied");
      } else {
        toast("error", "Transition failed", e instanceof Error ? e.message : String(e));
      }
    } finally {
      setBusy(false);
    }
  };

  // Single-key triage: one hotkey per ALLOWED action only.
  useHotkeys(
    allowedActions
      .filter((a) => ACTION_KEY[a])
      .map((a) => ({
        key: ACTION_KEY[a],
        handler: () => void apply(a),
      })),
  );

  return (
    <div>
      <div className="lifecycle-controls" data-testid="lifecycle-controls" data-state={state}>
        <span className="micro-plain" style={{ marginRight: 2 }}>
          operator review
        </span>
        {allowedActions.map((a) => (
          <button
            key={a}
            className={`btn ${ACTION_CLASS[a] ?? ""}`}
            data-testid={`action-${a}`}
            disabled={busy}
            onClick={() => void apply(a)}
            title={`${actionLabel(a)} incident #${incidentId}`}
          >
            {ACTION_ICON[a]}
            {actionLabel(a)}
            {ACTION_KEY[a] && <span className="kbd">{ACTION_KEY[a].toUpperCase()}</span>}
          </button>
        ))}
        <div className="lifecycle-note">
          {noteOpen ? (
            <input
              autoFocus
              placeholder="reviewer note (attached to transition)"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Escape") setNoteOpen(false);
              }}
              aria-label="Reviewer note"
            />
          ) : (
            <button className="btn btn-sm" onClick={() => setNoteOpen(true)}>
              + note
            </button>
          )}
        </div>
      </div>
      {rejected && <InlineAlert>{rejected}</InlineAlert>}
    </div>
  );
}
