from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

from app.agent_handoff import sanitize_value
from app.worker_runtime import (
    WorkerJob,
    WorkerResult,
    _resolve_worktree,
    _run_process,
)


_BRANCH_RE = re.compile(r"^superchat/[a-z0-9][a-z0-9._/-]{0,79}$")


def _validate_branch_name(raw: object) -> str:
    name = str(raw or "").strip()
    if not _BRANCH_RE.fullmatch(name):
        raise ValueError(
            "Branch name must use the restricted namespace superchat/ and lowercase safe characters"
        )
    if ".." in name or "//" in name or "@{" in name or name.endswith(("/", ".")):
        raise ValueError("Branch name contains a forbidden Git ref sequence")
    return name


def _git_env() -> dict[str, str]:
    env = {
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
    }
    if os.name == "nt":
        for key in ("SYSTEMROOT", "WINDIR", "TEMP", "TMP"):
            value = os.environ.get(key)
            if value:
                env[key] = value
    return env


def _git(job: WorkerJob, worktree: Path, *args: str) -> WorkerResult:
    executable = shutil.which("git")
    if executable is None:
        return WorkerResult(
            False,
            {"status": "unavailable", "action": "create_branch"},
            "Git executable is unavailable on the worker host",
        )
    argv = [executable, "-C", str(worktree), *args]
    return _run_process(
        argv,
        cwd=worktree,
        env=_git_env(),
        limits=job.limits,
    )


def execute_create_branch(job: WorkerJob) -> WorkerResult:
    if job.backend != "subprocess-sandbox":
        return WorkerResult(
            False,
            {"status": "unsupported", "backend": job.backend},
            "create_branch currently uses only the fixed-argv Git worker backend",
        )

    _root, worktree, relative = _resolve_worktree(job)
    if not (worktree / ".git").exists():
        return WorkerResult(
            False,
            {"status": "rejected", "worktree": relative},
            "create_branch requires a Git worktree",
        )

    name = _validate_branch_name(job.payload.get("branch_name"))

    check = _git(job, worktree, "check-ref-format", "--branch", name)
    if not check.ok:
        return WorkerResult(
            False,
            {"status": "rejected", "branch_name": name},
            "Git rejected the requested branch name",
        )

    head = _git(job, worktree, "rev-parse", "--verify", "HEAD")
    if not head.ok:
        return WorkerResult(
            False,
            {"status": "rejected", "branch_name": name},
            "Git worktree has no valid HEAD commit",
        )
    head_sha = str(head.result.get("stdout") or "").strip()
    if not head_sha or len(head_sha) < 40:
        return WorkerResult(
            False,
            {"status": "rejected", "branch_name": name},
            "Unable to resolve the current HEAD commit",
        )

    existing = _git(
        job,
        worktree,
        "branch",
        "--list",
        "--format=%(refname:short)",
        name,
    )
    if not existing.ok:
        return WorkerResult(False, existing.result, existing.error)
    if str(existing.result.get("stdout") or "").strip():
        return WorkerResult(
            False,
            sanitize_value(
                {
                    "status": "conflict",
                    "action": "create_branch",
                    "branch_name": name,
                    "base_sha": head_sha,
                    "worktree": relative,
                    "external_effects": False,
                }
            ),
            "Branch already exists and will not be overwritten",
        )

    created = _git(job, worktree, "branch", "--no-track", name, head_sha)
    if not created.ok:
        return WorkerResult(False, created.result, created.error)

    result = sanitize_value(
        {
            "status": "created",
            "action": "create_branch",
            "branch_name": name,
            "base_sha": head_sha,
            "worktree": relative,
            "checkout_performed": False,
            "worktree_files_changed": False,
            "push_performed": False,
            "network_policy": "no_network_operation_by_contract",
            "git_ref_effect": True,
            "external_effects": True,
            "environment_policy": "minimal_no_parent_secrets",
        }
    )
    return WorkerResult(True, result, None)
