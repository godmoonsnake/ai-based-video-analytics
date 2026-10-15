from datetime import datetime
from zoneinfo import ZoneInfo
import json
import time
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from app.config import get_settings
from app.db.session import SessionLocal
from app.main import app
from app.models.entities import Camera, Zone, Incident
from app.models.operations import SecurityPost, Shift
from app.models.pilot import PilotRule, PilotCase, PilotNotice, PilotContact
from app.models.security import Principal, PrincipalScope
from app.adapters.ingestion import ingest_event
from app.normalize import normalize_frigate_event
from app.pilot.service import process_event, maintenance, marker_key
from app.pilot.schedule import active_at
from app.pilot.notifications import deliver
from app.api.routes.pilot import TaskAction
from app.pilot.service import act
from app.security.context import Scope, scoped


@pytest.fixture
def pilot(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "pilot_mode", True)
    monkeypatch.setattr(settings, "pilot_supervisor_subject", "supervisor")
    with SessionLocal() as db:
        db.add(Camera(id="gate", name="Gate"))
        db.add(
            SecurityPost(id="gate-post", name="Gate post", instructions="Check door")
        )
        db.flush()
        db.add(Zone(camera_id="gate", name="protected", kind="restricted"))
        db.add(
            PilotRule(
                id="gate-rule",
                camera_id="gate",
                zone_name="protected",
                post_id="gate-post",
                schedule={
                    "weekdays": list(range(7)),
                    "start": "00:00",
                    "end": "00:00",
                    "all_day": True,
                },
                instruction="Check the gate and report the outcome.",
                acknowledgement_seconds=20,
            )
        )
        for subject, role in (("guard", "responder"), ("supervisor", "supervisor")):
            db.add(Principal(subject=subject, enabled=True, tokens_valid_after=0))
            db.flush()
            db.add(
                PrincipalScope(
                    subject=subject,
                    tenant_id="development",
                    site_id="site_a",
                    role=role,
                )
            )
            db.add(
                PilotContact(
                    id=marker_key(db, "contact", subject),
                    subject=subject,
                    channel="telegram",
                    destination="test-recipient",
                )
            )
        db.add(
            Shift(
                id="shift",
                post_id="gate-post",
                subject="guard",
                starts_at=0,
                ends_at=time.time() + 1000,
            )
        )
        db.commit()
    return settings


def event(
    db,
    now,
    track="track",
    kind="update",
    zones=None,
    label="person",
    snapshot=False,
    clip=False,
):
    msg = {
        "type": kind,
        "after": {
            "id": track,
            "camera": "gate",
            "label": label,
            "frame_time": now,
            "start_time": now - 3,
            "score": 0.8,
            "current_zones": ["protected"] if zones is None else zones,
            "entered_zones": ["protected"],
            "has_snapshot": snapshot,
            "has_clip": clip,
        },
    }
    return ingest_event(db, normalize_frigate_event(msg))


def test_current_presence_does_not_fall_back_to_historical_entry(pilot):
    with SessionLocal() as db:
        value = event(db, time.time(), zones=[])
        assert json.loads(value.zones_json) == []
        assert value.event_type == "detection"
        process_event(db, value.id)
        assert db.scalar(select(PilotCase)) is None


def test_one_task_routes_to_shift_and_late_media_does_not_create_more_copies(pilot):
    now = time.time()
    with SessionLocal() as db:
        first = event(db, now, snapshot=True)
        process_event(db, first.id, now)
        next_event = event(db, now + 0.1, snapshot=True, clip=True)
        process_event(db, next_event.id, now + 0.1)
        assert len(db.scalars(select(PilotCase)).all()) == 1
        case = db.scalar(select(PilotCase))
        assert case.owner == "guard"
        notices = db.scalars(select(PilotNotice)).all()
        assert [item.reason for item in notices] == ["assigned_guard"]
        from app.models.evidence import EvidenceObject, IncidentEvidence

        assert len(db.scalars(select(EvidenceObject)).all()) == 2
        assert len(db.scalars(select(IncidentEvidence)).all()) == 2
        assert db.get(Incident, case.incident_id).category == "restricted_entry"


