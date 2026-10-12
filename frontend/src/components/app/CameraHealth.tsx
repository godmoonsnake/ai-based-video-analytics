import { useEffect, useState } from "react";
import { api, type CameraHealth } from "../../services/api";
import type { Camera } from "../../types/system";

export function CameraHealthSummary() {
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [health, setHealth] = useState<CameraHealth[]>([]);
  const [error, setError] = useState(false);
  useEffect(() => {
    Promise.all([api.listCameras(), api.getCameraHealth()])
      .then(([registered, status]) => { setCameras(registered); setHealth(status); setError(false); })
      .catch(() => setError(true));
  }, []);
  const byId = new Map(health.map((item) => [item.camera_id, item]));
  return <details className="camera-health-panel">
    <summary>Camera health <span>{cameras.length} registered · {health.length} monitored</span></summary>
    {error ? <p>Camera status is unavailable.</p> : cameras.length === 0 ? <p>No cameras are registered for this site.</p> :
      <div className="camera-health-list">{cameras.map((camera) => {
        const item = byId.get(camera.id);
        return <div key={camera.id}><strong>{camera.name}</strong><span>Stream: {item?.stream_state ?? "Not monitored"}</span><span>Recording: {item?.recording_state ?? "No probe"}</span><span>Evidence: {item?.evidence_state ?? "No probe"}</span></div>;
      })}</div>}
  </details>;
}
