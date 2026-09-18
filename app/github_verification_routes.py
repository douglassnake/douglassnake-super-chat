from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, model_validator
from sqlalchemy.orm import Session

from app.agent_execution import execution_payload
from app.agent_models import AgentExecution, AgentTaskPack
from app.database import get_db
from app.github_verification import verify_execution_github


router = APIRouter(tags=["github-verification"])
EvidenceRule = Literal["checks_green"]


class GitHubVerificationRequest(BaseModel):
    criterion_index: int | None = None
    evidence_rule: EvidenceRule | None = None

    @model_validator(mode="after")
    def require_complete_evidence_mapping(self):
        if (self.criterion_index is None) != (self.evidence_rule is None):
            raise ValueError("criterion_index and evidence_rule must be supplied together")
        if self.criterion_index is not None and self.criterion_index < 0:
            raise ValueError("criterion_index must be non-negative")
        return self


def _get_execution(db: Session, execution_id: UUID) -> AgentExecution:
    execution = db.get(AgentExecution, execution_id)
    if execution is None:
        raise HTTPException(status_code=404, detail="Agent execution not found")
    return execution


def _get_pack(db: Session, pack_id: UUID) -> AgentTaskPack:
    pack = db.get(AgentTaskPack, pack_id)
    if pack is None:
        raise HTTPException(status_code=404, detail="Agent task pack not found")
    return pack


@router.post("/agent-executions/{execution_id}/verify-github")
def verify_agent_execution_github(
    execution_id: UUID,
    payload: GitHubVerificationRequest,
    db: Session = Depends(get_db),
) -> dict:
    execution = _get_execution(db, execution_id)
    pack = _get_pack(db, execution.pack_id)

    if execution.status != "running":
        raise HTTPException(
            status_code=409,
            detail=f"Execution is {execution.status} and cannot be externally verified",
        )
    if not execution.commit_sha and not execution.pr_url:
        raise HTTPException(
            status_code=409,
            detail="Execution must have commit_sha or pr_url before GitHub verification",
        )
    if payload.criterion_index is not None:
        criteria = list(pack.acceptance_criteria_json or [])
        if payload.criterion_index >= len(criteria):
            raise HTTPException(
                status_code=422,
                detail=f"Criterion index {payload.criterion_index} does not exist",
            )

    try:
        verification = verify_execution_github(
            db,
            execution,
            pack,
            criterion_index=payload.criterion_index,
            evidence_rule=payload.evidence_rule,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    db.refresh(execution)
    return {
        **verification,
        "execution": execution_payload(db, execution, pack),
    }
