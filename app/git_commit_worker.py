from __future__ import annotations

import os
import shutil
import stat
import subprocess
import tempfile
import time
from pathlib import Path, PurePosixPath
from typing import Any

from app.agent_task_pack import redact_secrets
from app.git_apply_worker import _review_applied_change, _staging_root
from app.git_branch_worker import _git, _git_env, _validate_branch_name
from app.worker_runtime import (
    WorkerJob,
    WorkerResult,
    _kill_process_tree,
    _posix_preexec,
    _resolve_worktree,
    _run_process,
)
from app.worktree_diff import _relative_path


def _valid_sha(raw: object, *, field: str) -> str:
    value = str(raw or "").strip().lower()
    if len(value) not in {40, 64} or any(ch not in "0123456789abcdef" for ch in value):
        raise ValueError(f"{field} must be a valid object SHA")
    return value


def _valid_digest(raw: object) -> str:
    value = str(raw or "").strip().lower()
    if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
        raise ValueError("patch_digest must be a valid SHA-256 digest")
    return value


def _staging_id(raw: object) -> str:
    value = str(raw or "").strip()
    if not value.startswith("approval-") or len(value) > 80:
        raise ValueError("create_commit requires a controlled approval staging id")
    suffix = value.removeprefix("approval-")
    import uuid

    try:
        uuid.UUID(suffix)
    except ValueError as exc:
        raise ValueError("create_commit staging id is invalid") from exc
    return value


def _commit_message(raw: object) -> str:
    if not isinstance(raw, str):
        raise ValueError("commit_message must be a string")
    value = raw.strip()
    if not value or len(value) > 200:
        raise ValueError("commit_message must contain between 1 and 200 characters")
    if "\x00" in value or "\n" in value or "\r" in value:
        raise ValueError("commit_message must be a single line without NUL bytes")
    if (redact_secrets(value) or "") != value:
        raise ValueError("commit_message contains detectable secret-like content")
    return value


def _identity(name_raw: object, email_raw: object) -> tuple[str, str]:
    name = str(name_raw or "").strip()
    email = str(email_raw or "").strip()
    if not name or len(name) > 100 or any(ch in name for ch in "\r\n\x00"):
        raise ValueError("Configured Git executor author name is invalid")
    if (
        not email
        or len(email) > 254
        or any(ch in email for ch in "\r\n\x00 <>\t")
        or "@" not in email
    ):
        raise ValueError("Configured Git executor author email is invalid")
    return name, email


def _changed_inventory(raw: object) -> list[dict[str, Any]]:
    if not isinstance(raw, list) or not raw:
        raise ValueError("create_commit requires a non-empty approved changed-file inventory")
    if len(raw) > 20:
        raise ValueError("create_commit changed-file inventory exceeds hard cap")
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("create_commit changed-file entries must be objects")
        path = _relative_path(item.get("path")).as_posix()
        status_value = str(item.get("status") or "")
        if status_value not in {"added", "modified", "deleted"}:
            raise ValueError(f"Unsupported approved file status: {status_value!r}")
        if path in seen:
            raise ValueError(f"Duplicate approved file path: {path}")
        seen.add(path)
        result.append({"path": path, "status": status_value})
    return result


def _split_nul_paths(raw: object) -> list[str]:
    text = str(raw or "")
    return [item for item in text.split("\x00") if item]


def _git_with_env(
    job: WorkerJob,
    worktree: Path,
    *args: str,
    extra_env: dict[str, str] | None = None,
) -> WorkerResult:
    executable = shutil.which("git")
    if executable is None:
        return WorkerResult(False, {"status": "unavailable"}, "Git executable is unavailable")
    env = _git_env()
    if extra_env:
        env.update(extra_env)
    return _run_process(
        [executable, "-C", str(worktree), *args],
        cwd=worktree,
        env=env,
        limits=job.limits,
    )


