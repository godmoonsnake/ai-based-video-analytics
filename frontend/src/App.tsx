import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "./services/api";
import { useAsync } from "./hooks/useAsync";
import { usePolling } from "./hooks/usePolling";
import { useHotkeys } from "./hooks/useHotkeys";
import { IncidentFeed } from "./components/feed/IncidentFeed";
import { IncidentDetail } from "./components/detail/IncidentDetail";
import { CameraHealthSummary } from "./components/app/CameraHealth";
import { Rail, Topbar, AboutModal, HelpModal } from "./components/app/Chrome";
import { ToastProvider } from "./components/ui/Toasts";
import { IconAperture } from "./components/icons";
import type { HealthStatus } from "./types/system";
import { useAuth } from "./services/auth";
import { GuardDesk } from "./components/app/GuardDesk";

/**
 * Unified incident dashboard backed by the existing operator APIs.
 */
export default function App() {
  const [supervisor, setSupervisor] = useState(false);
  const auth = useAuth();
  const role = auth.identity?.role ?? "supervisor";
  const taskRole = ["supervisor", "operator", "responder"].includes(role);
  return supervisor || !taskRole ? <><div className="guard-return"><button onClick={() => setSupervisor(false)}>← Guard desk</button></div><SupervisorConsole /></> :
    <GuardDesk onOpenSupervisor={() => setSupervisor(true)} />;
}

