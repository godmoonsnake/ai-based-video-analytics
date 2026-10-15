import { useEffect, useRef, useState } from "react";
import { api } from "../../services/api";
import type { DetectedObject, ObjectDetection } from "@tensorflow-models/coco-ssd";

let detectorPromise: Promise<ObjectDetection> | null = null;
function loadDetector(): Promise<ObjectDetection> {
  detectorPromise ??= (async () => {
    const [tf, , , cocoSsd] = await Promise.all([
      import("@tensorflow/tfjs-core"),
      import("@tensorflow/tfjs-backend-cpu"),
      import("@tensorflow/tfjs-backend-webgl"),
      import("@tensorflow-models/coco-ssd"),
    ]);
    await tf.ready();
    return cocoSsd.load({ base: "lite_mobilenet_v2", modelUrl: "/models/ssdlite_mobilenet_v2/model.json" });
  })().catch(error => { detectorPromise = null; throw error; });
  return detectorPromise;
}

export function VideoDemo() {
  const [url, setUrl] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [duration, setDuration] = useState<number | null>(null);
  const [phase, setPhase] = useState<"idle" | "loading" | "running">("idle");
  const [people, setPeople] = useState<number | null>(null);
  const [sampledAt, setSampledAt] = useState<number | null>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const runningRef = useRef(false);
  const generationRef = useRef(0);
  const timerRef = useRef<number | null>(null);

  const clearBoxes = () => {
    const canvas = canvasRef.current;
    canvas?.getContext("2d")?.clearRect(0, 0, canvas.width, canvas.height);
  };
  const stop = () => {
    generationRef.current += 1;
    runningRef.current = false;
    if (timerRef.current != null) window.clearTimeout(timerRef.current);
    timerRef.current = null;
    clearBoxes(); setPhase("idle"); setPeople(null); setSampledAt(null);
  };
  useEffect(() => () => { runningRef.current = false; generationRef.current += 1;
    if (timerRef.current != null) window.clearTimeout(timerRef.current); }, []);
  useEffect(() => () => { if (url) URL.revokeObjectURL(url); }, [url]);

  const open = (blob: Blob, label: string) => {
    stop(); setUrl(URL.createObjectURL(blob)); setName(label); setDuration(null); setError("");
  };
  const choose = (file?: File) => {
    if (!file) return;
    if (!(["video/mp4", "video/webm"].includes(file.type) || /\.(mp4|webm)$/i.test(file.name))) {
      setError("Choose an MP4 or WebM video."); return;
    }
    if (file.size > 100_000_000) { setError("Choose a clip under 100 MB for this local demo."); return; }
    open(file, file.name);
  };
  const sample = async () => {
    setLoading(true); setError("");
    try { open(await api.getDemoSampleVideo("people"), "People detection sample · prerecorded"); }
    catch { setError("The bundled sample video is unavailable from the local demo server. Choose your own MP4 instead."); }
    finally { setLoading(false); }
  };

  const draw = (detections: DetectedObject[], video: HTMLVideoElement) => {
    const canvas = canvasRef.current;
    if (!canvas || !video.videoWidth || !video.videoHeight) return;
    const width = video.clientWidth, height = video.clientHeight;
    const pixelRatio = window.devicePixelRatio || 1;
    canvas.width = Math.round(width * pixelRatio);
    canvas.height = Math.round(height * pixelRatio);
    const context = canvas.getContext("2d");
    if (!context) return;
    context.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);
    const scale = Math.min(width / video.videoWidth, height / video.videoHeight);
    const offsetX = (width - video.videoWidth * scale) / 2;
    const offsetY = (height - video.videoHeight * scale) / 2;
    context.lineWidth = 3;
    context.font = "bold 14px sans-serif";
    for (const detection of detections) {
      const [x, y, boxWidth, boxHeight] = detection.bbox;
      const left = offsetX + x * scale, top = offsetY + y * scale;
      context.strokeStyle = "#50edb7";
      context.strokeRect(left, top, boxWidth * scale, boxHeight * scale);
      const label = `PERSON · score ${detection.score.toFixed(2)}`;
      const labelWidth = context.measureText(label).width + 12;
      context.fillStyle = "#0a4939";
      context.fillRect(left, Math.max(0, top - 23), labelWidth, 22);
      context.fillStyle = "#ffffff";
      context.fillText(label, left + 6, Math.max(17, top - 7));
    }
  };
  const scan = async (generation: number, detector: ObjectDetection) => {
    if (!runningRef.current || generation !== generationRef.current) return;
    const video = videoRef.current;
    if (video && video.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA && !video.seeking) {
      try {
        const detections = (await detector.detect(video, 20, 0.5)).filter(item => item.class === "person");
        if (runningRef.current && generation === generationRef.current) {
          draw(detections, video); setPeople(detections.length); setSampledAt(video.currentTime);
        }
      } catch {
        if (generation === generationRef.current) { stop(); setError("Person detection failed on this frame. Try another clip or browser."); }
        return;
      }
    }
    if (runningRef.current && generation === generationRef.current) {
      timerRef.current = window.setTimeout(() => void scan(generation, detector), 1000);
    }
  };
  const start = async () => {
    if (!videoRef.current || videoRef.current.readyState < HTMLMediaElement.HAVE_METADATA) {
      setError("Wait until the selected video loads before starting detection."); return;
    }
    const generation = ++generationRef.current;
    setError(""); setPhase("loading");
    try {
      const detector = await loadDetector();
      if (generation !== generationRef.current) return;
      runningRef.current = true; setPhase("running");
      void scan(generation, detector);
    } catch {
      if (generation === generationRef.current) { setPhase("idle"); setError("The bundled person detector could not load. Check the local model files and try again."); }
    }
  };

  return <main className="guard-workspace" aria-label="Video test">
    <div className="guard-workspace-heading"><div><small>RECORDED VIDEO TEST</small><h1>Upload and test a video</h1></div><span>MP4 or WebM · up to 100 MB</span></div>
    <p className="guard-workspace-note">Choose a clip from this computer or load the bundled sample. The file stays in this browser. Run the bundled pretrained person detector on sampled frames to see real bounding boxes.</p>
    <div className="guard-video-controls"><label htmlFor="guard-video-upload">Choose video from computer</label><input id="guard-video-upload" type="file" accept="video/mp4,video/webm,.mp4,.webm" onChange={event => choose(event.target.files?.[0])} />
      <button type="button" disabled={loading} onClick={() => void sample()}>{loading ? "Loading sample…" : "Load bundled sample clip"}</button>
      <button type="button" disabled={!url || phase === "loading"} onClick={() => phase === "running" ? stop() : void start()}>{phase === "loading" ? "Loading model…" : phase === "running" ? "Stop detection" : "Run person detection"}</button></div>
    {error && <p role="alert" className="guard-action-error">{error}</p>}
    <div className="guard-video-player">{url ? <><video ref={videoRef} key={url} src={url} controls playsInline onLoadedMetadata={event => setDuration(event.currentTarget.duration)} onError={() => setError("This browser cannot play the selected video encoding.")} /><canvas ref={canvasRef} aria-hidden="true" /></> : <div>No video selected</div>}
      <span>RECORDED / TEST VIDEO</span></div>
    {name && <div className="guard-video-meta"><strong>{name}</strong><span>{duration != null && Number.isFinite(duration) ? `${duration.toFixed(1)} seconds` : "Loading duration"}</span></div>}
    <div className="guard-video-disclosure"><strong>{phase === "running" ? `People in sampled frame: ${people ?? "analyzing"}` : "Person detection: ready to test"}</strong>
      <p>{sampledAt != null ? `Last analyzed at ${sampledAt.toFixed(1)} seconds. ` : ""}Pretrained COCO-SSD baseline, sampled about once per second. It can miss people or draw false boxes. This is not a trained DARSON model, an accuracy score, a restriction-zone decision, or a guard alert.</p></div>
  </main>;
}
