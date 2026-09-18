from __future__ import annotations

from typing import Any

from app.agent_models import AgentHandoff, AgentTaskPack
from app.agent_task_pack import redact_secrets, sanitize_source_ref


ALLOWED_HANDOFF_ACTIONS = {
    "read_context",
    "read_repository",
    "modify_worktree",
    "run_tests",
    "create_branch",
    "create_commit",
    "create_pull_request",
}

NEVER_IMPLICITLY_AUTHORIZED = [
    "merge",
    "deploy",
    "publish",
    "write_drive",
    "write_calendar",
    "write_external_service",
]

SENSITIVE_PAYLOAD_KEYS = {
    "password",
    "passwd",
    "secret",
    "client_secret",
    "refresh_token",
    "access_token",
    "api_key",
    "apikey",
    "token",
    "authorization",
    "key",
    "signature",
    "sig",
}


def sanitize_value(value: Any) -> Any:
    if isinstance(value, str):
        return redact_secrets(value)
    if isinstance(value, list):
        return [sanitize_value(item) for item in value]
    if isinstance(value, tuple):
        return [sanitize_value(item) for item in value]
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            string_key = str(key)
            normalized_key = string_key.strip().lower().replace("-", "_")
            if normalized_key in SENSITIVE_PAYLOAD_KEYS:
                result[string_key] = "[REDACTED]"
            else:
                result[string_key] = sanitize_value(item)
        return result
    return value


def clean_allowed_actions(values: list[str] | None) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    unsupported: list[str] = []
    for raw in values or []:
        action = str(raw).strip()
        if not action:
            continue
        if action not in ALLOWED_HANDOFF_ACTIONS:
            unsupported.append(action)
            continue
        if action not in seen:
            seen.add(action)
            result.append(action)
    if unsupported:
        supported = ", ".join(sorted(ALLOWED_HANDOFF_ACTIONS))
        invalid = ", ".join(sorted(set(unsupported)))
        raise ValueError(f"Unsupported handoff actions: {invalid}. Supported actions: {supported}")
    return result


def build_pack_handoff_snapshot(pack: AgentTaskPack) -> dict[str, Any]:
    sources = []
    for source in pack.sources_json or []:
        sources.append(
            {
                "source_type": source.get("source_type"),
                "source_ref": sanitize_source_ref(source.get("source_ref")),
            }
        )
    return sanitize_value(
        {
            "pack_id": str(pack.id),
            "project_id": str(pack.project_id),
            "fingerprint": pack.fingerprint,
            "project": pack.project_snapshot_json or {},
            "objective": pack.objective,
            "profile": pack.profile,
            "query": pack.query_text,
            "acceptance_criteria": pack.acceptance_criteria_json or [],
            "constraints": pack.constraints_json or [],
            "suggested_areas": pack.suggested_areas_json or [],
            "sources": sources,
            "budget": pack.budget_json or {},
        }
    )


def handoff_payload(handoff: AgentHandoff) -> dict[str, Any]:
    return {
        "id": handoff.id,
        "pack_id": handoff.pack_id,
        "project_id": handoff.project_id,
        "status": handoff.status,
        "execution_released": handoff.status == "released",
        "executor_type": handoff.executor_type,
        "executor_target": handoff.executor_target,
        "allowed_actions": handoff.allowed_actions_json or [],
        "never_implicitly_authorized": NEVER_IMPLICITLY_AUTHORIZED,
        "pack_fingerprint": handoff.pack_fingerprint,
        "pack_snapshot": handoff.pack_snapshot_json or {},
        "notes": handoff.notes,
        "result": handoff.result_json or {},
        "error": handoff.error_text,
        "created_at": handoff.created_at,
        "released_at": handoff.released_at,
        "completed_at": handoff.completed_at,
        "failed_at": handoff.failed_at,
        "cancelled_at": handoff.cancelled_at,
    }


