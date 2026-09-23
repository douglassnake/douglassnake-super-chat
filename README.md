# Douglas Snake — Super Chat

O **Super Chat** é a interface operacional do **Segundo Cérebro**: memória persistente, continuidade de projetos, recuperação seletiva de contexto e preparação/auditoria segura de trabalho para agentes.

## Arquitetura atual

```text
Usuário
  ↓
Web / API
  ↓
Projeto
  ├── memória operacional (PostgreSQL)
  ├── Session Memory
  ├── GitHub (leitura)
  ├── Google Drive (leitura sob demanda)
  └── Google Calendar (leitura)
        ↓
Context Engine
  ├── minimal   1.800 tokens
  ├── standard  5.000 tokens
  └── deep     15.000 tokens
        ↓
Agent Task Pack
pending → aprovação humana → approved
        ↓
Agent Handoff
prepared → release explícito → released
        ↓
Agent Execution
running
  ├── progresso
  ├── referências técnicas
  ├── evidências por critério
  ├── verificação GitHub somente leitura
  └── log append-only
        ↓
completed | failed | cancelled
```

A autorização é separada por camada:

```text
Task Pack approved  = pronto para handoff
Handoff released    = ações listadas explicitamente foram liberadas
Execution completed = critérios de aceite possuem evidência explícita passed
```

Nenhuma dessas etapas autoriza implicitamente merge, deploy, publicação ou escrita em serviços externos.

## Marcos M1–M8.3

- **M1 — Memória operacional:** projetos, decisões, tarefas, resumos, PostgreSQL, Alembic e Docker.
- **M2 — Context Engine:** ranking, deduplicação, compactação, orçamento de tokens e `continue`.
- **M3 — GitHub Connector:** commits, PRs, Issues e Actions em modo somente leitura.
- **M4 — Session Memory:** `SessionDelta` revisável e aplicação após confirmação.
- **M5 — Interface Web:** dashboard, Health Score, contexto/tokens e revisão visual dos deltas.
- **M6 — Google Context:** Drive sob demanda + Calendar normalizado em eventos.
- **M7.0 — Retrieval Benchmark:** precision/recall, cobertura, compressão, latência e baseline reproduzível.
- **M8.0 — Agent Task Packs:** objetivo, critérios de aceite, guardrails, contexto, fontes e fingerprint.
- **M8.1 — Agent Handoffs:** executor/alvo, allowlist de ações, release explícito e trilha de auditoria.
- **M8.2 — Agent Executions:** progresso, referências observadas, eventos append-only e gate de evidências por critério.
- **M8.3 — GitHub Verification:** commit/PR/check-runs verificados por leitura e evidência de CI somente por regra explícita.

## Agent Task Packs

Um `AgentTaskPack` aprovado está pronto para originar handoff, mas permanece:

```text
ready_for_handoff = true
authorized_for_execution = false
```

Critérios de aceite são explícitos e obrigatórios; o sistema não os inventa. O pack preserva contexto selecionado, fontes, budget e fingerprint SHA-256.

Veja `docs/AGENT_TASK_PACKS.md`.

## Agent Handoffs

Um handoff só nasce de pack `approved`. Ações reconhecidas pelo M8.1:

```text
read_context
read_repository
modify_worktree
run_tests
create_branch
create_commit
create_pull_request
```

Ações como `merge`, `deploy`, `publish`, `write_drive`, `write_calendar` e escrita genérica em serviço externo nunca são implicitamente autorizadas.

Veja `docs/AGENT_HANDOFFS.md`.

## Agent Executions

Uma execução rastreada só pode nascer de um handoff `released` e existe no máximo uma por handoff.

O estado atual guarda progresso, etapa e referências observadas de branch/commit/PR. Essas referências são apenas metadados: os endpoints do M8.2 não criam nem modificam recursos externos.

Cada alteração relevante gera um `AgentExecutionEvent` append-only com sequência crescente:

```text
started
progress
technical_refs
criterion_evidence
external_verification
status
```

Evidências apontam para um índice real de critério do Task Pack e informam explicitamente `passed` ou `failed`. A evidência de maior sequência determina o estado atual daquele critério.

A conclusão é bloqueada enquanto qualquer critério estiver `pending` ou `failed`:

```json
{
  "total": 2,
  "passed": 2,
  "failed": 0,
  "pending": 0,
  "complete_allowed": true
}
```

