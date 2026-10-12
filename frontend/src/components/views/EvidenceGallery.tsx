import type { TimelineStep } from "../../types/incident";
import { camLabel, fmtClock } from "../../lib/format";
import { IconCamera, IconImage, IconPlay } from "../icons";
import { ProtectedImage } from "../ui/ProtectedMedia";

interface Props {
  steps: TimelineStep[];
  onOpen: (index: number) => void;
}

/**
 * Evidence gallery: one viewfinder card per event. Frames draw corner
 * brackets; a missing payload renders an intentional hatch state rather than
 * a broken image. Cards open the lightbox.
 */
export function EvidenceGallery({ steps, onOpen }: Props) {
  return (
    <div>
      <div className="lanes-head">
        <span className="micro">Evidence</span>
        <span className="lanes-caption">
          {steps.length} frames · click to inspect · served through the same-origin proxy
        </span>
      </div>
      <div className="ev-grid">
        {steps.map((s, i) => (
          <EvidenceCard key={s.event_id} step={s} index={i} onOpen={onOpen} />
        ))}
      </div>
    </div>
  );
}

function EvidenceCard({
  step,
  index,
  onOpen,
}: {
  step: TimelineStep;
  index: number;
  onOpen: (index: number) => void;
}) {
  const snap = step.evidence.snapshot_url;
  const restricted = step.zone_kinds.includes("restricted");

  return (
    <button className="ev-card" data-testid="evidence-card" onClick={() => onOpen(index)}>
      <span className="ev-frame">
        <ProtectedImage src={snap} alt={`${step.event_type ?? "event"} frame from ${camLabel(step.camera_id)}`} fallback={
          <span className="ev-unavailable" data-testid="evidence-unavailable"><IconImage />Evidence unavailable · no stored snapshot for this event</span>} />
      </span>
      <span className="ev-meta">
        <span className="ev-cam">
          <IconCamera style={{ display: "inline", width: 11, height: 11, marginRight: 5 }} />
          {camLabel(step.camera_id)}
        </span>
        <span className="ev-sub">
          <span>{step.event_type ?? "event"}</span>
          <span className={restricted ? "zt" : ""}>{step.zones.join(", ") || "—"}</span>
          <span>{fmtClock(step.ts)}</span>
          {step.evidence.media_origin === "synthetic" && <span>synthetic replay</span>}
          {step.evidence.snapshot_status === "unavailable" && <span>snapshot unavailable</span>}
          {step.evidence.clip_url && (
            <span className="play">
              <IconPlay /> clip
            </span>
          )}
        </span>
      </span>
    </button>
  );
}
