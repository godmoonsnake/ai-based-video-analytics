// Small presentation helpers. Pure functions, no API access.
import type { ConfidenceBand } from "../types/incident";

/** Format a UNIX epoch (seconds) as a readable local timestamp. */
export function fmtTime(ts: number | null | undefined): string {
  if (ts == null) return "—";
  return new Date(ts * 1000).toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

/** Format only the time-of-day portion (for dense timeline rows). */
export function fmtClock(ts: number | null | undefined): string {
  if (ts == null) return "—";
  return new Date(ts * 1000).toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

/** Duration between two epochs (seconds) as a compact human string. */
export function fmtDuration(start: number | null, end: number | null): string {
  if (start == null || end == null) return "—";
  const s = Math.max(0, Math.round(end - start));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  const rem = s % 60;
  return rem ? `${m}m ${rem}s` : `${m}m`;
}

export function fmtConfidence(c: number | null | undefined): string {
  return c == null ? "n/a" : c.toFixed(2);
}

export function bandClass(band: ConfidenceBand | string | null | undefined): string {
  return `band-${band ?? "unknown"}`;
}

/** The incident "type"/severity. The backend uses `priority` as the severity;
 *  the operator UI surfaces it as the incident type label. */
export function incidentType(priority: string | null | undefined): string {
  return priority ?? "unclassified";
}

export function priorityClass(priority: string | null | undefined): string {
  return `priority-${priority ?? "unknown"}`;
}

/** Human label for a lifecycle action button. */
export function actionLabel(action: string): string {
  switch (action) {
    case "start_triage":
      return "Start triage";
    case "confirm":
      return "Confirm";
    case "dismiss":
      return "Dismiss";
    case "reopen":
      return "Reopen";
    default:
      return action;
  }
}
