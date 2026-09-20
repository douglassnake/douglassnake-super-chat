from __future__ import annotations

import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from app.agent_handoff import sanitize_value
from app.agent_task_pack import redact_secrets
from app.core.config import Settings
from app.executor_control import ExecutorCommand, ExecutorOutcome, ExecutorUnavailable


ISOLATED_EXECUTABLE_ACTIONS = frozenset({"read_repository", "run_tests"})
RUN_TESTS_KEYS = frozenset({"worktree", "preset", "test_target", "timeout_seconds"})
READ_REPOSITORY_KEYS = frozenset({"worktree", "scope"})
SENSITIVE_ENV_MARKERS = ("TOKEN", "SECRET", "PASSWORD", "PASSWD", "API_KEY", "APIKEY", "AUTHORIZATION")


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
    ) -> None:
        self.enabled = bool(enabled)
        self.worktree_root_raw = worktree_root
        self.timeout_seconds = max(0.1, float(timeout_seconds))
        self.max_timeout_seconds = max(self.timeout_seconds, float(max_timeout_seconds))
        self.output_max_bytes = max(1_024, int(output_max_bytes))
        self.env_allowlist = tuple(
            item.strip() for item in str(env_allowlist or "").split(",") if item.strip()
        )
        self.root: Path | None = None
        if worktree_root:
            self.root = Path(worktree_root).expanduser().resolve(strict=False)
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
        )

    def execute(self, command: ExecutorCommand) -> ExecutorOutcome:
        self._ensure_available()
        if command.action == "read_repository":
            return self._read_repository(command.payload)
        if command.action == "run_tests":
            return self._run_tests(command.payload)
        return ExecutorOutcome(
            ok=False,
            result={"status": "unsupported", "action": command.action},
            error=f"Action {command.action!r} has no isolated-local execution contract",
        )

    def _ensure_available(self) -> None:
        if not self.enabled:
            raise ExecutorUnavailable("The isolated-local adapter is disabled")
        if self.root is None:
            raise ExecutorUnavailable("EXECUTOR_WORKTREE_ROOT is not configured")
        if not self.root.exists() or not self.root.is_dir():
            raise ExecutorUnavailable("Configured executor worktree root does not exist or is not a directory")

    @staticmethod
    def _validate_keys(payload: dict[str, Any], allowed: frozenset[str], action: str) -> None:
        unknown = sorted(set(payload) - set(allowed))
        if unknown:
            raise ExecutorUnavailable(
                f"Unsupported payload fields for {action}: {', '.join(unknown)}"
            )

    def _resolve_relative(self, base: Path, raw_value: str, *, must_be_dir: bool | None = None) -> Path:
        candidate = Path(str(raw_value or "").strip())
        if not str(candidate) or candidate.is_absolute():
            raise ExecutorUnavailable("Executor paths must be non-empty relative paths")
        try:
            resolved = (base / candidate).resolve(strict=True)
        except (FileNotFoundError, OSError) as exc:
            raise ExecutorUnavailable(f"Executor path does not exist: {candidate}") from exc
        base_resolved = base.resolve(strict=True)
        if resolved != base_resolved and base_resolved not in resolved.parents:
            raise ExecutorUnavailable("Executor path escapes the configured worktree boundary")
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

    def _minimal_env(self) -> dict[str, str]:
        env = {
            "PYTHONUNBUFFERED": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
        }
        for key in self.env_allowlist:
            upper = key.upper()
            if any(marker in upper for marker in SENSITIVE_ENV_MARKERS):
                continue
            value = os.environ.get(key)
            if value is not None:
                env[key] = value
        return env

    def _read_limited(self, handle) -> tuple[str, bool]:
        handle.seek(0)
        data = handle.read(self.output_max_bytes + 1)
        truncated = len(data) > self.output_max_bytes
        data = data[: self.output_max_bytes]
        text = data.decode("utf-8", errors="replace")
        return redact_secrets(text) or "", truncated

    @staticmethod
    def _terminate_process(process: subprocess.Popen[bytes]) -> None:
        if process.poll() is not None:
            return
        try:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
        except (ProcessLookupError, PermissionError, OSError):
            try:
                process.kill()
            except (ProcessLookupError, OSError):
                pass

    def _read_repository(self, payload: dict[str, Any]) -> ExecutorOutcome:
        self._validate_keys(payload, READ_REPOSITORY_KEYS, "read_repository")
        worktree, relative = self._worktree(payload)
        scope = str(payload.get("scope") or "metadata")
        if scope != "metadata":
            return ExecutorOutcome(
                ok=False,
                result={"status": "unsupported", "scope": scope},
                error="isolated-local read_repository supports only scope='metadata'",
            )
        entries = sorted(item.name for item in worktree.iterdir())[:100]
        result = {
            "status": "completed",
            "action": "read_repository",
            "worktree": relative,
            "scope": "metadata",
            "top_level_entries": entries,
            "top_level_entry_count": sum(1 for _ in worktree.iterdir()),
            "git_metadata_present": (worktree / ".git").exists(),
            "python_project": any((worktree / name).exists() for name in ("pyproject.toml", "requirements.txt", "setup.py")),
        }
        return ExecutorOutcome(ok=True, result=sanitize_value(result))

    def _run_tests(self, payload: dict[str, Any]) -> ExecutorOutcome:
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
        argv = [sys.executable, "-m", "pytest", "-q", target_rel]
        started = time.monotonic()
        timed_out = False

        with tempfile.TemporaryFile() as stdout_file, tempfile.TemporaryFile() as stderr_file:
            process = subprocess.Popen(
                argv,
                cwd=worktree,
                env=self._minimal_env(),
                stdin=subprocess.DEVNULL,
                stdout=stdout_file,
                stderr=stderr_file,
                shell=False,
                start_new_session=(os.name == "posix"),
            )
            try:
                return_code = process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                self._terminate_process(process)
                try:
                    return_code = process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    return_code = -9
            stdout, stdout_truncated = self._read_limited(stdout_file)
            stderr, stderr_truncated = self._read_limited(stderr_file)

        duration_ms = int((time.monotonic() - started) * 1000)
        result = sanitize_value(
            {
                "status": "timed_out" if timed_out else ("passed" if return_code == 0 else "failed"),
                "action": "run_tests",
                "preset": "pytest",
                "worktree": relative,
                "target": target_rel,
                "timeout_seconds": timeout,
                "duration_ms": duration_ms,
                "exit_code": return_code,
                "timed_out": timed_out,
                "stdout": stdout,
                "stderr": stderr,
                "stdout_truncated": stdout_truncated,
                "stderr_truncated": stderr_truncated,
            }
        )
        if timed_out:
            return ExecutorOutcome(ok=False, result=result, error="Test execution exceeded the configured timeout")
        if return_code != 0:
            return ExecutorOutcome(ok=False, result=result, error=f"Test preset exited with code {return_code}")
        return ExecutorOutcome(ok=True, result=result)
