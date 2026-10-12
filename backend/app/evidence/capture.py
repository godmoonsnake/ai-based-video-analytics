import hashlib
import time
from urllib.parse import quote, urlparse
import httpx
from sqlalchemy import select

from app.config import get_settings
from app.models.entities import Event
from app.models.evidence import EvidenceObject, IncidentEvidence
from app.processing.jobs import digest, enqueue, insert_once
from app.evidence.policy import audit
from app.evidence.storage import ObjectStore


def request_capture(db, event, enqueue_job=True):
    settings, scope = get_settings(), db.info["scope"]
    for kind, needed in (("snapshot", event.has_snapshot), ("clip", event.has_clip)):
        if not needed:
            continue
        # Pilot keeps one representative object per source track/kind, not a
        # copy for every MQTT update. Unrelated detections are not captured.
        source_key = [event.source_instance, event.camera_id, event.source_event_id] if settings.pilot_mode else event.id
        identifier = digest([scope.tenant, scope.site, source_key, kind])
        now = time.time()
        insert_once(db, EvidenceObject, dict(id=identifier, tenant_id=scope.tenant, site_id=scope.site,
            event_id=event.id, kind=kind, status="requested", created_at=now,
            expires_at=now + settings.evidence_retention_days * 86400,
            manifest={"source_instance": event.source_instance, "source_event": event.source_event_id,
                "source_type": event.source_type, "camera": event.camera_id, "source_timestamp": event.ts,
                "source_start": event.start_time, "source_end": event.end_time,
                "ingest_timestamp": event.received_at, "time_sync_uncertainty_seconds": None,
                "policy_version": "evidence-v1", "media_origin": "synthetic" if event.source_type == "mock" else "source",
                "capture_deadline": now + 600}))
        if enqueue_job:
            enqueue(db, "evidence", identifier, {"evidence_id": identifier})


def attach_evidence(db, incident_id, event_ids):
    scope = db.info["scope"]
    for obj in db.scalars(select(EvidenceObject).where(EvidenceObject.event_id.in_(event_ids))):
        insert_once(db, IncidentEvidence, dict(id=digest([incident_id, obj.id]),
            incident_id=incident_id, evidence_id=obj.id, tenant_id=scope.tenant, site_id=scope.site))
    if get_settings().pilot_mode:
        # Stable pilot object IDs can refer to an earlier revision of this track.
        for event in db.scalars(select(Event).where(Event.id.in_(event_ids))):
            for kind in ("snapshot", "clip"):
                identifier = digest([scope.tenant, scope.site,
                    [event.source_instance, event.camera_id, event.source_event_id], kind])
                if db.get(EvidenceObject, identifier):
                    insert_once(db, IncidentEvidence, dict(id=digest([incident_id, identifier]),
                        incident_id=incident_id, evidence_id=identifier, tenant_id=scope.tenant, site_id=scope.site))


def validate_media(content, mime, kind):
    if not content or len(content) > get_settings().evidence_max_bytes:
        raise ValueError("empty or oversized evidence")
    valid = ((mime == "image/jpeg" and content.startswith(b"\xff\xd8\xff")) or
             (mime == "image/png" and content.startswith(b"\x89PNG\r\n\x1a\n"))) if kind == "snapshot" else (
             mime == "video/mp4" and len(content) >= 12 and content[4:8] == b"ftyp")
    if not valid:
        raise ValueError("evidence content does not match permitted media type")


def store_capture(db, obj, content: bytes, mime: str):
    from app.evidence.policy import held
    if obj.expires_at <= time.time() and not held(db, obj.id):
        raise ValueError("evidence retention expired before capture")
    validate_media(content, mime, obj.kind)
    obj.object_key = ObjectStore().put(db.info["scope"], content)
    obj.sha256 = hashlib.sha256(content).hexdigest()
    obj.size, obj.mime, obj.status = len(content), mime, "available"
    obj.captured_at, obj.error = time.time(), None
    obj.manifest = {**obj.manifest, "object_version": obj.object_key.rsplit("/", 1)[-1],
                    "sha256": obj.sha256, "bytes": obj.size, "mime": mime,
                    "captured_at": obj.captured_at, "expires_at": obj.expires_at}
    audit(db, obj.id, "capture_verified")
    db.commit()


def capture(db, identifier):
    obj = db.get(EvidenceObject, identifier)
    if obj is None or obj.status in {"available", "source-expired", "integrity-failed", "unavailable"}:
        return
    from app.evidence.policy import held
    if obj.expires_at <= time.time() and not held(db, obj.id):
        obj.status, obj.error = "unavailable", "retention_expired"
        audit(db, obj.id, "retention_delete")
        db.commit()
        return
    event = db.get(Event, obj.event_id)
    if not event:
        raise ValueError("source event missing")
    if event.source_type == "mock":
        obj.status, obj.error = "unavailable", "synthetic_fixture_not_loaded"
        db.commit()
        return
    settings = get_settings()
    base = settings.frigate_api_base.rstrip("/")
    parsed = urlparse(base)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.query or parsed.fragment:
        raise ValueError("invalid configured source endpoint")
    # Never read event-supplied URLs. Only the configured connector and escaped source ID.
    suffix = "snapshot.jpg" if obj.kind == "snapshot" else "clip.mp4"
    url = f"{base}/api/events/{quote(event.source_event_id or '', safe='')}/{suffix}"
    headers = {"Cookie": f"frigate_token={settings.frigate_api_token}"} if settings.frigate_api_token else {}
    with httpx.Client(timeout=15, follow_redirects=False, trust_env=False, headers=headers) as client:
        with client.stream("GET", url) as response:
            if response.status_code in {404, 410}:
                expired = response.status_code == 410 or time.time() >= obj.manifest["capture_deadline"]
                obj.status, obj.error = ("source-expired" if expired else "pending"), "source_not_ready"
                db.commit()
                if not expired:
                    raise RuntimeError("source clip/snapshot pending")
                return
            if response.status_code != 200:
                raise RuntimeError("source unavailable or redirect denied")
            mime = response.headers.get("content-type", "").split(";")[0].lower()
            content = bytearray()
            for chunk in response.iter_bytes():
                content.extend(chunk)
                if len(content) > settings.evidence_max_bytes:
                    raise ValueError("source media exceeds capture budget")
    store_capture(db, obj, bytes(content), mime)
