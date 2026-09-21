from __future__ import annotations

import tempfile
from pathlib import Path

from app.agent_handoff import sanitize_value
from app.worker_runtime import WorkerJob, WorkerResult, _copy_worktree, _resolve_worktree
from app.worktree_diff import ModificationPolicy, propose_worktree_changes


HARD_MAX_FILES = 50
HARD_MAX_OPERATIONS = 100
HARD_MAX_TOTAL_WRITE_BYTES = 1_048_576
HARD_MAX_PATCH_BYTES = 262_144


def _bounded_int(value, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return min(maximum, max(minimum, parsed))


def _policy(job: WorkerJob) -> ModificationPolicy:
    raw = job.payload.get("policy") or {}
    if not isinstance(raw, dict):
        raise ValueError("modify_worktree policy must be an object")
    return ModificationPolicy(
        max_files=_bounded_int(
            raw.get("max_files"), default=20, minimum=1, maximum=HARD_MAX_FILES
        ),
        max_operations=_bounded_int(
            raw.get("max_operations"),
            default=40,
            minimum=1,
            maximum=HARD_MAX_OPERATIONS,
        ),
        max_total_write_bytes=_bounded_int(
            raw.get("max_total_write_bytes"),
            default=65_536,
            minimum=1,
            maximum=HARD_MAX_TOTAL_WRITE_BYTES,
        ),
        max_patch_bytes=_bounded_int(
            raw.get("max_patch_bytes"),
            default=65_536,
            minimum=1,
            maximum=HARD_MAX_PATCH_BYTES,
        ),
    )


def execute_modify_worktree(job: WorkerJob) -> WorkerResult:
    if job.backend != "subprocess-sandbox":
        return WorkerResult(
            False,
            {"status": "unsupported", "backend": job.backend},
            "modify_worktree currently uses only the filesystem worker backend",
        )

    _root, worktree, relative = _resolve_worktree(job)
    operations = job.payload.get("operations")
    policy = _policy(job)

    with tempfile.TemporaryDirectory(
        prefix=f"superchat-modify-{job.request_id[:12]}-"
    ) as tmp:
        sandbox = Path(tmp) / "worktree"
        _copy_worktree(worktree, sandbox)
        proposal = propose_worktree_changes(
            worktree,
            sandbox,
            operations,
            policy=policy,
        )
        result = sanitize_value(
            {
                "status": "proposed",
                "action": "modify_worktree",
                "backend": "worker-filesystem",
                "worktree": relative,
                "changed_files": proposal.changed_files,
                "changed_file_count": len(proposal.changed_files),
                "patch": proposal.patch,
                "patch_digest": proposal.patch_digest,
                "patch_bytes": proposal.patch_bytes,
                "patch_redacted": proposal.patch_redacted,
                "workspace_persistence": "ephemeral_only",
                "source_write_policy": "read_only_by_design",
                "workspace_cleanup": "completed_on_return",
                "external_effects": False,
                "effective_policy": {
                    "max_files": policy.max_files,
                    "max_operations": policy.max_operations,
                    "max_total_write_bytes": policy.max_total_write_bytes,
                    "max_patch_bytes": policy.max_patch_bytes,
                },
            }
        )
        return WorkerResult(True, result, None)
