from __future__ import annotations

from typing import Any, Protocol
from urllib.parse import quote

import httpx

from app.agent_handoff import sanitize_value
from app.agent_task_pack import redact_secrets
from app.core.config import Settings
from app.executor_control import ExecutorCommand, ExecutorOutcome, ExecutorUnavailable


_EXPECTED_KEYS = frozenset(
    {
        "publish_request_id",
        "project_source_id",
        "repository",
        "base_branch",
        "head_branch",
        "head_sha",
        "title",
        "body",
        "draft",
    }
)


class GitHubPRWriteError(RuntimeError):
    pass


class GitHubPRWriter(Protocol):
    def get_branch_head(self, repository: str, branch: str) -> str | None: ...

    def find_open_pull_request(
        self,
        repository: str,
        *,
        base_branch: str,
        head_branch: str,
    ) -> dict[str, Any] | None: ...

    def create_pull_request(
        self,
        repository: str,
        *,
        title: str,
        body: str,
        base_branch: str,
        head_branch: str,
        draft: bool,
    ) -> dict[str, Any]: ...

    def get_pull_request(self, repository: str, number: int) -> dict[str, Any]: ...


class HttpGitHubPRWriter:
    def __init__(self, *, token: str, api_url: str = "https://api.github.com", timeout: float = 20.0) -> None:
        value = str(token or "").strip()
        if not value:
            raise ValueError("GitHub write token is required")
        self._token = value
        self.api_url = str(api_url or "https://api.github.com").rstrip("/")
        self.timeout = max(1.0, float(timeout))

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> Any:
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self._token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "super-chat-controlled-pr",
        }
        try:
            response = httpx.request(
                method,
                f"{self.api_url}{path}",
                headers=headers,
                params=params,
                json=json_body,
                timeout=self.timeout,
                follow_redirects=False,
            )
        except httpx.HTTPError as exc:
            raise GitHubPRWriteError("GitHub write API is unavailable") from exc

        if response.status_code == 404 and method == "GET" and "/branches/" in path:
            return None
        if response.status_code >= 400:
            message = ""
            try:
                body = response.json()
                if isinstance(body, dict):
                    message = str(body.get("message") or "")
            except ValueError:
                message = ""
            safe_message = redact_secrets(message) or "GitHub API rejected the request"
            raise GitHubPRWriteError(f"GitHub API error {response.status_code}: {safe_message[:500]}")
        try:
            return response.json()
        except ValueError as exc:
            raise GitHubPRWriteError("GitHub API returned invalid JSON") from exc

    @staticmethod
    def _repo_path(repository: str) -> str:
        owner, name = repository.split("/", 1)
        return f"/repos/{quote(owner, safe='')}/{quote(name, safe='')}"

    def get_branch_head(self, repository: str, branch: str) -> str | None:
        payload = self._request(
            "GET",
            f"{self._repo_path(repository)}/branches/{quote(branch, safe='')}",
        )
        if payload is None:
            return None
        if not isinstance(payload, dict):
            raise GitHubPRWriteError("GitHub branch response is invalid")
        commit = payload.get("commit") or {}
        sha = str(commit.get("sha") or "").strip().lower()
        return sha or None

    def find_open_pull_request(
        self,
        repository: str,
        *,
        base_branch: str,
        head_branch: str,
    ) -> dict[str, Any] | None:
        owner = repository.split("/", 1)[0]
        payload = self._request(
            "GET",
            f"{self._repo_path(repository)}/pulls",
            params={"state": "open", "base": base_branch, "head": f"{owner}:{head_branch}"},
        )
        if not isinstance(payload, list):
            raise GitHubPRWriteError("GitHub pull request list response is invalid")
        return dict(payload[0]) if payload else None

    def create_pull_request(
        self,
        repository: str,
        *,
        title: str,
        body: str,
        base_branch: str,
        head_branch: str,
        draft: bool,
    ) -> dict[str, Any]:
        payload = self._request(
            "POST",
            f"{self._repo_path(repository)}/pulls",
            json_body={
                "title": title,
                "body": body,
                "base": base_branch,
                "head": head_branch,
                "draft": bool(draft),
            },
        )
        if not isinstance(payload, dict):
            raise GitHubPRWriteError("GitHub create pull request response is invalid")
        return dict(payload)

    def get_pull_request(self, repository: str, number: int) -> dict[str, Any]:
        payload = self._request(
            "GET",
            f"{self._repo_path(repository)}/pulls/{int(number)}",
        )
        if not isinstance(payload, dict):
            raise GitHubPRWriteError("GitHub pull request verification response is invalid")
        return dict(payload)


