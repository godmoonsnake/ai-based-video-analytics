"""DARSON intelligence-layer FastAPI application.

An intelligence layer ABOVE an existing VMS: EVENT -> CONTEXT -> CORRELATION ->
INCIDENT -> HISTORY -> INVESTIGATION. Human-in-the-loop decision support only.
No facial/gait recognition, no PII database, no autonomous verdicts.
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import (
    cameras,
    events,
    health,
    incidents,
    patterns,
    search,
    tracks,
    v1_incidents,
)
from app.config import get_settings
from app.db.init_db import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.pilot.readiness import validate_configuration
    validate_configuration()
    init_db()
    # Connector and processing workers are separately supervised processes.
    yield


app = FastAPI(
    title="DARSON Intelligence Layer",
    description="Camera event review, guard tasks and protected evidence above an existing recorder.",
    version="0.1.0",
    lifespan=lifespan,
)

from app.security.middleware import security_boundary  # noqa: E402

app.middleware("http")(security_boundary)


@app.get("/api/v1/session")
def session_info():
    from app.security.context import session_scope
    scope = session_scope()
    return {"tenant": scope.tenant, "site": scope.site, "actor": scope.actor,
            "role": scope.role, "mode": get_settings().auth_mode,
            "status_label": "PROPOSED", "production_ready": False}

app.include_router(health.router)
app.include_router(events.router)
app.include_router(cameras.router)
app.include_router(tracks.router)
app.include_router(incidents.router)
app.include_router(v1_incidents.router)
app.include_router(patterns.router)
app.include_router(search.router)
from app.api.routes import evidence  # noqa: E402
app.include_router(evidence.router)
from app.api.routes import operations  # noqa: E402
app.include_router(operations.router)
from app.api.routes import auth  # noqa: E402
app.include_router(auth.router)
from app.api.routes import demo  # noqa: E402
app.include_router(demo.router)
from app.api.routes import case_studies  # noqa: E402
app.include_router(case_studies.router)
from app.api.routes import parking  # noqa: E402
app.include_router(parking.router)
from app.api.routes import pilot  # noqa: E402
app.include_router(pilot.router)


@app.get("/")
def root() -> dict:
    return {
        "service": "darson-intel",
        "pipeline": "EVENT -> CONTEXT -> CORRELATION -> INCIDENT -> HISTORY -> INVESTIGATION",
        "human_in_the_loop": True,
    }
