"""Run with python -m app.processing.worker [jobs|connector]. Supervise externally."""

import json
import logging
from pathlib import Path
import sys
import time
import uuid

from pydantic import ValidationError
from sqlalchemy import update

from app.config import get_settings
from app.db.session import SessionLocal
from app.models.processing import SourceLease
from app.processing.jobs import claim, finish, source_lease, digest
from app.security.context import Scope, scoped

log = logging.getLogger("darson.worker")


def dispatch(db, job):
    if get_settings().pilot_mode and job.kind == "case_alert":
        raise ValueError("experimental case-study delivery is disabled in the pilot")
    if job.kind == "pipeline":
        if get_settings().pilot_mode:
            from app.pilot.service import process_event
            process_event(db, job.payload["event_id"])
            return
        from app.pipeline.correlator import correlate
        from app.pipeline.incident_builder import build_incidents

        correlate(db)
        build_incidents(db)
    elif job.kind == "evidence":
        from app.evidence.capture import capture

        capture(db, job.payload["evidence_id"])
    elif job.kind == "sla":
        from app.operations.sla import evaluate_episode

        evaluate_episode(db, job.payload["episode_id"])
    elif job.kind == "notification":
        from app.operations.notifications import deliver

        deliver(db, job.payload["notification_id"])
    elif job.kind == "case_alert":
        from app.case_studies.alerts import deliver

        deliver(db, job.payload["alert_id"])
    elif job.kind == "pilot_notice":
        from app.pilot.notifications import deliver
        deliver(db, job.payload["notice_id"])
    elif job.kind == "export":
        from app.exports.service import process_export

        process_export(db, job.payload["export_id"])
    else:
        raise ValueError(f"unknown job type: {job.kind}")


def run_once(owner):
    with SessionLocal() as db:
        run_maintenance(db)
        job = claim(db, owner)
        if job is None:
            # SLA checks are also enqueued durably by a bounded periodic scan.
            from app.operations.sla import enqueue_due_checks

            if not get_settings().pilot_mode:
                enqueue_due_checks(db)
            return False
        identifier = job.id
        try:
            dispatch(db, job)
            finish(db, identifier, owner)
        except Exception as exc:
            db.rollback()
            log.exception("job failed: %s", identifier)
            finish(db, identifier, owner, exc)
        return True


def run_maintenance(db, now=None):
    from app.models.pilot import PilotMaintenance
    from app.pilot.service import marker_key, maintenance, _lock
    from app.evidence.policy import retention_sweep
    now = time.time() if now is None else now
    settings = get_settings()
    if settings.pilot_mode:
        maintenance(db, now)
    _lock(db)
    key = marker_key(db, "retention")
    row = db.get(PilotMaintenance, key)
    if row is None or now - row.last_run_at >= settings.retention_interval_seconds:
        retention_sweep(db, now)
        if row:
            row.last_run_at = now
        else:
            db.add(PilotMaintenance(id=key, name="retention", last_run_at=now))
        db.commit()
    else:
        db.commit()


def drain_spool(spool):
    from app.adapters.frigate_source import decode_message, is_false_positive
    from app.adapters.ingestion import ingest_event

    for identifier, payload in spool.pending():
        try:
            msg = json.loads(payload)
            if not isinstance(msg, dict):
                raise ValueError("object required")
            if not is_false_positive(msg):
                evt = decode_message(msg)
                with SessionLocal() as db:
                    ingest_event(db, evt)
            spool.delivered(identifier)
        except (ValueError, TypeError, ValidationError) as exc:
            spool.quarantine(identifier, exc)
        # DB/network errors propagate; the encrypted record stays pending.


def connector(owner):
    import paho.mqtt.client as mqtt
    from app.processing.spool import Spool

    settings = get_settings()
    source = settings.source_instance
    identity = digest([settings.worker_tenant, settings.worker_site, source])
    spool_root = Path(settings.spool_root)
    spool_key = settings.spool_key
    if not spool_key and settings.environment != "production":
        from cryptography.fernet import Fernet

        spool_root.mkdir(parents=True, exist_ok=True)
        key_path = spool_root / ".development-spool.key"
        try:
            with key_path.open("xb") as key_file:
                key_file.write(Fernet.generate_key())
        except FileExistsError:
            pass
        spool_key = key_path.read_text().strip()
    spool = Spool(
        spool_root / (identity + ".sqlite"), spool_key, settings.spool_max_bytes
    )
    with SessionLocal() as db:
        lease = source_lease(db, source, owner)
        if not lease:
            raise RuntimeError("source already leased")
    client = mqtt.Client(
        client_id="darson-" + identity[:30], clean_session=False, manual_ack=True
    )
    if settings.environment == "production" and not (
        settings.mqtt_username and settings.mqtt_password
    ):
        raise RuntimeError("production MQTT requires credentials")
    if settings.mqtt_username:
        client.username_pw_set(settings.mqtt_username, settings.mqtt_password)
    if settings.mqtt_tls:
        client.tls_set()
    failed = []

    def connected(client, userdata, flags, rc):
        if rc == 0:
            client.subscribe(settings.frigate_mqtt_topic, qos=1)

    def receive(client, userdata, message):
        try:
            spool.put(message.payload)
            client.ack(message.mid, message.qos)
        except Exception as exc:
            failed.append(type(exc).__name__)
            log.exception("spool write failed; message not acknowledged")
            client.disconnect()

    client.on_connect, client.on_message = connected, receive
    client.connect(settings.frigate_mqtt_host, settings.frigate_mqtt_port)
    client.loop_start()
    try:
        while not failed:
            with SessionLocal() as db:
                if not source_lease(db, source, owner):
                    raise RuntimeError("source lease lost")
                db.execute(
                    update(SourceLease)
                    .where(SourceLease.id == lease)
                    .values(last_seen=time.time())
                )
                db.commit()
            drain_spool(spool)
            time.sleep(settings.connector_poll_seconds)
    finally:
        client.disconnect()
        client.loop_stop()
    raise RuntimeError("connector stopped after spool failure")


def main():
    logging.basicConfig(level=logging.INFO)
    settings = get_settings()
    from app.pilot.readiness import validate_configuration
    validate_configuration()
    owner = uuid.uuid4().hex
    with scoped(Scope(settings.worker_tenant, settings.worker_site, owner, "worker")):
        if len(sys.argv) > 1 and sys.argv[1] == "connector":
            connector(owner)
        elif len(sys.argv) > 1 and sys.argv[1] == "health":
            from app.operations.camera_health import probe_site

            while True:
                try:
                    with SessionLocal() as db:
                        probe_site(db)
                except Exception:
                    log.exception("camera health probe failed")
                time.sleep(settings.health_probe_interval_seconds)
        else:
            while True:
                try:
                    if not run_once(owner):
                        time.sleep(1)
                except Exception:
                    log.exception(
                        "database unavailable; retrying without discarding work"
                    )
                    time.sleep(5)


if __name__ == "__main__":
    main()
