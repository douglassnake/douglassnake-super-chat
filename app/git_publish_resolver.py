from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from app.agent_models import AgentExecution, ExecutorRequest


class GitPublishResolutionError(ValueError):
    pass


def _uuid(raw: object, field: str) -> UUID:
    try:
        return UUID(str(raw))
    except (TypeError, ValueError) as exc:
        raise GitPublishResolutionError(f"{field} must be a valid UUID") from exc


def _sha(raw: object, field: str) -> str:
    value = str(raw or "").strip().lower()
    if len(value) not in {40, 64} or any(ch not in "0123456789abcdef" for ch in value):
        raise GitPublishResolutionError(f"{field} is not a valid object SHA")
    return value


def _digest(raw: object) -> str:
    value = str(raw or "").strip().lower()
    if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
        raise GitPublishResolutionError("commit result does not contain a valid patch digest")
    return value


def resolve_publish_branch_payload(
    db: Session,
    execution: AgentExecution,
    public_payload: dict,
) -> dict:
    if set(public_payload) != {"commit_request_id"}:
        raise GitPublishResolutionError("publish_branch accepts only commit_request_id")

    request_id = _uuid(public_payload.get("commit_request_id"), "commit_request_id")
    commit_request = db.get(ExecutorRequest, request_id)
    if commit_request is None:
        raise GitPublishResolutionError("Commit executor request not found")
    if commit_request.project_id != execution.project_id:
        raise GitPublishResolutionError("Commit request belongs to a different project")
    if commit_request.action != "create_commit" or commit_request.status != "completed":
        raise GitPublishResolutionError("publish_branch requires a completed create_commit request")

    result = commit_request.result_json or {}
    payload = commit_request.payload_json or {}
    if result.get("status") != "committed_local" or result.get("commit_created") is not True:
        raise GitPublishResolutionError("Commit request does not contain a controlled local commit")
    if result.get("push_performed") is not False:
        raise GitPublishResolutionError("Commit result is not explicitly unpublished")
    if result.get("pull_request_created") is not False:
        raise GitPublishResolutionError("Commit result already reports a pull request effect")

    branch_name = str(result.get("branch_name") or "").strip()
    if not branch_name.startswith("superchat/"):
        raise GitPublishResolutionError("Commit branch is outside the controlled namespace")
    worktree = str(payload.get("worktree") or result.get("source_worktree") or "").strip()
    if not worktree:
        raise GitPublishResolutionError("Commit request does not contain the source worktree")
    staging_id = str(result.get("staging_id") or payload.get("staging_id") or "").strip()
    if not staging_id.startswith("approval-"):
        raise GitPublishResolutionError("Commit result does not contain a controlled staging id")

    commit_sha = _sha(result.get("commit_sha"), "commit_sha")
    base_sha = _sha(result.get("base_sha"), "base_sha")
    patch_digest = _digest(result.get("patch_digest"))
    changed_files = result.get("changed_files")
    if not isinstance(changed_files, list) or not changed_files:
        raise GitPublishResolutionError("Commit result does not contain a changed-file inventory")

    # Cross-check snapshots persisted before and after the commit.
    if str(payload.get("branch_name") or "").strip() != branch_name:
        raise GitPublishResolutionError("Commit branch snapshot is inconsistent")
    if _sha(payload.get("base_sha"), "resolved base_sha") != base_sha:
        raise GitPublishResolutionError("Commit base snapshot is inconsistent")
    if _digest(payload.get("patch_digest")) != patch_digest:
        raise GitPublishResolutionError("Commit patch digest snapshot is inconsistent")

    return {
        "commit_request_id": str(commit_request.id),
        "worktree": worktree,
        "staging_id": staging_id,
        "branch_name": branch_name,
        "base_sha": base_sha,
        "commit_sha": commit_sha,
        "patch_digest": patch_digest,
        "changed_files": changed_files,
    }
