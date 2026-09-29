import type { IncidentDetail } from "../api";
import { CrossCameraTimeline } from "./CrossCameraTimeline";

interface Props {
  incident: IncidentDetail;
  onFeedback: (action: "confirm" | "dismiss") => void;
}

function fmt(ts: number | null): string {
  return ts ? new Date(ts * 1000).toLocaleString() : "—";
}

export function ExplainableIncidentCard({ incident, onFeedback }: Props) {
  const evidenceCount = incident.timeline.filter(
    (t) => t.evidence?.clip_url || t.evidence?.snapshot_url,
  ).length;

  return (
    <div className="card">
      <div className="card-head">
        <h2>Incident #{incident.id}</h2>
        <span className={`pill priority-${incident.priority}`}>{incident.priority}</span>
        <span className="pill">{incident.status}</span>
      </div>

      {/* Explainable: What / Where / When / Why / Confidence */}
      <dl className="explain">
        <dt>What</dt>
        <dd>{incident.summary_text}</dd>
        <dt>Where</dt>
        <dd>{incident.cameras.join(" → ")}</dd>
        <dt>When</dt>
        <dd>
          {fmt(incident.start_time)} — {fmt(incident.end_time)}
        </dd>
        <dt>Why flagged</dt>
        <dd>
          Cross-camera track through a restricted zone; graph has{" "}
          {incident.graph.edges.length} transitions across {incident.cameras.length} cameras.
        </dd>
        <dt>Confidence</dt>
        <dd>{incident.confidence != null ? incident.confidence.toFixed(2) : "n/a"}</dd>
        <dt>Evidence</dt>
        <dd>{evidenceCount} clip/snapshot references (traceable to source)</dd>
      </dl>

      <CrossCameraTimeline timeline={incident.timeline} />

      <p className="review-note">
        Decision support only — requires human review. No automated verdict is issued.
      </p>
      <div className="actions">
        <button className="confirm" onClick={() => onFeedback("confirm")}>
          Confirm
        </button>
        <button className="dismiss" onClick={() => onFeedback("dismiss")}>
          Dismiss
        </button>
      </div>
    </div>
  );
}
