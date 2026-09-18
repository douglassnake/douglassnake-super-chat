from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.dashboard import dashboard_payload, project_overview
from app.database import get_db

router = APIRouter(tags=["dashboard"])


@router.get("/dashboard")
def get_dashboard(db: Session = Depends(get_db)) -> dict:
    return dashboard_payload(db)


@router.get("/projects/{project_id}/overview")
def get_project_overview(project_id: UUID, db: Session = Depends(get_db)) -> dict:
    payload = project_overview(db, project_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return payload
