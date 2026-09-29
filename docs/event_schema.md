# Canonical Event Schema

Both the mock source and the Frigate adapter normalize to this identical shape,
so downstream stages never branch on the source.

```json
{
  "event_id": "uuid",
  "source": { "type": "mock | frigate", "source_event_id": "..." },
  "camera_id": "gate_3",
  "track": { "local_id": "A1" },
  "event_type": "detection | zone_enter | zone_exit | loiter | dwell",
  "label": "person",
  "sub_label": "red_bag",
  "confidence": 0.9,
  "time": { "start": 0.0, "end": 6.0, "observed": 1.0 },
  "spatial": {
    "bbox": [x1, y1, x2, y2],
    "region": [x1, y1, x2, y2],
    "zones": ["restricted"],
    "velocity_angle": 90,
    "avg_speed": 1.2
  },
  "evidence": {
    "has_clip": true,
    "has_snapshot": true,
    "snapshot_url": "...",
    "clip_url": "..."
  },
  "embedding_ref": null,
  "raw_json": { }
}
```

## Frigate mapping (`frigate/events`)
- Uses the `after` object; finalizes on `type: "end"`.
- `event_type` derived from `entered_zones` / `stationary` / `motionless_count`
  (motionless ≥ 30 → loiter, ≥ 60 → dwell).
- `sub_label` flattened from Frigate's `[name, score]` pairs.
- Evidence URLs built from `{FRIGATE_API_BASE}/api/events/{id}/snapshot.jpg|clip.mp4`.

## Mock mapping
- Canonical-ish scenario dicts; relative times shifted by a base epoch.
- Evidence URLs synthesized as `/mock-evidence/{camera}/{track}/...` when flags set,
  so Incident → Event → Camera → Evidence traceability is demonstrable offline.
