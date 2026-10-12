"""Rules for pilot observations. Detector outputs remain unverified signals."""
from __future__ import annotations

import time

from sqlalchemy import select

from app.models.case_studies import CasePolicy
from app.processing.jobs import digest


def _policies(db, kind: str, subject: str, zone: str, at: float):
    return [p for p in db.scalars(select(CasePolicy).where(
        CasePolicy.kind == kind, CasePolicy.subject == subject)).all()
        if (p.zone is None or p.zone == zone)
        and (p.valid_from is None or p.valid_from <= at)
        and (p.valid_until is None or at <= p.valid_until)]


def _grant(db, kind: str, subject: str, zone: str, principal: str | None, at: float):
    if not principal:
        return False
    return any(p.allowed and p.principal == principal
               for p in _policies(db, kind, subject, zone, at))


def _driver_grant(db, plate: str, zone: str, principal: str | None, at: float):
    """An explicit active vehicle-driver denial overrides an allowance."""
    if not principal:
        return False
    matching = [p for p in _policies(db, "vehicle", plate, zone, at)
                if p.principal == principal]
    return bool(matching) and all(p.allowed for p in matching)


def policy_snapshot(db, body):
    kind = body.kind
    if kind == "restricted_reading":
        pairs = [("material", body.item_id), ("material_access", body.item_id)]
    elif kind == "material_change":
        pairs = [("asset", body.item_id), ("asset_transfer", body.item_id)]
    elif kind in {"smoking", "drinking"}:
        pairs = [("prohibited_activity", kind)]
    elif kind == "restricted_entry":
        pairs = [("restricted_zone", body.zone), ("area_access", body.zone)]
    elif kind.startswith("parking_"):
        pairs = [("vehicle", (body.plate or "").upper().replace(" ", "").replace("-", ""))]
    else:
        pairs = [("vehicle", (body.plate or "").upper().replace(" ", "").replace("-", ""))]
    matched = [p for policy_kind, subject in pairs if subject
               for p in _policies(db, policy_kind, subject, body.zone, body.observed_at)]
    rules = [{"id": p.id, "kind": p.kind, "subject": p.subject, "zone": p.zone,
              "principal": p.principal, "allowed": p.allowed,
              "valid_from": p.valid_from, "valid_until": p.valid_until}
             for p in sorted(matched, key=lambda item: item.id)]
    return {"version": f"case-policy-v1:{digest(rules)[:12]}",
            "matched_policy_ids": [rule["id"] for rule in rules], "rules": rules}


def decide(db, body):
    """Return (decision, reason, priority). Never infer identity or intoxication."""
    kind, zone, at = body.kind, body.zone, body.observed_at
    if kind == "restricted_reading":
        if not body.item_id or not _policies(db, "material", body.item_id, zone, at):
            return "unverified", "Item is not in the restricted material register", None
        if body.source_type == "document_access" and _grant(db, "material_access", body.item_id, zone, body.principal_ref, at):
            return "allowed", "Matching material access grant", None
        return "review", "Restricted item observed without a matching access grant", "high"
    if kind == "material_change":
        if not body.item_id or not _policies(db, "asset", body.item_id, zone, at):
            return "unverified", "Asset is not in the protected asset register", None
        if body.action not in {"removed", "replaced"}:
            return "unverified", "Removal or replacement action required", None
        if body.source_type == "asset_custody" and _grant(db, "asset_transfer", body.item_id, zone, body.principal_ref, at):
            return "allowed", "Matching asset transfer grant", None
        return "review", f"Protected asset {body.action} without a matching transfer grant", "high"
    if kind in {"smoking", "drinking"}:
        if not _policies(db, "prohibited_activity", kind, zone, at):
            return "unverified", "No matching restricted-area activity policy", None
        reason = "Suspected smoking in a prohibited zone" if kind == "smoking" else \
            "Suspected drinking in a prohibited zone; beverage contents unknown"
        return "review", reason, "medium"
    if kind == "restricted_entry":
        if not _policies(db, "restricted_zone", zone, zone, at):
            return "unverified", "Zone is not registered as restricted", None
        if body.source_type == "access_control" and _grant(db, "area_access", zone, zone, body.principal_ref, at):
            return "allowed", "Matching area access grant", None
        return "review", "Entry observed without a matching access grant", "high"
    if kind == "parking_exit":
        return "allowed", "Person track observed exiting vehicle; identity unverified", None
    if kind == "parking_authorization":
        plate = (body.plate or "").upper().replace(" ", "").replace("-", "")
        if _driver_grant(db, plate, zone, body.principal_ref, at):
            return "allowed", "Approved driver credential matched the vehicle register", None
        return "unverified", "Credential has no matching vehicle driver grant", None
    if kind == "parking_approach":
        if body.action == "registry_authorized":
            return "allowed", "Approved driver credential linked to this camera track", None
        if body.action == "baseline_only":
            return "unverified", "Exit-track appearance matches, but registered driver credential is absent", None
        if body.action == "different":
            return "review", "Yellow review: person appearance differs from observed exit tracks; identity unverified", "medium"
        if body.action == "same":
            return "allowed", "Detector reports similar appearance; identity unverified", None
        return "unverified", "Appearance comparison is inconclusive", None
    if kind == "parking_interaction":
        if body.action in {"door_tamper", "trunk_tamper", "forced_entry", "damage",
                           "object_removal", "door_handle", "trunk_handle", "loitering"}:
            return "review", f"Vehicle interaction observed ({body.action}); guard verification required", "high"
        return "unverified", "No configured vehicle interaction rule", None
    if kind == "parking_departure":
        return "allowed", "Vehicle departure closes parking session", None
    if kind == "vehicle_plate":
        plate = (body.plate or "").upper().replace(" ", "").replace("-", "")
        if not plate or not body.vehicle_type:
            return "unverified", "Plate text and car/bike type required", None
        if body.confidence is None or body.confidence < 0.85:
            return "review", "Plate read needs manual verification", "medium"
        if any(p.allowed for p in _policies(db, "vehicle", plate, zone, at)):
            return "allowed", "Vehicle permit matches the plate and access window", None
        return "review", "No active vehicle permit matches the observed plate", "high"
    raise ValueError("unsupported case study")


def alert_text(incident, observation):
    # Sensitive content stays behind the authenticated incident endpoint.
    if observation.kind == "parking_interaction":
        action = str(observation.signal.get("action", "vehicle interaction")).replace("_", " ")
        return (f"DARSON parking case #{incident.id}: possible {action}. "
                f"Zone: {observation.zone}. Camera: {observation.camera_id}. "
                f"Time: {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime(observation.observed_at))}. "
                "Floor guard and security: verify in the incident console and acknowledge response.")
    return (f"DARSON case #{incident.id}: {observation.kind.replace('_', ' ')}. "
            f"Zone: {observation.zone}. Time: {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime(observation.observed_at))}. "
            "Review in the DARSON incident console.")
