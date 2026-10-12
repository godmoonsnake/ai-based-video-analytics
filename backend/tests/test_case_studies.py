"""Case study policy and demo behavior through the shared incident API."""
from fastapi.testclient import TestClient

from app.config import get_settings
from app.db.session import SessionLocal
from app.main import app
from app.models.case_studies import CaseAlert
from app.case_studies.alerts import deliver
from app.security.context import Scope, scoped
from sqlalchemy import select
import pytest


def _client():
    return TestClient(app)


def _policy(client, **body):
    response = client.post("/api/v1/case-studies/policies", json=body)
    assert response.status_code == 200, response.text


def _source(client, source_type, instance="manual"):
    response = client.post("/api/v1/case-studies/sources", json={
        "source_type": source_type, "instance": instance,
        "actor": "development-operator", "enabled": True})
    assert response.status_code == 200, response.text


def test_demo_is_idempotent_and_never_queues_external_channels(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "telegram_chat_id", "demo-recipient")
    monkeypatch.setattr(settings, "whatsapp_recipient", "demo-number")
    client = _client()
    first = client.post("/api/v1/case-studies/demo")
    assert first.status_code == 200, first.text
    first_rows = first.json()["observations"]
    assert len(first_rows) == 7
    assert sum(row["decision"] == "review" for row in first_rows) == 6
    assert sum(row["decision"] == "allowed" for row in first_rows) == 1
    incident_ids = [row["incident_id"] for row in first_rows if row["incident_id"]]
    assert len(set(incident_ids)) == 6
    assert all(row["synthetic"] for row in first_rows)
    alerts = client.get("/api/v1/case-studies/alerts").json()
    assert len(alerts) == 6
    assert {row["channel"] for row in alerts} == {"local"}
    detail = client.get(f"/api/v1/incidents/{incident_ids[0]}").json()
    assert detail["case_study"]["type"] == "restricted_reading"
    assert detail["case_study"]["synthetic"] is True
    again = client.post("/api/v1/case-studies/demo")
    assert again.status_code == 200
    assert [row["incident_id"] for row in again.json()["observations"]] == [
        row["incident_id"] for row in first_rows]
    assert len(client.get("/api/v1/case-studies/alerts").json()) == 6


def test_policy_decisions_require_authoritative_source_and_conflicts_reject():
    client = _client()
    _policy(client, id="restricted", kind="restricted_zone", subject="server_room", zone="server_room")
    _policy(client, id="grant", kind="area_access", subject="server_room", zone="server_room",
            principal="worker-17")
    _source(client, "camera_detector")
    _source(client, "access_control")
    base = {"source_event_id": "entry-1", "kind": "restricted_entry", "camera_id": "door-1",
            "zone": "server_room", "observed_at": 1791335100, "principal_ref": "worker-17"}
    camera_claim = client.post("/api/v1/case-studies/observations", json={**base,
        "source_type": "camera_detector"})
    assert camera_claim.status_code == 200, camera_claim.text
    assert camera_claim.json()["decision"] == "review"
    assert camera_claim.json()["incident_id"] is not None
    assert client.post("/api/v1/case-studies/observations", json={**base,
        "source_type": "camera_detector"}).json() == camera_claim.json()
    assert client.post("/api/v1/case-studies/observations", json={**base,
        "source_type": "camera_detector", "zone": "other"}).status_code == 409
    granted = client.post("/api/v1/case-studies/observations", json={**base,
        "source_event_id": "entry-2", "source_type": "access_control"})
    assert granted.status_code == 200
    assert granted.json()["decision"] == "allowed"
    assert granted.json()["incident_id"] is None
    unknown = client.post("/api/v1/case-studies/observations", json={**base,
        "source_event_id": "entry-3", "zone": "lobby"})
    assert unknown.json()["decision"] == "unverified"


