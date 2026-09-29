"""Task 6 verification: OSNet/TorchReID embedding service + similarity."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.db.session import SessionLocal
from app.main import app
from app.pipeline.reid_service import (
    MockEmbeddingBackend,
    add_embedding,
    cosine,
    mean_track_vector,
    query_similar,
)

client = TestClient(app)


def test_same_seed_clusters_tighter_than_distractor():
    backend = MockEmbeddingBackend()
    a1 = backend.embed_seed("red_bag")
    a2 = backend.embed_seed("red_bag")
    other = backend.embed_seed("blue_jacket")
    assert cosine(a1, a2) > cosine(a1, other)
    assert cosine(a1, a2) > 0.9  # same identity clusters tightly


def test_same_seed_similarity_is_dimension_robust():
    """Same-seed cosine must stay well above the clustering threshold at any
    embedding dimensionality. Guards against unnormalized jitter, whose angular
    impact scaled with sqrt(dim) and previously dipped below 0.9 at dim=512."""
    for dim in (128, 512, 1024):
        backend = MockEmbeddingBackend(dim=dim)
        v1 = backend.embed_seed("red_bag")
        v2 = backend.embed_seed("red_bag")
        v3 = backend.embed_seed("red_bag")
        assert cosine(v1, v2) > 0.95
        assert cosine(v1, v3) > 0.95
        # still distinguishable from a different identity
        other = backend.embed_seed("blue_jacket")
        assert cosine(v1, other) < cosine(v1, v2)


def test_same_seed_embeddings_deterministic_across_instances():
    """Two independent backend instances must produce identical embeddings for
    the same (seed, call-index). Proves the SHA-256 jitter seed is stable and
    not dependent on Python's per-process randomized hash()."""
    b1 = MockEmbeddingBackend()
    b2 = MockEmbeddingBackend()
    # advance both identically: first (idx=0, no jitter) then (idx=1, jittered)
    b1.embed_seed("red_bag")
    b2.embed_seed("red_bag")
    v1 = b1.embed_seed("red_bag")
    v2 = b2.embed_seed("red_bag")
    assert v1 == v2


def test_nearest_neighbour_returns_same_identity():
    db = SessionLocal()
    try:
        # Same person (red_bag) seen on 3 cameras + a distractor on a 4th.
        add_embedding(db, "gate_3", "A1", seed="red_bag")
        add_embedding(db, "corridor_1", "B7", seed="red_bag")
        add_embedding(db, "restricted_2", "C3", seed="red_bag")
        add_embedding(db, "corridor_1", "Z9", seed="blue_jacket")  # distractor

        vec = mean_track_vector(db, "gate_3", "A1")
        hits = query_similar(db, vec, top_k=3, exclude=("gate_3", "A1"))
        # The top two hits should be the other red_bag tracks, not the distractor.
        top_two = {(h.camera_id, h.track_local_id) for h in hits[:2]}
        assert ("corridor_1", "B7") in top_two
        assert ("restricted_2", "C3") in top_two
        assert hits[0].score > hits[-1].score
    finally:
        db.close()


def test_similar_endpoint():
    resp = client.post("/events/ingest/mock")
    assert resp.status_code == 200
    body = resp.json()
    assert body["embeddings"] == 4  # A1,B7,C3,D9

    # A1 on gate_3 should find the other same-identity tracks.
    resp = client.get("/tracks/gate_3/A1/similar", params={"top_k": 3})
    assert resp.status_code == 200
    hits = resp.json()
    assert len(hits) == 3
    assert all(h["score"] > 0.5 for h in hits)  # all same red_bag identity

    assert client.get("/tracks/gate_3/NOPE/similar").status_code == 404
