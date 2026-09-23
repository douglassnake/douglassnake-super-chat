from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from app.agent_models import AgentExecution, ExecutorRequest
from app.agent_task_pack import redact_secrets


class GitCommitResolutionError(ValueError):
    pass


def _uuid(value: object, field: str) -> UUID:
    try:
        return UUID(str(value))
    except (TypeError, ValueError) as exc:
        raise GitCommitResolutionError(f"{field} must be a valid UUID") from exc


def _commit_message(raw: object) -> str:
    if not isinstance(raw, str):
        raise GitCommitResolutionError("commit_message must be a string")
    value = raw.strip()
    if not value:
        raise GitCommitResolutionError("commit_message is required")
    if len(value) > 200:
        raise GitCommitResolutionError("commit_message must contain at most 200 characters")
    if "\x00" in value or "\n" in value or "\r" in value:
        raise GitCommitResolutionError("commit_message must be a single line without NUL bytes")
    if (redact_secrets(value) or "") != value:
        raise GitCommitResolutionError("commit_message contains detectable secret-like content")
    return value


def _valid_sha(value: object, *, field: str) -> str:
    text = str(value or "").strip().lower()
    if len(text) not in {40, 64} or any(ch not in "0123456789abcdef" for ch in text):
        raise GitCommitResolutionError(f"{field} is not a valid object SHA")
    return text


def _valid_digest(value: object) -> str:
    text = str(value or "").strip().lower()
    if len(text) != 64 or any(ch not in "0123456789abcdef" for ch in text):
        raise GitCommitResolutionError("apply result does not contain a valid patch digest")
    return text


def resolve_create_commit_payload(
    db: Session,
    execution: AgentExecution,
    public_payload: dict,
) -> dict:
    if set(public_payload) != {"apply_request_id", "commit_message"}:
        raise GitCommitResolutionError(
            "create_commit accepts only apply_request_id and commit_message"
        )

    apply_request_id = _uuid(public_payload.get("apply_request_id"), "apply_request_id")
    message = _commit_message(public_payload.get("commit_message"))
    apply_request = db.get(ExecutorRequest, apply_request_id)
    if apply_request is None:
        raise GitCommitResolutionError("Git apply executor request not found")
    if apply_request.project_id != execution.project_id:
        raise GitCommitResolutionError("Git apply request belongs to a different project")
    if apply_request.action != "apply_git_change" or apply_request.status != "completed":
        raise GitCommitResolutionError(
            "create_commit requires a completed apply_git_change request"
        )

    result = apply_request.result_json or {}
    if result.get("status") != "applied_uncommitted":
        raise GitCommitResolutionError("Git apply request is not an uncommitted staging result")
    if result.get("commit_created") is not False:
        raise GitCommitResolutionError("Git apply result is not explicitly uncommitted")

    payload = apply_request.payload_json or {}
    worktree = str(payload.get("worktree") or "").strip()
    branch_name = str(result.get("branch_name") or "").strip()
    base_sha = _valid_sha(result.get("base_sha"), field="base_sha")
    patch_digest = _valid_digest(result.get("patch_digest"))
    staging_id = str(result.get("staging_id") or "").strip()
    approval_id = str(result.get("approval_id") or "").strip()
    changed_files = result.get("changed_files")

    if not worktree:
        raise GitCommitResolutionError("Git apply request does not contain its source worktree")
    if not branch_name.startswith("superchat/"):
        raise GitCommitResolutionError("Git apply result is outside the controlled branch namespace")
    if not staging_id.startswith("approval-"):
        raise GitCommitResolutionError("Git apply result does not contain a controlled staging id")
    try:
        UUID(staging_id.removeprefix("approval-"))
        UUID(approval_id)
    except ValueError as exc:
        raise GitCommitResolutionError("Git apply result contains invalid approval/staging identity") from exc
    if not isinstance(changed_files, list) or not changed_files:
        raise GitCommitResolutionError("Git apply result does not contain a changed-file inventory")

    # Cross-check immutable server-resolved apply payload against its result snapshot.
    if str(payload.get("branch_name") or "").strip() != branch_name:
        raise GitCommitResolutionError("Git apply branch snapshot is inconsistent")
    if _valid_sha(payload.get("base_sha"), field="resolved base_sha") != base_sha:
        raise GitCommitResolutionError("Git apply base SHA snapshot is inconsistent")
    if _valid_digest(payload.get("patch_digest")) != patch_digest:
        raise GitCommitResolutionError("Git apply patch digest snapshot is inconsistent")
    if str(payload.get("approval_id") or "").strip() != approval_id:
        raise GitCommitResolutionError("Git apply approval snapshot is inconsistent")

    return {
        "apply_request_id": str(apply_request.id),
        "approval_id": approval_id,
        "worktree": worktree,
        "staging_id": staging_id,
        "branch_name": branch_name,
        "base_sha": base_sha,
        "patch_digest": patch_digest,
        "changed_files": changed_files,
        "commit_message": message,
    }
