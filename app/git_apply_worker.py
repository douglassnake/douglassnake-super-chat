from __future__ import annotations

import hashlib
import shutil
import tempfile
from pathlib import Path, PurePosixPath
from uuid import UUID

from app.agent_task_pack import redact_secrets
from app.git_branch_worker import _git
from app.worker_modify import _policy
from app.worker_runtime import WorkerJob, WorkerResult, _copy_worktree, _resolve_worktree
from app.worktree_diff import _diff_one, propose_worktree_changes


def _staging_root(raw: object) -> Path:
    value = str(raw or "").strip()
    if not value:
        raise ValueError("Git staging root is not configured")
    path = Path(value).expanduser().resolve(strict=True)
    if not path.is_dir():
        raise ValueError("Git staging root is not a directory")
    return path


def _approval_id(raw: object) -> str:
    try:
        return str(UUID(str(raw)))
    except (TypeError, ValueError) as exc:
        raise ValueError("approval_id must be a valid UUID") from exc


def _review_applied_change(
    base: Path,
    target: Path,
    changed_files: list[dict],
    *,
    max_patch_bytes: int,
) -> tuple[str, str, int, bool, list[dict]]:
    patches: list[str] = []
    metadata: list[dict] = []
    for item in changed_files:
        relative = str(item.get("path") or "")
        patch, current = _diff_one(base, target, relative)
        if current is not None:
            patches.append(patch)
            metadata.append(current)
    raw_patch = "".join(patches)
    safe_patch = redact_secrets(raw_patch) or ""
    size = len(safe_patch.encode("utf-8"))
    if size > max(1, int(max_patch_bytes)):
        raise ValueError("Post-apply patch exceeds configured persistence limit")
    digest = hashlib.sha256(safe_patch.encode("utf-8")).hexdigest()
    return safe_patch, digest, size, safe_patch != raw_patch, metadata


def _copy_proposal_files(
    proposed: Path,
    staging: Path,
    changed_files: list[dict],
) -> None:
    root = staging.resolve(strict=True)
    for item in changed_files:
        relative = PurePosixPath(str(item.get("path") or ""))
        source = proposed.joinpath(*relative.parts)
        target = staging.joinpath(*relative.parts)
        resolved_parent = target.parent.resolve(strict=True)
        if resolved_parent != root and root not in resolved_parent.parents:
            raise ValueError(f"Approved path escapes staging worktree: {relative.as_posix()}")
        status = str(item.get("status") or "")
        if status == "deleted":
            resolved = target.resolve(strict=True)
            if resolved != root and root not in resolved.parents:
                raise ValueError(f"Delete path escapes staging worktree: {relative.as_posix()}")
            if not resolved.is_file():
                raise ValueError(f"Delete target is not a regular file: {relative.as_posix()}")
            resolved.unlink()
        elif status in {"added", "modified"}:
            if not source.is_file():
                raise ValueError(f"Proposed file is missing: {relative.as_posix()}")
            shutil.copy2(source, target)
        else:
            raise ValueError(f"Unsupported changed-file status: {status!r}")


def _cleanup_staging(job: WorkerJob, source: Path, staging: Path, root: Path) -> str:
    try:
        if staging.exists():
            _git(job, source, "worktree", "remove", "--force", str(staging))
        _git(job, source, "worktree", "prune")
        if staging.exists():
            resolved = staging.resolve(strict=False)
            if resolved != root and root not in resolved.parents:
                return "refused_outside_staging_root"
            shutil.rmtree(staging, ignore_errors=True)
        return "completed"
    except Exception:
        return "incomplete"


