from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from app.agent_handoff import sanitize_value
from app.agent_task_pack import redact_secrets


WORKER_SCHEMA_VERSION = 1
WORKER_REAL_ACTIONS = frozenset({"read_repository", "run_tests"})
SENSITIVE_ENV_MARKERS = ("TOKEN", "SECRET", "PASSWORD", "PASSWD", "API_KEY", "APIKEY", "AUTHORIZATION")
COPY_IGNORE_NAMES = {".git", ".venv", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}


class WorkerJobError(RuntimeError):
    pass


@dataclass(frozen=True)
class WorkerLimits:
    timeout_seconds: float = 60.0
    output_max_bytes: int = 65_536
    cpu_seconds: int = 120
    memory_mb: int = 1024
    pids: int = 128
    nofile: int = 256
    file_size_mb: int = 64


@dataclass(frozen=True)
class WorkerJob:
    request_id: str
    action: str
    worktree_root: str
    worktree: str
    payload: dict[str, Any]
    limits: WorkerLimits = field(default_factory=WorkerLimits)
    backend: str = "subprocess-sandbox"
    env_allowlist: tuple[str, ...] = ()
    container_runtime: str = "docker"
    container_image: str = "python:3.13-slim"
    schema_version: int = WORKER_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["env_allowlist"] = list(self.env_allowlist)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorkerJob":
        if int(data.get("schema_version", 0)) != WORKER_SCHEMA_VERSION:
            raise WorkerJobError("Unsupported worker job schema version")
        limits_raw = data.get("limits") or {}
        limits = WorkerLimits(
            timeout_seconds=float(limits_raw.get("timeout_seconds", 60.0)),
            output_max_bytes=int(limits_raw.get("output_max_bytes", 65_536)),
            cpu_seconds=int(limits_raw.get("cpu_seconds", 120)),
            memory_mb=int(limits_raw.get("memory_mb", 1024)),
            pids=int(limits_raw.get("pids", 128)),
            nofile=int(limits_raw.get("nofile", 256)),
            file_size_mb=int(limits_raw.get("file_size_mb", 64)),
        )
        return cls(
            request_id=str(data.get("request_id") or ""),
            action=str(data.get("action") or ""),
            worktree_root=str(data.get("worktree_root") or ""),
            worktree=str(data.get("worktree") or ""),
            payload=dict(data.get("payload") or {}),
            limits=limits,
            backend=str(data.get("backend") or "subprocess-sandbox"),
            env_allowlist=tuple(str(item) for item in (data.get("env_allowlist") or [])),
            container_runtime=str(data.get("container_runtime") or "docker"),
            container_image=str(data.get("container_image") or "python:3.13-slim"),
            schema_version=WORKER_SCHEMA_VERSION,
        )


@dataclass(frozen=True)
class WorkerResult:
    ok: bool
    result: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return sanitize_value({"ok": self.ok, "result": self.result, "error": self.error})

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorkerResult":
        return cls(bool(data.get("ok")), dict(data.get("result") or {}), data.get("error"))


def _resolve_worktree(job: WorkerJob) -> tuple[Path, Path, str]:
    root = Path(job.worktree_root).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise WorkerJobError("Worker root is not a directory")
    raw = Path(job.worktree.strip())
    if not str(raw) or raw.is_absolute():
        raise WorkerJobError("Worker worktree must be a non-empty relative path")
    worktree = (root / raw).resolve(strict=True)
    if worktree != root and root not in worktree.parents:
        raise WorkerJobError("Worker worktree escapes the configured root")
    if not worktree.is_dir():
        raise WorkerJobError("Worker worktree is not a directory")
    return root, worktree, worktree.relative_to(root).as_posix() or "."


def _validate_symlinks(worktree: Path) -> None:
    base = worktree.resolve(strict=True)
    for current, dirs, files in os.walk(base, followlinks=False):
        current_path = Path(current)
        for name in [*dirs, *files]:
            candidate = current_path / name
            if not candidate.is_symlink():
                continue
            resolved = candidate.resolve(strict=True)
            if resolved != base and base not in resolved.parents:
                raise WorkerJobError(f"Symlink escapes worktree boundary: {candidate.relative_to(base)}")


def _copy_worktree(worktree: Path, destination: Path) -> None:
    _validate_symlinks(worktree)

    def ignore(_directory: str, names: list[str]) -> set[str]:
        return {name for name in names if name in COPY_IGNORE_NAMES}

    shutil.copytree(worktree, destination, symlinks=False, ignore=ignore)


