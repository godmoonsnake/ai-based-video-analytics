import type { Pattern } from "../api";

export function PatternView({ patterns }: { patterns: Pattern[] }) {
  const byType = new Map<string, Pattern[]>();
  for (const p of patterns) {
    const arr = byType.get(p.pattern_type) ?? [];
    arr.push(p);
    byType.set(p.pattern_type, arr);
  }
  return (
    <div>
      <h2>Historical Patterns</h2>
      {patterns.length === 0 && <p className="muted">No patterns mined yet.</p>}
      {[...byType.entries()].map(([type, rows]) => (
        <div key={type} className="pattern-group">
          <h4>{type}</h4>
          <ul>
            {rows.slice(0, 5).map((p) => (
              <li key={p.id}>
                <code>{JSON.stringify(p.key)}</code> · count {p.count}
                {p.score != null && ` · score ${p.score}`}
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}
