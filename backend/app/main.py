"""DARSON intelligence-layer FastAPI application.

An intelligence layer ABOVE an existing VMS: EVENT -> CONTEXT -> CORRELATION ->
INCIDENT -> HISTORY -> INVESTIGATION. Human-in-the-loop decision support only.
No facial/gait recognition, no PII database, no autonomous verdicts.
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import cameras, events, health, incidents, patterns, search, tracks
from app.db.init_db import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="DARSON Intelligence Layer",
    description="AI-based video-analytics intelligence layer above an existing VMS.",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(health.router)
app.include_router(events.router)
app.include_router(cameras.router)
app.include_router(tracks.router)
app.include_router(incidents.router)
app.include_router(patterns.router)
app.include_router(search.router)


@app.get("/")
def root() -> dict:
    return {
        "service": "darson-intel",
        "pipeline": "EVENT -> CONTEXT -> CORRELATION -> INCIDENT -> HISTORY -> INVESTIGATION",
        "human_in_the_loop": True,
    }
