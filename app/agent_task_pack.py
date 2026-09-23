from __future__ import annotations

import hashlib
import json
import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from app.google_context import build_context_with_google
from app.models import Project


DEFAULT_GUARDRAILS = [
    "Não fazer merge, deploy ou publicação sem aprovação explícita.",
    "Não expor, copiar ou persistir credenciais, tokens, senhas ou secrets.",
    "Não escrever em serviços externos fora do escopo explicitamente autorizado.",
    "Preservar rastreabilidade: citar a fonte quando uma decisão depender do contexto recuperado.",
    "Se um critério de aceite for ambíguo ou impossível de verificar, sinalizar a lacuna em vez de inventar um requisito.",
]

_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(password|passwd|secret|client_secret|refresh_token|access_token|api[_-]?key|token|authorization)\b"
    r"\s*([:=])\s*([^\s,;]+)"
)
_BEARER = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+\-/=]{8,}")
_KNOWN_TOKEN = re.compile(
    r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{20,})\b"
)
_SENSITIVE_QUERY_KEYS = {
    "token",
    "access_token",
    "refresh_token",
    "secret",
    "client_secret",
    "api_key",
    "apikey",
    "key",
    "signature",
    "sig",
}


def redact_secrets(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value)
    text = _SECRET_ASSIGNMENT.sub(lambda match: f"{match.group(1)}{match.group(2)}[REDACTED]", text)
    text = _BEARER.sub("Bearer [REDACTED]", text)
    text = _KNOWN_TOKEN.sub("[REDACTED]", text)
    return text


def sanitize_source_ref(value: str | None) -> str | None:
    redacted = redact_secrets(value)
    if not redacted:
        return redacted
    try:
        parsed = urlsplit(redacted)
    except ValueError:
        return redacted
    if parsed.scheme not in {"http", "https"}:
        return redacted
    query = []
    for key, item_value in parse_qsl(parsed.query, keep_blank_values=True):
        if key.lower() in _SENSITIVE_QUERY_KEYS:
            query.append((key, "[REDACTED]"))
        else:
            query.append((key, item_value))
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment))


def clean_list(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for raw in values:
        value = (redact_secrets(raw) or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def build_agent_task_pack(
    db,
    project: Project,
    *,
    objective: str,
    acceptance_criteria: list[str],
    constraints: list[str] | None = None,
    suggested_areas: list[str] | None = None,
    profile: str = "standard",
    query: str | None = None,
) -> dict[str, Any]:
    clean_objective = (redact_secrets(objective) or "").strip()
    criteria = clean_list(acceptance_criteria)
    if not criteria:
        raise ValueError("At least one explicit acceptance criterion is required")

    user_constraints = clean_list(constraints or [])
    guardrails = clean_list([*DEFAULT_GUARDRAILS, *user_constraints])
    areas = clean_list(suggested_areas or [])
    clean_query = (redact_secrets(query) or "").strip() if query else ""
    if not clean_query:
        clean_query = " ".join([clean_objective, *criteria])[:4000]

    package = build_context_with_google(db, project, clean_query, profile)
    context_items = [
        {
            "kind": item.get("kind"),
            "title": redact_secrets(item.get("title")),
            "content": redact_secrets(item.get("content")),
            "source_type": item.get("source_type"),
            "source_ref": sanitize_source_ref(item.get("source_ref")),
            "score": item.get("score"),
            "estimated_tokens": item.get("estimated_tokens"),
        }
        for item in package.get("items", [])
    ]
    sources = _unique_sources(
        [
            {
                "source_type": source.get("source_type"),
                "source_ref": sanitize_source_ref(source.get("source_ref")),
            }
            for source in package.get("sources", [])
        ]
    )
    budget = {
        key: int(value) if isinstance(value, (int, float)) else value
        for key, value in (package.get("budget") or {}).items()
    }

    content = {
        "project": {
            "id": str(project.id),
            "slug": project.slug,
            "name": redact_secrets(project.name),
            "status": project.status,
            "next_action": redact_secrets(project.next_action),
        },
        "objective": clean_objective,
        "profile": profile,
        "query": clean_query,
        "acceptance_criteria": criteria,
        "constraints": guardrails,
        "suggested_areas": areas,
        "context": context_items,
        "sources": sources,
        "budget": budget,
    }
    content["fingerprint"] = fingerprint_pack(content)
    return content


def fingerprint_pack(content: dict[str, Any]) -> str:
    stable = {
        **content,
        "context": [
            {key: value for key, value in item.items() if key != "score"}
            for item in content.get("context", [])
        ],
    }
    canonical = json.dumps(stable, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def render_task_pack_markdown(pack: dict[str, Any], *, status: str) -> str:
    project = pack["project"]
    lines = [
        "# Agent Task Pack",
        "",
        f"**Fingerprint:** `{pack['fingerprint']}`",
        f"**Status:** `{status}`",
        f"**Projeto:** {project['name']} (`{project['slug']}`)",
        f"**Estado atual:** `{project['status']}`",
        f"**Perfil de contexto:** `{pack['profile']}`",
        "",
        "## Objetivo",
        "",
        pack["objective"],
        "",
        "## Próxima ação registrada",
        "",
        project.get("next_action") or "Não definida.",
        "",
        "## Critérios de aceite",
        "",
    ]
    lines.extend(f"- [ ] {item}" for item in pack["acceptance_criteria"])
    lines.extend(["", "## Restrições / guardrails", ""])
    lines.extend(f"- {item}" for item in pack["constraints"])

    if pack["suggested_areas"]:
        lines.extend(["", "## Áreas/arquivos sugeridos pelo solicitante", ""])
        lines.extend(f"- `{item}`" for item in pack["suggested_areas"])

    lines.extend(["", "## Contexto selecionado", ""])
    for index, item in enumerate(pack["context"], start=1):
        title = item.get("title") or item.get("kind") or f"Item {index}"
        lines.extend(
            [
                f"### {index}. {title}",
                "",
                item.get("content") or "",
                "",
                f"Fonte: `{item.get('source_type') or 'unknown'}`"
                + (f" — {item['source_ref']}" if item.get("source_ref") else ""),
                "",
            ]
        )

    budget = pack["budget"]
    lines.extend(
        [
            "## Orçamento de contexto",
            "",
            f"- Perfil: `{pack['profile']}`",
            f"- Tokens selecionados: {budget.get('estimated_tokens', 0)}",
            f"- Tokens candidatos: {budget.get('candidate_tokens', 0)}",
            f"- Limite: {budget.get('max_tokens', 0)}",
            "",
            "## Autorização",
            "",
            "Este pacote descreve trabalho. Ele não autoriza merge, deploy, publicação ou escrita externa por si só.",
            "",
        ]
    )
    return "\n".join(lines)


def _unique_sources(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[tuple[Any, Any]] = set()
    for source in sources:
        key = (source.get("source_type"), source.get("source_ref"))
        if key in seen:
            continue
        seen.add(key)
        result.append(source)
    return result
