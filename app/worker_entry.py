from __future__ import annotations

import json
import sys

from app.agent_handoff import sanitize_value
from app.worker_runtime import WorkerJobError, execute_worker_job, loads_job


def main() -> int:
    raw = sys.stdin.read()
    try:
        job = loads_job(raw)
        outcome = execute_worker_job(job)
        payload = outcome.to_dict()
    except (WorkerJobError, json.JSONDecodeError, ValueError, OSError) as exc:
        payload = sanitize_value(
            {
                "ok": False,
                "result": {"status": "rejected", "termination_reason": "worker_validation"},
                "error": str(exc),
            }
        )
    except Exception as exc:  # process boundary: never leak an unstructured traceback to the API
        payload = sanitize_value(
            {
                "ok": False,
                "result": {"status": "failed", "termination_reason": "worker_internal_error"},
                "error": f"Worker internal error: {exc}",
            }
        )
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
