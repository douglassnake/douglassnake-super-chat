from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Protocol
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Event, Project, ProjectSource


class GitHubAPIError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class GitHubReader(Protocol):
    def repository(self, repository: str) -> dict[str, Any]: ...
    def commits(self, repository: str) -> list[dict[str, Any]]: ...
    def pulls(self, repository: str) -> list[dict[str, Any]]: ...
    def issues(self, repository: str) -> list[dict[str, Any]]: ...
    def workflow_runs(self, repository: str) -> list[dict[str, Any]]: ...
    def commit(self, repository: str, sha: str) -> dict[str, Any]: ...
    def pull(self, repository: str, number: int) -> dict[str, Any]: ...
    def check_runs(self, repository: str, sha: str) -> list[dict[str, Any]]: ...


class GitHubConnector:
    def __init__(
        self,
        token: str | None = None,
        api_url: str | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        settings = get_settings()
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "douglassnake-super-chat",
        }
        resolved_token = token if token is not None else settings.github_token
        if resolved_token:
            headers["Authorization"] = f"Bearer {resolved_token}"
        self.client = httpx.Client(
            base_url=(api_url or settings.github_api_url).rstrip("/"),
            headers=headers,
            timeout=15.0,
            transport=transport,
        )

    def close(self) -> None:
        self.client.close()

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        try:
            response = self.client.get(path, params=params)
        except httpx.HTTPError as exc:
            raise GitHubAPIError(f"GitHub request unavailable: {exc}") from exc
        if response.status_code >= 400:
            rate_remaining = response.headers.get("x-ratelimit-remaining")
            detail = response.text[:500]
            raise GitHubAPIError(
                f"GitHub request failed ({response.status_code}, rate_remaining={rate_remaining}): {detail}",
                status_code=response.status_code,
            )
        return response.json()

    def repository(self, repository: str) -> dict[str, Any]:
        return self._get(f"/repos/{repository}")

    def commits(self, repository: str) -> list[dict[str, Any]]:
        return self._get(f"/repos/{repository}/commits", {"per_page": 20})

    def pulls(self, repository: str) -> list[dict[str, Any]]:
        return self._get(f"/repos/{repository}/pulls", {"state": "open", "per_page": 20})

    def issues(self, repository: str) -> list[dict[str, Any]]:
        payload = self._get(f"/repos/{repository}/issues", {"state": "open", "per_page": 20})
        return [item for item in payload if "pull_request" not in item]

    def workflow_runs(self, repository: str) -> list[dict[str, Any]]:
        payload = self._get(f"/repos/{repository}/actions/runs", {"per_page": 20})
        return payload.get("workflow_runs", [])

    def commit(self, repository: str, sha: str) -> dict[str, Any]:
        return self._get(f"/repos/{repository}/commits/{sha}")

    def pull(self, repository: str, number: int) -> dict[str, Any]:
        return self._get(f"/repos/{repository}/pulls/{number}")

    def check_runs(self, repository: str, sha: str) -> list[dict[str, Any]]:
        payload = self._get(
            f"/repos/{repository}/commits/{sha}/check-runs",
            {"per_page": 100},
        )
        return payload.get("check_runs", [])


