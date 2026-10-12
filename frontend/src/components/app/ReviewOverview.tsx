import type { ReviewManifest } from "../../services/api";

type Overview = Awaited<ReturnType<typeof import("../../services/api").api.getOperationsOverview>>;

export function ReviewOverview({ manifest, overview, loading, error, onReplay, onOpenCase }:
  { manifest: ReviewManifest | null; overview: Overview | null; loading: boolean; error: string;
    onReplay: () => void; onOpenCase: (id: number) => void }) {
  const demo = overview?.demo_mode !== false;
  return <div className="review-page">
    <div className="review-hero">
      <div className="review-hero-copy">
        <span className="review-kicker">DARSON / SECURITY INTELLIGENCE PLATFORM</span>
        <h1>From camera events to decisions you can defend.</h1>
        <p>DARSON connects signals from existing video systems, explains movement across cameras, and gives security teams a reviewable case with response and audit in one place.</p>
        {demo && <div className="review-actions">
          <button className="review-primary" onClick={onReplay} disabled={loading}>{loading ? "Preparing review…" : manifest?.ready ? "Refresh review cases" : "Load guided review"}</button>
          <span>Local synthetic replay · no real people or customer footage</span>
        </div>}
        {error && <p className="review-error" role="alert">{error}</p>}
      </div>
      <div className="review-signal" aria-hidden="true">
        <div className="review-signal-head"><span>EXPLAINABLE PIPELINE</span><span>01 — 05</span></div>
        {["Capture event", "Add site context", "Correlate movement", "Build a case", "Operator review"].map((item, index) =>
          <div className="review-signal-row" key={item}><b>0{index + 1}</b><span>{item}</span><i /></div>)}
        <div className="review-signal-foot">Human decision remains in control</div>
      </div>
    </div>

    <section className="review-section">
      <div className="review-section-title"><span>THE PLATFORM</span><h2>One operating picture from alert to evidence.</h2></div>
      <div className="review-capabilities">
        <article><b>01 / Detect with context</b><h3>Fewer orphan alerts</h3><p>Zone rules and camera topology put detections into a site-specific story. A restricted-zone signal becomes a reviewable incident.</p></article>
        <article><b>02 / Investigate movement</b><h3>Follow the evidence</h3><p>Timeline and graph views show the observations behind a proposed cross-camera path, with confidence and gaps visible.</p></article>
        <article><b>03 / Coordinate response</b><h3>Make ownership clear</h3><p>Assign, acknowledge, work through steps, and track service targets. Each action is recorded for later review.</p></article>
        <article><b>04 / Report responsibly</b><h3>Share an accountable case</h3><p>Export case data and reports with provenance, review status, and a human decision trail.</p></article>
      </div>
    </section>

    {demo && <section className="review-section review-cases">
      <div className="review-section-title"><span>GUIDED PRODUCT REVIEW</span><h2>Open a case and test the workflow.</h2></div>
      <div className="review-case-grid">
        {(manifest?.scenarios ?? []).map((scenario, index) => <article key={scenario.id}>
          <span className="review-case-index">SCENARIO 0{index + 1}</span>
          <h3>{scenario.title}</h3><p>{scenario.subtitle}</p>
          <div className="review-case-note">{scenario.talk_track}</div>
          <button disabled={scenario.incident_id == null} onClick={() => scenario.incident_id && onOpenCase(scenario.incident_id)}>
            {scenario.incident_id ? `Open case #${scenario.incident_id} →` : "Load review to open →"}
          </button>
        </article>)}
      </div>
      {!manifest && <p className="review-quiet">Guided cases are available when the local review API is running.</p>}
    </section>}

    <section className="review-live" aria-label="Current operations snapshot">
      <div><span>OPERATIONS SNAPSHOT</span><h2>Designed for a live security desk.</h2><p>These values come from the connected instance.{demo ? " Replay data is synthetic and clearly marked." : ""}</p></div>
      <div className="review-live-metrics">
        <div><b>{overview?.active_incidents ?? "—"}</b><span>active cases</span></div>
        <div><b>{overview?.unassigned_incidents ?? "—"}</b><span>awaiting owner</span></div>
        <div><b>{overview?.open_sla_breaches ?? "—"}</b><span>SLA breaches</span></div>
        <div><b>{overview?.camera_offline ?? "—"}</b><span>streams offline</span></div>
      </div>
    </section>
    <p className="review-disclosure">{demo ? "Development pilot · synthetic replay · " : ""}movement correlation is not person identification · no autonomous verdicts</p>
  </div>;
}