def _resolve_target(worktree: Path, raw_value: str) -> tuple[Path, str]:
    raw = Path(str(raw_value or "tests").strip())
    if not str(raw) or raw.is_absolute():
        raise WorkerJobError("Test target must be a non-empty relative path")
    target = (worktree / raw).resolve(strict=True)
    base = worktree.resolve(strict=True)
    if target != base and base not in target.parents:
        raise WorkerJobError("Test target escapes the sandbox worktree")
    return target, target.relative_to(base).as_posix() or "."


def _minimal_env(allowlist: tuple[str, ...]) -> dict[str, str]:
    env = {
        "PYTHONUNBUFFERED": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
    }
    for key in allowlist:
        upper = key.upper()
        if any(marker in upper for marker in SENSITIVE_ENV_MARKERS):
            continue
        value = os.environ.get(key)
        if value is not None:
            env[key] = value
    return env


def _read_limited(handle, max_bytes: int) -> tuple[str, bool]:
    handle.seek(0)
    data = handle.read(max_bytes + 1)
    truncated = len(data) > max_bytes
    data = data[:max_bytes]
    return redact_secrets(data.decode("utf-8", errors="replace")) or "", truncated


def _kill_process_tree(process: subprocess.Popen[bytes]) -> None:
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


def _posix_preexec(limits: WorkerLimits):
    if os.name != "posix":
        return None, {}, ["cpu", "memory", "pids", "nofile", "file_size"]
    try:
        import resource
    except ImportError:
        return None, {}, ["cpu", "memory", "pids", "nofile", "file_size"]

    requested = {
        "cpu": (resource.RLIMIT_CPU, max(1, limits.cpu_seconds)),
        "memory": (resource.RLIMIT_AS, max(64, limits.memory_mb) * 1024 * 1024),
        "nofile": (resource.RLIMIT_NOFILE, max(32, limits.nofile)),
        "file_size": (resource.RLIMIT_FSIZE, max(1, limits.file_size_mb) * 1024 * 1024),
    }
    if hasattr(resource, "RLIMIT_NPROC"):
        requested["pids"] = (resource.RLIMIT_NPROC, max(8, limits.pids))

    effective: dict[str, int] = {name: value for name, (_kind, value) in requested.items()}
    unsupported = [] if "pids" in requested else ["pids"]

    def apply_limits() -> None:
        for _name, (kind, requested_value) in requested.items():
            soft, hard = resource.getrlimit(kind)
            limit = requested_value
            if hard not in (-1, resource.RLIM_INFINITY):
                limit = min(limit, int(hard))
            resource.setrlimit(kind, (limit, limit))

    return apply_limits, effective, unsupported


def _run_process(
    argv: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    limits: WorkerLimits,
) -> WorkerResult:
    preexec_fn, effective_limits, unsupported_limits = _posix_preexec(limits)
    started = time.monotonic()
    timed_out = False
    max_bytes = max(1024, limits.output_max_bytes)

    with tempfile.TemporaryFile() as stdout_file, tempfile.TemporaryFile() as stderr_file:
        process = subprocess.Popen(
            argv,
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=stdout_file,
            stderr=stderr_file,
            shell=False,
            start_new_session=(os.name == "posix"),
            preexec_fn=preexec_fn,
        )
        try:
            return_code = process.wait(timeout=max(0.1, limits.timeout_seconds))
        except subprocess.TimeoutExpired:
            timed_out = True
            _kill_process_tree(process)
            try:
                return_code = process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                return_code = -9
        stdout, stdout_truncated = _read_limited(stdout_file, max_bytes)
        stderr, stderr_truncated = _read_limited(stderr_file, max_bytes)

    result = sanitize_value(
        {
            "backend": "subprocess-sandbox",
            "termination_reason": "timeout" if timed_out else "exit",
            "duration_ms": int((time.monotonic() - started) * 1000),
            "exit_code": return_code,
            "timed_out": timed_out,
            "stdout": stdout,
            "stderr": stderr,
            "stdout_truncated": stdout_truncated,
            "stderr_truncated": stderr_truncated,
            "effective_limits": effective_limits,
            "unsupported_limits": unsupported_limits,
            "network_policy": "not_isolated_by_subprocess_backend",
        }
    )
    if timed_out:
        return WorkerResult(False, result, "Worker process exceeded the configured timeout")
    if return_code != 0:
        return WorkerResult(False, result, f"Worker process exited with code {return_code}")
    return WorkerResult(True, result, None)


