from __future__ import annotations

import re
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent_models import AgentExecution, ExecutorRequest
from app.core.config import Settings, get_settings
from app.models import ProjectSource


_REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,199}$")


class GitHubPublishResolutionError(ValueError):
    pass


def _uuid(raw: object, field: str) -> UUID:
    try:
        return UUID(str(raw or "").strip())
    except (TypeError, ValueError) as exc:
        raise GitHubPublishResolutionError(f"{field} must be a valid UUID") from exc


def _repository(raw: object) -> str:
    value = str(raw or "").strip().strip("/")
    if not _REPOSITORY_RE.fullmatch(value):
        raise GitHubPublishResolutionError(
            "EXECUTOR_GITHUB_PUBLISH_REPOSITORY must be configured as owner/repository"
        )
    return value


def _branch(raw: object) -> str:
    value = str(raw or "").strip()
    if (
        not _REF_RE.fullmatch(value)
        or ".." in value
        or "//" in value
        or "@{" in value
        or value.endswith(("/", "."))
        or not value.startswith("superchat/")
    ):
        raise GitHubPublishResolutionError("Published branch is not a safe superchat/* ref")
    return value


def resolve_publish_github_branch_payload(
    db: Session,
    execution: AgentExecution,
    public_payload: dict[str, Any],
    *,
    settings: Settings | None = None,
) -> dict[str, Any]:
    if set(public_payload) != {"publish_request_id"}:
        raise GitHubPublishResolutionError(
            "publish_github_branch accepts only publish_request_id"
        )

    publish_id = _uuid(public_payload.get("publish_request_id"), "publish_request_id")
    publish_request = db.get(ExecutorRequest, publish_id)
    if publish_request is None:
        raise GitHubPublishResolutionError("Referenced publish_branch request was not found")
    if publish_request.execution_id != execution.id or publish_request.project_id != execution.project_id:
        raise GitHubPublishResolutionError("Referenced publication does not belong to this execution/project")
    if publish_request.action != "publish_branch" or publish_request.status != "completed":
        raise GitHubPublishResolutionError(
            "publish_github_branch requires a completed publish_branch request"
        )

    result = dict(publish_request.result_json or {})
    if result.get("status") != "published_remote" or result.get("remote_publication_performed") is not True:
        raise GitHubPublishResolutionError("Referenced M8.12 publication is not verified")

    head_sha = str(result.get("commit_sha") or "").strip().lower()
    remote_sha = str(result.get("remote_sha") or "").strip().lower()
    if remote_sha != head_sha or len(head_sha) not in {40, 64} or any(ch not in "0123456789abcdef" for ch in head_sha):
        raise GitHubPublishResolutionError("M8.12 remote SHA does not match a valid commit SHA")
    head_branch = _branch(result.get("branch_name"))

    cfg = settings or get_settings()
    repository = _repository(cfg.executor_github_publish_repository)
    source_stmt = select(ProjectSource).where(
        ProjectSource.project_id == execution.project_id,
        ProjectSource.source_type == "github",
        ProjectSource.is_active.is_(True),
    )
    source = next(
        (
            item
            for item in db.scalars(source_stmt).all()
            if str(item.external_id or "").strip().strip("/").lower() == repository.lower()
        ),
        None,
    )
    if source is None:
        raise GitHubPublishResolutionError(
            "Project has no active GitHub source matching the configured publication repository"
        )

    prior_stmt = select(ExecutorRequest).where(
        ExecutorRequest.execution_id == execution.id,
        ExecutorRequest.action == "publish_github_branch",
    )
    for prior in db.scalars(prior_stmt).all():
        if str((prior.payload_json or {}).get("publish_request_id") or "") != str(publish_id):
            continue
        if prior.status not in {"failed", "cancelled"}:
            raise GitHubPublishResolutionError(
                f"A publish_github_branch request already exists for this publication ({prior.status})"
            )

    return {
        "publish_request_id": str(publish_id),
        "project_source_id": str(source.id),
        "repository": repository,
        "head_branch": head_branch,
        "head_sha": head_sha,
        "local_remote_id": str(result.get("remote_id") or "controlled-bare")[:80],
    }
