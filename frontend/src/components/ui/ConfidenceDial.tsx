import { clamp01 } from "../../lib/format";

const BAND_COLOR: Record<string, string> = {
  high: "#43e0a0",
  medium: "#f2b33d",
  low: "#ff9e64",
  unknown: "#71809a",
};

/**
 * Instrument-style confidence dial: 270° arc with tick marks, value in the
 * center. Reads as a gauge, not a verdict — paired with the band word.
 */
export function ConfidenceDial({
  confidence,
  band,
}: {
  confidence: number | null | undefined;
  band: string | null | undefined;
}) {
  const v = clamp01(confidence);
  const color = BAND_COLOR[band ?? "unknown"] ?? BAND_COLOR.unknown;
  const r = 34;
  // 270° sweep starting at 135° (bottom-left), like a gauge.
  const circumference = 2 * Math.PI * r;
  const sweep = circumference * 0.75;
  const filled = sweep * v;

  return (
    <div>
      <div className="dial" role="img" aria-label={`Confidence ${v.toFixed(2)}, band ${band ?? "unknown"}`}>
        <svg viewBox="0 0 88 88">
          {/* tick marks */}
          {Array.from({ length: 19 }, (_, i) => {
            const a = 135 + (i * 270) / 18;
            const rad = (a * Math.PI) / 180;
            const inner = i % 3 === 0 ? 40.5 : 42.5;
            const x1 = 44 + inner * Math.sin(rad);
            const y1 = 44 - inner * Math.cos(rad);
            const x2 = 44 + 44.8 * Math.sin(rad);
            const y2 = 44 - 44.8 * Math.cos(rad);
            return (
              <line
                key={i}
                x1={x1}
                y1={y1}
                x2={x2}
                y2={y2}
                stroke={i % 3 === 0 ? "#2b3a55" : "#1b2434"}
                strokeWidth={1}
              />
            );
          })}
          {/* track + value arc */}
          <circle
            cx="44"
            cy="44"
            r={r}
            fill="none"
            stroke="#16202f"
            strokeWidth="6"
            strokeLinecap="round"
            strokeDasharray={`${sweep} ${circumference}`}
            transform="rotate(135 44 44)"
          />
          <circle
            cx="44"
            cy="44"
            r={r}
            fill="none"
            stroke={color}
            strokeWidth="6"
            strokeLinecap="round"
            strokeDasharray={`${filled} ${circumference}`}
            transform="rotate(135 44 44)"
            style={{
              filter: `drop-shadow(0 0 5px ${color}66)`,
              transition: "stroke-dasharray 500ms cubic-bezier(0.22,1,0.36,1)",
            }}
          />
        </svg>
        <div className="dial-label">
          <span className="dial-value" style={{ color }}>
            {confidence == null ? "n/a" : v.toFixed(2)}
          </span>
          <span className="dial-band">{band ?? "unknown"}</span>
        </div>
      </div>
      <div className="dial-caption">
        confidence
        <br />
        min(corr, behaviour)
      </div>
    </div>
  );
}
