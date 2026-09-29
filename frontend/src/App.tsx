import { useState } from "react";
import { api } from "./services/api";
import { IncidentListPage } from "./pages/IncidentListPage";
import { IncidentDetailPage } from "./pages/IncidentDetailPage";

/**
 * DARSON operator investigation dashboard.
 *
 * Master–detail workflow over the read-only v1 incident API:
 *   incident list → open incident → why / timeline / correlations / graph /
 *   evidence → operator lifecycle review.
 * The frontend consumes only the backend HTTP API (no DB, no Frigate creds).
 */
export default function App() {
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  const bumpList = () => setRefreshKey((k) => k + 1);

  return (
    <div className="op-app">
      <header className="op-header">
        <div>
          <h1>DARSON — Incident Investigation</h1>
          <span className="op-sub">
            Observation → Correlation → Inference → Incident · human-in-the-loop review
          </span>
        </div>
        <span className="op-api" title="backend API base">
          API: {api.base}
        </span>
      </header>

      <div className="op-layout">
        <aside className="op-list" aria-label="Incident list">
          <IncidentListPage
            selectedId={selectedId}
            onSelect={setSelectedId}
            refreshKey={refreshKey}
          />
        </aside>
        <main className="op-detail">
          {selectedId == null ? (
            <div className="state state-empty op-placeholder">
              Select an incident to begin investigation.
            </div>
          ) : (
            <IncidentDetailPage
              key={selectedId}
              incidentId={selectedId}
              onStateChanged={bumpList}
            />
          )}
        </main>
      </div>
    </div>
  );
}
