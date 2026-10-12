"""Durable deadline evaluation; escalation records are idempotent and auditable."""
import time
from sqlalchemy import select
from app.models.operations import ResponseEpisode, SLAEscalation, SLANotification
from app.processing.jobs import digest, enqueue, insert_once


def evaluate_episode(db, episode_id):
    ep = db.get(ResponseEpisode, episode_id)
    if not ep or ep.state == "resolved":
        return
    definition = ep.policy_snapshot
    created = ep.created_at
    candidates = [
        ("acknowledgement", created + definition["acknowledgement_seconds"], ep.acknowledged_at is not None),
        ("response", created + definition["response_seconds"], ep.responded_at is not None),
        ("resolution", created + definition["resolution_seconds"], ep.resolved_at is not None),
    ]
    now = time.time()
    for stage, deadline, completed in candidates:
        key = digest([ep.tenant_id, ep.site_id, ep.id, stage])
        if not completed and now >= deadline and db.get(SLAEscalation, key) is None:
            insert_once(db, SLAEscalation, dict(id=key, episode_id=ep.id, incident_id=ep.incident_id,
                tenant_id=ep.tenant_id, site_id=ep.site_id, stage=stage, deadline_at=deadline,
                recorded_at=now, owner_at_deadline=ep.owner, status="open"))
            notification_id = digest([key, "level-1"])
            insert_once(db, SLANotification, dict(id=notification_id, escalation_id=key,
                incident_id=ep.incident_id, episode_id=ep.id, escalation_level=1,
                tenant_id=ep.tenant_id, site_id=ep.site_id, provider="local",
                destination_ref=ep.owner, status="queued", retry_count=0,
                idempotency_key=notification_id))
            enqueue(db, "notification", notification_id, {"notification_id": notification_id})
    db.commit()


def enqueue_due_checks(db):
    now = time.time()
    episodes = db.scalars(select(ResponseEpisode).where(ResponseEpisode.state != "resolved")
        .order_by(ResponseEpisode.created_at).limit(100)).all()
    for ep in episodes:
        # A durable queue job ensures checks survive worker restarts. The unique
        # key is time-bucketed to avoid hot-loop duplicates while keeping retries.
        bucket = int(now // 60)
        enqueue(db, "sla", digest([ep.tenant_id, ep.site_id, ep.id, bucket]), {"episode_id": ep.id})
    db.commit()
