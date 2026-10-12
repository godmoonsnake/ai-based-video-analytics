from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session
import pytest

from app.db.session import engine, SessionLocal
from app.main import app
from app.models.entities import Incident, IncidentCamera
from app.models.security import Tenant, Site, Principal, PrincipalScope
from app.security.context import Scope, scoped
from app.config import get_settings


def seed_scope():
    with Session(engine) as db:
        db.add(Tenant(id="other", name="Test only"))
        db.flush()
        db.add(Site(tenant_id="other", id="private", name="Test only"))
        db.add(Principal(subject="viewer", enabled=True, tokens_valid_after=0))
        db.flush()
        db.add(PrincipalScope(subject="viewer", tenant_id="other", site_id="private", role="client_viewer"))
        db.commit()


def test_scoped_reads_and_writes():
    seed_scope()
    with scoped(Scope("other", "private", "viewer", "client_viewer")), SessionLocal() as db:
        row = Incident(status="open")
        db.add(row)
        db.commit()
        identifier = row.id
    with SessionLocal() as db:
        assert db.get(Incident, identifier) is None
        assert list(db.scalars(select(Incident))) == []
        db.add(Incident(tenant_id="other", site_id="private"))
        with pytest.raises(PermissionError):
            db.commit()


def test_foreign_parent_scope_denied():
    seed_scope()
    with scoped(Scope("other", "private")), SessionLocal() as db:
        row = Incident(status="open")
        db.add(row)
        db.commit()
        identifier = row.id
    with SessionLocal() as db:
        db.add(IncidentCamera(incident_id=identifier, camera_id="none"))
        with pytest.raises(PermissionError):
            db.commit()


def test_oidc_grants_and_disabled_user(monkeypatch):
    seed_scope()
    settings = get_settings()
    monkeypatch.setattr(settings, "auth_mode", "oidc")
    monkeypatch.setattr("app.security.auth.verify_token", lambda token: {"sub": "viewer", "iat": 100,
        "tenant_id": "other", "site_id": "private"})
    client = TestClient(app)
    assert client.get("/api/v1/incidents").status_code == 401
    headers = {"Authorization": "Bearer test"}
    assert client.get("/api/v1/incidents", headers=headers).status_code == 200
    me = client.get("/api/v1/auth/me", headers=headers)
    assert me.status_code == 200 and me.json()["tenant_id"] == "other" and me.json()["role"] == "client_viewer"
    assert client.post("/api/v1/auth/logout", headers=headers).json()["revoked"] is True
    assert client.get("/api/v1/incidents", headers=headers).status_code == 401
    with Session(engine) as db:
        db.get(Principal, "viewer").tokens_valid_after = 0
        db.commit()
    assert client.post("/incidents/build", headers=headers).status_code == 403
    assert client.post("/search", json={}, headers={**headers, "X-Darson-Tenant": "development",
        "X-Darson-Site": "site_a"}).status_code == 200
    monkeypatch.setattr("app.security.auth.verify_token", lambda token: {"sub": "viewer", "iat": 100})
    assert client.get("/api/v1/incidents", headers={**headers, "X-Darson-Tenant": "other",
        "X-Darson-Site": "private"}).status_code == 403
    with Session(engine) as db:
        db.get(Principal, "viewer").enabled = False
        db.commit()
    assert client.get("/api/v1/incidents", headers=headers).status_code == 401


def test_context_does_not_leak_between_sessions():
    with scoped(Scope("other", "private")), SessionLocal() as db:
        assert db.info["scope"].tenant == "other"
    with SessionLocal() as db:
        assert db.info["scope"].tenant == "development"
