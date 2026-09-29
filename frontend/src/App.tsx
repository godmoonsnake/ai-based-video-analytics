import { useCallback, useEffect, useState } from "react";
import {
  api,
  type Camera,
  type GlobalTrack,
  type IncidentDetail,
  type IncidentSummary,
  type Pattern,
} from "./api";
import { IncidentFeed } from "./components/IncidentFeed";
import { ExplainableIncidentCard } from "./components/ExplainableIncidentCard";
import { TopologyMap } from "./components/TopologyMap";
import { PatternView } from "./components/PatternView";
import { InvestigationSearch } from "./components/InvestigationSearch";

export default function App() {
  const [incidents, setIncidents] = useState<IncidentSummary[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [detail, setDetail] = useState<IncidentDetail | null>(null);
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [patterns, setPatterns] = useState<Pattern[]>([]);
  const [globalTracks, setGlobalTracks] = useState<GlobalTrack[]>([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setErr(null);
    try {
      const [inc, cams, pats, gts] = await Promise.all([
        api.incidents(),
        api.cameras(),
        api.patterns(),
        api.globalTracks(),
      ]);
      setIncidents(inc);
      setCameras(cams);
      setPatterns(pats);
      setGlobalTracks(gts);
    } catch (e) {
      setErr(String(e));
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  useEffect(() => {
    if (selectedId == null) {
      setDetail(null);
      return;
    }
    api.incident(selectedId).then(setDetail).catch((e) => setErr(String(e)));
  }, [selectedId]);

  async function runPipeline() {
    setBusy(true);
    setErr(null);
    try {
      await api.ingestMock();
      await api.correlate();
      await api.buildIncidents();
      await api.minePatterns();
      await refresh();
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function onFeedback(action: "confirm" | "dismiss") {
    if (selectedId == null) return;
    await api.feedback(selectedId, action);
    await refresh();
    setDetail(await api.incident(selectedId));
  }

  // Track path for the topology map = cameras of the selected incident.
  const selectedPath = detail?.cameras ?? [];

  return (
    <div className="app">
      <header>
        <h1>DARSON Intelligence Layer</h1>
        <span className="tag">EVENT → CONTEXT → CORRELATION → INCIDENT → HISTORY → INVESTIGATION</span>
        <button onClick={runPipeline} disabled={busy}>
          {busy ? "Running…" : "Run demo pipeline"}
        </button>
      </header>

      {err && <p className="error">API error: {err} (is the backend running at {api.base}?)</p>}

      <div className="layout">
        <aside>
          <IncidentFeed incidents={incidents} selectedId={selectedId} onSelect={setSelectedId} />
          <TopologyMap cameras={cameras} path={selectedPath} />
        </aside>
        <main>
          {detail ? (
            <ExplainableIncidentCard incident={detail} onFeedback={onFeedback} />
          ) : (
            <p className="muted">Select an incident to see its explainable card and timeline.</p>
          )}
          <InvestigationSearch />
          <PatternView patterns={patterns} />
          <section>
            <h2>Global Tracks (cross-camera)</h2>
            {globalTracks.length === 0 && <p className="muted">None yet.</p>}
            <ul>
              {globalTracks
                .filter((g) => g.members.length > 1)
                .map((g) => (
                  <li key={g.global_track_id}>
                    #{g.global_track_id}: {g.members.map((m) => m.camera_id).join(" → ")}
                    {g.confidence != null && ` (conf ${g.confidence})`}
                  </li>
                ))}
            </ul>
          </section>
        </main>
      </div>
    </div>
  );
}
