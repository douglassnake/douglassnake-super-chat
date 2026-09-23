from __future__ import annotations

from pathlib import Path
from typing import Any

from app.core.config import Settings
from app.executor_control import ExecutorCommand, ExecutorOutcome, ExecutorUnavailable
from app.worker_client import ProcessWorkerClient, WorkerClientError
from app.worker_runtime import WorkerJob, WorkerLimits


ISOLATED_EXECUTABLE_ACTIONS = frozenset(
    {
        "read_repository",
        "run_tests",
        "modify_worktree",
        "create_branch",
        "apply_git_change",
    }
)
RUN_TESTS_KEYS = frozenset({"worktree", "preset", "test_target", "timeout_seconds"})
READ_REPOSITORY_KEYS = frozenset({"worktree", "scope"})
MODIFY_WORKTREE_KEYS = frozenset({"worktree", "operations"})
CREATE_BRANCH_KEYS = frozenset({"worktree", "branch_name"})
APPLY_GIT_CHANGE_KEYS = frozenset(
    {
        "approval_id",
        "source_request_id",
        "branch_request_id",
        "patch_digest",
        "changed_files",
        "worktree",
        "operations",
        "branch_name",
        "base_sha",
    }
)


class IsolatedLocalExecutorAdapter:
    name = "isolated-local"

    def __init__(
        self,
        *,
        enabled: bool,
        worktree_root: str | None,
        timeout_seconds: float = 60.0,
        max_timeout_seconds: float = 300.0,
        output_max_bytes: int = 65_536,
        env_allowlist: str = "",
        worker_backend: str = "subprocess-sandbox",
        worker_cpu_seconds: int = 120,
        worker_memory_mb: int = 1024,
        worker_pids: int = 128,
        worker_nofile: int = 256,
        worker_file_size_mb: int = 64,
        container_runtime: str = "docker",
        container_image: str = "python:3.13-slim",
        modify_max_files: int = 20,
        modify_max_operations: int = 40,
        modify_max_total_write_bytes: int = 65_536,
        modify_max_patch_bytes: int = 65_536,
        git_staging_root: str | None = None,
        worker_client: ProcessWorkerClient | None = None,
    ) -> None:
        self.enabled = bool(enabled)
        self.worktree_root_raw = worktree_root
        self.timeout_seconds = max(0.1, float(timeout_seconds))
        self.max_timeout_seconds = max(self.timeout_seconds, float(max_timeout_seconds))
        self.output_max_bytes = max(1_024, int(output_max_bytes))
        self.env_allowlist = tuple(
            item.strip() for item in str(env_allowlist or "").split(",") if item.strip()
        )
        self.worker_backend = str(worker_backend or "subprocess-sandbox")
        self.worker_cpu_seconds = max(1, int(worker_cpu_seconds))
        self.worker_memory_mb = max(64, int(worker_memory_mb))
        self.worker_pids = max(8, int(worker_pids))
        self.worker_nofile = max(32, int(worker_nofile))
        self.worker_file_size_mb = max(1, int(worker_file_size_mb))
        self.container_runtime = str(container_runtime or "docker")
        self.container_image = str(container_image or "python:3.13-slim")
        self.modify_max_files = max(1, int(modify_max_files))
        self.modify_max_operations = max(1, int(modify_max_operations))
        self.modify_max_total_write_bytes = max(1, int(modify_max_total_write_bytes))
        self.modify_max_patch_bytes = max(1, int(modify_max_patch_bytes))
        self.worker_client = worker_client or ProcessWorkerClient()
        self.root: Path | None = None
        self.git_staging_root: Path | None = None
        if worktree_root:
            self.root = Path(worktree_root).expanduser().resolve(strict=False)
        if git_staging_root:
            self.git_staging_root = Path(git_staging_root).expanduser().resolve(strict=False)
        self.available = bool(
            self.enabled
            and self.root is not None
            and self.root.exists()
            and self.root.is_dir()
        )

    @classmethod
    def from_settings(cls, settings: Settings) -> "IsolatedLocalExecutorAdapter":
        return cls(
            enabled=settings.executor_isolated_enabled,
            worktree_root=settings.executor_worktree_root,
            timeout_seconds=settings.executor_timeout_seconds,
            max_timeout_seconds=settings.executor_max_timeout_seconds,
            output_max_bytes=settings.executor_output_max_bytes,
            env_allowlist=settings.executor_env_allowlist,
            worker_backend=settings.executor_worker_backend,
            worker_cpu_seconds=settings.executor_worker_cpu_seconds,
            worker_memory_mb=settings.executor_worker_memory_mb,
            worker_pids=settings.executor_worker_pids,
            worker_nofile=settings.executor_worker_nofile,
            worker_file_size_mb=settings.executor_worker_file_size_mb,
            container_runtime=settings.executor_container_runtime,
            container_image=settings.executor_container_image,
            modify_max_files=settings.executor_modify_max_files,
            modify_max_operations=settings.executor_modify_max_operations,
            modify_max_total_write_bytes=settings.executor_modify_max_total_write_bytes,
            modify_max_patch_bytes=settings.executor_modify_max_patch_bytes,
            git_staging_root=settings.executor_git_staging_root,
        )

    def execute(self, command: ExecutorCommand) -> ExecutorOutcome:
        self._ensure_available()
        if command.action not in ISOLATED_EXECUTABLE_ACTIONS:
            return ExecutorOutcome(
                ok=False,
                result={"status": "unsupported", "action": command.action},
                error=f"Action {command.action!r} has no isolated-local execution contract",
            )
        if command.action == "read_repository":
            return self._read_repository(command)
        if command.action == "modify_worktree":
            return self._modify_worktree(command)
        if command.action == "create_branch":
            return self._create_branch(command)
        if command.action == "apply_git_change":
            return self._apply_git_change(command)
        return self._run_tests(command)

    def _ensure_available(self) -> None:
        if not self.enabled:
            raise ExecutorUnavailable("The isolated-local adapter is disabled")
        if self.root is None:
            raise ExecutorUnavailable("EXECUTOR_WORKTREE_ROOT is not configured")
        if not self.root.exists() or not self.root.is_dir():
            raise ExecutorUnavailable(
                "Configured executor worktree root does not exist or is not a directory"
            )

    @staticmethod
    def _validate_keys(
        payload: dict[str, Any],
        allowed: frozenset[str],
        action: str,
    ) -> None:
        unknown = sorted(set(payload) - set(allowed))
        if unknown:
            raise ExecutorUnavailable(
                f"Unsupported payload fields for {action}: {', '.join(unknown)}"
            )

    def _resolve_relative(
        self,
        base: Path,
        raw_value: str,
        *,
        must_be_dir: bool | None = None,
    ) -> Path:
        candidate = Path(str(raw_value or "").strip())
        if not str(candidate) or candidate.is_absolute():
            raise ExecutorUnavailable("Executor paths must be non-empty relative paths")
        try:
            resolved = (base / candidate).resolve(strict=True)
        except (FileNotFoundError, OSError) as exc:
            raise ExecutorUnavailable(f"Executor path does not exist: {candidate}") from exc
        base_resolved = base.resolve(strict=True)
        if resolved != base_resolved and base_resolved not in resolved.parents:
            raise ExecutorUnavailable(
                "Executor path escapes the configured worktree boundary"
            )
        if must_be_dir is True and not resolved.is_dir():
            raise ExecutorUnavailable("Executor worktree must be a directory")
        if must_be_dir is False and not resolved.is_file():
            raise ExecutorUnavailable("Executor target must be a file")
        return resolved

    def _worktree(self, payload: dict[str, Any]) -> tuple[Path, str]:
        assert self.root is not None
        raw = str(payload.get("worktree") or "").strip()
        if not raw:
            raise ExecutorUnavailable("worktree is required")
        worktree = self._resolve_relative(self.root, raw, must_be_dir=True)
        relative = worktree.relative_to(self.root.resolve(strict=True)).as_posix()
        return worktree, relative or "."

    def _requested_timeout(self, payload: dict[str, Any]) -> float:
        raw = payload.get("timeout_seconds", self.timeout_seconds)
        try:
            value = float(raw)
        except (TypeError, ValueError) as exc:
            raise ExecutorUnavailable("timeout_seconds must be numeric") from exc
        if value <= 0:
            raise ExecutorUnavailable("timeout_seconds must be greater than zero")
        return min(value, self.max_timeout_seconds)

    def _limits(self, timeout: float) -> WorkerLimits:
        return WorkerLimits(
            timeout_seconds=timeout,
            output_max_bytes=self.output_max_bytes,
            cpu_seconds=self.worker_cpu_seconds,
            memory_mb=self.worker_memory_mb,
            pids=self.worker_pids,
            nofile=self.worker_nofile,
            file_size_mb=self.worker_file_size_mb,
        )

    def _dispatch(
        self,
        command: ExecutorCommand,
        *,
        relative_worktree: str,
        payload: dict[str, Any],
        timeout: float,
        backend: str | None = None,
    ) -> ExecutorOutcome:
        assert self.root is not None
        job = WorkerJob(
            request_id=str(command.request_id),
            action=command.action,
            worktree_root=str(self.root.resolve(strict=True)),
            worktree=relative_worktree,
            payload=payload,
            limits=self._limits(timeout),
            backend=backend or self.worker_backend,
            env_allowlist=self.env_allowlist,
            container_runtime=self.container_runtime,
            container_image=self.container_image,
        )
        try:
            outcome = self.worker_client.execute(job)
        except WorkerClientError as exc:
            raise ExecutorUnavailable(str(exc)) from exc
        return ExecutorOutcome(ok=outcome.ok, result=outcome.result, error=outcome.error)

    def _read_repository(self, command: ExecutorCommand) -> ExecutorOutcome:
        payload = command.payload
        self._validate_keys(payload, READ_REPOSITORY_KEYS, "read_repository")
        worktree, relative = self._worktree(payload)
        scope = str(payload.get("scope") or "metadata")
        if scope != "metadata":
            return ExecutorOutcome(
                ok=False,
                result={"status": "unsupported", "scope": scope},
                error="isolated-local read_repository supports only scope='metadata'",
            )
        outcome = self._dispatch(
            command,
            relative_worktree=relative,
            payload={"scope": "metadata"},
            timeout=min(self.timeout_seconds, self.max_timeout_seconds),
        )
        if outcome.ok:
            result = dict(outcome.result)
            result["git_metadata_present"] = (worktree / ".git").exists()
            result["python_project"] = any(
                (worktree / name).exists()
                for name in ("pyproject.toml", "requirements.txt", "setup.py")
            )
            return ExecutorOutcome(True, result, None)
        return outcome

    def _modify_worktree(self, command: ExecutorCommand) -> ExecutorOutcome:
        payload = command.payload
        self._validate_keys(payload, MODIFY_WORKTREE_KEYS, "modify_worktree")
        _worktree, relative = self._worktree(payload)
        operations = payload.get("operations")
        if not isinstance(operations, list) or not operations:
            raise ExecutorUnavailable("modify_worktree requires a non-empty operations list")
        worker_payload = {
            "operations": operations,
            "policy": {
                "max_files": self.modify_max_files,
                "max_operations": self.modify_max_operations,
                "max_total_write_bytes": self.modify_max_total_write_bytes,
                "max_patch_bytes": self.modify_max_patch_bytes,
            },
        }
        return self._dispatch(
            command,
            relative_worktree=relative,
            payload=worker_payload,
            timeout=min(self.timeout_seconds, self.max_timeout_seconds),
            backend="subprocess-sandbox",
        )

    def _create_branch(self, command: ExecutorCommand) -> ExecutorOutcome:
        payload = command.payload
        self._validate_keys(payload, CREATE_BRANCH_KEYS, "create_branch")
        _worktree, relative = self._worktree(payload)
        branch_name = str(payload.get("branch_name") or "").strip()
        if not branch_name:
            raise ExecutorUnavailable("create_branch requires branch_name")
        return self._dispatch(
            command,
            relative_worktree=relative,
            payload={"branch_name": branch_name},
            timeout=min(self.timeout_seconds, self.max_timeout_seconds),
            backend="subprocess-sandbox",
        )

    def _apply_git_change(self, command: ExecutorCommand) -> ExecutorOutcome:
        payload = command.payload
        self._validate_keys(payload, APPLY_GIT_CHANGE_KEYS, "apply_git_change")
        _worktree, relative = self._worktree(payload)
        if self.git_staging_root is None:
            raise ExecutorUnavailable("EXECUTOR_GIT_STAGING_ROOT is not configured")
        if not self.git_staging_root.exists() or not self.git_staging_root.is_dir():
            raise ExecutorUnavailable("Configured Git staging root does not exist or is not a directory")
        worker_payload = dict(payload)
        worker_payload["staging_root"] = str(self.git_staging_root.resolve(strict=True))
        worker_payload["policy"] = {
            "max_files": self.modify_max_files,
            "max_operations": self.modify_max_operations,
            "max_total_write_bytes": self.modify_max_total_write_bytes,
            "max_patch_bytes": self.modify_max_patch_bytes,
        }
        return self._dispatch(
            command,
            relative_worktree=relative,
            payload=worker_payload,
            timeout=min(self.timeout_seconds, self.max_timeout_seconds),
            backend="subprocess-sandbox",
        )

    def _run_tests(self, command: ExecutorCommand) -> ExecutorOutcome:
        payload = command.payload
        self._validate_keys(payload, RUN_TESTS_KEYS, "run_tests")
        worktree, relative = self._worktree(payload)
        preset = str(payload.get("preset") or "pytest")
        if preset != "pytest":
            return ExecutorOutcome(
                ok=False,
                result={"status": "unsupported", "preset": preset},
                error="isolated-local run_tests supports only the server-side 'pytest' preset",
            )
        raw_target = str(payload.get("test_target") or "tests").strip()
        target = self._resolve_relative(worktree, raw_target)
        target_rel = target.relative_to(worktree).as_posix()
        timeout = self._requested_timeout(payload)
        return self._dispatch(
            command,
            relative_worktree=relative,
            payload={"preset": "pytest", "test_target": target_rel},
            timeout=timeout,
        )
