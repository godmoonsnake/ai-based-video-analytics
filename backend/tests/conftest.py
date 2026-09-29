"""Shared pytest fixtures.

Forces an isolated SQLite database per test session so the backend runs without
Docker/Postgres. Because settings are cached, we set the env var before any app
import happens (conftest is imported very early by pytest).
"""
from __future__ import annotations

import os
import tempfile

os.environ.setdefault("DARSON_EVENT_SOURCE", "mock")

_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["DARSON_DATABASE_URL"] = f"sqlite:///{_tmp.name}"

import pytest  # noqa: E402

from app.db.init_db import init_db  # noqa: E402
from app.db.session import Base, engine  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_db():
    Base.metadata.drop_all(bind=engine)
    init_db()
    yield
    Base.metadata.drop_all(bind=engine)
