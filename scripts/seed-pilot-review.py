"""Create one visibly simulated task in an isolated local review database."""
import os
from pathlib import Path
import sys
import time
import uuid

root = Path(__file__).resolve().parents[1]
if os.environ.get("DARSON_ENVIRONMENT", "development") == "production":
    raise SystemExit("Synthetic review is forbidden in production")
os.environ["DARSON_DATABASE_URL"] = f"sqlite:///{(root/'backend/var/pilot-review-v1.db').as_posix()}"
os.environ["DARSON_PILOT_MODE"] = "true"
os.environ["DARSON_AUTH_MODE"] = "development"
os.environ["DARSON_EVIDENCE_ROOT"] = str(root / "backend/var/pilot-review-evidence")
sys.path.insert(0, str(root / "backend"))

from sqlalchemy import select  # noqa: E402
from app.db.init_db import init_db  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.models.entities import Camera, Zone  # noqa: E402
from app.models.operations import SecurityPost, Shift  # noqa: E402
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
        db.add(SecurityPost(id="review-post", name="Review post", instructions="Synthetic review only"))
        db.flush()
        db.add(Zone(camera_id="review-gate", name="Protected gate", kind="restricted"))
        db.add(PilotRule(id="review-rule", camera_id="review-gate", zone_name="Protected gate", post_id="review-post",
                        schedule={"weekdays": list(range(7)), "start": "00:00", "end": "00:00", "all_day": True},
                        instruction="SIMULATED TASK: check the gate view, acknowledge, then record an example outcome.",
                        acknowledgement_seconds=300))
        db.add(PilotContact(id=marker_key(db, "contact", "development-operator"), subject="development-operator",
                            channel="telegram", destination="demo-only-no-send"))
    shift = db.get(Shift, "review-shift")
    if shift:
        shift.starts_at, shift.ends_at = now-1, now+3600
    else:
        db.add(Shift(id="review-shift", post_id="review-post", subject="development-operator", starts_at=now-1, ends_at=now+3600))
    db.commit()
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
