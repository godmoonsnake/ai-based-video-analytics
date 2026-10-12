from fastapi import HTTPException
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse

from app.config import get_settings
from app.security.auth import authenticate
from app.security.context import scoped

DEMO_PATHS = {"/events/ingest/mock", "/events/ingest/frigate/replay", "/tracks/correlate",
              "/incidents/build", "/patterns/mine", "/api/v1/demo/replay",
              "/api/v1/demo/manifest"}


async def security_boundary(request, call_next):
    if request.url.path in {"/health", "/health/live"}:
        return await call_next(request)
    try:
        scope = await run_in_threadpool(authenticate, request)
        settings = get_settings()
        path, method = request.url.path, request.method
        if settings.pilot_mode and (path in DEMO_PATHS or
                path.startswith(("/api/v1/case-studies", "/api/v1/parking"))):
            raise HTTPException(404, "feature is outside the pilot")
        if settings.environment == "production" and path in DEMO_PATHS:
            raise HTTPException(404, "not found")
        if scope.role == "configuration_admin" and not path.startswith(("/cameras", "/api/v1/config/", "/api/v1/session", "/api/v1/auth/")):
            raise HTTPException(403, "configuration privilege does not grant case/media access")
        responder_read_suffixes = ("/timeline", "/graph", "/explanation", "/state", "/state/history", "/evidence")
        responder_case_read = method == "GET" and (path == "/api/v1/incidents" or
            path.startswith("/api/v1/incidents/") and (path.count("/") == 4 or path.endswith(responder_read_suffixes)))
        responder_media = method == "GET" and path.startswith("/api/v1/evidence/") and path.endswith("/content")
        responder_allowed = responder_media or path.startswith(("/api/v1/pilot/", "/api/v1/operations", "/api/v1/session", "/api/v1/auth/", "/api/v1/health/")) or responder_case_read or (
            path.startswith("/api/v1/incidents/") and path.endswith(("/actions", "/response", "/sla"))) or (
            path.startswith("/api/v1/notifications/") and path.endswith("/acknowledge"))
        if scope.role == "responder" and not responder_allowed:
            raise HTTPException(403, "responders use their assigned task view")
        if method not in {"GET", "HEAD", "OPTIONS"}:
            if scope.role in {"client_viewer", "auditor"} and not (
                    path.endswith("/exports") or path == "/search" or path.endswith("/auth/logout")):
                raise HTTPException(403, "read-only role")
            if path in DEMO_PATHS and scope.role != "supervisor":
                raise HTTPException(403, "demo administration requires supervisor")
        with scoped(scope):
            response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response
    except HTTPException as exc:
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code,
                            headers={"Cache-Control": "no-store"})
