import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api, type HistoricalPattern, type InvestigationResults } from "../../services/api";

export function InvestigationWorkspace({ onOpenCase, canMine }: { onOpenCase: (id: number) => void; canMine: boolean }) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<InvestigationResults | null>(null);
  const [patterns, setPatterns] = useState<HistoricalPattern[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const loadPatterns = useCallback(() => api.getPatterns().then(setPatterns).catch(() => setError("Historical patterns are unavailable.")), []);
  useEffect(() => { void loadPatterns(); }, [loadPatterns]);
  const search = async (event: FormEvent) => {
    event.preventDefault();
    if (!query.trim()) return;
    setBusy(true); setError("");
    try { setResults(await api.searchInvestigation(query.trim())); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Search failed."); }
    finally { setBusy(false); }
  };
  const mine = async () => {
    setBusy(true); setError("");
    try { await api.minePatterns(); await loadPatterns(); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Pattern refresh failed."); }
    finally { setBusy(false); }
  };
  return <div className="workspace-page">
    <header className="workspace-heading"><div><span className="review-kicker">INVESTIGATION</span><h1>Find the event. Understand the case.</h1><p>Search site observations and review historical patterns. All results remain signals for human assessment.</p></div></header>
    <section className="workspace-search"><form onSubmit={(event) => void search(event)}><label htmlFor="investigation-query">Search observations and cases</label><div><input id="investigation-query" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="e.g. restricted zone near Gate 3" /><button className="review-primary" disabled={busy || !query.trim()}>Search</button></div></form></section>
    {error && <p className="workspace-alert" role="alert">{error}</p>}
    {results && <section className="workspace-section"><div className="workspace-section-title"><h2>Search results</h2><span>{results.incidents.length} cases · {results.events.length} events</span></div>
      <p className="workspace-note">Human review required. Parsed filters: {Object.entries(results.parsed_filter).map(([key, value]) => `${key}: ${String(value)}`).join(" · ") || "no structured filter identified"}</p>
      <div className="workspace-list">{results.incidents.map((caseItem) => <button key={caseItem.id} onClick={() => onOpenCase(caseItem.id)}><b>CASE #{caseItem.id}</b><span>{caseItem.summary_text ?? "Incident under review"}</span><small>{caseItem.priority ?? "Unranked"} · {caseItem.status} →</small></button>)}</div>
      {results.incidents.length === 0 && <p className="workspace-empty">No cases matched this query.</p>}
      {results.events.length > 0 && <div className="workspace-event-list">{results.events.slice(0, 30).map((item) => <div key={item.event_id}><strong>{item.camera_id}</strong><span>{item.event_type} · {item.label ?? "unlabeled"}</span><small>{new Date(item.ts * 1000).toLocaleString()}</small><small>Media: {item.evidence.snapshot.status}</small></div>)}</div>}
      {results.events.length > 30 && <p className="workspace-note">Showing the first 30 event matches.</p>}
    </section>}
    <section className="workspace-section"><div className="workspace-section-title"><div><span className="review-kicker">HISTORICAL SIGNALS</span><h2>Patterns worth reviewing</h2></div>{canMine && <button className="btn" onClick={() => void mine()} disabled={busy}>Refresh patterns</button>}</div>
      {patterns.length === 0 ? <p className="workspace-empty">No patterns have been mined for this site yet. Patterns need enough observations to be useful.</p> : <div className="workspace-patterns">{patterns.slice(0, 12).map((item) => <article key={item.id}><span>{item.pattern_type.replace(/_/g, " ")}</span><b>{item.count} observations</b><p>{Object.entries(item.key).map(([key, value]) => `${key}: ${String(value)}`).join(" · ")}</p></article>)}</div>}
      <p className="workspace-note">Pattern counts reflect stored observations; they are not exposure-adjusted risk or proof of wrongdoing.</p>
    </section>
  </div>;
}
