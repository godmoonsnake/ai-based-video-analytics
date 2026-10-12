from fastapi.testclient import TestClient

from app.main import app


def test_review_replay_builds_linked_cases_and_vault_media():
    client = TestClient(app)
    assert client.get("/api/v1/demo/manifest").json()["ready"] is False

    response = client.post("/api/v1/demo/replay")
    assert response.status_code == 200
    payload = response.json()
    assert payload["ready"] is True
    assert payload["ingested"] == 6
    overview = client.get("/api/v1/operations/overview")
    assert overview.status_code == 200
    assert overview.json()["demo_mode"] is True
    case_ids = {item["id"]: item["incident_id"] for item in payload["scenarios"]}
    assert len(set(case_ids.values())) == 3

    movement = client.get(f"/api/v1/incidents/{case_ids['correlated-movement']}/timeline").json()["timeline"]
    assert len(movement) == 4
    assert len({step["camera_id"] for step in movement}) == 4
    assert all(step["evidence"]["snapshot_status"] == "available" for step in movement)
    media = client.get(movement[0]["evidence"]["snapshot_url"])
    assert media.status_code == 200
    assert media.headers["content-type"] == "image/jpeg"

    gap = client.get(f"/api/v1/incidents/{case_ids['evidence-gap']}/timeline").json()["timeline"][0]
    assert gap["evidence"]["snapshot_status"] == "unavailable"
    assert gap["evidence"]["snapshot_url"] is None
    search = client.post("/search", json={"q": "review-blue-bag"}).json()
    assert {item["id"] for item in search["incidents"]} == {case_ids["correlated-movement"]}
    assert len(search["events"]) == 4
    assert "/mock-evidence/" not in str(search)
    second = client.post("/api/v1/demo/replay").json()
    assert second["replayed"] is False
    assert second["ingested"] == 0
    assert {item["id"]: item["incident_id"] for item in second["scenarios"]} == case_ids
