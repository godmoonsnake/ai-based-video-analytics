import { useEffect, useState } from "react";
import type { TimelineStep } from "../../types/incident";
import { camLabel, fmtClock, fmtTime } from "../../lib/format";
import { IconChevronLeft, IconChevronRight, IconPlay, IconX } from "../icons";
import { ProtectedImage, ProtectedOpenLink, ProtectedVideo } from "../ui/ProtectedMedia";

interface Props {
  steps: TimelineStep[];
  index: number;
  onClose: () => void;
  onIndex: (i: number) => void;
}

/**
 * Evidence lightbox: frame + metadata side panel. Keyboard: ←/→ navigate,
 * Esc closes. When a clip URL exists the operator can switch to playback;
 * a missing clip renders an intentional unavailable state.
 */
export function Lightbox({ steps, index, onClose, onIndex }: Props) {
  const [mode, setMode] = useState<"frame" | "clip">("frame");
  const [clipFailed, setClipFailed] = useState(false);
  const step = steps[index];

  useEffect(() => {
    setMode("frame");
    setClipFailed(false);
  }, [index]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      if (e.key === "ArrowRight") onIndex((index + 1) % steps.length);
      if (e.key === "ArrowLeft") onIndex((index - 1 + steps.length) % steps.length);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [index, steps.length, onClose, onIndex]);

  if (!step) return null;
  const ev = step.evidence;
  const restricted = step.zone_kinds.includes("restricted");

  return (
    <div className="lightbox" data-testid="lightbox" onClick={onClose}>
      <button className="icon-btn lb-close" onClick={onClose} aria-label="Close lightbox">
        <IconX />
      </button>

      <div className="lb-body" onClick={(e) => e.stopPropagation()}>
        <div className="lb-media">
          {mode === "clip" && ev.clip_url ? (
            clipFailed ? (
              <span className="ev-unavailable" style={{ position: "relative", width: "100%", height: "100%" }}>
                clip unavailable at source
              </span>
            ) : (
              <ProtectedVideo src={ev.clip_url} onError={() => setClipFailed(true)} fallback={<span className="ev-unavailable">clip unavailable in DARSON evidence vault</span>} />
            )
          ) : ev.snapshot_url ? (
            <ProtectedImage src={ev.snapshot_url} alt={`${step.event_type ?? "event"} — ${camLabel(step.camera_id)}`} fallback={<span className="ev-unavailable">snapshot unavailable in DARSON evidence vault</span>} />
          ) : (
            <span className="ev-unavailable" style={{ position: "relative", width: "100%", height: "100%" }}>
              no evidence payload
            </span>
          )}
        </div>

        <aside className="lb-side">
          <div className="lb-count">
            EVIDENCE {index + 1} / {steps.length}
          </div>
          <div className="lb-title">
            {camLabel(step.camera_id)} · {step.event_type ?? "event"}
          </div>

          <div className="lb-kv">
            <span className="k">Event ID</span>
            <span className="v">{step.event_id}</span>
            <span className="k">Track</span>
            <span className="v">{step.track_local_id ?? "—"}</span>
            <span className="k">Clock</span>
            <span className="v">{fmtClock(step.ts)}</span>
            <span className="k">Full time</span>
            <span className="v">{fmtTime(step.ts)}</span>
            <span className="k">Zone</span>
            <span className="v" style={restricted ? { color: "var(--red)" } : undefined}>
              {step.zones.join(", ") || "—"}
            </span>
            <span className="k">Zone kind</span>
            <span className="v">{step.zone_kinds.join(", ") || "—"}</span>
          </div>

          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            {ev.clip_url && mode === "frame" && (
              <button className="btn btn-accent btn-sm" onClick={() => setMode("clip")}>
                <IconPlay /> Watch clip
              </button>
            )}
            {mode === "clip" && (
              <button className="btn btn-sm" onClick={() => setMode("frame")}>
                Show frame
              </button>
            )}
            {ev.snapshot_url && (
              <ProtectedOpenLink src={ev.snapshot_url}>
                Open snapshot
              </ProtectedOpenLink>
            )}
            {ev.clip_url && (
              <ProtectedOpenLink src={ev.clip_url}>
                Open clip
              </ProtectedOpenLink>
            )}
          </div>

          <div style={{ marginTop: "auto", display: "flex", justifyContent: "space-between" }}>
            <button
              className="icon-btn"
              onClick={() => onIndex((index - 1 + steps.length) % steps.length)}
              aria-label="Previous evidence"
            >
              <IconChevronLeft />
            </button>
            <button
              className="icon-btn"
              onClick={() => onIndex((index + 1) % steps.length)}
              aria-label="Next evidence"
            >
              <IconChevronRight />
            </button>
          </div>
        </aside>
      </div>

      <button
        className="lb-nav prev"
        onClick={(e) => {
          e.stopPropagation();
          onIndex((index - 1 + steps.length) % steps.length);
        }}
        aria-label="Previous evidence"
      >
        <IconChevronLeft />
      </button>
      <button
        className="lb-nav next"
        onClick={(e) => {
          e.stopPropagation();
          onIndex((index + 1) % steps.length);
        }}
        aria-label="Next evidence"
      >
        <IconChevronRight />
      </button>
    </div>
  );
}