def execute_apply_git_change(job: WorkerJob) -> WorkerResult:
    if job.backend != "subprocess-sandbox":
        return WorkerResult(
            False,
            {"status": "unsupported", "backend": job.backend},
            "apply_git_change currently uses only the fixed-argv Git worker backend",
        )

    _root, source, relative = _resolve_worktree(job)
    if not (source / ".git").exists():
        return WorkerResult(
            False,
            {"status": "rejected", "worktree": relative},
            "apply_git_change requires a Git worktree",
        )

    staging_root = _staging_root(job.payload.get("staging_root"))
    approval_id = _approval_id(job.payload.get("approval_id"))
    branch_name = str(job.payload.get("branch_name") or "").strip()
    expected_base = str(job.payload.get("base_sha") or "").strip().lower()
    approved_digest = str(job.payload.get("patch_digest") or "").strip().lower()
    operations = job.payload.get("operations")
    policy = _policy(job)

    if not branch_name.startswith("superchat/"):
        raise ValueError("apply_git_change requires a controlled superchat/ branch")
    if len(expected_base) not in {40, 64} or any(
        ch not in "0123456789abcdef" for ch in expected_base
    ):
        raise ValueError("apply_git_change requires a valid expected base SHA")
    if len(approved_digest) != 64 or any(
        ch not in "0123456789abcdef" for ch in approved_digest
    ):
        raise ValueError("apply_git_change requires a valid approved patch digest")
    if not isinstance(operations, list) or not operations:
        raise ValueError("apply_git_change requires server-resolved operations")

    branch_ref = _git(job, source, "rev-parse", "--verify", f"refs/heads/{branch_name}")
    if not branch_ref.ok:
        return WorkerResult(False, branch_ref.result, "Controlled branch cannot be resolved")
    branch_sha = str(branch_ref.result.get("stdout") or "").strip().lower()
    if branch_sha != expected_base:
        return WorkerResult(
            False,
            {
                "status": "drift_detected",
                "branch_name": branch_name,
                "expected_base_sha": expected_base,
                "observed_base_sha": branch_sha,
                "external_effects": False,
            },
            "Controlled branch moved after review; application aborted",
        )

    staging_id = f"approval-{approval_id}"
    staging = staging_root / staging_id
    if staging.exists():
        return WorkerResult(
            False,
            {
                "status": "conflict",
                "staging_id": staging_id,
                "external_effects": False,
            },
            "A staging worktree already exists for this approval",
        )

    added = False
    try:
        created = _git(
            job,
            source,
            "worktree",
            "add",
            "--quiet",
            str(staging),
            branch_name,
        )
        if not created.ok:
            return WorkerResult(False, created.result, created.error or "Unable to create staging worktree")
        added = True

        staging_head = _git(job, staging, "rev-parse", "--verify", "HEAD")
        if not staging_head.ok:
            raise ValueError("Unable to resolve staging HEAD")
        observed_head = str(staging_head.result.get("stdout") or "").strip().lower()
        if observed_head != expected_base:
            raise ValueError("Staging HEAD does not match the reviewed base SHA")

        with tempfile.TemporaryDirectory(
            prefix=f"superchat-apply-{job.request_id[:12]}-"
        ) as temp:
            base_snapshot = Path(temp) / "base"
            proposed_snapshot = Path(temp) / "proposed"
            _copy_worktree(staging, base_snapshot)
            _copy_worktree(base_snapshot, proposed_snapshot)

            proposal = propose_worktree_changes(
                base_snapshot,
                proposed_snapshot,
                operations,
                policy=policy,
            )
            if proposal.patch_digest != approved_digest:
                raise ValueError(
                    "Reconstructed patch digest differs from the human-approved digest"
                )

            _copy_proposal_files(
                proposed_snapshot,
                staging,
                proposal.changed_files,
            )

            (
                post_patch,
                post_digest,
                post_bytes,
                post_redacted,
                post_files,
            ) = _review_applied_change(
                base_snapshot,
                staging,
                proposal.changed_files,
                max_patch_bytes=policy.max_patch_bytes,
            )
            if post_digest != approved_digest:
                raise ValueError(
                    "Post-apply patch digest differs from the human-approved digest"
                )
            if [item.get("path") for item in post_files] != [
                item.get("path") for item in proposal.changed_files
            ]:
                raise ValueError("Post-apply changed-file inventory diverged from proposal")

        final_head = _git(job, staging, "rev-parse", "--verify", "HEAD")
        if not final_head.ok or str(final_head.result.get("stdout") or "").strip().lower() != expected_base:
            raise ValueError("Staging HEAD changed during content application")

        status = _git(
            job,
            staging,
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
        )
        if not status.ok:
            raise ValueError("Unable to inspect staged worktree status")

        return WorkerResult(
            True,
            {
                "status": "applied_uncommitted",
                "action": "apply_git_change",
                "approval_id": approval_id,
                "branch_name": branch_name,
                "base_sha": expected_base,
                "patch_digest": approved_digest,
                "patch_bytes": post_bytes,
                "patch_redacted": post_redacted,
                "changed_files": post_files,
                "git_status": str(status.result.get("stdout") or "").splitlines(),
                "staging_id": staging_id,
                "source_worktree": relative,
                "source_content_changed": False,
                "commit_created": False,
                "push_performed": False,
                "pull_request_created": False,
                "network_policy": "no_network_operation_by_contract",
                "external_effects": True,
                "persistence": "dedicated_git_worktree_uncommitted",
            },
            None,
        )
    except Exception as exc:
        cleanup = _cleanup_staging(job, source, staging, staging_root) if added else "not_needed"
        return WorkerResult(
            False,
            {
                "status": "rejected",
                "action": "apply_git_change",
                "approval_id": approval_id,
                "branch_name": branch_name,
                "rollback": cleanup,
                "external_effects": False,
            },
            str(exc),
        )