@pytest.mark.parametrize(
    "label,kind,age",
    [("car", "update", 0), ("person", "end", 0), ("person", "update", 100)],
)
def test_nonperson_finished_or_stale_events_do_not_raise_new_alert(
    pilot, label, kind, age
):
    with SessionLocal() as db:
        value = event(db, time.time() - age, label=label, kind=kind)
        process_event(db, value.id)
        assert db.scalar(select(PilotCase)) is None


def test_schedule_overnight_day_boundary():
    schedule = {"weekdays": [0], "start": "22:00", "end": "06:00"}

    def stamp(value):
        return (
            datetime.fromisoformat(value)
            .replace(tzinfo=ZoneInfo("Asia/Kolkata"))
            .timestamp()
        )

    assert active_at(schedule, stamp("2026-10-12T22:00"), "Asia/Kolkata")
    assert active_at(schedule, stamp("2026-10-13T05:59"), "Asia/Kolkata")
    assert not active_at(schedule, stamp("2026-10-13T06:00"), "Asia/Kolkata")
    assert not active_at(schedule, stamp("2026-10-13T22:00"), "Asia/Kolkata")


def test_outside_schedule_does_not_capture_media(pilot):
    with SessionLocal() as db:
        db.get(PilotRule, "gate-rule").schedule = {
            "weekdays": [0],
            "start": "01:00",
            "end": "02:00",
        }
        db.commit()
        now = datetime(2026, 10, 12, 12, tzinfo=ZoneInfo("Asia/Kolkata")).timestamp()
        value = event(db, now, snapshot=True)
        process_event(db, value.id, now)
        from app.models.evidence import EvidenceObject

        assert db.scalar(select(EvidenceObject)) is None


def test_empty_roster_and_overdue_tasks_escalate_once(pilot):
    now = time.time()
    with SessionLocal() as db:
        db.get(Shift, "shift").ends_at = now - 1
        db.commit()
        value = event(db, now)
        process_event(db, value.id, now)
        case = db.scalar(select(PilotCase))
        assert case.owner is None
        assert db.scalar(select(PilotNotice)).reason == "no_guard_on_shift"
        maintenance(db, now + 21)
        maintenance(db, now + 50)
        assert sorted(item.reason for item in db.scalars(select(PilotNotice))) == [
            "no_guard_on_shift",
            "unacknowledged",
        ]


def test_failed_phone_delivery_is_visible_and_escalates(pilot, monkeypatch):
    with SessionLocal() as db:
        value = event(db, time.time())
        process_event(db, value.id)
        row = db.scalar(select(PilotNotice))
        monkeypatch.setattr(pilot, "environment", "production")

        def fail(notice):
            raise TimeoutError()

        with pytest.raises(RuntimeError):
            deliver(db, row.id, sender=fail)
        assert row.status == "retrying" and row.attempts == 1
        assert any(
            item.reason == "guard_delivery_failed"
            for item in db.scalars(select(PilotNotice))
        )


def test_development_never_sends_external_messages(pilot):
    with SessionLocal() as db:
        value = event(db, time.time())
        process_event(db, value.id)
        row = db.scalar(select(PilotNotice))
        deliver(db, row.id, sender=lambda _: pytest.fail("demo sent external message"))
        assert row.status == "suppressed"