class GitHubPullRequestExecutorAdapter:
    name = "github-pr"

    def __init__(
        self,
        *,
        enabled: bool,
        repository: str | None,
        base_branch: str,
        draft: bool,
        writer: GitHubPRWriter | None,
    ) -> None:
        self.enabled = bool(enabled)
        self.repository = str(repository or "").strip().strip("/")
        self.base_branch = str(base_branch or "main").strip()
        self.draft = bool(draft)
        self.writer = writer
        self.available = bool(self.enabled and self.repository and self.base_branch and self.writer is not None)

    @classmethod
    def from_settings(cls, settings: Settings) -> "GitHubPullRequestExecutorAdapter":
        writer: GitHubPRWriter | None = None
        token = str(settings.executor_github_write_token or "").strip()
        if token:
            writer = HttpGitHubPRWriter(token=token, api_url=settings.github_api_url)
        return cls(
            enabled=settings.executor_github_write_enabled,
            repository=settings.executor_github_write_repository,
            base_branch=settings.executor_github_pr_base_branch,
            draft=settings.executor_github_pr_draft,
            writer=writer,
        )

    def execute(self, command: ExecutorCommand) -> ExecutorOutcome:
        if not self.available or self.writer is None:
            raise ExecutorUnavailable("GitHub PR writer is disabled or missing server-side credentials/configuration")
        if command.action != "create_pull_request":
            return ExecutorOutcome(
                False,
                {"status": "unsupported", "action": command.action},
                "github-pr adapter supports only create_pull_request",
            )

        payload = dict(command.payload or {})
        unknown = sorted(set(payload) - _EXPECTED_KEYS)
        if unknown:
            raise ExecutorUnavailable(
                f"Resolved create_pull_request payload contains unsupported fields: {', '.join(unknown)}"
            )

        repository = str(payload.get("repository") or "").strip().strip("/")
        base_branch = str(payload.get("base_branch") or "").strip()
        head_branch = str(payload.get("head_branch") or "").strip()
        head_sha = str(payload.get("head_sha") or "").strip().lower()
        title = str(payload.get("title") or "").strip()
        body = str(payload.get("body") or "")
        draft = bool(payload.get("draft"))

        if repository.lower() != self.repository.lower():
            return ExecutorOutcome(False, {"status": "rejected", "external_effects": False}, "Resolved repository differs from server configuration")
        if base_branch != self.base_branch or draft != self.draft:
            return ExecutorOutcome(False, {"status": "rejected", "external_effects": False}, "Resolved PR policy differs from server configuration")

        try:
            observed_head = self.writer.get_branch_head(repository, head_branch)
        except GitHubPRWriteError as exc:
            return ExecutorOutcome(False, {"status": "unavailable", "external_effects": False}, str(exc))
        if observed_head is None:
            return ExecutorOutcome(
                False,
                {
                    "status": "head_not_published_to_github",
                    "repository": repository,
                    "head_branch": head_branch,
                    "expected_head_sha": head_sha,
                    "external_effects": False,
                },
                "GitHub head branch does not exist; publish it through a separately authorized GitHub publication effect first",
            )
        if observed_head.lower() != head_sha:
            return ExecutorOutcome(
                False,
                {
                    "status": "head_drift_detected",
                    "repository": repository,
                    "head_branch": head_branch,
                    "expected_head_sha": head_sha,
                    "observed_head_sha": observed_head.lower(),
                    "external_effects": False,
                },
                "GitHub head branch SHA differs from the reviewed publication SHA",
            )

        try:
            existing = self.writer.find_open_pull_request(
                repository,
                base_branch=base_branch,
                head_branch=head_branch,
            )
        except GitHubPRWriteError as exc:
            return ExecutorOutcome(False, {"status": "unavailable", "external_effects": False}, str(exc))
        if existing is not None:
            number = int(existing.get("number") or 0)
            return ExecutorOutcome(
                False,
                {
                    "status": "pull_request_already_exists",
                    "repository": repository,
                    "pull_request_number": number or None,
                    "head_branch": head_branch,
                    "external_effects": False,
                },
                "An open pull request already exists for this controlled head branch",
            )

        try:
            created = self.writer.create_pull_request(
                repository,
                title=title,
                body=body,
                base_branch=base_branch,
                head_branch=head_branch,
                draft=draft,
            )
            number = int(created.get("number") or 0)
            if number <= 0:
                raise GitHubPRWriteError("GitHub did not return a valid pull request number")
            verified = self.writer.get_pull_request(repository, number)
        except GitHubPRWriteError as exc:
            return ExecutorOutcome(
                False,
                {
                    "status": "create_or_verify_failed",
                    "repository": repository,
                    "head_branch": head_branch,
                    "external_effects": bool(locals().get("number", 0)),
                    "manual_reconciliation_required": bool(locals().get("number", 0)),
                },
                str(exc),
            )

        verified_head = dict(verified.get("head") or {})
        verified_base = dict(verified.get("base") or {})
        verified_repo = dict(verified_base.get("repo") or {})
        observed_repo = str(verified_repo.get("full_name") or repository).strip()
        observed_head_branch = str(verified_head.get("ref") or "").strip()
        observed_head_sha = str(verified_head.get("sha") or "").strip().lower()
        observed_base_branch = str(verified_base.get("ref") or "").strip()
        if (
            observed_repo.lower() != repository.lower()
            or observed_head_branch != head_branch
            or observed_head_sha != head_sha
            or observed_base_branch != base_branch
        ):
            return ExecutorOutcome(
                False,
                sanitize_value(
                    {
                        "status": "post_verify_failed",
                        "repository": repository,
                        "pull_request_number": number,
                        "expected_head_sha": head_sha,
                        "observed_head_sha": observed_head_sha,
                        "external_effects": True,
                        "manual_reconciliation_required": True,
                    }
                ),
                "Pull request was created but post-verification did not match the controlled state",
            )

        safe_url = f"https://github.com/{repository}/pull/{number}"
        return ExecutorOutcome(
            True,
            sanitize_value(
                {
                    "status": "pull_request_created",
                    "action": "create_pull_request",
                    "repository": repository,
                    "pull_request_number": number,
                    "pull_request_url": safe_url,
                    "base_branch": base_branch,
                    "head_branch": head_branch,
                    "head_sha": head_sha,
                    "draft": bool(verified.get("draft", draft)),
                    "pull_request_created": True,
                    "merge_performed": False,
                    "deploy_performed": False,
                    "external_effects": True,
                    "credential_policy": "server_memory_only_not_serialized",
                }
            ),
            None,
        )
