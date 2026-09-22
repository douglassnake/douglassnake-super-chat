from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.agent_routes import router as agent_router
from app.core.config import get_settings
from app.dashboard_routes import router as dashboard_router
from app.evaluation_routes import router as evaluation_router
from app.execution_routes import router as execution_router
from app.executor_routes import router as executor_router
from app.git_change_routes import router as git_change_router
from app.github_verification_routes import router as github_verification_router
from app.handoff_routes import router as handoff_router
from app.routes import router
from app.session_routes import router as session_router
from app.worker_attempt_routes import router as worker_attempt_router

settings = get_settings()
app = FastAPI(title=settings.app_name, version="0.8.12")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "environment": settings.environment}


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse(url="/app/")


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
