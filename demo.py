"""DARSON demo driver — exercises the full pipeline over the HTTP API.

Usage:
    # start the backend first, e.g.:
    #   cd backend && uvicorn app.main:app
    python demo.py            # uses http://localhost:8000
    python demo.py http://host:8000

Runs EVENT -> CONTEXT -> CORRELATION -> INCIDENT -> HISTORY -> INVESTIGATION
and prints a human-readable trace. Decision support only — no verdicts.
"""
from __future__ import annotations

import sys
import urllib.request
import json

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"


def _req(method: str, path: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f"{BASE}{path}", data=data, method=method,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read().decode())


def main() -> None:
    print(f"DARSON demo against {BASE}\n")

    print("health:", _req("GET", "/health"))

    print("\n[EVENT] ingesting mock scenario…")
    print(" ", _req("POST", "/events/ingest/mock"))

    print("\n[CONTEXT] behavioural sequence for restricted-dwell track C3:")
    seq = _req("GET", "/tracks/C3/sequence")
    print("  signature:", seq["signature"], "| anomaly:", seq["anomaly_score"])
    print("  reasons:", seq["reasons"])

    print("\n[CORRELATION] stitching cross-camera global tracks…")
    _req("POST", "/tracks/correlate")
    for g in _req("GET", "/tracks/global"):
        if len(g["members"]) > 1:
            path = " -> ".join(m["camera_id"] for m in g["members"])
            print(f"  global #{g['global_track_id']}: {path} (conf {g['confidence']})")

    print("\n[INCIDENT] building incidents…")
    build = _req("POST", "/incidents/build")
    inc_id = build["incident_ids"][0]
    detail = _req("GET", f"/incidents/{inc_id}")
    print(f"  incident #{inc_id} priority={detail['priority']} cameras={detail['cameras']}")
    print("  timeline:")
    for step in detail["timeline"]:
        clip = step["evidence"].get("clip_url", "")
        print(f"    {step['camera_id']:<12} {step['event_type']:<10} role={step['role']} {clip}")

    print("\n[HISTORY] mining patterns…")
    _req("POST", "/patterns/mine")
    for h in _req("GET", "/patterns?pattern_type=hotspot"):
        print(f"  hotspot {h['key']['camera_id']} count={h['count']} score={h['score']}")

    print("\n[INVESTIGATION] NL query: 'red bag near Gate 3 yesterday'")
    s = _req("POST", "/search", {"q": "red bag near Gate 3 yesterday"})
    print("  parsed filter:", s["parsed_filter"])
    print("  human_review_required:", s["human_review_required"])

    print("\nDone. All results are decision support and require human review.")


if __name__ == "__main__":
    main()
