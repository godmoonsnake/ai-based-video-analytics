import type { TimelineStep } from "../api";

export function CrossCameraTimeline({ timeline }: { timeline: TimelineStep[] }) {
  if (!timeline.length) return null;
  const t0 = timeline[0].ts;
  return (
    <div>
      <h3>Cross-Camera Timeline</h3>
      <ol className="timeline">
        {timeline.map((s) => (
          <li key={s.event_id} className={`tl-step role-${s.role ?? "context"}`}>
            <div className="tl-cam">{s.camera_id}</div>
            <div className="tl-body">
              <span className="tl-type">{s.event_type}</span>
              {s.role && <span className="tl-role">{s.role}</span>}
              <span className="tl-offset">+{Math.round(s.ts - t0)}s</span>
              {s.zones.length > 0 && <span className="tl-zone">{s.zones.join(", ")}</span>}
              {s.evidence?.clip_url && (
                <a className="tl-evi" href={s.evidence.clip_url} target="_blank" rel="noreferrer">
                  clip
                </a>
              )}
              {s.evidence?.snapshot_url && (
                <a className="tl-evi" href={s.evidence.snapshot_url} target="_blank" rel="noreferrer">
                  snapshot
                </a>
              )}
            </div>
          </li>
        ))}
      </ol>
    </div>
  );
}
