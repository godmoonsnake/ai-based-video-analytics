import { useEffect, useState, type ReactNode } from "react";
import type { HealthStatus } from "../../types/system";
import {
  IconAperture,
  IconKeyboard,
  IconInfo,
  IconServer,
  IconPause,
  IconRadar,
  IconEye,
  IconX,
} from "../icons";

/* ---------------- Rail ---------------- */

export function Rail({
  onHelp,
  onAbout,
  health,
}: {
  onHelp: () => void;
  onAbout: () => void;
  health: HealthStatus | null;
}) {
  const dbOk = health?.database === true;
  return (
    <aside className="rail">
      <div className="rail-brand" title="DARSON — AI intelligence layer over your VMS">
        <IconAperture />
      </div>
      <div className="rail-sep" />
      <button className="rail-btn" onClick={onAbout} title="What is DARSON?">
        <IconInfo />
      </button>
      <button className="rail-btn" onClick={onHelp} title="Keyboard shortcuts (?)">
        <IconKeyboard />
      </button>
      <div className="rail-foot">
        <div className="rail-status" title={dbOk ? "API + PostgreSQL healthy" : "Stack degraded"}>
          <span
            className="dot"
            style={{
              width: 7,
              height: 7,
              borderRadius: "50%",
              background: dbOk ? "var(--mint)" : "var(--red)",
              boxShadow: dbOk
                ? "0 0 10px rgba(67,224,160,0.8)"
                : "0 0 10px rgba(255,92,92,0.8)",
            }}
          />
          <IconServer style={{ width: 14, height: 14, color: "var(--ink-faint)" }} />
        </div>
        <span className="rail-version">DARSON v1</span>
      </div>
    </aside>
  );
}

/* ---------------- Topbar ---------------- */

export function Topbar({
  live,
  onToggleLive,
  health,
  identity,
  onLogout,
}: {
  live: boolean;
  onToggleLive: () => void;
  health: HealthStatus | null;
  identity?: { display_name: string; tenant_id: string; site_id: string; role: string } | null;
  onLogout?: () => void;
}) {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const t = window.setInterval(() => setNow(new Date()), 1000);
    return () => window.clearInterval(t);
  }, []);

  const dbOk = health?.database === true;
  const apiOk = health != null && health.status === "ok";

  return (
    <header className="topbar">
      <div className="topbar-crumb">
        <span className="topbar-title">Operations</span>
        <span className="topbar-sub">EVENT → CONTEXT → CORRELATION → INCIDENT → REVIEW</span>
      </div>
      <div className="topbar-right">
        {identity && <span className="topbar-sub" title={`${identity.tenant_id} / ${identity.site_id}`}>{identity.display_name} · {identity.role}</span>}
        {onLogout && <button className="live-chip" onClick={onLogout} title="End this session">Sign out</button>}
        <span className="health" title="Stack health (backend /health, polled every 15s)">
          <span className={`health-item ${apiOk ? "ok" : health ? "bad" : ""}`}>
            <span className="dot" /> API
          </span>
          <span className={`health-item ${dbOk ? "ok" : health ? "bad" : ""}`}>
            <span className="dot" /> DB
          </span>
        </span>
        <button
          className={`live-chip ${live ? "on" : ""}`}
          onClick={onToggleLive}
          title={live ? "Live polling on (5s) — click to pause" : "Paused — click to resume"}
        >
          {live ? <span className="dot" /> : <IconPause style={{ width: 10, height: 10 }} />}
          {live ? "LIVE" : "PAUSED"}
          <IconEye style={{ width: 11, height: 11, opacity: 0.7 }} />
        </button>
        <span className="topbar-clock">{now.toLocaleTimeString()}</span>
      </div>
    </header>
  );
}

/* ---------------- Modals ---------------- */

function Modal({
  onClose,
  children,
  wide,
}: {
  onClose: () => void;
  children: ReactNode;
  wide?: boolean;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div
        className="modal"
        style={wide ? { width: "min(760px, 100%)" } : undefined}
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
      >
        <button className="icon-btn modal-close" onClick={onClose} aria-label="Close">
          <IconX />
        </button>
        {children}
      </div>
    </div>
  );
}

export function AboutModal({ onClose }: { onClose: () => void }) {
  return (
    <Modal onClose={onClose}>
      <div className="modal-title">What DARSON does</div>
      <div className="modal-sub">AI Video Intelligence</div>

      <div className="pipe">
        {["EVENT", "CONTEXT", "CORRELATION", "INCIDENT", "HISTORY", "INVESTIGATION"].map((s, i) => (
          <span key={s} style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
            {i > 0 && <span className="arr">→</span>}
            <span className="stage">{s}</span>
          </span>
        ))}
      </div>

      <p>
        DARSON receives camera events and groups related observations into incidents. Operators
        can inspect the timeline and evidence, review a proposed movement path, and record their
        response and decision.
      </p>
      <p>
        The local review uses synthetic events and media. Camera connections and live performance
        should be validated in a site pilot.
      </p>

      <div className="principle">
        <IconRadar />
        <span>
          <b>Movement correlation, not identity.</b> Tracks are stitched across cameras using
          topology, timing, motion and appearance similarity — never a claim about who someone is.
        </span>
      </div>
      <div className="principle">
        <IconRadar />
        <span>
          <b>Decision support, not a verdict.</b> Confidence bands help operators triage; the
          confirm/dismiss decision stays human, and the audit trail keeps it accountable.
        </span>
      </div>
    </Modal>
  );
}

const HELP_ROWS: [string, string[]][] = [
  ["Next / previous incident", ["J", "K", "↑", "↓"]],
  ["Start triage", ["T"]],
  ["Confirm incident", ["C"]],
  ["Dismiss incident", ["E"]],
  ["Reopen incident", ["R"]],
  ["Focus feed search", ["/"]],
  ["This cheatsheet", ["?"]],
  ["Close overlay / clear search", ["esc"]],
  ["Lightbox navigation", ["←", "→"]],
];

export function HelpModal({ onClose }: { onClose: () => void }) {
  return (
    <Modal onClose={onClose} wide>
      <div className="modal-title">Keyboard triage</div>
      <div className="modal-sub">Built for operators who live on the keyboard</div>
      <div className="help-grid">
        {HELP_ROWS.map(([what, keys]) => (
          <div className="help-row" key={what}>
            <span className="what">{what}</span>
            <span className="keys">
              {keys.map((k) => (
                <span className="kbd" key={k}>
                  {k}
                </span>
              ))}
            </span>
          </div>
        ))}
      </div>
    </Modal>
  );
}
