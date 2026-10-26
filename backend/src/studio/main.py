"""The FastAPI application."""

from fastapi import Depends, FastAPI

from studio import auth
from studio.request_id import RequestIdMiddleware
from studio.routes import (
    audit_logs,
    connections,
    executions,
    live,
    members,
    projects,
    versions,
    workflows,
)
from studio.security import require_csrf_header


def create_app() -> FastAPI:
    app = FastAPI(title="Agent Studio", dependencies=[Depends(require_csrf_header)])
    app.add_middleware(RequestIdMiddleware)
    app.include_router(auth.router)
    app.include_router(projects.router)
    app.include_router(workflows.router)
    app.include_router(versions.router)
    app.include_router(executions.router)
    app.include_router(members.router)
    app.include_router(connections.router)
    app.include_router(live.router)
    app.include_router(audit_logs.router)

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
