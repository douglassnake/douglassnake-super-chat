from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.core.config import get_settings
from app.dashboard_routes import router as dashboard_router
from app.routes import router
from app.session_routes import router as session_router

settings = get_settings()
app = FastAPI(title=settings.app_name, version="0.5.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "environment": settings.environment}


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse(url="/app/")


app.include_router(router)
app.include_router(session_router)
app.include_router(dashboard_router)

web_dir = Path(__file__).resolve().parent.parent / "web"
app.mount("/app", StaticFiles(directory=web_dir, html=True), name="web")
