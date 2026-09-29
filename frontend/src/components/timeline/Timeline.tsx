import type { TimelineStep } from "../../types/incident";
import { fmtClock } from "../../lib/format";

interface Props {
  steps: TimelineStep[];
}

/**
 * Chronological timeline derived from incident graph membership. Shows only
 * stored facts (timestamp, camera, zone, track, event type, evidence presence).
 * No narrative text is synthesized.
 */
export function Timeline({ steps }: Props) {
  return (
    <ol className="timeline" aria-label="Incident timeline">
      {steps.map((s) => {
        const hasEvidence = Boolean(s.evidence?.snapshot_url || s.evidence?.clip_url);
        return (
          <li key={s.event_id} className="tl-item" data-testid="timeline-step">
            <time className="tl-time">{fmtClock(s.ts)}</time>
            <div className="tl-body">
              <div className="tl-line">
                <span className="tl-camera">{s.camera_id ?? "—"}</span>
                <span className="tl-event">{s.event_type ?? "event"}</span>
                {s.track_local_id && <span className="tl-track">track {s.track_local_id}</span>}
              </div>
              <div className="tl-meta">
                {s.zones && s.zones.length > 0 && (
                  <span className="tl-zone">
                    zone: {s.zones.join(", ")}
                    {s.zone_kinds && s.zone_kinds.length > 0 && ` (${s.zone_kinds.join(", ")})`}
                  </span>
                )}
                <span className={`tl-evidence ${hasEvidence ? "has" : "none"}`}>
                  {hasEvidence ? "evidence available" : "no evidence"}
                </span>
                <span className="tl-eid" title="source event id">
                  {s.event_id}
                </span>
              </div>
            </div>
          </li>
        );
      })}
    </ol>
  );
}