def test_guard_registers_and_removes_only_its_current_phone(pilot):
    from app.api.routes.pilot import MobileDeviceIn, register_mobile_device, remove_mobile_device

    first = "first-guard-installation-123456"
    second = "second-guard-installation-123456"
    with scoped(Scope("development", "site_a", "guard", "responder")):
        with SessionLocal() as db:
            assert register_mobile_device(MobileDeviceIn(installation_id=first), db)["registered"]
            contact = db.scalar(select(PilotContact).where(PilotContact.subject == "guard"))
            assert (contact.channel, contact.destination) == ("fcm", first)
            assert contact.last_registered_at is not None
            register_mobile_device(MobileDeviceIn(installation_id=second), db)
            remove_mobile_device(MobileDeviceIn(installation_id=first), db)
            assert db.scalar(select(PilotContact).where(PilotContact.subject == "guard")).destination == second
            remove_mobile_device(MobileDeviceIn(installation_id=second), db)
            assert db.scalar(select(PilotContact).where(PilotContact.subject == "guard")) is None


def test_fcm_push_contains_only_task_reference(pilot, monkeypatch):
    from types import SimpleNamespace
    from app.pilot import notifications

    monkeypatch.setattr(notifications, "_fcm_credentials", lambda: {"project_id": "darson-pilot"})
    monkeypatch.setattr(notifications, "_fcm_access_token", lambda credentials: "access-token")
    sent = []

    class Response:
        def raise_for_status(self): pass
        def json(self): return {"name": "projects/darson-pilot/messages/1"}

    def fake_post(url, **kwargs):
        sent.append((url, kwargs))
        return Response()

    monkeypatch.setattr(notifications.httpx, "post", fake_post)
    notifications._send_fcm(SimpleNamespace(destination="device-installation", case_id="task-123"))
    url, call = sent[0]
    assert url == "https://fcm.googleapis.com/v1/projects/darson-pilot/messages:send"
    assert call["json"]["message"]["data"] == {"task_id": "task-123"}
    assert call["json"]["message"]["fid"] == "device-installation"
    assert call["json"]["message"]["android"]["priority"] == "HIGH"
    assert "notification" not in call["json"]["message"]


def test_stale_phone_is_not_treated_as_delivered(pilot, monkeypatch):
    with SessionLocal() as db:
        guard = db.scalar(select(PilotContact).where(PilotContact.subject == "guard"))
        guard.channel = "fcm"
        guard.destination = "old-installation-id-123456789"
        guard.last_registered_at = time.time() - 31 * 86400
        db.commit()
        value = event(db, time.time())
        process_event(db, value.id)
        row = db.scalar(select(PilotNotice).where(PilotNotice.reason == "assigned_guard"))
        monkeypatch.setattr(pilot, "environment", "production")
        with pytest.raises(RuntimeError):
            deliver(db, row.id, sender=lambda _: pytest.fail("stale phone was sent a notice"))
        assert row.status == "retrying" and row.failure_class == "RuntimeError"
        assert db.scalar(select(PilotNotice).where(PilotNotice.reason == "guard_delivery_failed"))


def test_guard_cannot_read_other_task_but_can_read_assigned_evidence(
    pilot, monkeypatch, tmp_path
):
    from app.evidence.capture import store_capture
    from app.models.evidence import EvidenceObject

    monkeypatch.setattr(pilot, "evidence_root", str(tmp_path))
    with SessionLocal() as db:
        value = event(db, time.time(), snapshot=True)
        process_event(db, value.id)
        case = db.scalar(select(PilotCase))
        identifier = case.id
        obj = db.scalar(select(EvidenceObject))
        store_capture(db, obj, b"\xff\xd8\xfftest", "image/jpeg")
        path = f"/api/v1/evidence/{obj.id}/content"
    monkeypatch.setattr(pilot, "auth_mode", "oidc")
    monkeypatch.setattr(
        "app.security.auth.verify_token",
        lambda token: {
            "sub": token,
            "iat": 100,
            "tenant_id": "development",
            "site_id": "site_a",
            "amr": ["mfa"],
        },
    )
    client = TestClient(app)
    headers = {"Authorization": "Bearer guard"}
    assert (
        client.get(f"/api/v1/pilot/tasks/{identifier}", headers=headers).status_code
        == 200
    )
    assert client.get(path, headers=headers).status_code == 200
    assert (
        client.post(
            f"/api/v1/pilot/tasks/{identifier}/verify-label", headers=headers
        ).status_code
        == 403
    )
    assert client.get("/api/v1/pilot/notices", headers=headers).status_code == 403
    with SessionLocal() as db:
        db.get(PilotCase, identifier).owner = "supervisor"
        db.commit()
    assert client.get(path, headers=headers).status_code == 404
    assert (
        client.get(f"/api/v1/pilot/tasks/{identifier}", headers=headers).status_code
        == 404
    )


