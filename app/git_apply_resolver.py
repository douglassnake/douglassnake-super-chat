from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from app.agent_models import AgentExecution, ExecutorRequest
from app.git_change_models import GitChangeApproval


class GitApplyResolutionError(ValueError):
    pass


def _uuid(value: object, field: str) -> UUID:
    try:
        return UUID(str(value))
    except (TypeError, ValueError) as exc:
        raise GitApplyResolutionError(f"{field} must be a valid UUID") from exc


def resolve_apply_git_change_payload(
    db: Session,
    execution: AgentExecution,
    public_payload: dict,
) -> dict:
    if set(public_payload) != {"approval_id", "branch_request_id"}:
        raise GitApplyResolutionError(
            "apply_git_change accepts only approval_id and branch_request_id"
        )

    approval_id = _uuid(public_payload.get("approval_id"), "approval_id")
    branch_request_id = _uuid(
        public_payload.get("branch_request_id"), "branch_request_id"
    )

    approval = db.get(GitChangeApproval, approval_id)
    if approval is None:
        raise GitApplyResolutionError("Git change approval not found")
    if approval.status != "approved":
        raise GitApplyResolutionError(
            f"Git change approval is {approval.status}; approved is required"
        )
    if approval.project_id != execution.project_id:
        raise GitApplyResolutionError(
            "Git change approval belongs to a different project"
        )

    source_request = db.get(ExecutorRequest, approval.executor_request_id)
    if source_request is None:
        raise GitApplyResolutionError("Approved source executor request not found")
    if source_request.project_id != execution.project_id:
        raise GitApplyResolutionError("Approved proposal belongs to a different project")
    if source_request.action != "modify_worktree" or source_request.status != "completed":
        raise GitApplyResolutionError(
            "Approved proposal must reference a completed modify_worktree request"
        )

    source_result = source_request.result_json or {}
    if source_result.get("status") != "proposed":
        raise GitApplyResolutionError("Approved source request is not a proposal")
    patch_digest = str(source_result.get("patch_digest") or "")
    if patch_digest != approval.patch_digest:
        raise GitApplyResolutionError(
            "Approved digest no longer matches the source proposal snapshot"
        )

    source_payload = source_request.payload_json or {}
    worktree = str(source_payload.get("worktree") or "").strip()
    operations = source_payload.get("operations")
    if not worktree or not isinstance(operations, list) or not operations:
        raise GitApplyResolutionError(
            "Approved source proposal does not contain a valid worktree/operations snapshot"
        )

    branch_request = db.get(ExecutorRequest, branch_request_id)
    if branch_request is None:
        raise GitApplyResolutionError("Branch executor request not found")
    if branch_request.project_id != execution.project_id:
        raise GitApplyResolutionError("Branch request belongs to a different project")
    if branch_request.action != "create_branch" or branch_request.status != "completed":
        raise GitApplyResolutionError(
            "Branch request must be a completed create_branch action"
        )

    branch_result = branch_request.result_json or {}
    if branch_result.get("status") != "created":
        raise GitApplyResolutionError("Branch request does not contain a created branch")
    branch_name = str(branch_result.get("branch_name") or "").strip()
    base_sha = str(branch_result.get("base_sha") or "").strip().lower()
    branch_worktree = str((branch_request.payload_json or {}).get("worktree") or "").strip()
    if not branch_name.startswith("superchat/"):
        raise GitApplyResolutionError("Branch is outside the controlled superchat/ namespace")
    if len(base_sha) not in {40, 64} or any(ch not in "0123456789abcdef" for ch in base_sha):
        raise GitApplyResolutionError("Branch request does not contain a valid base SHA")
    if branch_worktree != worktree:
        raise GitApplyResolutionError(
            "Approved proposal and branch request target different worktrees"
        )

    return {
        "approval_id": str(approval.id),
        "source_request_id": str(source_request.id),
        "branch_request_id": str(branch_request.id),
        "patch_digest": patch_digest,
        "changed_files": approval.changed_files_json or [],
        "worktree": worktree,
        "operations": operations,
        "branch_name": branch_name,
        "base_sha": base_sha,
    }