function SupervisorConsole() {
  const auth = useAuth();
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [live, setLive] = useState(true);
  const [refreshKey, setRefreshKey] = useState(0);
  const [aboutOpen, setAboutOpen] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);
  const [visibleIds, setVisibleIds] = useState<number[]>([]);
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [overview, setOverview] = useState<Awaited<ReturnType<typeof api.getOperationsOverview>> | null>(null);
  const [caseDemoBusy, setCaseDemoBusy] = useState(false);
  const [caseDemoError, setCaseDemoError] = useState<string | null>(null);

  const incidents = useAsync(() => api.listIncidents(), [refreshKey]);
  usePolling(() => incidents.reload(), 5000, live);

  const reloadHealth = useCallback(() => {
    api
      .getHealth()
      .then(setHealth)
      .catch(() => setHealth({ status: "unreachable", database: false }));
  }, []);
  useEffect(() => reloadHealth(), [reloadHealth]);
  usePolling(reloadHealth, 15000, true);
  const reloadOverview = useCallback(() => { api.getOperationsOverview().then(setOverview).catch(() => setOverview(null)); }, []);
  useEffect(() => reloadOverview(), [reloadOverview]);
  usePolling(reloadOverview, 15000, true);

  const select = useCallback((id: number) => {
    setSelectedId(id);
  }, []);
  const role = auth.identity?.role ?? "supervisor";
  const parkingReviews = (incidents.data ?? []).filter((item) =>
    item.status === "open" && item.summary_text?.startsWith("Yellow review: person appearance differs"));

  // The local review should open with useful cases; production has no demo endpoint.
  useEffect(() => {
    api.getReviewManifest().then(async (current) => {
      if (!current.ready) {
        await api.replayReview();
        setRefreshKey((key) => key + 1);
        reloadOverview();
      }
    }).catch(() => undefined);
  }, [reloadOverview]);

  useEffect(() => {
    if (selectedId == null && incidents.data?.length) {
      const first = [...incidents.data].sort((a, b) => (b.start_time ?? 0) - (a.start_time ?? 0))[0];
      if (first) select(first.id);
    }
  }, [incidents.data, selectedId, select]);

  const move = useCallback(
    (dir: 1 | -1) => {
      if (visibleIds.length === 0) return;
      const idx = selectedId == null ? -1 : visibleIds.indexOf(selectedId);
      if (idx === -1) {
        select(visibleIds[0]);
        return;
      }
      const next = Math.min(visibleIds.length - 1, Math.max(0, idx + dir));
      if (visibleIds[next] !== selectedId) select(visibleIds[next]);
    },
    [visibleIds, selectedId, select],
  );

  const focusSearch = useCallback(() => {
    const el = document.querySelector<HTMLInputElement>('input[data-testid="feed-search"]');
    el?.focus();
    el?.select();
  }, []);

  const hotkeys = useMemo(
    () => [
      { key: "j", handler: () => move(1) },
      { key: "arrowdown", handler: (e: KeyboardEvent) => { e.preventDefault(); move(1); } },
      { key: "k", handler: () => move(-1) },
      { key: "arrowup", handler: (e: KeyboardEvent) => { e.preventDefault(); move(-1); } },
      { key: "/", handler: (e: KeyboardEvent) => { e.preventDefault(); focusSearch(); } },
      { key: "?", handler: () => setHelpOpen((v) => !v) },
    ],
    [move, focusSearch],
  );
  useHotkeys(hotkeys);

  return (
    <ToastProvider>
      <div className="shell">
        <Rail onAbout={() => setAboutOpen(true)} onHelp={() => setHelpOpen(true)} health={health} />
        <Topbar live={live} onToggleLive={() => setLive((v) => !v)} health={health}
          identity={auth.identity} onLogout={auth.enabled ? () => void auth.logout() : undefined} />

        <div className="main console-mode">
          <div className="dashboard-heading"><div><span>DARSON / SUPERVISOR REVIEW</span><h1>Dashboard</h1></div><span>Last updated {overview?.checked_at ? new Date(overview.checked_at * 1000).toLocaleTimeString() : "—"}</span></div>
          {overview?.demo_mode && <div style={{ padding: "0 0 14px" }}>
            <button type="button" disabled={caseDemoBusy} onClick={async () => {
              setCaseDemoBusy(true);
              setCaseDemoError(null);
              try {
                const result = await api.loadCaseStudyDemo();
                const first = result.observations.find((item) => item.incident_id != null);
                if (first?.incident_id != null) setSelectedId(first.incident_id);
                setRefreshKey((key) => key + 1);
                reloadOverview();
              } catch (error) {
                setCaseDemoError(error instanceof Error ? error.message : "Could not load case studies");
              } finally {
                setCaseDemoBusy(false);
              }
            }}>{caseDemoBusy ? "Loading case studies…" : "Load six case study examples"}</button>
            {caseDemoError && <span role="alert" style={{ marginLeft: 12 }}>{caseDemoError}</span>}
          </div>}
          <section className="system-strip" aria-label="System status">
            <span>System <b>{health?.status === "ok" ? "Operational" : "Unavailable"}</b></span>
            <span>Database <b>{health?.database ? "Connected" : "Disconnected"}</b></span>
            <span>Video sources <b>{overview?.source_count ? `${overview.source_count} configured` : "None connected"}</b></span>
            <span>Evidence <b>{overview?.pending_evidence ? `${overview.pending_evidence} pending` : "No pending capture"}</b></span>
          </section>
          <section className="ops-overview" aria-label="Operations summary">
            <span>Active incidents <b>{overview?.active_incidents ?? "—"}</b></span>
            <span>Unassigned <b>{overview?.unassigned_incidents ?? "—"}</b></span>
            <span>High priority <b>{incidents.data?.filter((item) => ["high", "critical"].includes(item.priority ?? "")).length ?? "—"}</b></span>
            <span>Cameras offline <b>{overview?.camera_offline ?? "—"}</b></span>
            <span>Evidence pending <b>{overview?.pending_evidence ?? "—"}</b></span>
            <span>SLA breaches <b>{overview?.open_sla_breaches ?? "—"}</b></span>
          </section>
          {parkingReviews.length > 0 && <section className="parking-risk-monitor" aria-label="Parking risk monitor">
            <h2>Parking risk monitor · yellow review</h2>
            <p>Appearance differed from this vehicle visit’s exit tracks. Identity and authorization are unverified.</p>
            {parkingReviews.map((item) => <button type="button" key={item.id} onClick={() => select(item.id)}>
              Review case #{item.id} · {item.cameras.join(", ") || "parking camera"}
            </button>)}
          </section>}
          <CameraHealthSummary />
          <IncidentFeed
            incidents={incidents.data}
            loading={incidents.loading}
            error={incidents.error}
            reload={() => setRefreshKey((k) => k + 1)}
            selectedId={selectedId}
            onSelect={select}
            onVisibleChange={setVisibleIds}
          />

          {selectedId == null ? (
            <NoSelection />
          ) : (
            <IncidentDetail
              key={selectedId}
              incidentId={selectedId}
              tab="case"
              onTabChange={() => undefined}
              onChanged={() => setRefreshKey((k) => k + 1)}
              role={role}
              actor={auth.identity?.subject ?? "development-operator"}
            />
          )}
        </div>
      </div>

      {aboutOpen && <AboutModal onClose={() => setAboutOpen(false)} />}
      {helpOpen && <HelpModal onClose={() => setHelpOpen(false)} />}
    </ToastProvider>
  );
}

/** Empty-detail placeholder: the console at rest. */
function NoSelection() {
  return (
    <div className="placeholder">
      <div className="mark">
        <IconAperture />
      </div>
      <h2>Console ready</h2>
      <p className="state-sub" style={{ maxWidth: 420 }}>
        Select an incident from the feed to open its dossier — explainable reasons, movement
        timeline, evidence graph and the full audit trail.
      </p>
      <div className="hint-list">
        <span className="r">
          <span className="kbd">J</span>
          <span className="kbd">K</span> move through the feed
        </span>
        <span className="r">
          <span className="kbd">/</span> search · <span className="kbd">?</span> all shortcuts
        </span>
      </div>
    </div>
  );
}
