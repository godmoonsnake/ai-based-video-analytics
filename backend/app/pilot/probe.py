"""Read-only live Frigate/MQTT diagnostic; never stores footage or credentials.

Run on the site node: python -m app.pilot.probe --seconds 60 --output /tmp/probe.json
Results measure source timing and hardware load, not detection accuracy.
"""

import argparse
import hashlib
import json
import math
from pathlib import Path
import threading
import time
import httpx
import paho.mqtt.client as mqtt
from app.config import get_settings


def sample(message, arrived):
    obj = message.get("after") or message.get("before") or {}
    return {
        "track": hashlib.sha256(str(obj.get("id", "")).encode()).hexdigest()[:20],
        "camera_id": obj.get("camera"),
        "kind": message.get("type"),
        "source_time": obj.get("frame_time"),
        "arrived_at": arrived,
        "current_zones": obj.get("current_zones", []),
        "has_box": bool(obj.get("box")),
        "position_history_samples": len(obj.get("path_data") or []),
        "person": obj.get("label") == "person",
    }


def summarize(samples):
    last, gaps = {}, []
    for value in samples:
        key = (value["camera_id"], value["track"])
        if key in last:
            gaps.append(value["arrived_at"] - last[key])
        last[key] = value["arrived_at"]
    ordered = sorted(gaps)
    return {
        "messages": len(samples),
        "tracks": len(last),
        "p95_same_track_message_gap_seconds": ordered[
            math.ceil(0.95 * len(ordered)) - 1
        ]
        if ordered
        else None,
        "messages_with_position_history": sum(
            row["position_history_samples"] > 0 for row in samples
        ),
        "note": "MQTT updates are not guaranteed frame samples; these observations do not prove line-crossing reliability.",
    }


def hardware_snapshot(settings):
    headers = (
        {"Cookie": f"frigate_token={settings.frigate_api_token}"}
        if settings.frigate_api_token
        else {}
    )
    with httpx.Client(
        timeout=10, follow_redirects=False, trust_env=False, headers=headers
    ) as client:
        version = client.get(settings.frigate_api_base.rstrip("/") + "/api/version")
        version.raise_for_status()
        stats = client.get(settings.frigate_api_base.rstrip("/") + "/api/stats")
        stats.raise_for_status()
        data = stats.json()
    camera_keys = ("camera_fps", "process_fps", "skipped_fps", "detection_fps")
    return {
        "version": version.text[:100],
        "cameras": {
            name: {key: values.get(key) for key in camera_keys}
            for name, values in data.get("cameras", {}).items()
        },
        "detectors": {
            name: {"inference_speed": values.get("inference_speed")}
            for name, values in data.get("detectors", {}).items()
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=int, default=60)
    parser.add_argument("--output", default="pilot-event-probe.json")
    args = parser.parse_args()
    if not 10 <= args.seconds <= 3600:
        parser.error("duration must be between 10 and 3600 seconds")
    settings = get_settings()
    lock, samples, errors, connected = threading.Lock(), [], [], threading.Event()
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    if settings.mqtt_username:
        client.username_pw_set(settings.mqtt_username, settings.mqtt_password)
    if settings.mqtt_tls:
        client.tls_set()

    def on_connect(client, userdata, flags, reason_code, properties):
        if reason_code == 0:
            client.subscribe(settings.frigate_mqtt_topic, qos=1)
            connected.set()
        else:
            errors.append("broker_authentication_failed")

    def on_message(client, userdata, message):
        try:
            value = sample(json.loads(message.payload), time.time())
            with lock:
                if len(samples) < 50000:
                    samples.append(value)
                elif "sample_limit_reached" not in errors:
                    errors.append("sample_limit_reached")
        except (ValueError, TypeError, AttributeError):
            errors.append("invalid_payload")

    client.on_connect, client.on_message = on_connect, on_message
    try:
        hardware_before = hardware_snapshot(settings)
        client.connect(settings.frigate_mqtt_host, settings.frigate_mqtt_port)
        client.loop_start()
        if not connected.wait(10):
            raise RuntimeError("broker connection unavailable")
        # The operator runs this bounded command; it is not an assistant sleep.
        threading.Event().wait(args.seconds)
        hardware_after = hardware_snapshot(settings)
    except Exception as error:
        parser.error(
            f"probe failed: {type(error).__name__}; inspect source reachability and credentials"
        )
    finally:
        client.disconnect()
        client.loop_stop()
    report = {
        "hardware_before": hardware_before,
        "hardware_after": hardware_after,
        "summary": summarize(samples),
        "samples": samples,
        "errors": errors,
    }
    Path(args.output).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(
        f"Recorded {len(samples)} lifecycle messages. Review the local report; no footage was captured."
    )


if __name__ == "__main__":
    main()
