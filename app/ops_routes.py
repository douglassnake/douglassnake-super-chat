from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.ops import build_operational_status, build_operational_summary, build_recent_failures

router = APIRouter(prefix="/ops", tags=["operations"])


@router.get("/status")
def operational_status(request: Request, db: Session = Depends(get_db)):
    settings = request.app.state.settings
    payload, status_code = build_operational_status(
        db,
        app_version=request.app.version,
        environment=settings.environment,
        started_monotonic=request.app.state.started_monotonic,
    )
    if status_code != 200:
        return JSONResponse(status_code=status_code, content=payload)
    return payload


@router.get("/summary")
def operational_summary(db: Session = Depends(get_db)) -> dict:
    return build_operational_summary(db)


@router.get("/failures")
def operational_failures(
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> dict:
    return {"items": build_recent_failures(db, limit=limit), "limit": limit}
