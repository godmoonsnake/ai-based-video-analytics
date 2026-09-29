import { useState } from "react";
import { api, type SearchResponse } from "../api";

export function InvestigationSearch() {
  const [q, setQ] = useState("red bag near Gate 3 yesterday");
  const [res, setRes] = useState<SearchResponse | null>(null);
  const [err, setErr] = useState<string | null>(null);

  async function run() {
    setErr(null);
    try {
      setRes(await api.search({ q }));
    } catch (e) {
      setErr(String(e));
    }
  }

  return (
    <div>
      <h2>Investigation</h2>
      <div className="search-bar">
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder='e.g. "red bag near Gate 3 yesterday"'
        />
        <button onClick={run}>Search</button>
      </div>
      {err && <p className="error">{err}</p>}
      {res && (
        <div>
          <p className="muted">
            Parsed filter: <code>{JSON.stringify(res.parsed_filter)}</code>
          </p>
          <p className="review-note">
            Results are for human review — {res.events.length} events,{" "}
            {res.incidents.length} incidents.
          </p>
          <ul className="search-events">
            {res.events.map((e) => (
              <li key={e.event_id}>
                {e.camera_id} · {e.event_type} · {e.sub_label ?? e.label ?? "?"}
                {e.evidence?.clip_url && (
                  <a href={e.evidence.clip_url} target="_blank" rel="noreferrer">
                    {" "}clip
                  </a>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
