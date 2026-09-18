from fastapi import FastAPI

from app.core.config import get_settings
from app.routes import router
from app.session_routes import router as session_router

settings = get_settings()
app = FastAPI(title=settings.app_name, version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "environment": settings.environment}


app.include_router(router)
app.include_router(session_router)