def _git_blob_bytes(job: WorkerJob, repository: Path, object_spec: str) -> bytes:
    executable = shutil.which("git")
    if executable is None:
        raise ValueError("Git executable is unavailable")
    preexec_fn, _effective, _unsupported = _posix_preexec(job.limits)
    max_bytes = max(1, int(job.limits.file_size_mb)) * 1024 * 1024
    started = time.monotonic()
    with tempfile.TemporaryFile() as stdout_file, tempfile.TemporaryFile() as stderr_file:
        process = subprocess.Popen(
            [executable, "-C", str(repository), "cat-file", "blob", object_spec],
            cwd=repository,
            env=_git_env(),
            stdin=subprocess.DEVNULL,
            stdout=stdout_file,
            stderr=stderr_file,
            shell=False,
            start_new_session=(os.name == "posix"),
            preexec_fn=preexec_fn,
        )
        try:
            return_code = process.wait(timeout=max(0.1, job.limits.timeout_seconds))
        except subprocess.TimeoutExpired as exc:
            _kill_process_tree(process)
            process.wait(timeout=5)
            raise ValueError("Git blob read exceeded the configured timeout") from exc
        if return_code != 0:
            stderr_file.seek(0)
            stderr = stderr_file.read(8192).decode("utf-8", errors="replace")
            raise ValueError(redact_secrets(stderr) or "Unable to read Git blob")
        stdout_file.seek(0)
        data = stdout_file.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise ValueError("Approved base file exceeds configured worker file-size limit")
    if time.monotonic() - started > max(0.1, job.limits.timeout_seconds) + 1:
        raise ValueError("Git blob read exceeded the configured timeout")
    return data


def _build_base_snapshot(
    job: WorkerJob,
    repository: Path,
    base_sha: str,
    changed_files: list[dict[str, Any]],
    destination: Path,
) -> None:
    destination.mkdir(parents=True, exist_ok=False)
    for item in changed_files:
        if item["status"] == "added":
            continue
        relative = PurePosixPath(item["path"])
        data = _git_blob_bytes(job, repository, f"{base_sha}:{relative.as_posix()}")
        try:
            data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(f"Approved base file is no longer UTF-8: {relative.as_posix()}") from exc
        target = destination.joinpath(*relative.parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)


def _working_paths(job: WorkerJob, staging: Path) -> tuple[set[str], bool]:
    cached = _git(
        job,
        staging,
        "diff",
        "--cached",
        "--no-ext-diff",
        "--no-textconv",
        "--name-only",
        "-z",
        "HEAD",
        "--",
    )
    if not cached.ok:
        raise ValueError("Unable to inspect staging index")
    if _split_nul_paths(cached.result.get("stdout")):
        return set(), True

    tracked = _git(
        job,
        staging,
        "diff",
        "--no-ext-diff",
        "--no-textconv",
        "--name-only",
        "-z",
        "HEAD",
        "--",
    )
    untracked = _git(job, staging, "ls-files", "--others", "--exclude-standard", "-z")
    ignored = _git(
        job,
        staging,
        "ls-files",
        "--others",
        "--ignored",
        "--exclude-standard",
        "-z",
    )
    if not tracked.ok or not untracked.ok or not ignored.ok:
        raise ValueError("Unable to enumerate staging changes")
    paths = set(_split_nul_paths(tracked.result.get("stdout")))
    paths.update(_split_nul_paths(untracked.result.get("stdout")))
    paths.update(_split_nul_paths(ignored.result.get("stdout")))
    return paths, False


def _base_mode(job: WorkerJob, repository: Path, base_sha: str, path: str) -> str | None:
    outcome = _git(job, repository, "ls-tree", base_sha, "--", path)
    if not outcome.ok:
        raise ValueError(f"Unable to inspect base mode for {path}")
    line = str(outcome.result.get("stdout") or "").strip()
    if not line:
        return None
    mode = line.split(" ", 1)[0]
    if mode not in {"100644", "100755"}:
        raise ValueError(f"Unsupported Git file mode for controlled commit: {mode} ({path})")
    return mode


