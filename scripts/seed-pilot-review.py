"""Create one visibly simulated task in an isolated local review database."""
import os
from datetime import datetime, time as clock_time, timedelta
from pathlib import Path
import sys
import time
import uuid
from zoneinfo import ZoneInfo

root = Path(__file__).resolve().parents[1]
if os.environ.get("DARSON_ENVIRONMENT", "development") == "production":
    raise SystemExit("Synthetic review is forbidden in production")
os.environ["DARSON_DATABASE_URL"] = f"sqlite:///{(root/'backend/var/pilot-review-v2.db').as_posix()}"
os.environ["DARSON_PILOT_MODE"] = "true"
os.environ["DARSON_AUTH_MODE"] = "development"
os.environ["DARSON_EVIDENCE_ROOT"] = str(root / "backend/var/pilot-review-evidence")
sys.path.insert(0, str(root / "backend"))

from sqlalchemy import select  # noqa: E402
from app.db.init_db import init_db  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.models.entities import Camera, Zone  # noqa: E402
from app.models.operations import SecurityPost, Shift  # noqa: E402
from app.models.security import Principal, PrincipalScope  # noqa: E402
from app.models.pilot import PilotRule, PilotCase, PilotContact, PilotNotice  # noqa: E402
from app.models.evidence import EvidenceObject  # noqa: E402
from app.normalize import normalize_mock_event  # noqa: E402
from app.adapters.ingestion import ingest_event  # noqa: E402
from app.pilot.service import process_event, marker_key  # noqa: E402
from app.evidence.capture import store_capture  # noqa: E402
from app.pilot.notifications import deliver  # noqa: E402

(root / "backend/var").mkdir(parents=True, exist_ok=True)
init_db()
now = time.time()
with SessionLocal() as db:
    if not db.get(Camera, "review-gate"):
        db.add(Camera(id="review-gate", name="SIMULATED gate"))
        db.add(SecurityPost(id="review-post", name="Review post", block="A", floor="Ground",
                            instructions="Synthetic review only"))
        db.flush()
        db.add(Zone(camera_id="review-gate", name="Protected gate", kind="restricted"))
        db.add(PilotRule(id="review-rule", camera_id="review-gate", zone_name="Protected gate", post_id="review-post",
                        schedule={"weekdays": list(range(7)), "start": "00:00", "end": "00:00", "all_day": True},
                        instruction="SIMULATED TASK: check the gate view, acknowledge, then record an example outcome.",
                        acknowledgement_seconds=300))
        db.add(PilotContact(id=marker_key(db, "contact", "development-operator"), subject="development-operator",
                            channel="telegram", destination="demo-only-no-send"))
    else:
        post = db.get(SecurityPost, "review-post")
        post.block, post.floor = "A", "Ground"
    for subject in ("demo-guard-day", "demo-guard-night"):
        if not db.get(Principal, subject):
            db.add(Principal(subject=subject, enabled=True, tokens_valid_after=0))
        if not db.scalar(select(PrincipalScope).where(PrincipalScope.subject == subject,
                                                    PrincipalScope.tenant_id == "development",
                                                    PrincipalScope.site_id == "site_a")):
            db.add(PrincipalScope(subject=subject, tenant_id="development", site_id="site_a", role="responder"))
    today = datetime.now(ZoneInfo("Asia/Kolkata")).date()
    def at(day, hour):
        return datetime.combine(day, clock_time(hour), tzinfo=ZoneInfo("Asia/Kolkata")).timestamp()
    for identifier, subject, label, starts_at, ends_at in (
        ("review-demo-prev-night", "demo-guard-night", "night", at(today-timedelta(days=1), 20), at(today, 8)),
        ("review-demo-day", "demo-guard-day", "day", at(today, 8), at(today, 20)),
        ("review-demo-night", "demo-guard-night", "night", at(today, 20), at(today+timedelta(days=1), 8)),
    ):
        item = db.get(Shift, identifier)
        if not item:
            db.add(Shift(id=identifier, post_id="review-post", subject=subject, label=label,
                         starts_at=starts_at, ends_at=ends_at))
        elif item.cancelled_at is None:
            item.starts_at, item.ends_at = starts_at, ends_at
    shift = db.get(Shift, "review-shift")
    if shift:
        shift.starts_at, shift.ends_at = now-1, now+3600
    else:
        db.add(Shift(id="review-shift", post_id="review-post", subject="development-operator", starts_at=now-1, ends_at=now+3600))
    db.commit()
    existing = db.scalar(select(PilotCase).where(PilotCase.state != "resolved").limit(1))
    if existing:
        print(f"Using existing SIMULATED task #{existing.incident_id}; no external notifications were sent.")
        raise SystemExit(0)
    source = normalize_mock_event({"camera_id": "review-gate", "track_local_id": "review-"+uuid.uuid4().hex,
        "event_type": "zone_enter", "label": "person", "confidence": .8, "start_time": now, "ts": now,
        "zones": ["Protected gate"], "has_snapshot": True})
    event = ingest_event(db, source)
    process_event(db, event.id, now)
    case = db.scalar(select(PilotCase).where(PilotCase.trigger_event_id == event.id))
    evidence = db.scalar(select(EvidenceObject).where(EvidenceObject.event_id == event.id))
    fixture = root / "deploy/mock-evidence/gate_3/A1/snapshot.jpg"
    if fixture.exists():
        store_capture(db, evidence, fixture.read_bytes(), "image/jpeg")
    for notice in db.scalars(select(PilotNotice).where(PilotNotice.case_id == case.id)):
        deliver(db, notice.id)
    print(f"Created SIMULATED task #{case.incident_id}; no external notifications were sent.")
