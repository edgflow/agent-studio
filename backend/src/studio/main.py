"""The FastAPI application."""

from fastapi import Depends, FastAPI

from studio import auth
from studio.routes import executions, projects, workflows
from studio.security import require_csrf_header


def create_app() -> FastAPI:
    app = FastAPI(title="Agent Studio", dependencies=[Depends(require_csrf_header)])
    app.include_router(auth.router)
    app.include_router(projects.router)
    app.include_router(workflows.router)
    app.include_router(executions.router)

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
