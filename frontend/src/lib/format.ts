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

/** Date portion only. */
export function fmtDate(ts: number | null | undefined): string {
  if (ts == null) return "—";
  return new Date(ts * 1000).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "2-digit",
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

/** Seconds as compact human string ("6s", "1m 41s"). */
export function fmtSeconds(s: number | null | undefined): string {
  if (s == null) return "—";
  return fmtDuration(0, s);
}

export function fmtConfidence(c: number | null | undefined): string {
  return c == null ? "n/a" : c.toFixed(2);
}

/** Relative "x min ago" from a UNIX epoch; falls back to absolute when old. */
export function fmtAgo(ts: number | null | undefined): string {
  if (ts == null) return "—";
  const delta = Date.now() / 1000 - ts;
  if (delta < 45) return "just now";
  if (delta < 3600) return `${Math.round(delta / 60)} min ago`;
  if (delta < 86400) return `${Math.round(delta / 3600)} h ago`;
  return fmtDate(ts);
}

export function bandClass(band: ConfidenceBand | string | null | undefined): string {
  return `band-${band ?? "unknown"}`;
}

/** Severity rank — higher is hotter. Unknown sorts lowest. */
export function priorityRank(priority: string | null | undefined): number {
  switch (priority) {
    case "critical":
      return 4;
    case "high":
      return 3;
    case "medium":
      return 2;
    case "low":
      return 1;
    default:
      return 0;
  }
}

/** Human label for a lifecycle action button. */
export function actionLabel(action: string): string {
  switch (action) {
    case "start_triage":
      return "Triage";
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

/** snake_case -> readable words. */
export function titleize(s: string | null | undefined): string {
  if (!s) return "—";
  return s
    .replace(/_/g, " ")
    .replace(/\b\w/g, (m) => m.toUpperCase());
}

/** Pretty camera id: "gate_3" -> "GATE 3". */
export function camLabel(id: string | null | undefined): string {
  if (!id) return "—";
  return id.replace(/_/g, " ").toUpperCase();
}

export function clamp01(n: number | null | undefined): number {
  if (n == null || Number.isNaN(n)) return 0;
  return Math.min(1, Math.max(0, n));
}
