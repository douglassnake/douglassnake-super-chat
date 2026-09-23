from pathlib import Path
import time

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.agent_routes import router as agent_router
from app.auth import AuthMiddleware, validate_security_settings
from app.auth_routes import router as auth_router
from app.core.config import get_settings
from app.dashboard_routes import router as dashboard_router
from app.database import SessionLocal
from app.evaluation_routes import router as evaluation_router
from app.execution_routes import router as execution_router
from app.executor_routes import router as executor_router
from app.git_change_routes import router as git_change_router
from app.github_verification_routes import router as github_verification_router
from app.handoff_routes import router as handoff_router
from app.observability import ObservabilityMiddleware
from app.ops_routes import router as ops_router
from app.routes import router
from app.session_routes import router as session_router
from app.worker_attempt_routes import router as worker_attempt_router

settings = get_settings()
validate_security_settings(settings)
app = FastAPI(title=settings.app_name, version="0.9.1")
app.state.settings = settings
app.state.started_monotonic = time.monotonic()
app.add_middleware(AuthMiddleware, settings=settings, session_factory=SessionLocal)
# Starlette inserts the most recently added middleware as the outer layer.
# Observability therefore sees responses produced by AuthMiddleware without
# inspecting authentication cookies or headers directly.
app.add_middleware(ObservabilityMiddleware)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse(url="/app/")


app.include_router(auth_router)
app.include_router(ops_router)
app.include_router(router)
app.include_router(session_router)
app.include_router(dashboard_router)
app.include_router(evaluation_router)
app.include_router(agent_router)
app.include_router(handoff_router)
app.include_router(execution_router)
app.include_router(github_verification_router)
app.include_router(executor_router)
app.include_router(worker_attempt_router)
app.include_router(git_change_router)

web_dir = Path(__file__).resolve().parent.parent / "web"
app.mount("/app", StaticFiles(directory=web_dir, html=True), name="web")
