import { useEffect, useRef, useState } from "react";
import { api, type CameraHealth } from "../../services/api";
import type { Camera } from "../../types/system";

export function CameraWall() {
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [health, setHealth] = useState<CameraHealth[]>([]);
  const [frames, setFrames] = useState<Record<string, string>>({});
  const [updated, setUpdated] = useState<Record<string, number>>({});
  const [error, setError] = useState("");
  const frameUrls = useRef<Record<string, string>>({});

  useEffect(() => {
    let active = true;
    const reload = async () => {
      try {
        const [registered, statuses] = await Promise.all([api.listCameras(), api.getCameraHealth()]);
        if (active) { setCameras(registered); setHealth(statuses); setError(""); }
      } catch { if (active) setError("Camera registry or health is unavailable."); }
    };
    void reload();
    const timer = window.setInterval(() => void reload(), 10000);
    return () => { active = false; window.clearInterval(timer); };
  }, []);

  useEffect(() => {
    if (!cameras.length) return;
    let active = true;
    let busy = false;
    const refresh = async () => {
      if (busy) return;
      busy = true;
      const results = await Promise.allSettled(cameras.slice(0, 9).map(async camera => {
        const blob = await api.getLatestCameraFrame(camera.id);
        return { id: camera.id, url: URL.createObjectURL(blob) };
      }));
      if (active) {
        const next = { ...frameUrls.current };
        const times: Record<string, number> = {};
        for (const result of results) if (result.status === "fulfilled") {
          const { id, url } = result.value;
          if (next[id]) URL.revokeObjectURL(next[id]);
          next[id] = url; times[id] = Date.now();
        }
        frameUrls.current = next; setFrames({ ...next }); setUpdated(current => ({ ...current, ...times }));
      } else for (const result of results) if (result.status === "fulfilled") URL.revokeObjectURL(result.value.url);
      busy = false;
    };
    void refresh();
    const timer = window.setInterval(() => void refresh(), 2500);
    return () => {
      active = false; window.clearInterval(timer);
      for (const url of Object.values(frameUrls.current)) URL.revokeObjectURL(url);
      frameUrls.current = {};
    };
  }, [cameras.map(camera => camera.id).join("|")]);

  const byId = new Map(health.map(item => [item.camera_id, item]));
  return <main className="guard-workspace" aria-label="Camera wall">
    <div className="guard-workspace-heading"><div><small>CAMERA WALL</small><h1>Live camera section</h1></div><span>{cameras.length} registered · up to 9 shown</span></div>
    <p className="guard-workspace-note">Frames refresh about every 2.5 seconds from the configured Frigate source. This is a monitoring preview, not a smooth video stream. A saved last frame never counts as live.</p>
    {error && <p role="alert" className="guard-action-error">{error}</p>}
    {!cameras.length ? <div className="guard-empty">No cameras are registered at this site. Connect the recorder and register its cameras to populate this wall.</div> :
      <div className="guard-camera-wall">{cameras.slice(0, 9).map(camera => {
        const status = byId.get(camera.id);
        const fresh = status?.stream_state === "online" || status?.stream_state === "healthy";
        const live = fresh && status?.last_frame_at != null && Date.now() / 1000 - status.last_frame_at < 15;
        return <article key={camera.id} className="guard-camera-tile">
          <div className="guard-camera-visual">{frames[camera.id] ? <img src={frames[camera.id]} alt={`Latest frame from ${camera.name}`} /> : <span>No frame available</span>}
            <b className={live ? "guard-camera-live" : "guard-camera-unavailable"}>{live ? "LIVE FRAMES" : "NOT VERIFIED LIVE"}</b>
          </div>
          <div className="guard-camera-caption"><strong>{camera.name}</strong><span>{camera.id}</span></div>
          <small>{updated[camera.id] ? `Preview fetched ${new Date(updated[camera.id]).toLocaleTimeString()}` : "Waiting for a source"}</small>
        </article>;
      })}</div>}
  </main>;
}