def _execute_subprocess_sandbox(job: WorkerJob) -> WorkerResult:
    _root, worktree, relative = _resolve_worktree(job)
    if job.action == "read_repository":
        scope = str(job.payload.get("scope") or "metadata")
        if scope != "metadata":
            return WorkerResult(False, {"status": "unsupported", "scope": scope}, "Only metadata scope is supported")
        entries = sorted(item.name for item in worktree.iterdir())[:100]
        return WorkerResult(
            True,
            sanitize_value(
                {
                    "status": "completed",
                    "action": "read_repository",
                    "backend": "subprocess-sandbox",
                    "worktree": relative,
                    "scope": "metadata",
                    "top_level_entries": entries,
                    "top_level_entry_count": sum(1 for _ in worktree.iterdir()),
                    "network_policy": "not_applicable_read_only_metadata",
                    "effective_limits": {},
                    "unsupported_limits": [],
                }
            ),
        )

    if job.action != "run_tests":
        return WorkerResult(False, {"status": "unsupported", "action": job.action}, "Action has no hardened worker contract")

    preset = str(job.payload.get("preset") or "pytest")
    if preset != "pytest":
        return WorkerResult(False, {"status": "unsupported", "preset": preset}, "Only the server-side pytest preset is supported")

    with tempfile.TemporaryDirectory(prefix=f"superchat-worker-{job.request_id[:12]}-") as tmp:
        sandbox = Path(tmp) / "worktree"
        _copy_worktree(worktree, sandbox)
        _target, target_rel = _resolve_target(sandbox, str(job.payload.get("test_target") or "tests"))
        argv = [sys.executable, "-m", "pytest", "-q", target_rel]
        outcome = _run_process(argv, cwd=sandbox, env=_minimal_env(job.env_allowlist), limits=job.limits)
        merged = dict(outcome.result)
        merged.update({"status": "passed" if outcome.ok else ("timed_out" if merged.get("timed_out") else "failed"), "action": "run_tests", "preset": "pytest", "worktree": relative, "target": target_rel, "workspace_cleanup": "completed_on_return"})
        return WorkerResult(outcome.ok, sanitize_value(merged), outcome.error)


def build_container_argv(job: WorkerJob, sandbox: Path, target_rel: str) -> list[str]:
    limits = job.limits
    return [
        job.container_runtime,
        "run",
        "--rm",
        "--network",
        "none",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--pids-limit",
        str(max(8, limits.pids)),
        "--memory",
        f"{max(64, limits.memory_mb)}m",
        "--cpus",
        "1.0",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,size=64m",
        "-v",
        f"{sandbox}:/workspace:rw",
        "-w",
        "/workspace",
        job.container_image,
        "python",
        "-m",
        "pytest",
        "-q",
        target_rel,
    ]


def _execute_container(job: WorkerJob) -> WorkerResult:
    _root, worktree, relative = _resolve_worktree(job)
    if job.action != "run_tests":
        return WorkerResult(False, {"status": "unsupported", "action": job.action}, "Container backend currently supports run_tests only")
    if shutil.which(job.container_runtime) is None:
        return WorkerResult(False, {"status": "unavailable", "backend": "container"}, "Configured container runtime is unavailable")
    if str(job.payload.get("preset") or "pytest") != "pytest":
        return WorkerResult(False, {"status": "unsupported", "preset": job.payload.get("preset")}, "Only pytest is supported")

    with tempfile.TemporaryDirectory(prefix=f"superchat-container-{job.request_id[:12]}-") as tmp:
        sandbox = Path(tmp) / "worktree"
        _copy_worktree(worktree, sandbox)
        _target, target_rel = _resolve_target(sandbox, str(job.payload.get("test_target") or "tests"))
        argv = build_container_argv(job, sandbox, target_rel)
        outcome = _run_process(argv, cwd=sandbox, env=_minimal_env(()), limits=job.limits)
        merged = dict(outcome.result)
        merged.update(
            {
                "backend": "container",
                "network_policy": "none",
                "container_image": job.container_image,
                "worktree": relative,
                "target": target_rel,
                "workspace_cleanup": "completed_on_return",
            }
        )
        return WorkerResult(outcome.ok, sanitize_value(merged), outcome.error)


def execute_worker_job(job: WorkerJob) -> WorkerResult:
    if not job.request_id:
        raise WorkerJobError("request_id is required")
    if job.action not in WORKER_REAL_ACTIONS:
        return WorkerResult(False, {"status": "unsupported", "action": job.action}, "Action has no hardened worker contract")
    if job.backend == "subprocess-sandbox":
        return _execute_subprocess_sandbox(job)
    if job.backend == "container":
        return _execute_container(job)
    return WorkerResult(False, {"status": "unsupported", "backend": job.backend}, "Unknown worker backend")


def dumps_job(job: WorkerJob) -> str:
    return json.dumps(job.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def loads_job(raw: str) -> WorkerJob:
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise WorkerJobError("Worker job must be a JSON object")
    return WorkerJob.from_dict(data)
