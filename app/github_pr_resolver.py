from __future__ import annotations

import re
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent_models import AgentExecution, ExecutorRequest
from app.agent_task_pack import redact_secrets
from app.core.config import Settings, get_settings
from app.models import ProjectSource


_REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,199}$")
_ALLOWED_PUBLIC_FIELDS = {"publish_request_id", "title", "body"}


class GitHubPRResolutionError(ValueError):
    pass


def _uuid(raw: object, field: str) -> UUID:
    try:
        return UUID(str(raw or "").strip())
    except (TypeError, ValueError) as exc:
        raise GitHubPRResolutionError(f"{field} must be a valid UUID") from exc


def _repository(raw: object) -> str:
    value = str(raw or "").strip().strip("/")
    if not _REPOSITORY_RE.fullmatch(value):
        raise GitHubPRResolutionError(
            "EXECUTOR_GITHUB_WRITE_REPOSITORY must be configured as owner/repository"
        )
    return value


def _ref(raw: object, field: str) -> str:
    value = str(raw or "").strip()
    if (
        not _REF_RE.fullmatch(value)
        or ".." in value
        or "//" in value
        or "@{" in value
        or value.endswith(("/", "."))
    ):
        raise GitHubPRResolutionError(f"{field} is not a safe Git ref")
    return value


def _title(raw: object, head_branch: str) -> str:
    value = str(raw or "").strip() or f"Super Chat: {head_branch}"
    if "\n" in value or "\r" in value or len(value) > 240:
        raise GitHubPRResolutionError("Pull request title must be a single line up to 240 characters")
    return redact_secrets(value) or "Super Chat change"


def _body(raw: object) -> str:
    value = str(raw or "").strip()
    if len(value) > 12_000:
        raise GitHubPRResolutionError("Pull request body exceeds the 12000 character limit")
    return redact_secrets(value) or ""


def resolve_create_pull_request_payload(
    db: Session,
    execution: AgentExecution,
    public_payload: dict[str, Any],
    *,
    settings: Settings | None = None,
) -> dict[str, Any]:
    unknown = sorted(set(public_payload) - _ALLOWED_PUBLIC_FIELDS)
    if unknown:
        raise GitHubPRResolutionError(
            "create_pull_request accepts only publish_request_id, title and body; "
            f"remove: {', '.join(unknown)}"
        )

    publish_id = _uuid(public_payload.get("publish_request_id"), "publish_request_id")
    publish_request = db.get(ExecutorRequest, publish_id)
    if publish_request is None:
        raise GitHubPRResolutionError("Referenced publish_branch request was not found")
    if publish_request.execution_id != execution.id or publish_request.project_id != execution.project_id:
        raise GitHubPRResolutionError("Referenced publication does not belong to this execution/project")
    if publish_request.action != "publish_branch" or publish_request.status != "completed":
        raise GitHubPRResolutionError("create_pull_request requires a completed publish_branch request")

    publish_result = dict(publish_request.result_json or {})
    if publish_result.get("status") != "published_remote":
        raise GitHubPRResolutionError("Referenced publication did not finish as published_remote")
    if publish_result.get("remote_publication_performed") is not True:
        raise GitHubPRResolutionError("Referenced publication has no verified remote publication effect")

    commit_sha = str(publish_result.get("commit_sha") or "").strip().lower()
    remote_sha = str(publish_result.get("remote_sha") or "").strip().lower()
    if not commit_sha or remote_sha != commit_sha:
        raise GitHubPRResolutionError("Published remote SHA does not match the committed SHA")
    if len(commit_sha) not in {40, 64} or any(ch not in "0123456789abcdef" for ch in commit_sha):
        raise GitHubPRResolutionError("Published commit SHA is invalid")

    head_branch = _ref(publish_result.get("branch_name"), "Published head branch")
    if not head_branch.startswith("superchat/"):
        raise GitHubPRResolutionError("Published head branch must use the superchat/ namespace")

    cfg = settings or get_settings()
    repository = _repository(cfg.executor_github_write_repository)
    base_branch = _ref(cfg.executor_github_pr_base_branch, "Configured PR base branch")

    source_stmt = select(ProjectSource).where(
        ProjectSource.project_id == execution.project_id,
        ProjectSource.source_type == "github",
        ProjectSource.is_active.is_(True),
    )
    github_sources = list(db.scalars(source_stmt).all())
    matching_source = next(
        (
            item
            for item in github_sources
            if str(item.external_id or "").strip().strip("/").lower() == repository.lower()
        ),
        None,
    )
    if matching_source is None:
        raise GitHubPRResolutionError(
            "Project has no active GitHub source matching the configured write repository"
        )

    prior_stmt = select(ExecutorRequest).where(
        ExecutorRequest.execution_id == execution.id,
        ExecutorRequest.action == "create_pull_request",
    )
    for prior in db.scalars(prior_stmt).all():
        if str((prior.payload_json or {}).get("publish_request_id") or "") != str(publish_id):
            continue
        if prior.status not in {"failed", "cancelled"}:
            raise GitHubPRResolutionError(
                f"A create_pull_request request already exists for this publication ({prior.status})"
            )

    return {
        "publish_request_id": str(publish_id),
        "project_source_id": str(matching_source.id),
        "repository": repository,
        "base_branch": base_branch,
        "head_branch": head_branch,
        "head_sha": commit_sha,
        "title": _title(public_payload.get("title"), head_branch),
        "body": _body(public_payload.get("body")),
        "draft": bool(cfg.executor_github_pr_draft),
    }
