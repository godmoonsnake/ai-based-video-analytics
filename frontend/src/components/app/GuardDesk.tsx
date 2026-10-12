import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, type PilotTask, type PilotStatus, type PilotNotice, type CameraHealth } from "../../services/api";
import { useAuth } from "../../services/auth";
import { ProtectedImage, ProtectedVideo } from "../ui/ProtectedMedia";
import "../../styles/guard.css";

const names: Record<string, string> = {
  open: "Needs response", acknowledged: "Acknowledged", need_help: "Needs help", resolved: "Completed",
  assigned_guard: "Assigned guard", unacknowledged: "Acknowledgement overdue",
  no_guard_on_shift: "No guard on shift", guard_delivery_failed: "Guard notification failed",
  camera_offline: "Camera offline", critical_event: "Critical event",
  accepted: "Provider accepted", queued: "Queued", retrying: "Retrying", failed: "Failed",
  suppressed: "Simulated — not sent", cancelled: "Cancelled",
};

export function GuardDesk({ onOpenSupervisor }: { onOpenSupervisor: () => void }) {
  const auth = useAuth();
  const role = auth.identity?.role ?? "supervisor";
  const desk = role === "operator" || role === "supervisor";
  const [tasks, setTasks] = useState<PilotTask[]>([]);
  const [status, setStatus] = useState<PilotStatus | null>(null);
  const [notices, setNotices] = useState<PilotNotice[]>([]);
  const [cameras, setCameras] = useState<CameraHealth[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(new URLSearchParams(location.search).get("task"));
  const [history, setHistory] = useState(false);
  const [note, setNote] = useState("");
  const [error, setError] = useState("");
  const [actionError, setActionError] = useState("");
  const [busy, setBusy] = useState(false);
  const [lastRefresh, setLastRefresh] = useState<number | null>(null);
  const [sound, setSound] = useState(false);
  const [showClip, setShowClip] = useState(false);
  const audio = useRef<AudioContext | null>(null);
  const seen = useRef<Set<string> | null>(null);
  const presented = useRef(new Set<string>());
  const mounted = useRef(true);
  const generation = useRef(0);

  const reload = useCallback(async () => {
    const requestGeneration = ++generation.current;
    try {
      const values = await Promise.all([api.getPilotTasks(history), api.getPilotStatus(),
        api.getCameraHealth(), desk ? api.getPilotNotices() : Promise.resolve([])]);
      if (!mounted.current || requestGeneration !== generation.current) return;
      const [receivedTasks, nextStatus, health, nextNotices] = values;
      const nextTasks = history ? receivedTasks.filter(task => task.state === "resolved") : receivedTasks;
      if (!history && sound && seen.current && nextTasks.some(task => !seen.current!.has(task.id))) {
        const context = audio.current;
        if (context) {
          const oscillator = context.createOscillator();
          const gain = context.createGain();
          oscillator.frequency.value = 740;
          gain.gain.setValueAtTime(0.08, context.currentTime);
          gain.gain.exponentialRampToValueAtTime(0.001, context.currentTime + 0.45);
          oscillator.connect(gain); gain.connect(context.destination);
          oscillator.start(); oscillator.stop(context.currentTime + 0.45);
        }
      }
      seen.current = new Set(nextTasks.map(task => task.id));
      setTasks(nextTasks); setStatus(nextStatus); setCameras(health); setNotices(nextNotices);
      if (desk) for (const task of nextTasks) {
        if (!presented.current.has(task.id)) {
          presented.current.add(task.id);
          void api.markPilotPresented(task.id).catch(() => presented.current.delete(task.id));
        }
      }
      setLastRefresh(Date.now()); setError("");
      setSelectedId(current => nextTasks.some(task => task.id === current) ? current : nextTasks[0]?.id ?? null);
    } catch {
      if (mounted.current && requestGeneration === generation.current)
        setError("Connection lost. Displayed tasks may be out of date. Contact the desk by the site's backup procedure.");
    }
  }, [history, sound, desk]);

  useEffect(() => {
    mounted.current = true;
    void reload();
    const timer = window.setInterval(() => void reload(), 2000);
    return () => { mounted.current = false; generation.current++; window.clearInterval(timer); };
  }, [reload]);
  useEffect(() => { setNote(""); setActionError(""); setShowClip(false); }, [selectedId]);
  useEffect(() => () => { void audio.current?.close(); }, []);

  const selected = tasks.find(task => task.id === selectedId);
  const timestamp = (value: number) => new Intl.DateTimeFormat("en-IN", {
    hour: "2-digit", minute: "2-digit", second: "2-digit", timeZone: status?.timezone ?? "Asia/Kolkata",
  }).format(new Date(value * 1000));
  const act = async (action: "claim" | "acknowledge" | "outcome", outcome?: string) => {
    if (!selected) return;
    setBusy(true); setActionError("");
    try {
      await api.pilotAction(selected.id, selected.version, action, { outcome, note });
      setNote(""); await reload();
    } catch (failure) {
      setActionError(failure instanceof ApiError ? failure.detail ?? failure.message : "Could not save the action.");
      await reload();
    } finally { setBusy(false); }
  };
  const toggleSound = async () => {
    if (!sound) {
      audio.current ??= new AudioContext();
      await audio.current.resume();
    }
    setSound(value => !value);
  };
  const snapshot = selected?.evidence.find(item => item.kind === "snapshot" && item.content_url);
  const clip = selected?.evidence.find(item => item.kind === "clip" && item.content_url);
  const attention = notices.filter(notice => ["failed", "retrying"].includes(notice.status));

  return <div className="guard-app">
    <header className="guard-header">
      <div className="guard-brand"><span className="guard-mark">D</span><div><strong>DARSON</strong><small>Guard desk · {status?.site ?? "Connecting"}</small></div></div>
      <nav aria-label="Desk views">
        <button className={!history ? "active" : ""} onClick={() => setHistory(false)}>Active tasks</button>
        {desk && <button className={history ? "active" : ""} onClick={() => setHistory(true)}>Recent outcomes</button>}
        {role === "supervisor" && <button onClick={onOpenSupervisor}>Supervisor review</button>}
      </nav>
      <div className="guard-session">
        <button aria-pressed={sound} onClick={() => void toggleSound()}>Sound {sound ? "on" : "off"}</button>
        {auth.enabled && <button onClick={() => void auth.logout()}>Sign out</button>}
      </div>
    </header>
    {status?.simulated && <div className="guard-demo" role="status">SIMULATED / DEVELOPMENT — external messages are suppressed.</div>}
    {error && <div className="guard-warning" role="alert">{error}<button onClick={() => void reload()}>Retry connection</button></div>}
    <div className="guard-summary">
      <span><b>{tasks.filter(task => task.state !== "resolved").length}</b> active tasks</span>
      <span><b>{cameras.length ? cameras.filter(camera => camera.stream_state === "offline").length : "—"}</b> cameras offline</span>
      <span><b>{attention.length}</b> notification failures</span>
      <span className="guard-refresh">{lastRefresh ? `Updated ${timestamp(lastRefresh / 1000)}` : "Waiting for desk"}</span>
    </div>
    {status && !status.rules_configured && <div className="guard-warning">No restricted-area rule is active. An engineer must configure the camera, zone, schedule and guard roster.</div>}
    {desk && Boolean(status?.retention_failures) && <div className="guard-warning" role="alert">Evidence cleanup failed for {status?.retention_failures} objects. Ask the site administrator to check storage; cleanup will retry.</div>}
    <main className="guard-layout">
      <section className="guard-queue" aria-label="Guard task queue">
        <div className="guard-section-heading"><h1>{history ? "Recent outcomes" : "Action required"}</h1><span>{tasks.length}</span></div>
        {!tasks.length && <div className="guard-empty">{lastRefresh ? "No tasks in this view." : "Connecting to the site…"}</div>}
        {tasks.map(task => <button className={`guard-task ${task.id === selectedId ? "selected" : ""}`} key={task.id} onClick={() => setSelectedId(task.id)}>
          <div><span className={`guard-priority ${task.priority}`}>{task.priority}</span><time>{timestamp(task.observed_at)}</time></div>
          <strong>{task.zone_name}</strong><span>{task.camera_id} · Restricted-area entry</span>
          <div><small>{names[task.state] ?? task.state}</small><small>{task.owner ? "Assigned" : "Unassigned"}</small></div>
        </button>)}
      </section>
      <section className="guard-detail" aria-label="Selected task">
        {!selected ? <div className="guard-empty guard-welcome"><span className="guard-mark">D</span><h2>Ready for the next task</h2><p>Select a task to review its evidence and response instructions.</p></div> : <>
          <div className="guard-section-heading"><div><small>TASK #{selected.incident_id}</small><h2>{selected.zone_name}</h2></div><span>{names[selected.state]}</span></div>
          {selected.state !== "resolved" && !selected.acknowledged_at && <div className="guard-top-actions">
            {!selected.owner && desk && <button disabled={busy || Boolean(error)} onClick={() => void act("claim")}>Take this task</button>}
            <button className="guard-primary" disabled={busy || Boolean(error)} onClick={() => void act("acknowledge")}>Acknowledge</button>
          </div>}
          <div className="guard-media">
            {showClip && clip ? <ProtectedVideo src={clip.content_url} fallback={<p>Loading clip…</p>} /> :
              <ProtectedImage src={snapshot?.content_url} alt={`Event at ${selected.zone_name}`} fallback={<p>Evidence {selected.evidence.some(item => item.status === "pending" || item.status === "requested") ? "is being prepared" : "is unavailable"}. You can still acknowledge this task.</p>} />}
            <span>{selected.camera_id} · {timestamp(selected.observed_at)}</span>
          </div>
          {clip && <button className="guard-secondary" onClick={() => setShowClip(value => !value)}>{showClip ? "Show snapshot" : "Play event clip"}</button>}
          <div className="guard-instruction"><small>RESPONSE INSTRUCTIONS</small><p>{selected.instruction}</p><span>Assigned to: {selected.owner ?? "Nobody — desk response required"}</span></div>
          {!selected.acknowledged_at && selected.state !== "resolved" && <p className="guard-deadline">Acknowledge by {timestamp(selected.acknowledgement_deadline)}{Date.now() / 1000 > selected.acknowledgement_deadline ? " · OVERDUE" : ""}</p>}
          <div className="guard-actions">
            {selected.state !== "resolved" && <>
              {selected.acknowledged_at && <>
                <label htmlFor="guard-note">What did you observe?</label>
                <textarea id="guard-note" value={note} maxLength={2000} onChange={event => setNote(event.target.value)} placeholder="Brief observation for the desk" />
                <div className="guard-outcomes">
                  <button disabled={busy || Boolean(error) || note.trim().length < 3} onClick={() => void act("outcome", "real_incident")}>Real incident</button>
                  <button disabled={busy || Boolean(error) || note.trim().length < 3} onClick={() => void act("outcome", "false_alarm")}>False alarm</button>
                  <button className="guard-help" disabled={busy || Boolean(error) || note.trim().length < 3} onClick={() => void act("outcome", "need_help")}>Need help</button>
                </div>
              </>}
            </>}
          </div>
          {selected.outcome_note && <p className="guard-recorded">Recorded observation: {selected.outcome_note}</p>}
          {role === "supervisor" && selected.state === "resolved" && !selected.label_verified && <button onClick={async () => {
            try { await api.verifyPilotLabel(selected.id); await reload(); } catch { setActionError("Could not verify this label."); }
          }}>Verify outcome for accuracy review</button>}
          {selected.label_verified && <p className="guard-recorded">Outcome verified by a supervisor.</p>}
          {actionError && <p role="alert" className="guard-action-error">{actionError}</p>}
          <div className="guard-delivery"><h3>Notification status</h3>
            <p>The desk task is available immediately. Provider acceptance does not confirm that a guard has seen it.</p>
            {selected.notifications.map(notice => <div key={notice.id}><span>{names[notice.reason] ?? notice.reason}</span><b>{names[notice.status] ?? notice.status}</b></div>)}
          </div>
        </>}
      </section>
    </main>
    {desk && attention.length > 0 && <section className="guard-failures" aria-label="Delivery problems"><h2>Delivery needs attention</h2>
      {attention.map(notice => <div key={notice.id}><span>{names[notice.reason] ?? notice.reason} · {names[notice.status]} · {notice.failure_class?.replace(/_/g, " ")}</span>
        {role === "supervisor" && notice.status === "failed" && <button onClick={async () => {
          try { await api.retryPilotNotice(notice.id); await reload(); } catch { setActionError("Configure the recipient's contact before retrying delivery."); }
        }}>Retry after contact correction</button>}</div>)}
    </section>}
  </div>;
}
