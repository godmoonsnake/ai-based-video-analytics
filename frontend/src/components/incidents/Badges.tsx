import type { ConfidenceBand } from "../../types/incident";
import { bandClass, fmtConfidence } from "../../lib/format";

export function ConfidenceBadge({
  confidence,
  band,
}: {
  confidence: number | null;
  band: ConfidenceBand | string;
}) {
  return (
    <span className={`conf-badge ${bandClass(band)}`} title="Incident confidence (min of correlation & behaviour pillars)">
      {fmtConfidence(confidence)}
      <span className="conf-band">{band}</span>
    </span>
  );
}

export function StateBadge({ state }: { state: string }) {
  return <span className={`state-badge state-${state}`}>{state}</span>;
}
