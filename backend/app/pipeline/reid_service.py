"""Re-ID appearance embedding service.

Produces 512-d appearance embeddings used for cross-camera track stitching
(Task 7). Two backends implement a common interface:

- OSNetBackend: real OSNet via torchreid (KaiyangZhou/deep-person-reid, MIT).
  Heavy optional dependency; imported lazily and marked no-cover so the
  prototype and tests run without torch.
- MockEmbeddingBackend: deterministic 512-d unit vectors derived from an
  identity seed, so nearest-neighbour behaviour is reproducible offline.

Storage: TrackEmbedding rows. Similarity: cosine. On Postgres we can use the
pgvector `<=>` operator; here we compute cosine in Python so the same code path
works on SQLite (portable prototype). This is explicitly appearance-only —
no facial recognition, no identity database, no PII.
"""
from __future__ import annotations

import abc
import hashlib
from dataclasses import dataclass

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.entities import TrackEmbedding

_DIM = get_settings().embedding_dim


def _unit(vec: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(vec)
    return vec / n if n > 0 else vec


def cosine(a: list[float] | np.ndarray, b: list[float] | np.ndarray) -> float:
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


class EmbeddingBackend(abc.ABC):
    dim: int = _DIM

    @abc.abstractmethod
    def embed_seed(self, seed: str) -> list[float]:
        """Return a deterministic-or-model embedding for an identity/crop seed."""
        raise NotImplementedError


class MockEmbeddingBackend(EmbeddingBackend):
    """Deterministic embeddings from a seed string.

    Same seed -> same vector (with a tiny deterministic jitter per call index so
    repeated observations of one identity cluster tightly but aren't identical).
    """

    def __init__(self, dim: int = _DIM, jitter: float = 0.02):
        self.dim = dim
        self.jitter = jitter
        self._counts: dict[str, int] = {}

    def _base_vector(self, seed: str) -> np.ndarray:
        h = hashlib.sha256(seed.encode()).digest()
        rng = np.random.default_rng(int.from_bytes(h[:8], "big"))
        return _unit(rng.standard_normal(self.dim))

    def embed_seed(self, seed: str) -> list[float]:
        base = self._base_vector(seed)
        idx = self._counts.get(seed, 0)
        self._counts[seed] = idx + 1
        if self.jitter and idx > 0:
            rng = np.random.default_rng(hash((seed, idx)) & 0xFFFFFFFF)
            base = _unit(base + self.jitter * rng.standard_normal(self.dim))
        return base.tolist()


class OSNetBackend(EmbeddingBackend):  # pragma: no cover - requires torch/torchreid
    """Real OSNet feature extractor via torchreid.

    Lazily imports torchreid so the dependency is only needed when actually used
    (e.g. embedding real Frigate snapshot crops).
    """

    def __init__(self, model_name: str = "osnet_x1_0", device: str = "cpu"):
        from torchreid.utils import FeatureExtractor

        self.extractor = FeatureExtractor(model_name=model_name, device=device)
        self.dim = 512

    def embed_seed(self, seed: str) -> list[float]:
        # `seed` is expected to be an image path/crop for the real backend.
        feats = self.extractor([seed])
        return _unit(np.asarray(feats[0], dtype=float)).tolist()


_backend: EmbeddingBackend | None = None


def get_backend() -> EmbeddingBackend:
    """Return the active embedding backend (mock by default for the prototype)."""
    global _backend
    if _backend is None:
        _backend = MockEmbeddingBackend()
    return _backend


def set_backend(backend: EmbeddingBackend) -> None:
    global _backend
    _backend = backend


@dataclass
class SimilarTrack:
    camera_id: str
    track_local_id: str
    score: float


def add_embedding(db: Session, camera_id: str, track_local_id: str, seed: str,
                  event_id: str | None = None) -> TrackEmbedding:
    """Compute + store an embedding for a (camera, track) from an identity seed."""
    vec = get_backend().embed_seed(seed)
    row = TrackEmbedding(
        event_id=event_id, camera_id=camera_id,
        track_local_id=track_local_id, vector=vec,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def mean_track_vector(db: Session, camera_id: str, track_local_id: str) -> list[float] | None:
    rows = db.execute(
        select(TrackEmbedding).where(
            TrackEmbedding.camera_id == camera_id,
            TrackEmbedding.track_local_id == track_local_id,
        )
    ).scalars().all()
    if not rows:
        return None
    mat = np.asarray([r.vector for r in rows], dtype=float)
    return _unit(mat.mean(axis=0)).tolist()


def query_similar(db: Session, vector: list[float], top_k: int = 5,
                  exclude: tuple[str, str] | None = None) -> list[SimilarTrack]:
    """Return the top_k most similar (camera, track) mean-embeddings by cosine."""
    rows = db.execute(select(TrackEmbedding)).scalars().all()
    # Aggregate to mean vector per (camera, track).
    groups: dict[tuple[str, str], list[list[float]]] = {}
    for r in rows:
        groups.setdefault((r.camera_id, r.track_local_id), []).append(r.vector)

    results: list[SimilarTrack] = []
    for (cam, trk), vecs in groups.items():
        if exclude is not None and (cam, trk) == exclude:
            continue
        mean_vec = _unit(np.asarray(vecs, dtype=float).mean(axis=0)).tolist()
        results.append(SimilarTrack(cam, trk, cosine(vector, mean_vec)))

    results.sort(key=lambda s: s.score, reverse=True)
    return results[:top_k]
