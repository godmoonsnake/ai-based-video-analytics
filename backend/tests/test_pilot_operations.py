import uuid
from fastapi.testclient import TestClient
from app.main import app
from app.db.session import SessionLocal
from app.models.entities import Incident
from app.models.operations import ResponseEpisode, SLAEscalation, SLANotification, SLANotificationAttempt
from app.operations.sla import evaluate_episode
from app.operations.notifications import DeliveryResult, deliver, acknowledge
from app.models.operations import IncidentExport
from app.exports.service import process_export
from app.evidence.storage import ObjectStore
from app.models.evidence import EvidenceObject, IncidentEvidence
import hashlib
import zipfile
import io
import json
import time
from sqlalchemy import select

client = TestClient(app)


def setup_case():
    r = client.post("/api/v1/config/response-policy", json={"name": "Proposed test SOP", "version": 1,
        "acknowledgement_seconds": 60, "response_seconds": 120, "resolution_seconds": 600,
        "steps": ["Observe safely", "Record outcome"]})
    assert r.status_code == 200, r.text
    r = client.post("/api/v1/incidents/manual", json={"summary": "Controlled test incident",
        "priority": "high", "reason": "operator observation", "idempotency_key": "test-create-incident"})
    assert r.status_code == 200, r.text
    return r.json()["incident_id"]


def action(identifier, version, act, **kwargs):
    return client.post(f"/api/v1/incidents/{identifier}/actions", json={"action": act,
        "expected_version": version, "idempotency_key": uuid.uuid4().hex, **kwargs})


def test_complete_response_sop_and_review_separation():
    identifier = setup_case()
    r = action(identifier, 1, "assign")
    assert r.status_code == 200, r.text
    assert r.json()["response_state"] == "assigned"
    assert action(identifier, 1, "assign").status_code == 409
    assert action(identifier, 2, "acknowledge").status_code == 200
    assert action(identifier, 3, "respond", reason="arrived and observed area").status_code == 200
    assert action(identifier, 4, "resolve", reason="complete").status_code == 409
    steps = r.json()["policy"]["steps"]
    assert action(identifier, 4, "complete_step", step_id=steps[1]["id"]).status_code == 409
    assert action(identifier, 4, "complete_step", step_id=steps[0]["id"]).status_code == 200
    assert action(identifier, 5, "complete_step", step_id=steps[1]["id"]).status_code == 200
    assert action(identifier, 6, "resolve", reason="supervisor checked outcome").status_code == 200
    with SessionLocal() as db:
        assert db.get(Incident, identifier).status == "open"


def test_duplicate_action_and_handover_preserve_clock():
    identifier = setup_case()
    body = {"action": "assign", "expected_version": 1, "idempotency_key": "duplicate-test-key"}
    first = client.post(f"/api/v1/incidents/{identifier}/actions", json=body)
    assert first.status_code == 200, first.text
    assert client.post(f"/api/v1/incidents/{identifier}/actions", json=body).json() == first.json()
    assert client.post(f"/api/v1/incidents/{identifier}/actions", json={**body, "reason": "different"}).status_code == 409
    ack = action(identifier, 2, "acknowledge").json()
    handed = action(identifier, 3, "handover", reason="shift handover").json()
    assert handed["acknowledged_at"] == ack["acknowledged_at"]
    assert handed["episode_id"] == ack["episode_id"]


def test_cross_site_assignee_rejected_and_override_audited():
    identifier = setup_case()
    assert action(identifier, 1, "assign", assignee="unprovisioned").status_code == 422
    assert action(identifier, 1, "assign").status_code == 200
    assert action(identifier, 2, "acknowledge").status_code == 200
    assert action(identifier, 3, "respond", reason="responded safely").status_code == 200
    assert action(identifier, 4, "override_resolve", reason="supervisor approved exception").status_code == 200
    history = client.get(f"/api/v1/incidents/{identifier}/actions").json()
    assert history[-1]["actor"] == "development-operator"
    assert history[-1]["action"] == "override_resolve"


