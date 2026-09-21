from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from app.agent_task_pack import redact_secrets
from app.worker_provenance import worker_job_digest, worker_result_digest
from app.worker_runtime import WorkerJob, WorkerResult, dumps_job


class WorkerClientError(RuntimeError):
    pass


class ProcessWorkerClient:
    def __init__(self, *, grace_seconds: float = 10.0) -> None:
        self.grace_seconds = max(1.0, float(grace_seconds))
        self.package_root = Path(__file__).resolve().parent.parent

    @staticmethod
    def _worker_env() -> dict[str, str]:
        env = {
            "PYTHONUNBUFFERED": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
        }
        if os.name == "nt":
            for key in ("SYSTEMROOT", "WINDIR", "TEMP", "TMP"):
                value = os.environ.get(key)
                if value:
                    env[key] = value
        return env

    @staticmethod
    def _verify_provenance(job: WorkerJob, result: WorkerResult) -> None:
        provenance = dict(result.result.get("provenance") or {})
        if not provenance:
            raise WorkerClientError("Worker result is missing provenance")
        expected_job = worker_job_digest(job.to_dict())
        if provenance.get("job_digest") != expected_job:
            raise WorkerClientError("Worker job digest mismatch")
        expected_result = worker_result_digest(
            ok=result.ok,
            result=result.result,
            error=result.error,
        )
        if provenance.get("result_digest") != expected_result:
            raise WorkerClientError("Worker result digest mismatch")
        if not provenance.get("worker_id"):
            raise WorkerClientError("Worker result is missing worker identity")

    def execute(self, job: WorkerJob) -> WorkerResult:
        timeout = max(1.0, job.limits.timeout_seconds + self.grace_seconds)
        try:
            completed = subprocess.run(
                [sys.executable, "-m", "app.worker_entry"],
                input=dumps_job(job),
                cwd=self.package_root,
                env=self._worker_env(),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                shell=False,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise WorkerClientError("Worker process exceeded the outer execution deadline") from exc

        raw_stdout = completed.stdout or ""
        raw_stderr = redact_secrets(completed.stderr or "") or ""
        if completed.returncode != 0:
            raise WorkerClientError(
                f"Worker process failed before returning a result (exit={completed.returncode}): {raw_stderr[:2000]}"
            )
        try:
            payload = json.loads(raw_stdout)
        except json.JSONDecodeError as exc:
            raise WorkerClientError(
                f"Worker returned invalid JSON: {(redact_secrets(raw_stdout) or '')[:2000]}"
            ) from exc
        if not isinstance(payload, dict):
            raise WorkerClientError("Worker result must be a JSON object")
        result = WorkerResult.from_dict(payload)
        self._verify_provenance(job, result)
        return result