def test_outcome_requires_ack_and_stale_actions_fail(pilot):
    from fastapi import HTTPException

    with SessionLocal() as db:
        value = event(db, time.time())
        process_event(db, value.id)
        case = db.scalar(select(PilotCase))
        from app.pipeline.incident_lifecycle import apply_transition, InvalidTransition
        with pytest.raises(InvalidTransition):
            apply_transition(db, db.get(Incident, case.incident_id), "dismiss")
        with pytest.raises(HTTPException) as failure:
            act(
                db,
                case.id,
                TaskAction(
                    action="outcome",
                    expected_version=1,
                    outcome="false_alarm",
                    note="Shadow",
                ),
            )
        assert failure.value.status_code == 409
        act(db, case.id, TaskAction(action="acknowledge", expected_version=1))
        with pytest.raises(HTTPException):
            act(
                db,
                case.id,
                TaskAction(
                    action="outcome",
                    expected_version=1,
                    outcome="false_alarm",
                    note="Shadow",
                ),
            )
        act(
            db,
            case.id,
            TaskAction(
                action="outcome",
                expected_version=2,
                outcome="false_alarm",
                note="Shadow",
            ),
        )
        assert case.state == "resolved" and case.label_verified_at is None


def test_pilot_blocks_research_demo_routes(pilot):
    client = TestClient(app)
    for path in (
        "/api/v1/demo/replay",
        "/api/v1/case-studies/demo",
        "/tracks/correlate",
    ):
        assert client.post(path).status_code == 404


def test_retention_runs_while_pipeline_has_work(pilot):
    from app.models.evidence import EvidenceObject, EvidenceAccess
    from app.processing.worker import run_once

    now = time.time()
    with SessionLocal() as db:
        event(db, now, zones=[])
        db.add(
            EvidenceObject(
                id="expired-pending",
                event_id="none",
                kind="clip",
                status="pending",
                created_at=now - 100,
                expires_at=now - 1,
                manifest={},
            )
        )
        db.commit()
    assert run_once("test-worker")
    with SessionLocal() as db:
        assert db.get(EvidenceObject, "expired-pending").status == "unavailable"
        assert (
            db.scalar(
                select(EvidenceAccess).where(
                    EvidenceAccess.evidence_id == "expired-pending"
                )
            ).action
            == "retention_delete"
        )


def test_camera_health_alert_can_repeat_after_recovery(pilot):
    from app.models.operations import CameraHealthCurrent

    now = time.time()
    with SessionLocal() as db:
        db.add(
            CameraHealthCurrent(
                id="health-id",
                camera_id="gate",
                state="offline",
                stream_state="offline",
                video_state="unknown",
                recording_state="unknown",
                evidence_state="unknown",
                updated_at=now,
                metrics={},
            )
        )
        db.commit()
        maintenance(db, now)
        assert len(db.scalars(select(PilotNotice)).all()) == 1
        health = db.get(CameraHealthCurrent, "health-id")
        health.stream_state = "healthy"
        db.commit()
        maintenance(db, now + 20)
        health.stream_state = "offline"
        db.commit()
        maintenance(db, now + 40)
        assert len(db.scalars(select(PilotNotice)).all()) == 2