def test_sla_breach_is_durable_and_idempotent():
    identifier = setup_case()
    assigned = action(identifier, 1, "assign")
    episode = assigned.json()["episode_id"]
    with SessionLocal() as db:
        row = db.get(ResponseEpisode, episode)
        row.created_at = time.time() - 1000
        row.policy_snapshot = {**row.policy_snapshot, "acknowledgement_seconds": 10,
            "response_seconds": 20, "resolution_seconds": 30}
        db.commit()
        evaluate_episode(db, episode)
        evaluate_episode(db, episode)
        records = db.scalars(select(SLAEscalation).where(SLAEscalation.episode_id == episode)).all()
        assert {record.stage for record in records} == {"acknowledgement", "response", "resolution"}
        assert len(records) == 3
        notifications = db.scalars(select(SLANotification).where(SLANotification.episode_id == episode)).all()
        assert len(notifications) == 3
        assert len({item.idempotency_key for item in notifications}) == 3
        notify_id = notifications[0].id
        class FailingProvider:
            name = "test"
            def deliver(self, notification): raise TimeoutError()
        try:
            deliver(db, notify_id, FailingProvider())
        except TimeoutError:
            pass
        failed = db.get(SLANotification, notify_id)
        assert failed.status == "retrying" and failed.retry_count == 1
        class AcceptedProvider:
            name = "test"
            def deliver(self, notification): return DeliveryResult(accepted=True)
        deliver(db, notify_id, AcceptedProvider())
        accepted = db.get(SLANotification, notify_id)
        assert accepted.status == "accepted" and accepted.accepted_at is not None
        assert accepted.acknowledged_at is None
        assert len(db.scalars(select(SLANotificationAttempt).where(
            SLANotificationAttempt.notification_id == notify_id)).all()) == 2
        deliver(db, notify_id, AcceptedProvider())
        assert accepted.retry_count == 2
        assert acknowledge(db, notify_id)["status"] == "acknowledged"
        assert accepted.accepted_at is not None and accepted.acknowledged_at is not None


def test_async_version_pinned_pdf_zip_exports():
    identifier = setup_case()
    media = b"\xff\xd8\xffDARSON-TEST-SYNTHETIC"
    with SessionLocal() as db:
        object_key = ObjectStore().put(db.info["scope"], media)
        evidence_id = "test-export-evidence-" + uuid.uuid4().hex
        db.add(EvidenceObject(id=evidence_id, event_id="test-event", kind="snapshot", status="available",
            object_key=object_key, sha256=hashlib.sha256(media).hexdigest(), size=len(media), mime="image/jpeg",
            manifest={"source_type": "synthetic"}, created_at=time.time(), captured_at=time.time(),
            expires_at=time.time() + 3600))
        db.flush()
        db.add(IncidentEvidence(id=uuid.uuid4().hex, incident_id=identifier, evidence_id=evidence_id))
        db.commit()
    inc = client.get(f"/api/v1/incidents/{identifier}").json()
    pdf = client.post(f"/api/v1/incidents/{identifier}/exports", json={"format": "pdf",
        "expected_version": inc["version"], "idempotency_key": "pdf-export-test-123"})
    assert pdf.status_code == 202, pdf.text
    zip_job = client.post(f"/api/v1/incidents/{identifier}/exports", json={"format": "zip",
        "expected_version": inc["version"], "idempotency_key": "zip-export-test-123"})
    assert zip_job.status_code == 202, zip_job.text
    assert client.post(f"/api/v1/incidents/{identifier}/exports", json={"format": "pdf",
        "expected_version": inc["version"] + 1, "idempotency_key": "stale-export-test-123"}).status_code == 409
    with SessionLocal() as db:
        for job in (pdf.json(), zip_job.json()):
            process_export(db, job["id"])
            row = db.get(IncidentExport, job["id"])
            assert row.status == "ready" and row.case_version == inc["version"]
            content = ObjectStore().read(db.info["scope"], row.object_key)
            if row.format == "pdf":
                assert content.startswith(b"%PDF-1.4") and b"not proof of identity" in content
            else:
                with zipfile.ZipFile(io.BytesIO(content)) as archive:
                    assert {"manifest.json", "case.json", "timeline.json", "report.pdf", "evidence-manifest.json"} <= set(archive.namelist())
                    assert archive.read("report.pdf").startswith(b"%PDF-1.4")
                    manifest = json.loads(archive.read("evidence-manifest.json"))
                    media_entry = next(record for record in manifest if record.get("package_path"))
                    packaged = archive.read(media_entry["package_path"])
                    assert hashlib.sha256(packaged).hexdigest() == media_entry["sha256"]
