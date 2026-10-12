"""Incident lifecycle state machine (human-in-the-loop).

Minimal, explicit review lifecycle:

    open ──start_triage──▶ triage ──confirm──▶ confirmed
      │                      │
      │                      └──dismiss──▶ dismissed
      └──dismiss──▶ dismissed         (dismiss a raw incident without triage)

    confirmed/dismissed ──reopen──▶ open   (recoverable review decision)

Rules:
  - State is persisted on Incident.status.
  - Transitions are EXPLICIT actions; invalid transitions are rejected with a
    clear error (InvalidTransition) and no state change.
  - Every accepted transition is appended to incident_state_transition with a
    timestamp, the action, and optional reviewer handle/role + note.
  - A transition NEVER mutates the incident graph, nodes, edges, or evidence —
    it only changes status and appends a history row. This keeps the evidence
    immutable across review decisions.

`reviewer` is an operator handle or role label (e.g. "operator", "shift_lead"),
not a personal identity. No PII is required or stored beyond that optional label.
"""
from __future__ import annotations

from sqlalchemy.orm import Session
from sqlalchemy import update

from app.models.entities import AuditLog, Incident, IncidentStateTransition

# Canonical lifecycle states.
OPEN = "open"
TRIAGE = "triage"
CONFIRMED = "confirmed"
DISMISSED = "dismissed"
STATES = (OPEN, TRIAGE, CONFIRMED, DISMISSED)

# action -> (allowed from-states, resulting to-state)
TRANSITIONS: dict[str, tuple[tuple[str, ...], str]] = {
    "start_triage": ((OPEN,), TRIAGE),
    "confirm": ((TRIAGE,), CONFIRMED),
    "dismiss": ((OPEN, TRIAGE), DISMISSED),
    "reopen": ((CONFIRMED, DISMISSED), OPEN),
}


class InvalidTransition(Exception):
    """Raised when an incident cannot move via the requested action."""


def allowed_actions(state: str) -> list[str]:
    """Actions permitted from a given state (for UI affordances)."""
    return [a for a, (froms, _to) in TRANSITIONS.items() if state in froms]


def apply_transition(
    db: Session,
    incident: Incident,
    action: str,
    reviewer: str | None = None,
    note: str | None = None,
    expected_version: int | None = None,
    commit: bool = True,
) -> IncidentStateTransition:
    """Apply a lifecycle action to an incident, validating and recording it.

    Returns the persisted IncidentStateTransition. Raises InvalidTransition (with
    no state change) if the action is unknown or not allowed from the current
    state. Does not touch the incident graph/evidence.
    """
    from sqlalchemy import select
    from app.models.pilot import PilotCase
    if db.scalar(select(PilotCase.id).where(PilotCase.incident_id == incident.id)):
        raise InvalidTransition("use the guard desk outcome for this pilot task")
    if action not in TRANSITIONS:
        raise InvalidTransition(
            f"unknown action '{action}'; valid actions: {sorted(TRANSITIONS)}"
        )
    froms, to_state = TRANSITIONS[action]
    current = incident.status or OPEN
    if current not in froms:
        raise InvalidTransition(
            f"cannot '{action}' from state '{current}'; "
            f"allowed from {list(froms)} (actions available now: {allowed_actions(current)})"
        )

    version = incident.version if expected_version is None else expected_version
    if version != incident.version:
        raise InvalidTransition("stale incident version")
    changed = db.execute(update(Incident).where(Incident.id == incident.id,
        Incident.version == version, Incident.status == current).values(status=to_state, version=version + 1))
    if changed.rowcount != 1:
        db.rollback()
        raise InvalidTransition("stale incident version")
    transition = IncidentStateTransition(
        incident_id=incident.id,
        from_state=current,
        to_state=to_state,
        action=action,
        reviewer=reviewer,
        note=note,
    )
    db.add(transition)
    db.add(AuditLog(
        actor=reviewer or "operator",
        action=f"lifecycle:{action}",
        target=f"incident:{incident.id}",
    ))
    if commit:
        db.commit()
    else:
        db.flush()
    db.refresh(transition)
    return transition


def transition_history(db: Session, incident_id: int) -> list[dict]:
    """Ordered lifecycle history for an incident (oldest first)."""
    rows = (
        db.query(IncidentStateTransition)
        .filter(IncidentStateTransition.incident_id == incident_id)
        .order_by(IncidentStateTransition.id)
        .all()
    )
    return [
        {
            "from_state": r.from_state,
            "to_state": r.to_state,
            "action": r.action,
            "reviewer": r.reviewer,
            "note": r.note,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]
