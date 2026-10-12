from fastapi.testclient import TestClient
from sqlalchemy import select
import pytest
from app.config import get_settings
from app.db.session import SessionLocal
from app.main import app
from app.models.evidence import EvidenceObject, RetentionHold
from app.adapters.mock_source import load_topology, MockEventSource
from app.adapters.ingestion import ingest_source
from app.evidence.capture import store_capture, validate_media
from app.evidence.storage import ObjectStore
from app.evidence.policy import retention_sweep
from app.security.context import Scope, scoped


@pytest.fixture
def vault(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "evidence_root", str(tmp_path / "objects"))
    with SessionLocal() as db:
        load_topology(db)
        ingest_source(db, MockEventSource(base_epoch=1700000000))
        obj = db.scalar(select(EvidenceObject).where(EvidenceObject.kind == "snapshot"))
        store_capture(db, obj, b"\xff\xd8\xfftest-synthetic-jpeg", "image/jpeg")
        return obj.id


def test_evidence_independent_retrieval_and_hash_failure(vault):
    client = TestClient(app)
    # No Frigate/network process is involved in content retrieval.
    result = client.get(f"/api/v1/evidence/{vault}/content")
    assert result.status_code == 200
    assert result.headers["content-type"] == "image/jpeg"
    with SessionLocal() as db:
        obj = db.get(EvidenceObject, vault)
        ObjectStore().path(obj.object_key).write_bytes(b"tampered")
    assert client.get(f"/api/v1/evidence/{vault}/content").status_code == 409
    with SessionLocal() as db:
        assert db.get(EvidenceObject, vault).status == "integrity-failed"


def test_retention_hold_then_release(vault):
    with SessionLocal() as db:
        obj = db.get(EvidenceObject, vault)
        obj.expires_at = 1
        hold = RetentionHold(id="test-hold", evidence_id=vault, actor="test", reason="test preservation",
                             created_at=0)
        db.add(hold)
        db.commit()
        assert retention_sweep(db, now=100) == []
        hold.released_at = 99
        db.commit()
        assert retention_sweep(db, now=100) == [vault]
    assert TestClient(app).get(f"/api/v1/evidence/{vault}/content").status_code == 410


def test_other_scope_cannot_read_storage_or_manifest(vault):
    with SessionLocal() as db:
        key = db.get(EvidenceObject, vault).object_key
    with scoped(Scope("other", "private")), SessionLocal() as db:
        assert db.get(EvidenceObject, vault) is None
        with pytest.raises(PermissionError):
            ObjectStore().read(db.info["scope"], key)


def test_media_size_and_type_validation():
    with pytest.raises(ValueError):
        validate_media(b"<script>not a picture</script>", "image/jpeg", "snapshot")
    with pytest.raises(ValueError):
        validate_media(b"", "video/mp4", "clip")


def test_restored_object_is_readable(vault, tmp_path):
    with SessionLocal() as db:
        obj = db.get(EvidenceObject, vault)
        path = ObjectStore().path(obj.object_key)
        backup = tmp_path / "test-backup.bin"
        backup.write_bytes(path.read_bytes())
        path.unlink()
        path.write_bytes(backup.read_bytes())
    assert TestClient(app).get(f"/api/v1/evidence/{vault}/content").status_code == 200
