from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Protocol
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent_execution import append_execution_event
from app.agent_handoff import sanitize_value
from app.agent_models import AgentExecution, AgentTaskPack
from app.github_sync import GitHubAPIError, GitHubConnector
from app.models import ProjectSource


class GitHubVerificationReader(Protocol):
    def commit(self, repository: str, sha: str) -> dict[str, Any]: ...
    def pull(self, repository: str, number: int) -> dict[str, Any]: ...
    def check_runs(self, repository: str, sha: str) -> list[dict[str, Any]]: ...


def active_github_repositories(db: Session, project_id) -> list[str]:
    stmt = (
        select(ProjectSource)
        .where(
            ProjectSource.project_id == project_id,
            ProjectSource.source_type == "github",
            ProjectSource.is_active.is_(True),
        )
        .order_by(ProjectSource.created_at.asc())
    )
    repositories: list[str] = []
    seen: set[str] = set()
    for source in db.scalars(stmt).all():
        repository = (source.external_id or "").strip().strip("/")
        parts = repository.split("/")
        if len(parts) != 2 or not all(parts):
            continue
        normalized = f"{parts[0]}/{parts[1]}"
        if normalized.lower() not in seen:
            seen.add(normalized.lower())
            repositories.append(normalized)
    return repositories


def parse_github_pr_url(value: str | None) -> tuple[str, int] | None:
    if not value:
        return None
    try:
        parsed = urlsplit(value)
    except ValueError:
        return None
    if parsed.scheme != "https" or parsed.netloc.lower() not in {"github.com", "www.github.com"}:
        return None
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) != 4 or parts[2] != "pull":
        return None
    try:
        number = int(parts[3])
    except ValueError:
        return None
    if number <= 0:
        return None
    return f"{parts[0]}/{parts[1]}", number


def sha_matches(expected: str | None, observed: str | None) -> bool:
    if not expected or not observed:
        return False
    expected_normalized = expected.strip().lower()
    observed_normalized = observed.strip().lower()
    if not expected_normalized or not observed_normalized:
        return False
    return observed_normalized.startswith(expected_normalized) or expected_normalized.startswith(observed_normalized)


def summarize_check_runs(check_runs: list[dict[str, Any]]) -> dict[str, Any]:
    compact: list[dict[str, Any]] = []
    completed = 0
    successful = 0
    pending = 0
    non_success = 0
    for item in check_runs:
        status = str(item.get("status") or "unknown")
        conclusion = item.get("conclusion")
        if status == "completed":
            completed += 1
            if conclusion == "success":
                successful += 1
            else:
                non_success += 1
        else:
            pending += 1
        compact.append(
            sanitize_value(
                {
                    "id": item.get("id"),
                    "name": item.get("name"),
                    "status": status,
                    "conclusion": conclusion,
                    "details_url": item.get("details_url"),
                    "started_at": item.get("started_at"),
                    "completed_at": item.get("completed_at"),
                }
            )
        )
    checks_green = bool(compact) and pending == 0 and non_success == 0 and successful == len(compact)
    return {
        "count": len(compact),
        "completed": completed,
        "successful": successful,
        "pending": pending,
        "non_success": non_success,
        "checks_green": checks_green,
        "items": compact,
    }


def _base_result(
    *,
    status: str,
    repository: str | None,
    execution: AgentExecution,
    verified_at: str,
    reason: str | None = None,
) -> dict[str, Any]:
    return {
        "provider": "github",
        "status": status,
        "reason": reason,
        "repository": repository,
        "verified_at": verified_at,
        "provenance": "github_api_read_only",
        "references": {
            "commit_sha": execution.commit_sha,
            "pr_url": execution.pr_url,
        },
        "commit": None,
        "pull_request": None,
        "checks": {
            "count": 0,
            "completed": 0,
            "successful": 0,
            "pending": 0,
            "non_success": 0,
            "checks_green": False,
            "items": [],
        },
    }


def _record_verification_event(
    db: Session,
    execution: AgentExecution,
    result: dict[str, Any],
) -> None:
    append_execution_event(
        db,
        execution,
        event_type="external_verification",
        message=f"GitHub verification: {result['status']}",
        payload=result,
    )


