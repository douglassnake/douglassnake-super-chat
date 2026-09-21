from __future__ import annotations

import re
import shutil
from pathlib import Path

from app.agent_handoff import sanitize_value
from app.git_apply_worker import _staging_root
from app.git_branch_worker import _git, _git_env, _validate_branch_name
from app.git_commit_worker import _working_paths
from app.worker_runtime import WorkerJob, WorkerResult, _resolve_worktree, _run_process


_REMOTE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")


def _sha(raw: object, field: str) -> str:
    value = str(raw or "").strip().lower()
    if len(value) not in {40, 64} or any(ch not in "0123456789abcdef" for ch in value):
        raise ValueError(f"{field} must be a valid object SHA")
    return value


def _digest(raw: object) -> str:
    value = str(raw or "").strip().lower()
    if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
        raise ValueError("patch_digest must be a valid SHA-256 digest")
    return value


def _staging_id(raw: object) -> str:
    import uuid

    value = str(raw or "").strip()
    if not value.startswith("approval-") or len(value) > 80:
        raise ValueError("publish_branch requires a controlled approval staging id")
    try:
        uuid.UUID(value.removeprefix("approval-"))
    except ValueError as exc:
        raise ValueError("publish_branch staging id is invalid") from exc
    return value


def _remote_id(raw: object) -> str:
    value = str(raw or "").strip()
    if not _REMOTE_ID_RE.fullmatch(value):
        raise ValueError("Configured publish remote id is invalid")
    return value


def _remote_path(raw: object) -> Path:
    value = str(raw or "").strip()
    if not value or "\x00" in value or "\n" in value or "\r" in value or "://" in value:
        raise ValueError("Configured publish remote must be an absolute local path")
    candidate = Path(value)
    if not candidate.is_absolute():
        raise ValueError("Configured publish remote must be an absolute local path")
    resolved = candidate.resolve(strict=True)
    if not resolved.is_dir():
        raise ValueError("Configured publish remote must be a directory")
    return resolved


def _mask_remote(value: object, remote: Path) -> object:
    text = str(remote)
    if isinstance(value, str):
        return value.replace(text, "[CONTROLLED_REMOTE]")
    if isinstance(value, dict):
        return {str(key): _mask_remote(item, remote) for key, item in value.items()}
    if isinstance(value, list):
        return [_mask_remote(item, remote) for item in value]
    return value


def _remote_git(
    job: WorkerJob,
    cwd: Path,
    remote: Path,
    *args: str,
) -> WorkerResult:
    executable = shutil.which("git")
    if executable is None:
        return WorkerResult(False, {"status": "unavailable"}, "Git executable is unavailable")
    env = _git_env()
    # Fail closed: even repository-local url.*.insteadOf cannot escape to network.
    env["GIT_ALLOW_PROTOCOL"] = "file"
    outcome = _run_process(
        [executable, "-C", str(cwd), *args],
        cwd=cwd,
        env=env,
        limits=job.limits,
    )
    result = _mask_remote(outcome.result, remote)
    error = _mask_remote(outcome.error, remote) if outcome.error else None
    return WorkerResult(outcome.ok, sanitize_value(result), str(error) if error else None)


def _ls_remote_branch(job: WorkerJob, source: Path, remote: Path, branch_name: str) -> str | None:
    ref = f"refs/heads/{branch_name}"
    outcome = _remote_git(job, source, remote, "ls-remote", "--heads", str(remote), ref)
    if not outcome.ok:
        raise ValueError(outcome.error or "Unable to inspect controlled remote branch")
    raw = str(outcome.result.get("stdout") or "").strip()
    if not raw:
        return None
    lines = [line for line in raw.splitlines() if line.strip()]
    if len(lines) != 1 or "\t" not in lines[0]:
        raise ValueError("Controlled remote returned an ambiguous branch reference")
    sha, observed_ref = lines[0].split("\t", 1)
    if observed_ref != ref:
        raise ValueError("Controlled remote returned an unexpected branch reference")
    return _sha(sha, "remote branch SHA")


