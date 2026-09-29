import { useState } from "react";
import type { IncidentEvent } from "../../types/incident";

interface Props {
  events: IncidentEvent[];
}

/**
 * Evidence panel. Renders ONLY evidence the backend actually references:
 *   - a snapshot image when evidence_ref.snapshot_url exists,
 *   - a video player when evidence_ref.clip_url exists.
 * Each item is labelled with its originating event id + camera. Broken images
 * (e.g. the synthetic dev Frigate has no reachable media) degrade to a clear
 * "reference unavailable" note rather than fabricating media.
 */
export function Evidence({ events }: Props) {
  const withEvidence = events.filter(
    (e) => e.evidence_ref?.snapshot_url || e.evidence_ref?.clip_url,
  );

  if (withEvidence.length === 0) {
    return <div className="state state-empty">No evidence references for this incident.</div>;
  }

  return (
    <div className="evidence-grid">
      {withEvidence.map((e) => (
        <EvidenceCard key={e.event_id} event={e} />
      ))}
    </div>
  );
}

function EvidenceCard({ event }: { event: IncidentEvent }) {
  const snap = event.evidence_ref?.snapshot_url ?? null;
  const clip = event.evidence_ref?.clip_url ?? null;
  const [snapFailed, setSnapFailed] = useState(false);

  return (
    <figure className="evidence-card" data-testid="evidence-card">
      <div className="evidence-media">
        {clip ? (
          <video controls preload="none" className="evidence-video" data-testid="evidence-video">
            <source src={clip} type="video/mp4" />
            Clip reference: {clip}
          </video>
        ) : snap && !snapFailed ? (
          <img
            src={snap}
            alt={`snapshot for event ${event.event_id}`}
            className="evidence-img"
            data-testid="evidence-img"
            onError={() => setSnapFailed(true)}
          />
        ) : (
          <div className="evidence-unavailable" data-testid="evidence-unavailable">
            Reference unavailable in this environment
            <code>{snap ?? clip}</code>
          </div>
        )}
      </div>
      <figcaption className="evidence-caption">
        <span className="evidence-event">event {event.event_id}</span>
        <span className="evidence-cam">
          {event.camera_id ?? "—"} · {event.event_type ?? "event"}
        </span>
      </figcaption>
    </figure>
  );
}