def verify_execution_github(
    db: Session,
    execution: AgentExecution,
    pack: AgentTaskPack,
    *,
    criterion_index: int | None = None,
    evidence_rule: str | None = None,
    reader: GitHubVerificationReader | None = None,
) -> dict[str, Any]:
    if execution.status != "running":
        raise ValueError(f"Execution is {execution.status} and cannot be externally verified")
    if not execution.commit_sha and not execution.pr_url:
        raise ValueError("Execution must have commit_sha or pr_url before GitHub verification")

    criteria = list(pack.acceptance_criteria_json or [])
    if (criterion_index is None) != (evidence_rule is None):
        raise ValueError("criterion_index and evidence_rule must be supplied together")
    if criterion_index is not None and criterion_index >= len(criteria):
        raise ValueError(f"Criterion index {criterion_index} does not exist")
    if evidence_rule is not None and evidence_rule != "checks_green":
        raise ValueError(f"Unsupported evidence rule: {evidence_rule}")

    now = datetime.now(timezone.utc)
    verified_at = now.isoformat()
    repositories = active_github_repositories(db, execution.project_id)
    parsed_pr = parse_github_pr_url(execution.pr_url)

    if execution.pr_url and parsed_pr is None:
        result = _base_result(
            status="mismatch",
            repository=None,
            execution=execution,
            verified_at=verified_at,
            reason="invalid_or_non_github_pr_url",
        )
        _record_verification_event(db, execution, result)
        db.commit()
        return {"verification": result, "evidence_attached": False, "evidence_reason": "verification_not_verified"}

    repository: str | None = None
    pr_number: int | None = None
    if parsed_pr is not None:
        parsed_repository, pr_number = parsed_pr
        matched = next((repo for repo in repositories if repo.lower() == parsed_repository.lower()), None)
        if matched is None:
            result = _base_result(
                status="mismatch",
                repository=parsed_repository,
                execution=execution,
                verified_at=verified_at,
                reason="pr_repository_not_linked_to_project",
            )
            result["linked_repositories"] = repositories
            _record_verification_event(db, execution, result)
            db.commit()
            return {"verification": result, "evidence_attached": False, "evidence_reason": "verification_not_verified"}
        repository = matched
    elif len(repositories) == 1:
        repository = repositories[0]
    elif not repositories:
        result = _base_result(
            status="unavailable",
            repository=None,
            execution=execution,
            verified_at=verified_at,
            reason="no_active_github_source",
        )
        _record_verification_event(db, execution, result)
        db.commit()
        return {"verification": result, "evidence_attached": False, "evidence_reason": "verification_unavailable"}
    else:
        result = _base_result(
            status="unavailable",
            repository=None,
            execution=execution,
            verified_at=verified_at,
            reason="ambiguous_repository_for_commit_reference",
        )
        result["linked_repositories"] = repositories
        _record_verification_event(db, execution, result)
        db.commit()
        return {"verification": result, "evidence_attached": False, "evidence_reason": "verification_unavailable"}

    owns_reader = reader is None
    connector: GitHubVerificationReader = reader or GitHubConnector()
    result = _base_result(
        status="verified",
        repository=repository,
        execution=execution,
        verified_at=verified_at,
    )

    try:
        observed_pr: dict[str, Any] | None = None
        if pr_number is not None:
            observed_pr = connector.pull(repository, pr_number)
            observed_number = observed_pr.get("number")
            observed_url = observed_pr.get("html_url")
            observed_url_parsed = parse_github_pr_url(observed_url)
            if observed_number != pr_number or (
                observed_url_parsed is not None
                and observed_url_parsed[0].lower() != repository.lower()
            ):
                result["status"] = "mismatch"
                result["reason"] = "pull_request_identity_mismatch"
            result["pull_request"] = sanitize_value(
                {
                    "number": observed_number,
                    "state": observed_pr.get("state"),
                    "draft": bool(observed_pr.get("draft")),
                    "merged": bool(observed_pr.get("merged")),
                    "html_url": observed_url,
                    "head_sha": (observed_pr.get("head") or {}).get("sha"),
                    "head_ref": (observed_pr.get("head") or {}).get("ref"),
                    "base_ref": (observed_pr.get("base") or {}).get("ref"),
                    "updated_at": observed_pr.get("updated_at"),
                }
            )

        observed_commit: dict[str, Any] | None = None
        if execution.commit_sha:
            observed_commit = connector.commit(repository, execution.commit_sha)
            observed_sha = str(observed_commit.get("sha") or "")
            if not sha_matches(execution.commit_sha, observed_sha):
                result["status"] = "mismatch"
                result["reason"] = "commit_sha_mismatch"
            result["commit"] = sanitize_value(
                {
                    "sha": observed_sha,
                    "html_url": observed_commit.get("html_url"),
                    "message": ((observed_commit.get("commit") or {}).get("message") or "").splitlines()[0],
                }
            )

        pr_head_sha = ((observed_pr or {}).get("head") or {}).get("sha")
        if execution.commit_sha and pr_head_sha and not sha_matches(execution.commit_sha, pr_head_sha):
            result["status"] = "mismatch"
            result["reason"] = "commit_does_not_match_pr_head"

        checks_sha = execution.commit_sha or pr_head_sha
        if checks_sha and result["status"] == "verified":
            result["checks"] = summarize_check_runs(connector.check_runs(repository, checks_sha))
    except GitHubAPIError as exc:
        result["status"] = "not_found" if exc.status_code == 404 else "unavailable"
        result["reason"] = "github_resource_not_found" if exc.status_code == 404 else "github_api_unavailable"
        result["error"] = str(exc)[:500]
    except Exception as exc:
        result["status"] = "unavailable"
        result["reason"] = "github_reader_unavailable"
        result["error"] = str(exc)[:500]
    finally:
        if owns_reader and isinstance(connector, GitHubConnector):
            connector.close()

    result = sanitize_value(result)
    _record_verification_event(db, execution, result)

    evidence_attached = False
    evidence_reason = "no_explicit_evidence_rule"
    if criterion_index is not None and evidence_rule == "checks_green":
        if result["status"] != "verified":
            evidence_reason = "verification_not_verified"
        elif not (result.get("checks") or {}).get("checks_green"):
            evidence_reason = "checks_not_green"
        else:
            append_execution_event(
                db,
                execution,
                event_type="criterion_evidence",
                message="GitHub checks verified as green",
                payload={
                    "criterion": criteria[criterion_index],
                    "evidence_type": "github_checks",
                    "summary": "GitHub check-runs are completed with success",
                    "reference": execution.pr_url or f"github:{repository}@{execution.commit_sha}",
                    "verification_status": result["status"],
                    "verified_at": result["verified_at"],
                    "repository": repository,
                    "checks": result["checks"],
                },
                criterion_index=criterion_index,
                criterion_status="passed",
            )
            evidence_attached = True
            evidence_reason = "checks_green_rule_satisfied"

    db.commit()
    return {
        "verification": result,
        "evidence_attached": evidence_attached,
        "evidence_reason": evidence_reason,
    }
