import { useMemo } from "react";
import type { TimelineStep } from "../../types/incident";
import { camLabel, fmtClock, fmtSeconds } from "../../lib/format";
import { IconCamera, IconFilm, IconImage } from "../icons";

const LANE_H = 86;
const LABEL_W = 168;

interface Props {
  steps: TimelineStep[];
  onOpenStep: (step: TimelineStep) => void;
}

/**
 * Multi-lane timeline: one lane per camera (ordered by first appearance),
 * events positioned by wall-clock, stitched by the sequence overlay.
 * Reads like a multi-track recorder for the incident's movement.
 */
export function TimelineLanes({ steps, onOpenStep }: Props) {
  const model = useMemo(() => {
    const sorted = [...steps].sort((a, b) => (a.ts ?? 0) - (b.ts ?? 0));
    const cams: string[] = [];
    for (const s of sorted) {
      const c = s.camera_id ?? "unknown";
      if (!cams.includes(c)) cams.push(c);
    }
    const t0 = sorted[0]?.ts ?? 0;
    const t1 = sorted[sorted.length - 1]?.ts ?? t0 + 1;
    const pad = Math.max(1.5, (t1 - t0) * 0.06);
    const lo = t0 - pad;
    const hi = t1 + pad;
    const xPct = (ts: number | null) =>
      ts == null ? 50 : Math.min(97, Math.max(3, ((ts - lo) / (hi - lo)) * 100));

    const lanes = cams.map((cam) => ({
      camera: cam,
      nodes: sorted
        .filter((s) => (s.camera_id ?? "unknown") === cam)
        .map((s) => ({ step: s, x: xPct(s.ts) })),
    }));

    // sequence path across lanes in strict time order
    const seq = sorted.map((s) => ({
      x: xPct(s.ts),
      lane: cams.indexOf(s.camera_id ?? "unknown"),
    }));
    const gaps = seq.slice(1).map((pt, i) => ({
      x: (seq[i].x + pt.x) / 2,
      lane: seq[i].lane,
      dt: (sorted[i + 1].ts ?? 0) - (sorted[i].ts ?? 0),
    }));

    // axis ticks: ~6 even ticks
    const ticks = Array.from({ length: 6 }, (_, i) => ({
      x: 4 + (i * 92) / 5,
      ts: lo + ((hi - lo) * i) / 5,
    }));

    return { lanes, seq, gaps, ticks, height: lanes.length * LANE_H };
  }, [steps]);

  if (steps.length === 0) {
    return <p className="state-sub">No events on this incident's timeline.</p>;
  }

  return (
    <div className="lanes">
      <div className="lanes-head">
        <span className="micro">Movement timeline</span>
        <span className="lanes-caption">
          {model.lanes.length} cameras · {steps.length} events · sequence stitched in time order
        </span>
      </div>

      <div className="lanes-frame">
        {model.lanes.map((lane, laneIdx) => (
          <div className="lane" key={lane.camera}>
            <div className="lane-label">
              <span className="lane-cam">
                <IconCamera />
                {camLabel(lane.camera)}
              </span>
              <span className="lane-kind">
                {lane.nodes.length} event{lane.nodes.length === 1 ? "" : "s"}
              </span>
            </div>
            <div className="lane-track" style={{ height: LANE_H }}>
              {lane.nodes.map(({ step, x }) => (
                <button
                  key={step.event_id}
                  className={`tl-node${isHot(step) ? " hot" : ""}`}
                  data-testid="timeline-step"
                  data-event-type={step.event_type ?? "event"}
                  style={{ left: `${x}%` }}
                  onClick={() => onOpenStep(step)}
                  title={`${step.event_type ?? "event"} · ${fmtClock(step.ts)} · ${step.zones.join(", ") || "—"}`}
                >
                  <span className="tl-tag">
                    {step.event_type ?? "event"} · {fmtClock(step.ts)}
                  </span>
                  <span className="tl-thumb">
                    {step.evidence.snapshot_url ? (
                      <img
                        src={step.evidence.snapshot_url}
                        alt={`${step.event_type ?? "event"} on ${camLabel(step.camera_id)}`}
                        loading="lazy"
                        onError={(e) => {
                          e.currentTarget.style.display = "none";
                        }}
                      />
                    ) : (
                      <span className="noimg">
                        <IconImage />
                      </span>
                    )}
                  </span>
                  <span className="tl-pip" />
                </button>
              ))}
              {/* gap chips */}
              {model.gaps
                .filter((g) => g.lane === laneIdx)
                .map((g, i) => (
                  <span
                    key={i}
                    className="lane-gap"
                    style={{
                      left: `calc(${LABEL_W}px + (100% - ${LABEL_W}px) * ${g.x / 100})`,
                    }}
                  >
                    +{fmtSeconds(g.dt)}
                  </span>
                ))}
            </div>
          </div>
        ))}

        {/* sequence overlay */}
        <svg
          className="lanes-seq"
          viewBox={`0 0 100 ${model.height}`}
          preserveAspectRatio="none"
          aria-hidden
          style={{ left: LABEL_W, width: `calc(100% - ${LABEL_W}px)` }}
        >
          {model.seq.slice(1).map((pt, i) => {
            const prev = model.seq[i];
            const dx = pt.x - prev.x;
            const y1 = prev.lane * LANE_H + LANE_H / 2;
            const y2 = pt.lane * LANE_H + LANE_H / 2;
            const d = `M ${prev.x} ${y1} C ${prev.x + dx * 0.45} ${y1}, ${pt.x - dx * 0.45} ${y2}, ${pt.x} ${y2}`;
            return (
              <path
                key={i}
                d={d}
                fill="none"
                stroke="#43e0a0"
                strokeWidth={1.6}
                strokeDasharray="5 5"
                vectorEffect="non-scaling-stroke"
                opacity={0.75}
                className="g-edge corr"
              />
            );
          })}
        </svg>

        <div className="lanes-axis">
          <div className="corner">
            <span className="micro-plain">local time</span>
          </div>
          <div className="axis-track">
            {model.ticks.map((t, i) => (
              <span key={i} className="axis-tick" style={{ left: `${t.x}%` }}>
                {fmtClock(t.ts)}
              </span>
            ))}
          </div>
        </div>
      </div>

      <p className="state-sub" style={{ marginTop: 10, textAlign: "left" }}>
        <IconFilm style={{ display: "inline", width: 11, height: 11, marginRight: 6 }} />
        Thumbnails show source evidence (snapshot). Select a node to inspect frame + clip. Hot
        (red) markers sit in restricted zones.
      </p>
    </div>
  );
}

function isHot(step: TimelineStep): boolean {
  return step.zone_kinds.some((k) => k === "restricted");
}
