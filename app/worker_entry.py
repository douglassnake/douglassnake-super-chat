from __future__ import annotations

import json
import sys
from datetime import datetime, timezone

from app.agent_handoff import sanitize_value
from app.git_apply_worker import execute_apply_git_change
from app.git_branch_worker import execute_create_branch
from app.worker_modify import execute_modify_worktree
from app.worker_provenance import build_worker_provenance
from app.worker_runtime import WorkerJobError, execute_worker_job, loads_job


def main() -> int:
    raw = sys.stdin.read()
    started_at = datetime.now(timezone.utc).isoformat()
    job = None
    try:
        job = loads_job(raw)
        if job.action == "modify_worktree":
            outcome = execute_modify_worktree(job)
        elif job.action == "create_branch":
            outcome = execute_create_branch(job)
        elif job.action == "apply_git_change":
            outcome = execute_apply_git_change(job)
        else:
            outcome = execute_worker_job(job)
        payload = outcome.to_dict()
    except (WorkerJobError, json.JSONDecodeError, ValueError, OSError) as exc:
        payload = sanitize_value(
            {
                "ok": False,
                "result": {
                    "status": "rejected",
                    "termination_reason": "worker_validation",
                },
                "error": str(exc),
            }
        )
    except Exception as exc:  # process boundary: never leak an unstructured traceback to the API
        payload = sanitize_value(
            {
                "ok": False,
                "result": {
                    "status": "failed",
                    "termination_reason": "worker_internal_error",
                },
                "error": f"Worker internal error: {exc}",
            }
        )

    if job is not None:
        result = dict(payload.get("result") or {})
        provenance = build_worker_provenance(
            job_dict=job.to_dict(),
            ok=bool(payload.get("ok")),
            result=result,
            error=payload.get("error"),
            started_at=started_at,
        )
        result["provenance"] = provenance
        payload["result"] = sanitize_value(result)

    sys.stdout.write(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
