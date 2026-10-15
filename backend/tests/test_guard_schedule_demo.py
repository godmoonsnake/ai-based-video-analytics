"""The desk demo can schedule coverage without suggesting recorded media is live."""
import time

from fastapi.testclient import TestClient

from app.main import app
from app.db.session import SessionLocal
from app.models.entities import Camera

client = TestClient(app)


def test_demo_guard_post_and_shift_lifecycle():
    guard = client.post("/api/v1/demo/guards", json={"subject": "demo-guard-one"})
    assert guard.status_code == 200, guard.text
    assert {"subject": "demo-guard-one", "demo": True} in client.get("/api/v1/config/guards").json()

    post = client.post("/api/v1/config/posts", json={
        "name": "North entrance", "block": "A", "floor": "2",
        "instructions": "Check the entrance safely",
    })
    assert post.status_code == 200, post.text
    post_id = post.json()["id"]
    assert any(p["id"] == post_id and p["floor"] == "2" and p["block"] == "A"
               for p in client.get("/api/v1/config/posts").json())

    start = time.time() + 3600
    shift = {"post_id": post_id, "subject": "demo-guard-one", "label": "night",
             "starts_at": start, "ends_at": start + 12 * 3600}
    first = client.post("/api/v1/config/shifts", json=shift)
    assert first.status_code == 200, first.text
    first_id = first.json()["id"]
    assert client.post("/api/v1/config/shifts", json={
        **shift, "starts_at": start + 3600, "ends_at": start + 7200,
    }).status_code == 409
    assert client.delete(f"/api/v1/config/shifts/{first_id}").status_code == 200
    second = client.post("/api/v1/config/shifts", json=shift)
    assert second.status_code == 200, second.text
    assert second.json()["id"] != first_id
    rows = client.get("/api/v1/config/shifts").json()
    assert next(row for row in rows if row["id"] == first_id)["cancelled_at"] is not None
    assert next(row for row in rows if row["id"] == second.json()["id"])["cancelled_at"] is None


def test_media_demo_is_prerecorded_and_live_frames_require_a_source():
    sample = client.get("/api/v1/demo/sample-video/people")
    assert sample.status_code == 200, sample.text
    assert sample.headers["content-type"].startswith("video/mp4")
    assert sample.content[:8][4:] == b"ftyp"
    assert client.get("/api/v1/demo/sample-video/missing").status_code == 404

    with SessionLocal() as db:
        db.add(Camera(id="demo-camera", name="Demo camera"))
        db.commit()
    frame = client.get("/cameras/demo-camera/latest-frame")
    assert frame.status_code == 503
    assert frame.json()["detail"] == "live source is not configured"
