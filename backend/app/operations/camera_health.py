"""Camera/source/recording/evidence health are separate operational signals."""

import hashlib
import time
import uuid
from urllib.parse import quote
import httpx
import numpy as np
from sqlalchemy import select, func
from app.config import get_settings
from app.models.entities import Camera, Event, Incident, IncidentEvent
from app.models.evidence import EvidenceObject
from app.models.operations import (
    CameraHealthCurrent,
    CameraHealthSample,
    MaintenanceWindow,
)


def analyze_frame(
    frame,
    previous_hash=None,
    repeated_for=0,
    source_fps=None,
    source_stale=False,
    offline_after=60,
    freeze_debounce=120,
):
    if frame is None:
        return {
            "state": "unknown",
            "video_state": "unknown",
            "freeze": False,
            "black": False,
            "dark": False,
            "blur": False,
            "frame_hash": None,
        }
    array = np.asarray(frame, dtype=np.uint8)
    if array.size == 0:
        return {
            "state": "unknown",
            "video_state": "unknown",
            "freeze": False,
            "black": False,
            "dark": False,
            "blur": False,
            "frame_hash": None,
        }
    gray = array.mean(axis=2) if array.ndim == 3 else array
    mean = float(gray.mean())
    black_ratio = float(np.mean(gray <= 4))
    grad_x = (
        np.diff(gray.astype(np.float32), axis=1)
        if gray.ndim == 2 and gray.shape[1] > 1
        else np.zeros(1)
    )
    grad_y = (
        np.diff(gray.astype(np.float32), axis=0)
        if gray.ndim == 2 and gray.shape[0] > 1
        else np.zeros(1)
    )
    gradient_energy = float((np.mean(grad_x * grad_x) + np.mean(grad_y * grad_y)) / 2)
    frame_hash = hashlib.sha256(array.tobytes()).hexdigest()
    black, dark, blur = black_ratio > 0.90, mean < 16, gradient_energy < 2.0
    same = previous_hash is not None and frame_hash == previous_hash
    # A visually static scene alone is not a freeze: source FPS and stale-source
    # debounce must corroborate an unchanged frame before marking one.
    freeze = bool(
        same
        and source_fps is not None
        and source_fps < 0.5
        and source_stale
        and repeated_for >= freeze_debounce
    )
    video_state = "degraded" if black or dark or blur or freeze else "healthy"
    return {
        "state": "degraded" if video_state == "degraded" else "healthy",
        "video_state": video_state,
        "freeze": freeze,
        "black": black,
        "dark": dark,
        "blur": blur,
        "brightness_mean": round(mean, 2),
        "black_pixel_ratio": round(black_ratio, 4),
        "gradient_energy": round(gradient_energy, 3),
        "frame_hash": frame_hash,
        "static_scene": same,
    }


def classify_components(
    source_available,
    source_fps,
    video_state,
    recording_available,
    evidence_rate,
    recording_expected=True,
    maintenance=False,
):
    stream = (
        "unknown"
        if source_available is None
        else "offline"
        if not source_available or source_fps is not None and source_fps < 0.01
        else "healthy"
    )
    recording = (
        "unknown"
        if recording_available is None
        else "healthy"
        if recording_available
        else "degraded"
        if recording_expected
        else "unknown"
    )
    evidence = (
        "unknown"
        if evidence_rate is None
        else "healthy"
        if evidence_rate >= 0.95
        else "degraded"
    )
    if maintenance:
        overall = "unknown"
    elif stream == "offline":
        overall = "offline"
    elif video_state == "degraded" or recording == "degraded" or evidence == "degraded":
        overall = "degraded"
    elif stream == video_state == recording == evidence == "healthy":
        overall = "healthy"
    else:
        overall = "unknown"
    return {
        "state": overall,
        "stream_state": stream,
        "recording_state": recording,
        "evidence_state": evidence,
        "maintenance": maintenance,
    }


