/** Labeled horizontal meter for sub-scores. tone: mint | amber | violet | blue */
export function Meter({
  label,
  value,
  tone = "mint",
  digits = 2,
}: {
  label: string;
  value: number | null | undefined;
  tone?: "mint" | "amber" | "violet" | "blue";
  digits?: number;
}) {
  const v = value == null ? null : Math.min(1, Math.max(0, value));
  return (
    <div className={`meter ${tone}`} title={`${label}: ${v == null ? "n/a" : v.toFixed(digits)}`}>
      <span className="k">{label}</span>
      <span className="track">
        <span className="fill" style={{ width: v == null ? 0 : `${v * 100}%` }} />
      </span>
      <span className="n">{v == null ? "n/a" : v.toFixed(digits)}</span>
    </div>
  );
}