Quando existe execução rastreada, os endpoints diretos de `complete/fail/cancel` do handoff são bloqueados para impedir bypass do gate de evidências.

Veja `docs/AGENT_EXECUTIONS.md`.

## GitHub Verification

O M8.3 verifica referências já registradas em uma execução sem aceitar um repositório arbitrário do cliente. O repositório precisa existir como fonte GitHub ativa do projeto.

Leituras pontuais adicionadas ao conector:

```text
GET /repos/{repository}/commits/{sha}
GET /repos/{repository}/pulls/{number}
GET /repos/{repository}/commits/{sha}/check-runs
```

Resultados normalizados:

```text
verified
mismatch
not_found
unavailable
```

`verified` confirma a identidade/proveniência da referência; não significa automaticamente que um critério passou.

A condição de CI é separada:

```text
checks_green =
  pelo menos um check
  AND todos completed
  AND todos conclusion = success
```

Uma chamada sem regra explícita registra apenas `external_verification`. Para converter checks verdes em evidência é necessário mapear explicitamente o critério:

```json
{
  "criterion_index": 0,
  "evidence_rule": "checks_green"
}
```

Checks pendentes ou com qualquer conclusão diferente de `success` nunca produzem evidência `passed` por essa regra.

Veja `docs/GITHUB_VERIFICATION.md`.

## Recuperação e economia de tokens

No baseline sintético M7.0, o cenário de pressão do perfil `minimal` produziu:

```text
13.926 tokens candidatos
 1.794 tokens selecionados
87,12% de compressão aproximada
recall@2 = 1,0 no fixture
```

O resultado valida o mecanismo de budget em fixture sintético; não é garantia de desempenho em dados reais.

```bash
python scripts/context_benchmark.py benchmarks/context_cases.json
```

A busca semântica/pgvector do M7.1 continua condicionada a benchmark privado com consultas reais.

## Redaction e privacidade

O repositório é público. Memória real, `.env`, credenciais, conversas, dumps do banco e documentos privados não devem ser versionados.

A barreira de redaction cobre padrões textuais e também chaves sensíveis em JSON estruturado, como `token`, `secret`, `password`, `access_token`, `refresh_token`, `api_key` e `authorization`.

Redaction é defesa adicional, não autorização para inserir secrets no sistema.

## Executar

```bash
git clone https://github.com/douglassnake/douglassnake-super-chat.git
cd douglassnake-super-chat
git checkout codex/m8-3-github-verification
cp .env.example .env
docker compose up --build
```

Interface: `http://localhost:8000/app/`

OpenAPI: `http://localhost:8000/docs`

## Endpoints centrais

```text
GET    /dashboard
GET    /projects/{project_id}/overview
GET    /projects/{project_id}/snapshot
GET    /projects/{project_id}/continue
POST   /context/build
POST   /evaluation/context

POST   /projects/{project_id}/github/sync
POST   /projects/{project_id}/google/sync

POST   /projects/{project_id}/session-deltas
GET    /session-deltas/{delta_id}/preview
POST   /session-deltas/{delta_id}/apply
POST   /session-deltas/{delta_id}/discard

POST   /agent-task-packs/preview
POST   /agent-task-packs
POST   /agent-task-packs/{pack_id}/approve
GET    /agent-task-packs/{pack_id}/markdown

POST   /agent-task-packs/{pack_id}/handoffs
POST   /agent-handoffs/{handoff_id}/release
GET    /agent-handoffs/{handoff_id}/markdown

POST   /agent-handoffs/{handoff_id}/execution
GET    /agent-handoffs/{handoff_id}/execution
GET    /agent-executions/{execution_id}
GET    /agent-executions/{execution_id}/events
POST   /agent-executions/{execution_id}/progress
POST   /agent-executions/{execution_id}/technical-refs
POST   /agent-executions/{execution_id}/evidence
POST   /agent-executions/{execution_id}/verify-github
POST   /agent-executions/{execution_id}/complete
POST   /agent-executions/{execution_id}/fail
POST   /agent-executions/{execution_id}/cancel
```

## Próxima etapa

O **M8.4 — executor controlado** permanece futuro e condicional. Antes de qualquer capacidade de escrita real, cada ação precisará de política própria, auditoria do efeito produzido e autorização separada. Merge, deploy e publicação continuam fora da autorização implícita do sistema.
