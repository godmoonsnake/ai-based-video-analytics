import { useEffect, useState } from "react";
import type { TimelineStep } from "../../types/incident";
import { useIncidentBundle } from "../../hooks/useIncidentBundle";
import { fmtClock, fmtDate, fmtDuration } from "../../lib/format";
import { PriorityChip, StateBadge, BandPill } from "../ui/Badges";
import { ConfidenceDial } from "../ui/ConfidenceDial";
import { ErrorPanel, LoadingBlock } from "../ui/States";
import { LifecycleBar } from "./LifecycleBar";
import { CaseFile } from "./CaseFile";
import { TimelineLanes } from "../views/TimelineLanes";
import { EvidenceGraphView } from "../views/EvidenceGraphView";
import { SiteMapView } from "../views/SiteMapView";
import { EvidenceGallery } from "../views/EvidenceGallery";
import { Lightbox } from "../views/Lightbox";
import { AuditTrail } from "../views/AuditTrail";
import { ResponsePanel } from "./ResponsePanel";
import { api } from "../../services/api";

export type DetailTab = "case" | "timeline" | "graph" | "map" | "evidence" | "audit";

export const TAB_ORDER: DetailTab[] = ["case", "timeline", "graph", "map", "evidence", "audit"];

interface Props {
  incidentId: number;
  tab: DetailTab;
  onTabChange: (t: DetailTab) => void;
  onChanged: () => void; // notify list refresh after lifecycle change
  role?: string;
  actor?: string;
}

