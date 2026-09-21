from __future__ import annotations

import hashlib
import json
import os
import socket
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from app.agent_handoff import sanitize_value


PROCESS_WORKER_ID = f"worker-{uuid4()}"


def canonical_json(value: Any) -> str:
    return json.dumps(
        sanitize_value(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def worker_job_digest(job_dict: dict[str, Any]) -> str:
    return sha256_json(job_dict)


def worker_result_digest(*, ok: bool, result: dict[str, Any], error: str | None) -> str:
    clean_result = dict(result or {})
    clean_result.pop("provenance", None)
    clean_result.pop("result_digest", None)
    return sha256_json({"ok": bool(ok), "result": clean_result, "error": error})


def host_fingerprint() -> str:
    raw = socket.gethostname().encode("utf-8", errors="replace")
    return hashlib.sha256(raw).hexdigest()[:24]


def build_worker_provenance(
    *,
    job_dict: dict[str, Any],
    ok: bool,
    result: dict[str, Any],
    error: str | None,
    started_at: str,
    finished_at: str | None = None,
) -> dict[str, Any]:
    finished = finished_at or datetime.now(timezone.utc).isoformat()
    return sanitize_value(
        {
            "worker_id": PROCESS_WORKER_ID,
            "pid": os.getpid(),
            "host_fingerprint": host_fingerprint(),
            "schema_version": job_dict.get("schema_version"),
            "backend": job_dict.get("backend"),
            "job_digest": worker_job_digest(job_dict),
            "result_digest": worker_result_digest(ok=ok, result=result, error=error),
            "started_at": started_at,
            "finished_at": finished,
        }
    )