def test_local_public_jwks_keeps_expiry_and_signature_checks(
    pilot, monkeypatch, tmp_path
):
    import jwt
    from cryptography.hazmat.primitives.asymmetric import rsa
    from app.security.auth import verify_token
    from fastapi import HTTPException

    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private.public_key()))
    public.update(kid="site-key", use="sig", alg="RS256")
    path = tmp_path / "public-jwks.json"
    path.write_text(json.dumps({"keys": [public]}), encoding="utf-8")
    monkeypatch.setattr(pilot, "oidc_jwks_file", str(path))
    monkeypatch.setattr(pilot, "oidc_issuer", "https://site-identity.test")
    monkeypatch.setattr(pilot, "oidc_audience", "darson")
    payload = {
        "sub": "guard",
        "iss": pilot.oidc_issuer,
        "aud": "darson",
        "iat": int(time.time()),
        "exp": int(time.time()) + 60,
    }
    token = jwt.encode(payload, private, algorithm="RS256", headers={"kid": "site-key"})
    assert verify_token(token)["sub"] == "guard"
    expired = jwt.encode(
        {**payload, "exp": int(time.time()) - 1},
        private,
        algorithm="RS256",
        headers={"kid": "site-key"},
    )
    with pytest.raises(HTTPException):
        verify_token(expired)
    forged = jwt.encode(
        payload, "wrong-key", algorithm="HS256", headers={"kid": "site-key"}
    )
    with pytest.raises(HTTPException):
        verify_token(forged)


def test_acceptance_requires_signed_targets_and_includes_misses():
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location(
        "pilot_acceptance", Path(__file__).parents[2] / "scripts/pilot_acceptance.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with pytest.raises(ValueError):
        module.evaluate({}, [], [])
    targets = {
        "operations_lead": "Test signer",
        "signed_reference": "test-only",
        "conditions": ["night"],
        "min_repetitions_per_condition": 2,
        "detection_rate_min": 1,
        "p95_alert_seconds_max": 5,
        "p95_acknowledgement_seconds_max": 30,
        "false_alerts_per_camera_hour_max": 0.1,
        "min_monitored_camera_hours": 10,
    }
    trials = [
        {
            "test_id": "one",
            "condition": "night",
            "detected": "1",
            "alert_latency_seconds": "2",
            "acknowledgement_seconds": "10",
        },
        {
            "test_id": "two",
            "condition": "night",
            "detected": "0",
            "alert_latency_seconds": "",
            "acknowledgement_seconds": "",
        },
    ]
    report = module.evaluate(
        targets,
        trials,
        [{"session_id": "night1", "monitored_camera_hours": "10", "false_alerts": "0"}],
    )
    assert report["conditions"][0]["detection_rate"] == 0.5
    assert report["passed"] is False
    trials[1].update(
        detected="1", alert_latency_seconds="3", acknowledgement_seconds="12"
    )
    assert module.evaluate(
        targets,
        trials,
        [{"session_id": "night1", "monitored_camera_hours": "10", "false_alerts": "0"}],
    )["passed"]


def test_retention_failure_is_audited_without_stopping_other_deletions(pilot, monkeypatch):
    from app.models.evidence import EvidenceObject, EvidenceAccess
    from app.evidence.policy import retention_sweep
    from app.evidence.storage import ObjectStore
    now = time.time()
    with SessionLocal() as db:
        db.add(EvidenceObject(id="failed-expiry", event_id="none", kind="clip", status="available",
            created_at=now-100, expires_at=now-1, object_key="test-key", manifest={}))
        db.add(EvidenceObject(id="pending-expiry", event_id="none", kind="snapshot", status="pending",
            created_at=now-100, expires_at=now-1, manifest={}))
        db.commit()
        def fail(store, scope, key):
            raise PermissionError("test storage failure")
        monkeypatch.setattr(ObjectStore, "delete", fail)
        retention_sweep(db, now)
        assert db.get(EvidenceObject, "failed-expiry").status == "deletion-failed"
        assert db.get(EvidenceObject, "pending-expiry").status == "unavailable"
        assert db.scalar(select(EvidenceAccess).where(EvidenceAccess.evidence_id == "failed-expiry")).action == "retention_delete_failed"