def render_handoff_markdown(handoff: AgentHandoff, pack: AgentTaskPack) -> str:
    snapshot = handoff.pack_snapshot_json or {}
    project = snapshot.get("project") or {}
    allowed = handoff.allowed_actions_json or []
    criteria = snapshot.get("acceptance_criteria") or []
    constraints = snapshot.get("constraints") or []
    areas = snapshot.get("suggested_areas") or []
    sources = snapshot.get("sources") or []
    budget = snapshot.get("budget") or {}
    context_items = sanitize_value(pack.context_json or [])

    lines = [
        "# Agent Handoff",
        "",
        f"**Handoff:** `{handoff.id}`",
        f"**Status:** `{handoff.status}`",
        f"**Task Pack:** `{handoff.pack_id}`",
        f"**Pack fingerprint:** `{handoff.pack_fingerprint}`",
        f"**Executor:** `{handoff.executor_type}`",
        f"**Target:** {handoff.executor_target or 'Não informado.'}",
        "",
        "## Projeto",
        "",
        f"- Nome: {project.get('name') or 'Não informado.'}",
        f"- Slug: `{project.get('slug') or 'n/a'}`",
        f"- Estado capturado: `{project.get('status') or 'n/a'}`",
        "",
        "## Objetivo",
        "",
        snapshot.get("objective") or "Não informado.",
        "",
        "## Critérios de aceite",
        "",
    ]
    lines.extend(f"- [ ] {item}" for item in criteria)
    if not criteria:
        lines.append("- Nenhum critério registrado.")

    lines.extend(["", "## Ações explicitamente permitidas", ""])
    if allowed:
        lines.extend(f"- `{action}`" for action in allowed)
    else:
        lines.append("- Nenhuma. O handoff não recebeu permissões operacionais explícitas.")

    lines.extend(["", "## Ações não autorizadas implicitamente", ""])
    lines.extend(f"- `{action}`" for action in NEVER_IMPLICITLY_AUTHORIZED)

    lines.extend(["", "## Guardrails do Task Pack", ""])
    lines.extend(f"- {item}" for item in constraints)
    if not constraints:
        lines.append("- Nenhum guardrail registrado.")

    if areas:
        lines.extend(["", "## Áreas sugeridas", ""])
        lines.extend(f"- `{item}`" for item in areas)

    lines.extend(["", "## Contexto selecionado", ""])
    if context_items:
        for index, item in enumerate(context_items, start=1):
            title = item.get("title") or item.get("kind") or f"Item {index}"
            ref = sanitize_source_ref(item.get("source_ref"))
            suffix = f" — {ref}" if ref else ""
            lines.extend(
                [
                    f"### {index}. {title}",
                    "",
                    item.get("content") or "",
                    "",
                    f"Fonte: `{item.get('source_type') or 'unknown'}`{suffix}",
                    "",
                ]
            )
    else:
        lines.append("Nenhum item de contexto foi selecionado para este pack.")

    lines.extend(["", "## Fontes", ""])
    if sources:
        for source in sources:
            ref = source.get("source_ref")
            suffix = f" — {ref}" if ref else ""
            lines.append(f"- `{source.get('source_type') or 'unknown'}`{suffix}")
    else:
        lines.append("- Nenhuma fonte registrada.")

    lines.extend(
        [
            "",
            "## Orçamento do contexto entregue",
            "",
            f"- Tokens selecionados: {budget.get('estimated_tokens', 0)}",
            f"- Tokens candidatos: {budget.get('candidate_tokens', 0)}",
            f"- Limite: {budget.get('max_tokens', 0)}",
            "",
            "## Observações",
            "",
            handoff.notes or "Nenhuma.",
            "",
            "## Regra de execução",
            "",
            "`prepared` apenas prepara o envelope. `released` libera somente as ações listadas acima.",
            "Este handoff não executa ferramentas externas por si só e nunca autoriza merge, deploy ou publicação implicitamente.",
            "",
        ]
    )
    return "\n".join(lines)
