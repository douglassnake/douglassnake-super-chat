from __future__ import annotations

import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
from typing import Any, Callable, Protocol
from urllib.parse import quote

import httpx

from app.agent_handoff import sanitize_value
from app.credential_broker import (
    CredentialBroker,
    CredentialUnavailable,
    SettingsCredentialBroker,
)
from app.core.config import Settings
from app.executor_control import ExecutorCommand, ExecutorOutcome, ExecutorUnavailable


_EXPECTED_KEYS = frozenset(
    {
        "publish_request_id",
        "project_source_id",
        "repository",
        "head_branch",
        "head_sha",
        "local_remote_id",
    }
)


class GitHubPublishError(RuntimeError):
    pass


class GitHubBranchPublisher(Protocol):
    def get_branch_head(self, repository: str, branch: str) -> str | None: ...

    def stage_exact_commit(
        self,
        source_bare: Path,
        repository: str,
        *,
        commit_sha: str,
        staging_branch: str,
    ) -> None: ...

    def create_branch_ref(self, repository: str, *, branch: str, commit_sha: str) -> None: ...

    def delete_branch_ref(self, repository: str, *, branch: str) -> None: ...


class HttpGitHubBranchPublisher:
    def __init__(self, *, token: str, api_url: str = "https://api.github.com", timeout: float = 30.0) -> None:
        value = str(token or "").strip()
        if not value:
            raise ValueError("GitHub publication token is required")
        self._token = value
        self.api_url = str(api_url or "https://api.github.com").rstrip("/")
        self.timeout = max(1.0, float(timeout))

    def _safe(self, value: object) -> str:
        return str(value or "").replace(self._token, "[REDACTED]")[:1200]

    @staticmethod
    def _repo_path(repository: str) -> str:
        owner, name = repository.split("/", 1)
        return f"/repos/{quote(owner, safe='')}/{quote(name, safe='')}"

    def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        allow_404: bool = False,
    ) -> Any:
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self._token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "super-chat-github-publisher",
        }
        try:
            response = httpx.request(
                method,
                f"{self.api_url}{path}",
                headers=headers,
                json=json_body,
                timeout=self.timeout,
                follow_redirects=False,
            )
        except httpx.HTTPError as exc:
            raise GitHubPublishError("GitHub publication API is unavailable") from exc
        if allow_404 and response.status_code == 404:
            return None
        if response.status_code >= 400:
            message = ""
            try:
                payload = response.json()
                if isinstance(payload, dict):
                    message = str(payload.get("message") or "")
            except ValueError:
                message = ""
            raise GitHubPublishError(
                f"GitHub publication API error {response.status_code}: "
                f"{self._safe(message or 'request rejected')}"
            )
        if response.status_code == 204:
            return None
        try:
            return response.json()
        except ValueError as exc:
            raise GitHubPublishError("GitHub publication API returned invalid JSON") from exc

    def get_branch_head(self, repository: str, branch: str) -> str | None:
        payload = self._request(
            "GET",
            f"{self._repo_path(repository)}/branches/{quote(branch, safe='')}",
            allow_404=True,
        )
        if payload is None:
            return None
        if not isinstance(payload, dict):
            raise GitHubPublishError("GitHub branch response is invalid")
        commit = payload.get("commit") or {}
        return str(commit.get("sha") or "").strip().lower() or None

    def stage_exact_commit(
        self,
        source_bare: Path,
        repository: str,
        *,
        commit_sha: str,
        staging_branch: str,
    ) -> None:
        git = shutil.which("git")
        if git is None:
            raise GitHubPublishError("Git executable is unavailable")
        remote_url = f"https://github.com/{repository}.git"
        ref = f"refs/heads/{staging_branch}"
        with tempfile.TemporaryDirectory(prefix="superchat-github-auth-") as temp_dir:
            temp = Path(temp_dir)
            askpass = temp / "askpass.sh"
            askpass.write_text(
                "#!/bin/sh\n"
                "case \"$1\" in\n"
                "  *Username*) printf '%s\\n' 'x-access-token' ;;\n"
                "  *) printf '%s\\n' \"$SUPERCHAT_GITHUB_TOKEN\" ;;\n"
                "esac\n",
                encoding="utf-8",
            )
            askpass.chmod(askpass.stat().st_mode | stat.S_IXUSR)
            env = {
                "PATH": os.environ.get("PATH", ""),
                "HOME": str(temp),
                "GIT_TERMINAL_PROMPT": "0",
                "GIT_ASKPASS": str(askpass),
                "GIT_CONFIG_NOSYSTEM": "1",
                "SUPERCHAT_GITHUB_TOKEN": self._token,
            }
            completed = subprocess.run(
                [
                    git,
                    "-c",
                    "credential.helper=",
                    "-c",
                    "core.hooksPath=/dev/null",
                    "-C",
                    str(source_bare),
                    "push",
                    "--porcelain",
                    "--no-verify",
                    f"--force-with-lease={ref}:",
                    remote_url,
                    f"{commit_sha}:{ref}",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
                timeout=self.timeout,
                check=False,
            )
            if completed.returncode != 0:
                detail = self._safe(completed.stderr or completed.stdout)
                raise GitHubPublishError(
                    f"Unable to stage exact commit in unique GitHub ref: {detail or 'git push failed'}"
                )

    def create_branch_ref(self, repository: str, *, branch: str, commit_sha: str) -> None:
        self._request(
            "POST",
            f"{self._repo_path(repository)}/git/refs",
            json_body={"ref": f"refs/heads/{branch}", "sha": commit_sha},
        )

    def delete_branch_ref(self, repository: str, *, branch: str) -> None:
        self._request(
            "DELETE",
            f"{self._repo_path(repository)}/git/refs/heads/{quote(branch, safe='')}",
            allow_404=True,
        )


class GitHubBranchPublishExecutorAdapter:
    name = "github-publish"

    def __init__(
        self,
        *,
        enabled: bool,
        repository: str | None,
        source_bare: str | None,
        broker: CredentialBroker,
        publisher_factory: Callable[[str], GitHubBranchPublisher],
    ) -> None:
        self.enabled = bool(enabled)
        self.repository = str(repository or "").strip().strip("/")
        self.source_bare_raw = str(source_bare or "").strip()
        self.broker = broker
        self.publisher_factory = publisher_factory
        self.source_bare: Path | None = None
        if self.source_bare_raw:
            self.source_bare = Path(self.source_bare_raw).expanduser().resolve(strict=False)
        self.available = bool(
            self.enabled
            and self.repository
            and self.source_bare is not None
            and self.source_bare.exists()
            and self.source_bare.is_dir()
        )

    @classmethod
    def from_settings(cls, settings: Settings) -> "GitHubBranchPublishExecutorAdapter":
        broker = SettingsCredentialBroker(settings)
        return cls(
            enabled=settings.executor_github_publish_enabled,
            repository=settings.executor_github_publish_repository,
            source_bare=settings.executor_git_publish_remote,
            broker=broker,
            publisher_factory=lambda token: HttpGitHubBranchPublisher(
                token=token,
                api_url=settings.github_api_url,
            ),
        )

    @staticmethod
    def _local_head(source_bare: Path, branch: str) -> str:
        git = shutil.which("git")
        if git is None:
            raise ExecutorUnavailable("Git executable is unavailable")
        check = subprocess.run(
            [git, "-C", str(source_bare), "rev-parse", "--is-bare-repository"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if check.returncode != 0 or check.stdout.strip().lower() != "true":
            raise ExecutorUnavailable("Configured M8.12 source is not a bare Git repository")
        resolved = subprocess.run(
            [git, "-C", str(source_bare), "rev-parse", "--verify", f"refs/heads/{branch}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if resolved.returncode != 0:
            raise ExecutorUnavailable("Controlled M8.12 branch is missing from the local bare source")
        return resolved.stdout.strip().lower()

    def execute(self, command: ExecutorCommand) -> ExecutorOutcome:
        if not self.available or self.source_bare is None:
            raise ExecutorUnavailable("GitHub branch publisher is disabled or its local bare source is unavailable")
        if command.action != "publish_github_branch":
            return ExecutorOutcome(
                False,
                {"status": "unsupported", "action": command.action},
                "github-publish adapter supports only publish_github_branch",
            )
        payload = dict(command.payload or {})
        unknown = sorted(set(payload) - _EXPECTED_KEYS)
        if unknown:
            raise ExecutorUnavailable(
                f"Resolved publish_github_branch payload contains unsupported fields: {', '.join(unknown)}"
            )
        repository = str(payload.get("repository") or "").strip().strip("/")
        branch = str(payload.get("head_branch") or "").strip()
        head_sha = str(payload.get("head_sha") or "").strip().lower()
        if repository.lower() != self.repository.lower():
            return ExecutorOutcome(False, {"status": "rejected", "external_effects": False}, "Resolved repository differs from server configuration")

        local_sha = self._local_head(self.source_bare, branch)
        if local_sha != head_sha:
            return ExecutorOutcome(
                False,
                {
                    "status": "local_source_drift_detected",
                    "repository": repository,
                    "head_branch": branch,
                    "expected_head_sha": head_sha,
                    "observed_local_sha": local_sha,
                    "external_effects": False,
                },
                "M8.12 local bare branch drifted from the reviewed commit",
            )

        try:
            lease = self.broker.acquire_github_publish_token(repository)
            publisher = self.publisher_factory(lease.reveal())
        except (CredentialUnavailable, ValueError) as exc:
            raise ExecutorUnavailable(str(exc)) from exc

        staging_branch = f"superchat-staging/{command.request_id}"
        try:
            existing = publisher.get_branch_head(repository, branch)
            if existing is not None:
                return ExecutorOutcome(
                    False,
                    {
                        "status": "github_branch_already_exists",
                        "repository": repository,
                        "head_branch": branch,
                        "observed_head_sha": existing,
                        "external_effects": False,
                    },
                    "GitHub target branch already exists; first publication will not update it",
                )
            if publisher.get_branch_head(repository, staging_branch) is not None:
                return ExecutorOutcome(
                    False,
                    {"status": "staging_ref_collision", "repository": repository, "external_effects": False},
                    "Unique GitHub staging ref already exists",
                )
        except GitHubPublishError as exc:
            return ExecutorOutcome(
                False,
                {"status": "github_precheck_failed", "repository": repository, "external_effects": False},
                str(exc),
            )

        staged = False
        final_created = False
        cleanup_ok = True
        failure: ExecutorOutcome | None = None
        try:
            publisher.stage_exact_commit(
                self.source_bare,
                repository,
                commit_sha=head_sha,
                staging_branch=staging_branch,
            )
            staged = True
            staged_sha = publisher.get_branch_head(repository, staging_branch)
            if staged_sha != head_sha:
                raise GitHubPublishError("Temporary GitHub ref did not resolve to the expected commit")

            publisher.create_branch_ref(repository, branch=branch, commit_sha=head_sha)
            final_created = True
            observed_final = publisher.get_branch_head(repository, branch)
            if observed_final != head_sha:
                failure = ExecutorOutcome(
                    False,
                    {
                        "status": "post_verify_failed",
                        "repository": repository,
                        "head_branch": branch,
                        "expected_head_sha": head_sha,
                        "observed_head_sha": observed_final,
                        "external_effects": True,
                        "manual_reconciliation_required": True,
                    },
                    "GitHub branch was created but post-verification did not match the reviewed SHA",
                )
        except GitHubPublishError as exc:
            failure = ExecutorOutcome(
                False,
                sanitize_value(
                    {
                        "status": "github_publication_failed",
                        "repository": repository,
                        "head_branch": branch,
                        "external_effects": staged or final_created,
                        "final_branch_created": final_created,
                        "manual_reconciliation_required": final_created,
                    }
                ),
                str(exc),
            )
        finally:
            if staged:
                try:
                    publisher.delete_branch_ref(repository, branch=staging_branch)
                except GitHubPublishError:
                    cleanup_ok = False

        if not cleanup_ok:
            return ExecutorOutcome(
                False,
                {
                    "status": "temporary_ref_cleanup_failed",
                    "repository": repository,
                    "head_branch": branch,
                    "head_sha": head_sha,
                    "external_effects": True,
                    "final_branch_created": final_created,
                    "prior_status": (failure.result or {}).get("status") if failure else None,
                    "manual_reconciliation_required": True,
                },
                "GitHub temporary ref cleanup failed; manual reconciliation is required",
            )
        if failure is not None:
            return failure

        return ExecutorOutcome(
            True,
            sanitize_value(
                {
                    "status": "github_branch_published",
                    "action": "publish_github_branch",
                    "repository": repository,
                    "head_branch": branch,
                    "head_sha": head_sha,
                    "local_remote_id": payload.get("local_remote_id"),
                    "temporary_ref_cleaned": True,
                    "github_publication_performed": True,
                    "pull_request_created": False,
                    "merge_performed": False,
                    "deploy_performed": False,
                    "external_effects": True,
                    "credential_policy": "broker_memory_only_not_serialized",
                    "publication_policy": "unique_staging_ref_then_atomic_final_ref",
                }
            ),
            None,
        )
