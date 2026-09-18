from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Protocol
from uuid import UUID

from app.agent_handoff import ALLOWED_HANDOFF_ACTIONS, NEVER_IMPLICITLY_AUTHORIZED, sanitize_value
from app.agent_models import ExecutorRequest
from app.agent_task_pack import redact_secrets


EXECUTOR_POLICY_ACTIONS = frozenset(ALLOWED_HANDOFF_ACTIONS)
EXECUTOR_FORBIDDEN_ACTIONS = frozenset(NEVER_IMPLICITLY_AUTHORIZED) | {
    "merge",
    "deploy",
    "publish",
    "shell",
    "command",
}
FORBIDDEN_PAYLOAD_KEYS = {
    "argv",
    "cmd",
    "command",
    "executable",
    "script",
    "shell",
    "shell_command",
}
TERMINAL_REQUEST_STATES = {"completed", "failed", "cancelled"}


class ExecutorUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class ExecutorCommand:
    request_id: UUID
    execution_id: UUID
    handoff_id: UUID
    project_id: UUID
    action: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class ExecutorOutcome:
    ok: bool
    result: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


class ExecutorAdapter(Protocol):
    name: str
    available: bool

    def execute(self, command: ExecutorCommand) -> ExecutorOutcome: ...


class ManualExecutorAdapter:
    name = "manual"
    available = False

    def execute(self, command: ExecutorCommand) -> ExecutorOutcome:
        raise ExecutorUnavailable(
            "The manual adapter records authorization only and does not execute external actions"
        )


def resolve_executor_adapter(adapter_type: str) -> ExecutorAdapter:
    if adapter_type == "manual":
        return ManualExecutorAdapter()
    raise ExecutorUnavailable(f"Executor adapter {adapter_type!r} is not configured")


def validate_executor_action(action: str) -> None:
    if action in EXECUTOR_FORBIDDEN_ACTIONS:
        raise ValueError(f"Executor action {action!r} is globally forbidden")
    if action not in EXECUTOR_POLICY_ACTIONS:
        supported = ", ".join(sorted(EXECUTOR_POLICY_ACTIONS))
        raise ValueError(f"Unsupported executor action {action!r}. Supported actions: {supported}")


def _reject_command_keys(value: Any, path: str = "payload") -> None:
    if isinstance(value, dict):
        for raw_key, item in value.items():
            key = str(raw_key).strip().lower().replace("-", "_")
            current = f"{path}.{raw_key}"
            if key in FORBIDDEN_PAYLOAD_KEYS:
                raise ValueError(
                    f"Arbitrary command payloads are forbidden; remove key {current!r}"
                )
            _reject_command_keys(item, current)
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _reject_command_keys(item, f"{path}[{index}]")


def sanitize_executor_payload(payload: dict[str, Any]) -> dict[str, Any]:
    _reject_command_keys(payload)
    cleaned = sanitize_value(payload)
    if not isinstance(cleaned, dict):
        raise ValueError("Executor payload must be an object")
    return cleaned


def executor_request_fingerprint(
    *,
    execution_id: UUID,
    action: str,
    adapter_type: str,
    payload: dict[str, Any],
) -> str:
    canonical = json.dumps(
        {
            "execution_id": str(execution_id),
            "action": action,
            "adapter_type": adapter_type,
            "payload": payload,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def executor_request_payload(request: ExecutorRequest) -> dict[str, Any]:
    return {
        "id": request.id,
        "execution_id": request.execution_id,
        "handoff_id": request.handoff_id,
        "project_id": request.project_id,
        "action": request.action,
        "adapter_type": request.adapter_type,
        "status": request.status,
        "payload": request.payload_json or {},
        "fingerprint": request.fingerprint,
        "notes": request.notes,
        "result": request.result_json or {},
        "error": request.error_text,
        "created_at": request.created_at,
        "released_at": request.released_at,
        "started_at": request.started_at,
        "completed_at": request.completed_at,
        "failed_at": request.failed_at,
        "cancelled_at": request.cancelled_at,
    }


def executor_command(request: ExecutorRequest) -> ExecutorCommand:
    return ExecutorCommand(
        request_id=request.id,
        execution_id=request.execution_id,
        handoff_id=request.handoff_id,
        project_id=request.project_id,
        action=request.action,
        payload=sanitize_executor_payload(request.payload_json or {}),
    )


def sanitize_executor_error(value: str | None) -> str | None:
    return redact_secrets(value)