def execute_publish_branch(job: WorkerJob) -> WorkerResult:
    if job.backend != "subprocess-sandbox":
        return WorkerResult(
            False,
            {"status": "unsupported", "backend": job.backend},
            "publish_branch currently uses only the fixed-argv local-file Git backend",
        )

    _root, source, relative = _resolve_worktree(job)
    if not (source / ".git").exists():
        return WorkerResult(False, {"status": "rejected"}, "publish_branch requires a Git worktree")

    branch_name = _validate_branch_name(job.payload.get("branch_name"))
    base_sha = _sha(job.payload.get("base_sha"), "base_sha")
    commit_sha = _sha(job.payload.get("commit_sha"), "commit_sha")
    patch_digest = _digest(job.payload.get("patch_digest"))
    staging_id = _staging_id(job.payload.get("staging_id"))
    remote = _remote_path(job.payload.get("remote_path"))
    remote_id = _remote_id(job.payload.get("remote_id"))
    staging_root = _staging_root(job.payload.get("staging_root"))
    staging = (staging_root / staging_id).resolve(strict=True)

    source_resolved = source.resolve(strict=True)
    staging_resolved = staging.resolve(strict=True)
    if remote in {source_resolved, staging_resolved, staging_root.resolve(strict=True)}:
        raise ValueError("Controlled publish remote must be separate from source and staging worktrees")
    if source_resolved in remote.parents or remote in source_resolved.parents:
        raise ValueError("Controlled publish remote cannot be nested with the source worktree")
    if staging_resolved in remote.parents or remote in staging_resolved.parents:
        raise ValueError("Controlled publish remote cannot be nested with the staging worktree")

    bare = _remote_git(job, remote, remote, "rev-parse", "--is-bare-repository")
    if not bare.ok or str(bare.result.get("stdout") or "").strip().lower() != "true":
        return WorkerResult(
            False,
            {"status": "rejected", "remote_id": remote_id, "external_effects": False},
            "Configured publish remote is not a bare Git repository",
        )

    branch_ref = _git(job, source, "rev-parse", "--verify", f"refs/heads/{branch_name}")
    parent = _git(job, source, "rev-parse", "--verify", f"{commit_sha}^")
    staging_head = _git(job, staging, "rev-parse", "--verify", "HEAD")
    staging_branch = _git(job, staging, "rev-parse", "--abbrev-ref", "HEAD")
    if not branch_ref.ok or not parent.ok or not staging_head.ok or not staging_branch.ok:
        raise ValueError("Unable to resolve controlled local publication state")

    observed_branch_sha = str(branch_ref.result.get("stdout") or "").strip().lower()
    observed_parent = str(parent.result.get("stdout") or "").strip().lower()
    observed_staging_head = str(staging_head.result.get("stdout") or "").strip().lower()
    observed_staging_branch = str(staging_branch.result.get("stdout") or "").strip()
    if (
        observed_branch_sha != commit_sha
        or observed_staging_head != commit_sha
        or observed_staging_branch != branch_name
        or observed_parent != base_sha
    ):
        return WorkerResult(
            False,
            {
                "status": "drift_detected",
                "remote_id": remote_id,
                "branch_name": branch_name,
                "expected_commit_sha": commit_sha,
                "observed_branch_sha": observed_branch_sha,
                "observed_staging_head": observed_staging_head,
                "external_effects": False,
            },
            "Controlled local branch/staging drifted after commit; publication aborted",
        )

    working_paths, pre_staged = _working_paths(job, staging)
    if pre_staged or working_paths:
        return WorkerResult(
            False,
            {
                "status": "drift_detected",
                "reason": "staging_not_clean",
                "remote_id": remote_id,
                "observed_paths": sorted(working_paths),
                "external_effects": False,
            },
            "Controlled staging is not clean; publication aborted",
        )

    existing = _ls_remote_branch(job, source, remote, branch_name)
    if existing is not None:
        return WorkerResult(
            False,
            {
                "status": "conflict",
                "remote_id": remote_id,
                "branch_name": branch_name,
                "remote_sha": existing,
                "external_effects": False,
            },
            "Controlled remote branch already exists; first publication will not overwrite it",
        )

    ref = f"refs/heads/{branch_name}"
    pushed = _remote_git(
        job,
        source,
        remote,
        "push",
        "--porcelain",
        "--no-verify",
        str(remote),
        f"{commit_sha}:{ref}",
    )
    if not pushed.ok:
        return WorkerResult(
            False,
            {
                "status": "push_failed",
                "remote_id": remote_id,
                "branch_name": branch_name,
                "external_effects": False,
                "transport": pushed.result,
            },
            pushed.error or "Controlled local-file push failed",
        )

    observed_remote = _ls_remote_branch(job, source, remote, branch_name)
    if observed_remote != commit_sha:
        return WorkerResult(
            False,
            {
                "status": "post_verify_failed",
                "remote_id": remote_id,
                "branch_name": branch_name,
                "expected_commit_sha": commit_sha,
                "observed_remote_sha": observed_remote,
                "external_effects": True,
                "manual_reconciliation_required": True,
            },
            "Remote publication occurred but post-verification did not observe the expected commit",
        )

    return WorkerResult(
        True,
        sanitize_value(
            {
                "status": "published_remote",
                "action": "publish_branch",
                "remote_id": remote_id,
                "branch_name": branch_name,
                "remote_ref": ref,
                "base_sha": base_sha,
                "commit_sha": commit_sha,
                "remote_sha": observed_remote,
                "patch_digest": patch_digest,
                "source_worktree": relative,
                "push_performed": True,
                "pull_request_created": False,
                "force_used": False,
                "network_policy": "local_filesystem_remote_only",
                "credential_policy": "no_credentials_no_parent_secrets",
                "external_effects": True,
            }
        ),
        None,
    )