def test_plate_threshold_and_required_fields():
    client = _client()
    _policy(client, id="bike", kind="vehicle", subject="KA03MN1234", zone="gate")
    base = {"kind": "vehicle_plate", "camera_id": "gate-1", "zone": "gate",
            "observed_at": 1791335100, "plate": "KA 03 MN 1234", "vehicle_type": "bike"}
    low = client.post("/api/v1/case-studies/observations", json={**base,
        "source_event_id": "plate-low", "confidence": 0.84})
    assert low.status_code == 200 and low.json()["decision"] == "review"
    high = client.post("/api/v1/case-studies/observations", json={**base,
        "source_event_id": "plate-high", "confidence": 0.9})
    assert high.status_code == 200 and high.json()["decision"] == "allowed"
    invalid = client.post("/api/v1/case-studies/observations", json={**base,
        "source_event_id": "plate-missing", "vehicle_type": None})
    assert invalid.status_code == 422
    arbitrary_url = client.post("/api/v1/case-studies/observations", json={**base,
        "source_event_id": "plate-url", "confidence": 0.9,
        "snapshot_url": "http://untrusted.example/media.jpg"})
    assert arbitrary_url.status_code == 422


def test_case_media_uses_existing_evidence_vault(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "evidence_root", str(tmp_path / "case-vault"))
    client = _client()
    _policy(client, id="zone-media", kind="restricted_zone", subject="server_room", zone="server_room")
    _source(client, "camera_detector", "test-camera")
    created = client.post("/api/v1/case-studies/observations", json={
        "source_event_id": "media-entry-1", "kind": "restricted_entry",
        "camera_id": "door-1", "zone": "server_room", "observed_at": 1791335100,
        "source_type": "camera_detector", "source_instance": "test-camera",
    })
    assert created.status_code == 200, created.text
    observation_id = created.json()["id"]
    incident_id = created.json()["incident_id"]
    media = b"\xff\xd8\xffcase-study-synthetic-jpeg"
    uploaded = client.put(f"/api/v1/case-studies/observations/{observation_id}/evidence/snapshot",
                          content=media, headers={"Content-Type": "image/jpeg"})
    assert uploaded.status_code == 200, uploaded.text
    listed = client.get(f"/api/v1/incidents/{incident_id}/evidence")
    assert listed.status_code == 200
    assert len(listed.json()) == 1
    assert listed.json()[0]["status"] == "available"
    content = client.get(listed.json()[0]["content_url"])
    assert content.status_code == 200 and content.content == media
    detail = client.get(f"/api/v1/incidents/{incident_id}").json()
    assert detail["case_study"]["evidence_status"] == {"snapshot": "available"}
    repeated = client.put(f"/api/v1/case-studies/observations/{observation_id}/evidence/snapshot",
                          content=media, headers={"Content-Type": "image/jpeg"})
    assert repeated.status_code == 200
    conflict = client.put(f"/api/v1/case-studies/observations/{observation_id}/evidence/snapshot",
                          content=b"\xff\xd8\xffdifferent", headers={"Content-Type": "image/jpeg"})
    assert conflict.status_code == 409


def test_unregistered_external_source_is_rejected():
    client = _client()
    _policy(client, id="zone-unregistered", kind="restricted_zone",
            subject="server_room", zone="server_room")
    result = client.post("/api/v1/case-studies/observations", json={
        "source_event_id": "unregistered-1", "kind": "restricted_entry",
        "camera_id": "door-1", "zone": "server_room", "observed_at": 1791335100,
        "source_type": "access_control", "source_instance": "unknown"})
    assert result.status_code == 403


def test_alert_failure_records_retry_without_claiming_acceptance(monkeypatch):
    client = _client()
    _policy(client, id="zone-alert", kind="restricted_zone", subject="server_room", zone="server_room")
    created = client.post("/api/v1/case-studies/observations", json={
        "source_event_id": "alert-entry-1", "kind": "restricted_entry",
        "camera_id": "door-1", "zone": "server_room", "observed_at": 1791335100,
    })
    assert created.status_code == 200
    with SessionLocal() as db:
        alert = db.scalar(select(CaseAlert))
        alert.channel = "telegram"
        alert.destination = "test-chat"
        db.commit()
        identifier = alert.id
    settings = get_settings()
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "telegram_bot_token", "test-token")
    def fail_post(*args, **kwargs):
        raise RuntimeError("simulated provider outage")
    monkeypatch.setattr("app.case_studies.alerts._post", fail_post)
    with scoped(Scope("development", "site_a", "test-worker", "worker")), SessionLocal() as db, pytest.raises(RuntimeError, match="simulated provider outage"):
        deliver(db, identifier)
    with scoped(Scope("development", "site_a", "test-worker", "worker")), SessionLocal() as db:
        alert = db.get(CaseAlert, identifier)
        assert alert.status == "retrying"
        assert alert.accepted_at is None
        assert alert.attempt_count == 1