def _source_data(camera_id):
    settings = get_settings()
    base = settings.frigate_api_base.rstrip("/")
    headers = (
        {"Cookie": f"frigate_token={settings.frigate_api_token}"}
        if settings.frigate_api_token
        else {}
    )
    with httpx.Client(
        timeout=8, follow_redirects=False, trust_env=False, headers=headers
    ) as client:
        stats_response = client.get(base + "/api/stats")
        stats_response.raise_for_status()
        camera_stats = stats_response.json().get("cameras", {}).get(camera_id)
        if not camera_stats:
            return {"available": False, "error": "camera_missing_from_source"}
        frame_response = client.get(
            f"{base}/api/{quote(camera_id, safe='')}/latest.jpg"
        )
        frame_response.raise_for_status()
        from PIL import Image
        import io

        frame = np.asarray(
            Image.open(io.BytesIO(frame_response.content))
            .convert("RGB")
            .resize((160, 90))
        )
        now = time.time()
        recordings = client.get(
            f"{base}/api/{quote(camera_id, safe='')}/recordings",
            params={"after": int(now - 300), "before": int(now)},
        )
        recordings.raise_for_status()
        recording_rows = recordings.json() if recordings.is_success else None
        return {
            "available": True,
            "camera_fps": float(camera_stats.get("camera_fps", 0) or 0),
            "record_fps": float(camera_stats.get("record_fps", 0) or 0),
            "frame": frame,
            "recording_available": bool(recording_rows)
            if recording_rows is not None
            else None,
            "source_checked_at": now,
        }


