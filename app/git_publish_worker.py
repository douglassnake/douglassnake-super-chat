from __future__ import annotations

import re
import shutil
import tempfile
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


def _mask_paths(value: object, paths: tuple[Path, ...]) -> object:
    if isinstance(value, str):
        text = value
        for path in paths:
            text = text.replace(str(path), "[CONTROLLED_PATH]")
        return text
    if isinstance(value, dict):
        return {str(key): _mask_paths(item, paths) for key, item in value.items()}
    if isinstance(value, list):
        return [_mask_paths(item, paths) for item in value]
    return value


def _remote_git(
    job: WorkerJob,
    cwd: Path,
    remote: Path,
    *args: str,
    mask_paths: tuple[Path, ...] = (),
) -> WorkerResult:
    executable = shutil.which("git")
    if executable is None:
        return WorkerResult(False, {"status": "unavailable"}, "Git executable is unavailable")
    env = _git_env()
    # Even if a repository-local url.*.insteadOf exists, file is the only allowed transport.
    env["GIT_ALLOW_PROTOCOL"] = "file"
    # Avoid maintenance side effects while importing an object bundle.
    env["GIT_CONFIG_COUNT"] = "4"
    env["GIT_CONFIG_KEY_2"] = "gc.auto"
    env["GIT_CONFIG_VALUE_2"] = "0"
    env["GIT_CONFIG_KEY_3"] = "maintenance.auto"
    env["GIT_CONFIG_VALUE_3"] = "false"
    outcome = _run_process(
        [executable, "-C", str(cwd), *args],
        cwd=cwd,
        env=env,
        limits=job.limits,
    )
    paths = (remote, *mask_paths)
    result = _mask_paths(outcome.result, paths)
    error = _mask_paths(outcome.error, paths) if outcome.error else None
    return WorkerResult(outcome.ok, sanitize_value(result), str(error) if error else None)


def _remote_ref(job: WorkerJob, remote: Path, branch_name: str) -> str | None:
    ref = f"refs/heads/{branch_name}"
    # `show-ref --verify --hash` exits 128 for a missing ref in an otherwise
    # valid empty bare repository. `rev-parse --verify --quiet` gives the
    # contract we need here: 0=present, 1=absent, other=real failure.
    outcome = _remote_git(job, remote, remote, "rev-parse", "--verify", "--quiet", ref)
    if outcome.ok:
        return _sha(str(outcome.result.get("stdout") or "").strip(), "remote branch SHA")
    if int(outcome.result.get("exit_code") or 0) == 1:
        return None
    detail = str(outcome.result.get("stderr") or "").strip()
    raise ValueError(detail or outcome.error or "Unable to inspect controlled remote branch")


def execute_publish_branch(job: WorkerJob) -> WorkerResult:
    if job.backend != "subprocess-sandbox":
        return WorkerResult(
            False,
            {"status": "unsupported", "backend": job.backend},
            "publish_branch currently supports only the local-bare Git backend",
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

    existing = _remote_ref(job, remote, branch_name)
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

    # Local/bare publication deliberately avoids receive-pack. This prevents the
    # receive hook family from ever entering the execution path.
    with tempfile.TemporaryDirectory(prefix=f"superchat-publish-{job.request_id[:12]}-") as tmp:
        bundle = Path(tmp) / "publication.bundle"
        bundled = _git(job, source, "bundle", "create", str(bundle), f"refs/heads/{branch_name}")
        if not bundled.ok:
            return WorkerResult(False, bundled.result, bundled.error or "Unable to build publication bundle")

        imported = _remote_git(
            job,
            remote,
            remote,
            "fetch",
            "--quiet",
            "--no-tags",
            "--no-write-fetch-head",
            "--no-recurse-submodules",
            str(bundle),
            f"refs/heads/{branch_name}",
            mask_paths=(bundle,),
        )
        if not imported.ok:
            return WorkerResult(
                False,
                {
                    "status": "object_transfer_failed",
                    "remote_id": remote_id,
                    "branch_name": branch_name,
                    "external_effects": False,
                    "transport": imported.result,
                },
                imported.error or "Unable to import the controlled publication bundle",
            )

    object_check = _remote_git(job, remote, remote, "cat-file", "-e", f"{commit_sha}^{{commit}}")
    remote_parent = _remote_git(job, remote, remote, "rev-parse", "--verify", f"{commit_sha}^")
    if not object_check.ok or not remote_parent.ok:
        return WorkerResult(
            False,
            {"status": "object_verify_failed", "remote_id": remote_id, "external_effects": False},
            "Transferred remote objects could not be verified",
        )
    if str(remote_parent.result.get("stdout") or "").strip().lower() != base_sha:
        return WorkerResult(
            False,
            {"status": "object_verify_failed", "remote_id": remote_id, "external_effects": False},
            "Transferred commit parent differs from the reviewed base SHA",
        )

    ref = f"refs/heads/{branch_name}"
    zero_oid = "0" * len(commit_sha)
    created = _remote_git(job, remote, remote, "update-ref", ref, commit_sha, zero_oid)
    if not created.ok:
        observed = _remote_ref(job, remote, branch_name)
        return WorkerResult(
            False,
            {
                "status": "conflict",
                "remote_id": remote_id,
                "branch_name": branch_name,
                "observed_remote_sha": observed,
                "external_effects": False,
            },
            "Remote branch creation compare-and-swap failed; no overwrite was attempted",
        )

    observed_remote = _remote_ref(job, remote, branch_name)
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
            "Remote ref was created but post-verification did not observe the expected commit",
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
                "remote_publication_performed": True,
                "push_performed": False,
                "receive_pack_used": False,
                "pull_request_created": False,
                "force_used": False,
                "transport": "local_bundle_fetch_update_ref_cas",
                "network_policy": "local_filesystem_remote_only",
                "credential_policy": "no_credentials_no_parent_secrets",
                "external_effects": True,
            }
        ),
        None,
    )
