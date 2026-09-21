from __future__ import annotations

import hashlib
import json
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.agent_execution import append_execution_event
from app.agent_handoff import sanitize_value
from app.agent_models import AgentExecution, ExecutorRequest
from app.database import get_db
from app.git_change_models import GitChangeApproval
from app.models import utcnow


router = APIRouter(tags=["git-change-approval"])


class GitChangeApprovalConfirm(BaseModel):
    patch_digest: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")


def _approval_payload(item: GitChangeApproval) -> dict:
    return {
        "id": item.id,
        "executor_request_id": item.executor_request_id,
        "execution_id": item.execution_id,
        "project_id": item.project_id,
        "status": item.status,
        "patch_digest": item.patch_digest,
        "proposal_fingerprint": item.proposal_fingerprint,
        "changed_files": item.changed_files_json or [],
        "created_at": item.created_at,
        "approved_at": item.approved_at,
        "cancelled_at": item.cancelled_at,
    }


def _proposal_from_request(request: ExecutorRequest) -> tuple[str, list]:
    if request.action != "modify_worktree":
        raise HTTPException(
            status_code=409,
            detail="Git change approval requires a modify_worktree executor request",
        )
    if request.status != "completed":
        raise HTTPException(
            status_code=409,
            detail=f"Executor request is {request.status}; only completed proposals can be approved",
        )
    result = request.result_json or {}
    if result.get("status") != "proposed":
        raise HTTPException(status_code=409, detail="Executor request does not contain a proposed change")
    digest = str(result.get("patch_digest") or "")
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise HTTPException(status_code=409, detail="Proposal does not contain a valid patch digest")
    changed_files = sanitize_value(result.get("changed_files") or [])
    if not isinstance(changed_files, list) or not changed_files:
        raise HTTPException(status_code=409, detail="Proposal has no changed files")
    return digest, changed_files


def _fingerprint(request: ExecutorRequest, digest: str, changed_files: list) -> str:
    canonical = json.dumps(
        {
            "executor_request_id": str(request.id),
            "execution_id": str(request.execution_id),
            "project_id": str(request.project_id),
            "patch_digest": digest,
            "changed_files": changed_files,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _get_approval(db: Session, approval_id: UUID) -> GitChangeApproval:
    item = db.get(GitChangeApproval, approval_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Git change approval not found")
    return item


@router.post(
    "/executor-requests/{request_id}/git-change-approval",
    status_code=status.HTTP_201_CREATED,
)
def prepare_git_change_approval(
    request_id: UUID,
    db: Session = Depends(get_db),
) -> dict:
    request = db.get(ExecutorRequest, request_id)
    if request is None:
        raise HTTPException(status_code=404, detail="Executor request not found")
    digest, changed_files = _proposal_from_request(request)
    existing = db.scalar(
        select(GitChangeApproval).where(
            GitChangeApproval.executor_request_id == request.id
        )
    )
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "A Git change approval already exists for this proposal",
                "approval_id": str(existing.id),
                "status": existing.status,
            },
        )
    item = GitChangeApproval(
        executor_request_id=request.id,
        execution_id=request.execution_id,
        project_id=request.project_id,
        status="pending",
        patch_digest=digest,
        proposal_fingerprint=_fingerprint(request, digest, changed_files),
        changed_files_json=changed_files,
    )
    db.add(item)
    execution = db.get(AgentExecution, request.execution_id)
    try:
        db.flush()
        if execution is not None:
            append_execution_event(
                db,
                execution,
                event_type="git_change_approval_prepared",
                message="Git change proposal awaiting explicit digest approval",
                payload={
                    "approval_id": str(item.id),
                    "executor_request_id": str(request.id),
                    "patch_digest": digest,
                    "proposal_fingerprint": item.proposal_fingerprint,
                },
            )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Git change approval already exists") from exc
    db.refresh(item)
    return _approval_payload(item)


@router.get("/git-change-approvals/{approval_id}")
def read_git_change_approval(
    approval_id: UUID,
    db: Session = Depends(get_db),
) -> dict:
    return _approval_payload(_get_approval(db, approval_id))


@router.get("/agent-executions/{execution_id}/git-change-approvals")
def list_git_change_approvals(
    execution_id: UUID,
    db: Session = Depends(get_db),
) -> list[dict]:
    stmt = (
        select(GitChangeApproval)
        .where(GitChangeApproval.execution_id == execution_id)
        .order_by(GitChangeApproval.created_at.asc())
    )
    return [_approval_payload(item) for item in db.scalars(stmt).all()]


@router.post("/git-change-approvals/{approval_id}/approve")
def approve_git_change(
    approval_id: UUID,
    payload: GitChangeApprovalConfirm,
    db: Session = Depends(get_db),
) -> dict:
    item = _get_approval(db, approval_id)
    if item.status == "approved":
        if payload.patch_digest != item.patch_digest:
            raise HTTPException(status_code=409, detail="Approved digest does not match supplied digest")
        return _approval_payload(item)
    if item.status != "pending":
        raise HTTPException(status_code=409, detail=f"Approval is {item.status} and cannot be approved")
    if payload.patch_digest != item.patch_digest:
        raise HTTPException(
            status_code=409,
            detail="Patch digest mismatch; regenerate/review the proposal before approving",
        )
    item.status = "approved"
    item.approved_at = utcnow()
    execution = db.get(AgentExecution, item.execution_id)
    if execution is not None:
        append_execution_event(
            db,
            execution,
            event_type="git_change_approved",
            message="Git change proposal approved by exact patch digest",
            payload={
                "approval_id": str(item.id),
                "patch_digest": item.patch_digest,
                "proposal_fingerprint": item.proposal_fingerprint,
            },
        )
    db.commit()
    db.refresh(item)
    return _approval_payload(item)


@router.post("/git-change-approvals/{approval_id}/cancel")
def cancel_git_change(
    approval_id: UUID,
    db: Session = Depends(get_db),
) -> dict:
    item = _get_approval(db, approval_id)
    if item.status == "cancelled":
        return _approval_payload(item)
    if item.status != "pending":
        raise HTTPException(status_code=409, detail=f"Approval is {item.status} and cannot be cancelled")
    item.status = "cancelled"
    item.cancelled_at = utcnow()
    execution = db.get(AgentExecution, item.execution_id)
    if execution is not None:
        append_execution_event(
            db,
            execution,
            event_type="git_change_cancelled",
            message="Git change proposal cancelled",
            payload={
                "approval_id": str(item.id),
                "patch_digest": item.patch_digest,
            },
        )
    db.commit()
    db.refresh(item)
    return _approval_payload(item)
