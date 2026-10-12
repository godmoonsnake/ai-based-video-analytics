"""Evaluate the operations lead's targets; empty targets cannot produce a pass.

python scripts/pilot_acceptance.py --targets docs/pilot/acceptance.template.json
    --trials path/to/trials.csv --monitoring path/to/monitoring.csv --output pilot-results.json
"""
import argparse
import csv
import json
import math
from pathlib import Path


def p95(values):
    ordered = sorted(values)
    return ordered[math.ceil(.95 * len(ordered)) - 1] if ordered else None


def number(value):
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise ValueError("measurements must be finite and nonnegative")
    return result


def evaluate(targets, trials, monitoring):
    if not targets.get("signed_reference") or not targets.get("operations_lead"):
        raise ValueError("operations lead and signed target reference are required")
    required = targets.get("conditions")
    if not isinstance(required, list) or not required or len(set(required)) != len(required):
        raise ValueError("list the distinct required test conditions")
    fields = ("min_repetitions_per_condition", "detection_rate_min", "p95_alert_seconds_max",
              "p95_acknowledgement_seconds_max", "false_alerts_per_camera_hour_max", "min_monitored_camera_hours")
    limits = {key: number(targets[key]) for key in fields}
    if not 0 < limits["detection_rate_min"] <= 1 or limits["min_repetitions_per_condition"] < 1 or limits["min_monitored_camera_hours"] <= 0:
        raise ValueError("invalid detection rate, repetition count or monitored duration")
    if len({row["test_id"] for row in trials}) != len(trials):
        raise ValueError("duplicate staged test IDs")
    if len({row["session_id"] for row in monitoring}) != len(monitoring):
        raise ValueError("duplicate monitoring session IDs")
    reports = []
    for condition in required:
        rows = [row for row in trials if row["condition"] == condition]
        if any(row["detected"] not in {"0", "1"} for row in rows):
            raise ValueError("detected must be 0 or 1")
        detected = [row for row in rows if row["detected"] == "1"]
        latency = [number(row["alert_latency_seconds"]) for row in detected if row["alert_latency_seconds"].strip()]
        ack = [number(row["acknowledgement_seconds"]) for row in detected if row["acknowledgement_seconds"].strip()]
        rate = len(detected) / len(rows) if rows else 0
        passed = (len(rows) >= limits["min_repetitions_per_condition"] and rate >= limits["detection_rate_min"] and
                  len(latency) == len(detected) and len(ack) == len(detected) and bool(detected) and
                  p95(latency) <= limits["p95_alert_seconds_max"] and p95(ack) <= limits["p95_acknowledgement_seconds_max"])
        reports.append({"condition": condition, "trials": len(rows), "detected": len(detected),
                        "detection_rate": rate, "p95_alert_seconds": p95(latency),
                        "p95_acknowledgement_seconds": p95(ack), "passed": passed})
    hours = sum(number(row["monitored_camera_hours"]) for row in monitoring)
    false_alerts = sum(number(row["false_alerts"]) for row in monitoring)
    false_rate = false_alerts / hours if hours else None
    monitoring_passed = hours >= limits["min_monitored_camera_hours"] and false_rate is not None and false_rate <= limits["false_alerts_per_camera_hour_max"]
    return {"operations_lead": targets["operations_lead"], "signed_reference": targets["signed_reference"],
            "conditions": reports, "monitored_camera_hours": hours, "false_alerts": false_alerts,
            "false_alerts_per_camera_hour": false_rate, "monitoring_passed": monitoring_passed,
            "passed": all(row["passed"] for row in reports) and monitoring_passed,
            "latency_denominator": "detected staged violations; misses are reported in detection_rate",
            "note": "Staged detection rate is not a claim of general detector accuracy."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--targets", required=True)
    parser.add_argument("--trials", required=True)
    parser.add_argument("--monitoring", required=True)
    parser.add_argument("--output", default="pilot-results.json")
    args = parser.parse_args()
    try:
        with open(args.trials, newline="", encoding="utf-8") as stream:
            trials = list(csv.DictReader(stream))
        with open(args.monitoring, newline="", encoding="utf-8") as stream:
            monitoring = list(csv.DictReader(stream))
        report = evaluate(json.loads(Path(args.targets).read_text(encoding="utf-8")), trials, monitoring)
    except (ValueError, TypeError, KeyError) as error:
        parser.error(f"incomplete or invalid acceptance data: {error}")
    Path(args.output).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("PASS" if report["passed"] else "FAIL — review the report")
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
