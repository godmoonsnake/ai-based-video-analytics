import json
from pathlib import Path
from cryptography.fernet import Fernet
from sqlalchemy import func, select
import pytest

from app.adapters.ingestion import ingest_event
from app.db.session import SessionLocal
from app.models.entities import Event
from app.models.processing import ProcessingJob
from app.normalize.normalizer import normalize_frigate_event
from app.processing.jobs import claim, finish
from app.processing.spool import Spool, SpoolFull
from app.processing.worker import drain_spool


def messages():
    return json.loads((Path(__file__).parent / "fixtures/frigate_stream.json").read_text())


def test_duplicate_and_revision_safety():
    msg = messages()[0]
    with SessionLocal() as db:
        first = ingest_event(db, normalize_frigate_event(msg))
        second = ingest_event(db, normalize_frigate_event(msg))
        assert first.id == second.id
        assert db.scalar(select(func.count()).select_from(Event)) == 1
        assert db.scalar(select(func.count()).select_from(ProcessingJob).where(ProcessingJob.kind == "pipeline")) == 1
        assert db.scalar(select(func.count()).select_from(ProcessingJob).where(ProcessingJob.kind == "evidence")) == 1
        changed = json.loads(json.dumps(msg))
        changed["type"] = "end"
        ingest_event(db, normalize_frigate_event(changed))
        assert db.scalar(select(func.count()).select_from(Event)) == 2


def test_job_crash_reclaim_and_stale_owner():
    with SessionLocal() as db:
        ingest_event(db, normalize_frigate_event(messages()[0]))
        job = claim(db, "first", now=100, lease_seconds=10)
        assert job is not None
        other = claim(db, "second", now=105)
        assert other.id != job.id
        assert finish(db, other.id, "second", now=105)
        assert claim(db, "third", now=105) is None
        assert claim(db, "second", now=111).id == job.id
        assert not finish(db, job.id, "first", now=112)
        assert finish(db, job.id, "second", now=112)


def test_encrypted_spool_restart_poison_and_capacity(tmp_path):
    key = Fernet.generate_key().decode()
    spool = Spool(tmp_path / "buffer.db", key, max_bytes=10000)
    identifier = spool.put(b'{"invalid":true}')
    assert b'"invalid"' not in (tmp_path / "buffer.db").read_bytes()
    restarted = Spool(tmp_path / "buffer.db", key, max_bytes=10000)
    assert restarted.pending()[0][0] == identifier
    drain_spool(restarted)
    assert restarted.stats() == {"quarantined": 1}
    with pytest.raises(SpoolFull):
        restarted.put(b"x" * 20000)
    assert restarted.stats() == {"quarantined": 1}