def probe_site(db, probe=_source_data, now=None):
    now = time.time() if now is None else now
    settings = get_settings()
    scope = db.info["scope"]
    cameras = db.scalars(select(Camera).order_by(Camera.id)).all()
    output = []
    for camera in cameras:
        identifier = hashlib.sha256(
            f"{scope.tenant}\0{scope.site}\0{camera.id}".encode()
        ).hexdigest()
        current = db.get(CameraHealthCurrent, identifier)
        previous = (current.metrics or {}) if current else {}
        try:
            result = probe(camera.id)
        except Exception as exc:
            result = {"available": False, "error": type(exc).__name__}
        if result.get("available"):
            fps = result.get("camera_fps")
            previous_hash = previous.get("frame_hash")
            repeated_for = (
                (
                    float(previous.get("same_frame_since", now))
                    and max(0, now - previous.get("same_frame_since", now))
                )
                if previous_hash
                == analyze_frame(result.get("frame"), source_fps=fps).get("frame_hash")
                else 0
            )
            video = analyze_frame(
                result.get("frame"),
                previous_hash,
                repeated_for,
                fps,
                source_stale=(fps is not None and fps < 0.5),
                offline_after=settings.health_offline_after_seconds,
                freeze_debounce=settings.health_freeze_debounce_seconds,
            )
            metrics = {
                **video,
                "frame_arrival_fps": fps,
                "record_fps": result.get("record_fps"),
                "same_frame_since": previous.get("same_frame_since", now)
                if video.get("static_scene")
                else now,
                "recording_checked_at": now,
            }
            stream_state = "offline" if fps is not None and fps < 0.01 else "healthy"
            if result.get("recording_available") is None:
                recording_state = "unknown"
            elif result.get("recording_available"):
                recording_state = "healthy"
            else:
                recording_state = (
                    "degraded" if settings.health_recording_expected else "unknown"
                )
            last_frame = (
                now
                if fps is not None and fps > 0
                else (current.last_frame_at if current else None)
            )
            recording_gap = (
                max(0, now - (current.last_recording_at or now))
                if current and recording_state != "healthy"
                else 0
            )
            last_recording = (
                now
                if recording_state == "healthy"
                else (current.last_recording_at if current else None)
            )
        else:
            metrics = {
                "error_class": result.get("error", "source_unavailable"),
                "frame_hash": previous.get("frame_hash"),
            }
            fps, last_frame, last_recording, recording_gap = (
                None,
                current.last_frame_at if current else None,
                current.last_recording_at if current else None,
                max(0, now - (current.last_recording_at or now)) if current else None,
            )
            stream_state, video, recording_state = (
                "offline",
                {"video_state": "unknown"},
                "unknown",
            )
        events_24h = (
            db.scalar(
                select(func.count())
                .select_from(EvidenceObject)
                .where(
                    EvidenceObject.event_id.in_(
                        select(Event.id).where(Event.camera_id == camera.id)
                    ),
                    EvidenceObject.created_at >= now - 86400,
                )
            )
            or 0
        )
        available_24h = (
            db.scalar(
                select(func.count())
                .select_from(EvidenceObject)
                .where(
                    EvidenceObject.event_id.in_(
                        select(Event.id).where(Event.camera_id == camera.id)
                    ),
                    EvidenceObject.created_at >= now - 86400,
                    EvidenceObject.status == "available",
                )
            )
            or 0
        )
        evidence_rate = available_24h / events_24h if events_24h else None
        evidence_state = (
            "unknown"
            if not events_24h
            else "healthy"
            if evidence_rate >= 0.95
            else "degraded"
        )
        maintenance = (
            db.scalar(
                select(MaintenanceWindow.id)
                .where(
                    (MaintenanceWindow.camera_id == camera.id)
                    | (MaintenanceWindow.camera_id.is_(None)),
                    MaintenanceWindow.starts_at <= now,
                    MaintenanceWindow.ends_at > now,
                )
                .limit(1)
            )
            is not None
        )
        classification = classify_components(
            result.get("available"),
            fps,
            video.get("video_state", "unknown"),
            result.get("recording_available"),
            evidence_rate,
            settings.health_recording_expected,
            maintenance,
        )
        state, stream_state = classification["state"], classification["stream_state"]
        recording_state, evidence_state = (
            classification["recording_state"],
            classification["evidence_state"],
        )
        lag_rows = db.scalars(
            select(Event)
            .where(Event.camera_id == camera.id, Event.ts >= now - 86400)
            .limit(500)
        ).all()
        lag_values = [
            e.received_at - e.ts
            for e in lag_rows
            if e.received_at is not None and e.ts is not None
        ]
        latency_rows = db.execute(
            select(Incident.created_at, Event.received_at)
            .join(IncidentEvent, IncidentEvent.incident_id == Incident.id)
            .join(Event, Event.id == IncidentEvent.event_id)
            .where(Event.camera_id == camera.id, Event.received_at.is_not(None))
        ).all()
        incident_latencies = [
            max(0, created.timestamp() - received)
            for created, received in latency_rows
            if created is not None and received is not None
        ]
        latency = (
            sum(incident_latencies) / len(incident_latencies)
            if incident_latencies
            else None
        )
        source_lag = sum(lag_values) / len(lag_values) if lag_values else None
        video_state = video.get("video_state", "unknown")
        values = dict(
            id=identifier,
            tenant_id=scope.tenant,
            site_id=scope.site,
            camera_id=camera.id,
            state=state,
            stream_state=stream_state,
            video_state=video_state,
            recording_state=recording_state,
            evidence_state=evidence_state,
            maintenance=maintenance,
            frame_arrival_fps=fps,
            source_to_darson_lag_seconds=source_lag,
            event_to_incident_latency_seconds=latency,
            recording_gap_seconds=recording_gap,
            evidence_capture_success_rate=evidence_rate,
            last_frame_at=last_frame,
            last_recording_at=last_recording,
            last_evidence_at=db.scalar(
                select(func.max(EvidenceObject.captured_at)).where(
                    EvidenceObject.event_id.in_(
                        select(Event.id).where(Event.camera_id == camera.id)
                    ),
                    EvidenceObject.status == "available",
                )
            ),
            updated_at=now,
            metrics=metrics,
        )
        metrics.update(
            {
                "source_to_darson_lag_seconds": source_lag,
                "event_to_incident_latency_seconds": latency,
                "recording_gap_seconds": recording_gap,
                "evidence_capture_success_rate": evidence_rate,
            }
        )
        if current:
            for key, value in values.items():
                setattr(current, key, value)
        else:
            current = CameraHealthCurrent(**values)
            db.add(current)
        db.add(
            CameraHealthSample(
                id=uuid.uuid4().hex,
                tenant_id=scope.tenant,
                site_id=scope.site,
                camera_id=camera.id,
                checked_at=now,
                state=state,
                stream_state=stream_state,
                video_state=video_state,
                recording_state=recording_state,
                evidence_state=evidence_state,
                maintenance=maintenance,
                metrics=metrics,
            )
        )
        output.append(
            {
                "camera_id": camera.id,
                "state": state,
                "stream_state": stream_state,
                "video_state": video_state,
                "recording_state": recording_state,
                "evidence_state": evidence_state,
                "maintenance": maintenance,
                "metrics": metrics,
            }
        )
    db.commit()
    return output
