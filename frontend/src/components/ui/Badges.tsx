import type { ReactNode } from "react";
import type { ConfidenceBand } from "../../types/incident";
import { bandClass } from "../../lib/format";
import { IconLayers, IconCamera } from "../icons";

/** Severity chip — the backend `priority` surfaced as incident severity. */
export function PriorityChip({ priority }: { priority: string | null | undefined }) {
  const p = priority ?? "unknown";
  return (
    <span className={`badge pri-${p}`}>
      <span className="dot" />
      {p}
    </span>
  );
}

/** Lifecycle state badge (class contract: .state-badge.state-<state>). */
export function StateBadge({ state }: { state: string | null | undefined }) {
  const s = state ?? "open";
  return (
    <span className={`state-badge state-${s}`}>
      <span className="dot" />
      {s}
    </span>
  );
}

/** Confidence band — diamond marker + band word. */
export function BandPill({
  band,
  confidence,
}: {
  band: ConfidenceBand | string | null | undefined;
  confidence?: number | null;
}) {
  return (
    <span className={`band ${bandClass(band)}`}>
      {confidence != null ? confidence.toFixed(2) : (band ?? "unknown")}
    </span>
  );
}

export function Chip({
  children,
  mint,
  title,
}: {
  children: ReactNode;
  mint?: boolean;
  title?: string;
}) {
  return (
    <span className={`chip${mint ? " mint" : ""}`} title={title}>
      {children}
    </span>
  );
}

export function CameraCount({ n }: { n: number }) {
  return (
    <span className="m" title={`${n} camera${n === 1 ? "" : "s"} involved`}>
      <IconCamera />
      {n}
    </span>
  );
}

export function TrackCount({ n }: { n: number }) {
  return (
    <span className="m" title={`${n} global track${n === 1 ? "" : "s"}`}>
      <IconLayers />
      {n}
    </span>
  );
}
