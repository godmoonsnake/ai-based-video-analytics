import numpy as np
from app.operations.camera_health import analyze_frame, classify_components


def textured_frame(seed=1):
    return np.random.default_rng(seed).integers(30, 220, size=(48, 64, 3), dtype=np.uint8)


def test_source_alive_recording_missing_is_not_camera_uptime():
    result = classify_components(True, 25.0, "healthy", False, 1.0)
    assert result == {"state": "degraded", "stream_state": "healthy",
        "recording_state": "degraded", "evidence_state": "healthy", "maintenance": False}


def test_recording_alive_evidence_failed_is_separate():
    result = classify_components(True, 25, "healthy", True, .5)
    assert result["stream_state"] == "healthy" and result["recording_state"] == "healthy"
    assert result["evidence_state"] == "degraded" and result["state"] == "degraded"


def test_source_silence_is_offline_and_unknown_probe_is_unknown():
    assert classify_components(False, None, "unknown", None, None)["state"] == "offline"
    assert classify_components(None, None, "unknown", None, None)["state"] == "unknown"


def test_static_scene_is_not_freeze_without_source_fps_and_staleness():
    image = textured_frame()
    prior = analyze_frame(image)["frame_hash"]
    result = analyze_frame(image, prior, repeated_for=3600, source_fps=25, source_stale=False)
    assert result["static_scene"] is True
    assert result["freeze"] is False


def test_confirmed_freeze_requires_unchanged_frame_low_fps_and_debounce():
    image = textured_frame()
    prior = analyze_frame(image)["frame_hash"]
    before_debounce = analyze_frame(image, prior, repeated_for=60, source_fps=0, source_stale=True)
    after_debounce = analyze_frame(image, prior, repeated_for=180, source_fps=0, source_stale=True)
    assert before_debounce["freeze"] is False
    assert after_debounce["freeze"] is True and after_debounce["video_state"] == "degraded"


def test_blank_dark_blurry_and_recovery_signals():
    black = analyze_frame(np.zeros((48, 64, 3), dtype=np.uint8))
    assert black["black"] and black["dark"]
    dark = analyze_frame(np.full((48, 64, 3), 10, dtype=np.uint8))
    assert dark["dark"]
    blank = analyze_frame(np.full((48, 64, 3), 180, dtype=np.uint8))
    assert blank["blur"]
    good = analyze_frame(textured_frame(2), source_fps=24)
    assert good["video_state"] == "healthy"
    recovered = classify_components(True, 24, good["video_state"], True, 1.0)
    assert recovered["state"] == "healthy"


def test_maintenance_suppresses_offline_alarm_state_but_preserves_signal():
    result = classify_components(False, 0, "unknown", None, None, maintenance=True)
    assert result["state"] == "unknown" and result["stream_state"] == "offline" and result["maintenance"]