export function IncidentDetail({ incidentId, onChanged, role = "operator", actor = "" }: Props) {
  const bundle = useIncidentBundle(incidentId);
  const [lbIndex, setLbIndex] = useState<number | null>(null);
  const [exportMessage, setExportMessage] = useState("");
  const detail = bundle.detail;

  // close lightbox when switching incidents
  useEffect(() => setLbIndex(null), [incidentId]);

  if (bundle.error) {
    return (
      <div className="detail">
        <ErrorPanel error={bundle.error} onRetry={bundle.reload} />
      </div>
    );
  }
  if (!detail) {
    return (
      <div className="detail">
        <LoadingBlock label="Loading incident" />
      </div>
    );
  }

  const steps = bundle.timeline?.timeline ?? [];

  const openEvidence = (step: TimelineStep) => {
    const idx = steps.findIndex((s) => s.event_id === step.event_id);
    setLbIndex(idx >= 0 ? idx : 0);
  };

  const requestExport = async (format: "pdf" | "zip") => {
    setExportMessage(`Preparing ${format.toUpperCase()}…`);
    try {
      const job = await api.createExport(detail.id, format, detail.version ?? 1);
      for (let attempt = 0; attempt < 60; attempt += 1) {
        const status = await api.getExport(job.id);
        if (status.status === "ready" && status.download_url) {
          await api.downloadExport(status.download_url, format);
          setExportMessage(`${format.toUpperCase()} ready; download started.`);
          return;
        }
        if (["failed", "integrity-failed"].includes(status.status)) throw new Error(status.failure_class ?? status.status);
        await new Promise((resolve) => window.setTimeout(resolve, 1000));
      }
      setExportMessage("Export is still processing. Check again from the case export status.");
    } catch (error) { setExportMessage(error instanceof Error ? error.message : String(error)); }
  };

  const downloadSimple = async (format: "json" | "csv") => {
    setExportMessage(`Downloading ${format.toUpperCase()}…`);
    try { await api.downloadIncident(detail.id, format); setExportMessage(`${format.toUpperCase()} downloaded.`); }
    catch (error) { setExportMessage(error instanceof Error ? error.message : String(error)); }
  };

  return (
    <div className="detail" data-testid="incident-detail">
      <section className="hero">
        <div className="hero-top">
          <div style={{ minWidth: 0 }}>
            <div className="hero-eyebrow">
              <span className="micro-plain">Incident details</span>
            </div>
            <div className="hero-id-row">
              <span className="hero-id">#{detail.id}</span>
              <PriorityChip priority={detail.priority} />
              <StateBadge state={detail.state} />
              <BandPill band={detail.confidence_band} confidence={detail.confidence} />
            </div>
            <p className="hero-summary">{detail.summary_text ?? "No summary provided."}</p>
          </div>

          <div className="hero-right">
            <div className="hero-stats">
              <div className="stat">
                <div className="k">Window</div>
                <div className="v">
                  {fmtClock(detail.start_time)} <small>→ {fmtClock(detail.end_time)}</small>
                </div>
              </div>
              <div className="stat">
                <div className="k">Duration</div>
                <div className="v">{fmtDuration(detail.start_time, detail.end_time)}</div>
              </div>
              <div className="stat">
                <div className="k">Cameras</div>
                <div className="v">{detail.cameras.length}</div>
              </div>
              <div className="stat">
                <div className="k">Tracks</div>
                <div className="v">{detail.tracks.length}</div>
              </div>
              <div className="stat">
                <div className="k">Events</div>
                <div className="v">{detail.events.length}</div>
              </div>
              <div className="stat">
                <div className="k">Date</div>
                <div className="v" style={{ fontSize: 11 }}>
                  {fmtDate(detail.start_time)}
                </div>
              </div>
              <div className="stat"><div className="k">Site</div><div className="v">{detail.site_id ?? "—"}</div></div>
            </div>
            <ConfidenceDial confidence={detail.confidence} band={detail.confidence_band} />
          </div>
        </div>

        <div className="hero-actions">
          <button className="button" onClick={() => void downloadSimple("json")}>Export case JSON</button>
          <button className="button" onClick={() => void downloadSimple("csv")}>Export event CSV</button>
          <button className="button" onClick={() => void requestExport("pdf")}>Generate PDF</button>
          <button className="button" onClick={() => void requestExport("zip")}>Package evidence ZIP</button>
          {exportMessage && <span role="status">{exportMessage}</span>}
          {!detail.pilot_task_id && (role === "operator" || role === "supervisor") && <LifecycleBar
            incidentId={detail.id}
            state={detail.state}
            allowedActions={detail.allowed_actions}
            onTransitioned={() => {
              bundle.reload();
              onChanged();
            }}
          />}
        </div>
      </section>
      <div className="detail-flow">
        <section className="detail-section"><h3>Why this incident was created</h3><CaseFile detail={detail} /></section>
        <section className="detail-section"><h3>Evidence</h3><EvidenceGallery steps={steps} onOpen={setLbIndex} /></section>
        <section className="detail-section"><h3>Timeline</h3><TimelineLanes steps={steps} onOpenStep={openEvidence} /></section>
        {detail.pilot_task_id ? <section className="detail-section"><h3>Response</h3><p>Manage this task and its observed outcome in the guard desk.</p></section> : role !== "client_viewer" && <section className="detail-section"><h3>Response</h3><ResponsePanel incidentId={detail.id} role={role} actor={actor} /></section>}
        {detail.explanation.correlations.length > 0 && <section className="detail-section"><h3>Correlated movement across cameras</h3>{detail.explanation.correlations.map((correlation, index) =>
          <div className="clinical-correlation" data-testid="correlation-card" key={index}>
            <strong>{correlation.topology_transition ?? `${correlation.from_track ?? "Source"} → ${correlation.to_track ?? "Destination"}`}</strong>
            <dl><div><dt>Source camera</dt><dd>{correlation.from_track?.split(":")[0] ?? "—"}</dd></div><div><dt>Destination camera</dt><dd>{correlation.to_track?.split(":")[0] ?? "—"}</dd></div><div><dt>Time gap</dt><dd>{correlation.temporal_gap_seconds ?? "—"} s</dd></div><div><dt>Topology</dt><dd>{correlation.topology_transition ?? "—"}</dd></div><div><dt>Appearance signal</dt><dd>{correlation.s_appearance?.toFixed(2) ?? "—"}</dd></div><div><dt>Correlation score</dt><dd>{(correlation.combined_score ?? correlation.confidence)?.toFixed(2) ?? "—"}</dd></div></dl>
            <small>Proposed movement link. This does not verify identity.</small>
          </div>)}</section>}
        <section className="detail-section"><h3>Graph</h3><EvidenceGraphView graph={bundle.graph} /></section>
        <section className="detail-section"><h3>Location</h3><SiteMapView graph={bundle.graph} /></section>
        <section className="detail-section"><h3>Status history</h3><AuditTrail history={bundle.history} /></section>
      </div>

      {lbIndex != null && steps.length > 0 && (
        <Lightbox
          steps={steps}
          index={lbIndex}
          onClose={() => setLbIndex(null)}
          onIndex={(i) => setLbIndex(i)}
        />
      )}
    </div>
  );
}
