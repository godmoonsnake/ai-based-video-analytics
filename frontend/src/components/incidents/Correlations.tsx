import type { Correlation } from "../../types/incident";

interface Props {
  correlations: Correlation[];
}

function ScoreBar({ label, value }: { label: string; value: number | undefined }) {
  const v = value ?? 0;
  return (
    <div className="score">
      <span className="score-label">{label}</span>
      <span className="score-track" aria-hidden="true">
        <span className="score-fill" style={{ width: `${Math.round(Math.min(1, Math.max(0, v)) * 100)}%` }} />
      </span>
      <span className="score-val">{v.toFixed(2)}</span>
    </div>
  );
}

/**
 * Explains each cross-camera correlation: which tracks were linked, the combined
 * score and its temporal/topology(motion)/appearance components, and the
 * transition + temporal gap. This is why two observations were connected.
 */
export function Correlations({ correlations }: Props) {
  return (
    <div className="correlations">
      <p className="corr-note">
        Cross-camera movement correlation from topology, timing and appearance
        signals — not a claim of personal identity.
      </p>
      {correlations.map((c, i) => (
        <div className="correlation-card" key={i} data-testid="correlation-card">
          <div className="correlation-head">
            <span className="corr-transition">{c.topology_transition ?? "—"}</span>
            <span className="corr-combined" title="combined correlation score">
              {(c.combined_score ?? c.confidence ?? 0).toFixed(3)}
            </span>
          </div>
          <div className="corr-tracks">
            <span>{c.from_track ?? "?"}</span>
            <span aria-hidden="true"> → </span>
            <span>{c.to_track ?? "?"}</span>
          </div>
          <div className="corr-scores">
            <ScoreBar label="temporal" value={c.s_time} />
            <ScoreBar label="topology / motion" value={c.s_motion} />
            <ScoreBar label="appearance" value={c.s_appearance} />
          </div>
          <div className="corr-gap">
            temporal gap: {c.temporal_gap_seconds != null ? `${c.temporal_gap_seconds}s` : "—"}
          </div>
        </div>
      ))}
    </div>
  );
}
