from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.github_onboarding import (
    GitHubOnboardingConflict,
    GitHubOnboardingError,
    prepare_github_onboarding,
)
from app.github_sync import GitHubAPIError
from app.models import Project
from app.session_schemas import SessionDeltaRead

router = APIRouter(tags=["onboarding"])


@router.post("/projects/{project_id}/github/onboarding")
def prepare_project_github_onboarding(
    project_id: UUID,
    db: Session = Depends(get_db),
) -> dict:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    try:
        result = prepare_github_onboarding(db, project)
    except GitHubOnboardingConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except GitHubOnboardingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except GitHubAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return {
        **result,
        "delta": SessionDeltaRead.model_validate(result["delta"]),
    }