def parse_github_datetime(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def event_exists(
    db: Session,
    project_id: UUID,
    event_type: str,
    external_id: str,
) -> bool:
    stmt = select(Event.id).where(
        Event.project_id == project_id,
        Event.source_type == "github",
        Event.event_type == event_type,
        Event.external_id == external_id,
    )
    return db.scalar(stmt) is not None


def add_event_if_new(
    db: Session,
    *,
    project_id: UUID,
    event_type: str,
    external_id: str,
    title: str,
    body: str | None,
    occurred_at: datetime,
    url: str | None,
    metadata: dict[str, Any],
) -> bool:
    if event_exists(db, project_id, event_type, external_id):
        return False
    db.add(
        Event(
            project_id=project_id,
            source_type="github",
            event_type=event_type,
            external_id=external_id,
            title=title[:255],
            body=body,
            occurred_at=occurred_at,
            url=url,
            metadata_json=metadata,
        )
    )
    return True


def sync_project_github(
    db: Session,
    project: Project,
    reader: GitHubReader | None = None,
) -> dict[str, Any]:
    sources_stmt = select(ProjectSource).where(
        ProjectSource.project_id == project.id,
        ProjectSource.source_type == "github",
        ProjectSource.is_active.is_(True),
    )
    sources = list(db.scalars(sources_stmt).all())

    owns_reader = reader is None
    connector: GitHubReader = reader or GitHubConnector()
    now = datetime.now(timezone.utc)
    source_results: list[dict[str, Any]] = []
    total_created = 0
    total_skipped = 0

    try:
        for source in sources:
            repository = (source.external_id or "").strip().strip("/")
            if not repository or "/" not in repository:
                raise GitHubAPIError(f"Invalid GitHub repository identifier: {repository!r}")

            repo_data = connector.repository(repository)
            commits = connector.commits(repository)
            pulls = connector.pulls(repository)
            issues = connector.issues(repository)
            runs = connector.workflow_runs(repository)

            created = 0
            skipped = 0

            for item in commits:
                sha = str(item.get("sha") or "")
                commit_data = item.get("commit") or {}
                author = commit_data.get("author") or commit_data.get("committer") or {}
                message = str(commit_data.get("message") or "Commit sem mensagem")
                title = message.splitlines()[0] if message else "Commit"
                was_created = add_event_if_new(
                    db,
                    project_id=project.id,
                    event_type="github.commit",
                    external_id=f"{repository}:commit:{sha}",
                    title=f"Commit {sha[:7]}: {title}",
                    body=message,
                    occurred_at=parse_github_datetime(author.get("date")),
                    url=item.get("html_url"),
                    metadata={
                        "repository": repository,
                        "sha": sha,
                        "author": author.get("name"),
                    },
                )
                created += int(was_created)
                skipped += int(not was_created)

            for item in pulls:
                number = item.get("number")
                was_created = add_event_if_new(
                    db,
                    project_id=project.id,
                    event_type="github.pull_request",
                    external_id=f"{repository}:pr:{number}",
                    title=f"PR #{number}: {item.get('title') or 'sem título'}",
                    body=item.get("body"),
                    occurred_at=parse_github_datetime(item.get("updated_at") or item.get("created_at")),
                    url=item.get("html_url"),
                    metadata={
                        "repository": repository,
                        "number": number,
                        "state": item.get("state"),
                        "draft": bool(item.get("draft")),
                        "head": (item.get("head") or {}).get("ref"),
                        "base": (item.get("base") or {}).get("ref"),
                    },
                )
                created += int(was_created)
                skipped += int(not was_created)

            for item in issues:
                number = item.get("number")
                was_created = add_event_if_new(
                    db,
                    project_id=project.id,
                    event_type="github.issue",
                    external_id=f"{repository}:issue:{number}",
                    title=f"Issue #{number}: {item.get('title') or 'sem título'}",
                    body=item.get("body"),
                    occurred_at=parse_github_datetime(item.get("updated_at") or item.get("created_at")),
                    url=item.get("html_url"),
                    metadata={
                        "repository": repository,
                        "number": number,
                        "state": item.get("state"),
                    },
                )
                created += int(was_created)
                skipped += int(not was_created)

            for item in runs:
                run_id = item.get("id")
                conclusion = item.get("conclusion") or item.get("status") or "unknown"
                was_created = add_event_if_new(
                    db,
                    project_id=project.id,
                    event_type="github.workflow_run",
                    external_id=f"{repository}:run:{run_id}",
                    title=f"Action {item.get('name') or 'workflow'}: {conclusion}",
                    body=item.get("display_title"),
                    occurred_at=parse_github_datetime(item.get("updated_at") or item.get("created_at")),
                    url=item.get("html_url"),
                    metadata={
                        "repository": repository,
                        "run_id": run_id,
                        "status": item.get("status"),
                        "conclusion": item.get("conclusion"),
                        "head_branch": item.get("head_branch"),
                        "head_sha": item.get("head_sha"),
                    },
                )
                created += int(was_created)
                skipped += int(not was_created)

            source.metadata_json = {
                **(source.metadata_json or {}),
                "default_branch": repo_data.get("default_branch"),
                "private": bool(repo_data.get("private")),
                "last_synced_at": now.isoformat(),
                "last_sync": {
                    "commits": len(commits),
                    "pulls": len(pulls),
                    "issues": len(issues),
                    "workflow_runs": len(runs),
                    "created_events": created,
                    "skipped_events": skipped,
                },
            }
            source.updated_at = now
            total_created += created
            total_skipped += skipped
            source_results.append(
                {
                    "repository": repository,
                    "default_branch": repo_data.get("default_branch"),
                    "created_events": created,
                    "skipped_events": skipped,
                }
            )

        if sources:
            project.last_activity_at = now
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        if owns_reader and isinstance(connector, GitHubConnector):
            connector.close()

    return {
        "project_id": project.id,
        "source_count": len(sources),
        "created_events": total_created,
        "skipped_events": total_skipped,
        "sources": source_results,
        "synced_at": now,
    }