def _file_mode(path: Path) -> str:
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise ValueError(f"Controlled commit target must be a regular file: {path.name}")
    return "100755" if info.st_mode & 0o111 else "100644"


def _rollback_ref(
    job: WorkerJob,
    staging: Path,
    branch_name: str,
    base_sha: str,
    commit_sha: str,
) -> str:
    ref = f"refs/heads/{branch_name}"
    reverted = _git(job, staging, "update-ref", ref, base_sha, commit_sha)
    reset = _git(job, staging, "reset", "--mixed", "--quiet", base_sha)
    return "completed" if reverted.ok and reset.ok else "incomplete"


def execute_create_commit(job: WorkerJob) -> WorkerResult:
    if job.backend != "subprocess-sandbox":
        return WorkerResult(
            False,
            {"status": "unsupported", "backend": job.backend},
            "create_commit currently uses only the fixed-argv Git plumbing backend",
        )

    _root, source, relative = _resolve_worktree(job)
    if not (source / ".git").exists():
        return WorkerResult(False, {"status": "rejected"}, "create_commit requires a Git worktree")

    staging_root = _staging_root(job.payload.get("staging_root"))
    staging_id = _staging_id(job.payload.get("staging_id"))
    branch_name = _validate_branch_name(job.payload.get("branch_name"))
    base_sha = _valid_sha(job.payload.get("base_sha"), field="base_sha")
    approved_digest = _valid_digest(job.payload.get("patch_digest"))
    changed_files = _changed_inventory(job.payload.get("changed_files"))
    message = _commit_message(job.payload.get("commit_message"))
    author_name, author_email = _identity(
        job.payload.get("author_name"), job.payload.get("author_email")
    )
    max_patch_bytes = int((job.payload.get("policy") or {}).get("max_patch_bytes") or 65_536)

    staging = (staging_root / staging_id).resolve(strict=True)
    root = staging_root.resolve(strict=True)
    if staging == root or root not in staging.parents or not staging.is_dir():
        raise ValueError("Controlled staging worktree escapes the configured staging root")
    if not (staging / ".git").exists():
        raise ValueError("Controlled staging path is not a Git linked worktree")

    branch_ref = _git(job, source, "rev-parse", "--verify", f"refs/heads/{branch_name}")
    staging_head = _git(job, staging, "rev-parse", "--verify", "HEAD")
    staging_branch = _git(job, staging, "rev-parse", "--abbrev-ref", "HEAD")
    if not branch_ref.ok or not staging_head.ok or not staging_branch.ok:
        raise ValueError("Unable to resolve controlled branch/staging state")
    observed_ref = str(branch_ref.result.get("stdout") or "").strip().lower()
    observed_head = str(staging_head.result.get("stdout") or "").strip().lower()
    observed_branch = str(staging_branch.result.get("stdout") or "").strip()
    if observed_ref != base_sha or observed_head != base_sha or observed_branch != branch_name:
        return WorkerResult(
            False,
            {
                "status": "drift_detected",
                "branch_name": branch_name,
                "expected_base_sha": base_sha,
                "observed_branch_sha": observed_ref,
                "observed_staging_head": observed_head,
                "external_effects": False,
            },
            "Controlled staging/branch moved after apply; commit aborted",
        )

    expected_paths = {item["path"] for item in changed_files}
    working_paths, pre_staged = _working_paths(job, staging)
    if pre_staged:
        return WorkerResult(
            False,
            {"status": "drift_detected", "reason": "pre_staged_index", "external_effects": False},
            "Controlled staging index already contains staged changes",
        )
    if working_paths != expected_paths:
        return WorkerResult(
            False,
            {
                "status": "drift_detected",
                "reason": "changed_file_inventory",
                "expected_paths": sorted(expected_paths),
                "observed_paths": sorted(working_paths),
                "external_effects": False,
            },
            "Controlled staging contains unapproved or missing changes",
        )

    with tempfile.TemporaryDirectory(prefix=f"superchat-commit-{job.request_id[:12]}-") as temp:
        temp_root = Path(temp)
        base_snapshot = temp_root / "base"
        _build_base_snapshot(job, source, base_sha, changed_files, base_snapshot)
        _patch, digest, _size, _redacted, current_files = _review_applied_change(
            base_snapshot,
            staging,
            changed_files,
            max_patch_bytes=max_patch_bytes,
        )
        if digest != approved_digest:
            return WorkerResult(
                False,
                {"status": "drift_detected", "reason": "patch_digest", "external_effects": False},
                "Current staging digest differs from the human-approved digest",
            )
        if [item.get("path") for item in current_files] != [item["path"] for item in changed_files]:
            raise ValueError("Current staging inventory differs from approved ordering")

        index_file = temp_root / "index"
        index_env = {"GIT_INDEX_FILE": str(index_file)}
        read_tree = _git_with_env(
            job, source, "read-tree", base_sha, extra_env=index_env
        )
        if not read_tree.ok:
            return WorkerResult(False, read_tree.result, "Unable to initialize controlled temporary index")

        for item in changed_files:
            path_text = item["path"]
            status_value = item["status"]
            if status_value == "deleted":
                removed = _git_with_env(
                    job,
                    source,
                    "update-index",
                    "--force-remove",
                    "--",
                    path_text,
                    extra_env=index_env,
                )
                if not removed.ok:
                    return WorkerResult(False, removed.result, f"Unable to remove approved path from index: {path_text}")
                continue

            target = staging.joinpath(*PurePosixPath(path_text).parts)
            if target.is_symlink() or not target.is_file():
                raise ValueError(f"Approved commit path is not a regular file: {path_text}")
            base_mode = _base_mode(job, source, base_sha, path_text)
            if status_value == "modified":
                if base_mode is None:
                    raise ValueError(f"Modified approved path is absent from base tree: {path_text}")
                mode = base_mode
            else:
                if base_mode is not None:
                    raise ValueError(f"Added approved path already exists in base tree: {path_text}")
                mode = _file_mode(target)

            hashed = _git_with_env(
                job,
                staging,
                "hash-object",
                "-w",
                "--no-filters",
                "--",
                path_text,
                extra_env=index_env,
            )
            if not hashed.ok:
                return WorkerResult(False, hashed.result, f"Unable to hash approved path: {path_text}")
            blob_sha = str(hashed.result.get("stdout") or "").strip()
            updated = _git_with_env(
                job,
                source,
                "update-index",
                "--add",
                "--cacheinfo",
                mode,
                blob_sha,
                path_text,
                extra_env=index_env,
            )
            if not updated.ok:
                return WorkerResult(False, updated.result, f"Unable to update controlled index: {path_text}")

        tree = _git_with_env(job, source, "write-tree", extra_env=index_env)
        if not tree.ok:
            return WorkerResult(False, tree.result, "Unable to write controlled commit tree")
        tree_sha = str(tree.result.get("stdout") or "").strip().lower()

        tree_paths = _git(
            job,
            source,
            "diff-tree",
            "--no-commit-id",
            "--name-only",
            "--no-renames",
            "-r",
            "-z",
            base_sha,
            tree_sha,
            "--",
        )
        if not tree_paths.ok:
            return WorkerResult(False, tree_paths.result, "Unable to inspect controlled commit tree")
        if set(_split_nul_paths(tree_paths.result.get("stdout"))) != expected_paths:
            return WorkerResult(
                False,
                {"status": "rejected", "reason": "tree_path_mismatch", "external_effects": False},
                "Controlled commit tree contains paths outside the approved inventory",
            )

        identity_env = {
            "GIT_AUTHOR_NAME": author_name,
            "GIT_AUTHOR_EMAIL": author_email,
            "GIT_COMMITTER_NAME": author_name,
            "GIT_COMMITTER_EMAIL": author_email,
        }
        committed = _git_with_env(
            job,
            source,
            "-c",
            "commit.gpgSign=false",
            "commit-tree",
            tree_sha,
            "-p",
            base_sha,
            "-m",
            message,
            extra_env=identity_env,
        )
        if not committed.ok:
            return WorkerResult(False, committed.result, "Unable to create controlled commit object")
        commit_sha = str(committed.result.get("stdout") or "").strip().lower()
        _valid_sha(commit_sha, field="created commit SHA")

        moved = _git(
            job,
            source,
            "update-ref",
            f"refs/heads/{branch_name}",
            commit_sha,
            base_sha,
        )
        if not moved.ok:
            return WorkerResult(
                False,
                {"status": "drift_detected", "reason": "ref_compare_and_swap", "external_effects": False},
                "Controlled branch moved before atomic commit publication",
            )

        reset = _git(job, staging, "reset", "--mixed", "--quiet", commit_sha)
        if not reset.ok:
            rollback = _rollback_ref(job, staging, branch_name, base_sha, commit_sha)
            return WorkerResult(
                False,
                {"status": "rollback", "rollback": rollback, "external_effects": rollback != "completed"},
                "Commit ref was created but staging index synchronization failed",
            )

        try:
            head = _git(job, staging, "rev-parse", "--verify", "HEAD")
            parent = _git(job, staging, "rev-parse", "--verify", "HEAD^")
            branch_after = _git(job, source, "rev-parse", "--verify", f"refs/heads/{branch_name}")
            if not head.ok or not parent.ok or not branch_after.ok:
                raise ValueError("Unable to verify created commit")
            if str(head.result.get("stdout") or "").strip().lower() != commit_sha:
                raise ValueError("Staging HEAD does not reference the created commit")
            if str(parent.result.get("stdout") or "").strip().lower() != base_sha:
                raise ValueError("Created commit parent differs from reviewed base SHA")
            if str(branch_after.result.get("stdout") or "").strip().lower() != commit_sha:
                raise ValueError("Controlled branch does not reference the created commit")

            post_paths, post_staged = _working_paths(job, staging)
            if post_staged or post_paths:
                raise ValueError("Controlled staging is not clean after commit")

            _post_patch, post_digest, _post_size, _post_redacted, post_files = _review_applied_change(
                base_snapshot,
                staging,
                changed_files,
                max_patch_bytes=max_patch_bytes,
            )
            if post_digest != approved_digest:
                raise ValueError("Created commit content digest differs from approved digest")
            if [item.get("path") for item in post_files] != [item["path"] for item in changed_files]:
                raise ValueError("Created commit inventory differs from approved inventory")
        except Exception as exc:
            rollback = _rollback_ref(job, staging, branch_name, base_sha, commit_sha)
            return WorkerResult(
                False,
                {
                    "status": "rollback",
                    "commit_sha": commit_sha,
                    "rollback": rollback,
                    "external_effects": rollback != "completed",
                },
                str(exc),
            )

    return WorkerResult(
        True,
        {
            "status": "committed_local",
            "action": "create_commit",
            "branch_name": branch_name,
            "base_sha": base_sha,
            "commit_sha": commit_sha,
            "parent_sha": base_sha,
            "tree_sha": tree_sha,
            "patch_digest": approved_digest,
            "changed_files": changed_files,
            "staging_id": staging_id,
            "source_worktree": relative,
            "author_name": author_name,
            "author_email": author_email,
            "commit_message": message,
            "commit_created": True,
            "push_performed": False,
            "pull_request_created": False,
            "network_policy": "no_network_operation_by_contract",
            "index_policy": "temporary_index_approved_paths_only_no_filters",
            "hook_policy": "disabled_by_server_git_config",
            "external_effects": True,
            "persistence": "local_git_commit_only",
        },
        None,
    )
