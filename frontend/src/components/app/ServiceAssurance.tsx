import { useCallback, useEffect, useState } from "react";
import { api, type CameraHealth, type HealthMetrics, type ResponseTask } from "../../services/api";
import type { Camera } from "../../types/system";

export function ServiceAssurance({ onOpenCase, canSeeTasks }: { onOpenCase: (id: number) => void; canSeeTasks: boolean }) {
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [health, setHealth] = useState<CameraHealth[]>([]);
  const [metrics, setMetrics] = useState<HealthMetrics | null>(null);
  const [tasks, setTasks] = useState<ResponseTask[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const reload = useCallback(async () => {
    setLoading(true);
    const [cameraResult, healthResult, metricResult, taskResult] = await Promise.allSettled([
      api.listCameras(), api.getCameraHealth(), api.getHealthMetrics(),
      canSeeTasks ? api.getMyTasks() : Promise.resolve([]),
    ]);
    if (cameraResult.status === "fulfilled") setCameras(cameraResult.value);
    if (healthResult.status === "fulfilled") setHealth(healthResult.value);
    if (metricResult.status === "fulfilled") setMetrics(metricResult.value);
    if (taskResult.status === "fulfilled") setTasks(taskResult.value);
    setError([cameraResult, healthResult, metricResult, taskResult].some((result) => result.status === "rejected")
      ? "Some service data is unavailable. Refresh to try again." : "");
    setLoading(false);
  }, [canSeeTasks]);
  useEffect(() => { void reload(); }, [reload]);
  const byId = new Map(health.map((item) => [item.camera_id, item]));

  return <div className="workspace-page">
    <header className="workspace-heading"><div><span className="review-kicker">SERVICE ASSURANCE</span><h1>Know when coverage and response are real.</h1><p>Camera availability, recording, evidence capture, and owned work are separate operational signals.</p></div><button className="btn" onClick={() => void reload()} disabled={loading}>Refresh status</button></header>
    {error && <p className="workspace-alert" role="alert">{error}</p>}
    <section className="workspace-metrics" aria-label="24-hour service metrics">
      <div><b>{metrics?.samples ? `${metrics.unavailable_camera_minutes}m` : "—"}</b><span>camera unavailable · 24h</span></div>
      <div><b>{metrics?.samples ? `${metrics.recording_gap_minutes}m` : "—"}</b><span>recording gaps · 24h</span></div>
      <div><b>{metrics?.evidence_capture_success_rate != null ? `${Math.round(metrics.evidence_capture_success_rate * 100)}%` : "—"}</b><span>evidence capture</span></div>
      <div><b>{metrics?.event_to_incident_latency_seconds != null ? `${Math.round(metrics.event_to_incident_latency_seconds)}s` : "—"}</b><span>event to case latency</span></div>
    </section>
    {!metrics?.samples && <p className="workspace-note">No health samples are recorded yet. The replay cases do not simulate a live camera-health probe.</p>}
    <section className="workspace-section"><div className="workspace-section-title"><h2>Camera coverage</h2><span>{cameras.length} registered</span></div>
      {cameras.length === 0 ? <p className="workspace-empty">No cameras are registered for this site.</p> : <div className="workspace-camera-grid">{cameras.map((camera) => {
        const item = byId.get(camera.id);
        return <article key={camera.id}><div><strong>{camera.name}</strong><small>{camera.id}</small></div>
          <span className={`workspace-state ${item?.stream_state === "offline" ? "bad" : item ? "known" : "unknown"}`}>{item?.maintenance ? "Maintenance" : item?.stream_state ?? "Not monitored"}</span>
          <dl><div><dt>Video</dt><dd>{item?.video_state ?? "No probe"}</dd></div><div><dt>Recording</dt><dd>{item?.recording_state ?? "No probe"}</dd></div><div><dt>Evidence</dt><dd>{item?.evidence_state ?? "No probe"}</dd></div></dl>
        </article>;
      })}</div>}
    </section>
    {canSeeTasks && <section className="workspace-section"><div className="workspace-section-title"><h2>My response work</h2><span>{tasks.length} active assignments</span></div>
      {tasks.length === 0 ? <p className="workspace-empty">No cases are currently assigned to this account. Assign a case from the operations console to see it here.</p> : <div className="workspace-list">{tasks.map((task) => <button key={task.incident_id} onClick={() => onOpenCase(task.incident_id)}><b>CASE #{task.incident_id}</b><span>{task.priority ?? "Unranked"} · {task.response_state} · {task.location.site}</span><small>Open response →</small></button>)}</div>}
    </section>}
  </div>;
}
