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
Controlled Executor
ExecutorRequest prepared
        ↓ release explícito
released
        ↓ adapter explicitamente configurado
running → completed | failed
```

A autorização é separada por camada:

```text
Task Pack approved       = pronto para handoff
Handoff released         = ações listadas explicitamente foram liberadas
ExecutorRequest released = uma ação específica foi liberada para um adapter
Execution completed      = critérios de aceite possuem evidência explícita passed
```

Nenhuma dessas etapas autoriza implicitamente merge, deploy, publicação ou escrita em serviços externos.

## Marcos M1–M8.4

- **M1 — Memória operacional:** projetos, decisões, tarefas, resumos, PostgreSQL, Alembic e Docker.
- **M2 — Context Engine:** ranking, deduplicação, compactação, orçamento de tokens e `continue`.
- **M3 — GitHub Connector:** commits, PRs, Issues e Actions em modo somente leitura.
- **M4 — Session Memory:** `SessionDelta` revisável e aplicação após confirmação.
- **M5 — Interface Web:** dashboard, Health Score, contexto/tokens e revisão visual dos deltas.
- **M6 — Google Context:** Drive sob demanda + Calendar normalizado em eventos.
- **M7.0 — Retrieval Benchmark:** precision/recall, cobertura, compressão, latência e baseline reproduzível.
- **M8.0 — Agent Task Packs:** objetivo, critérios de aceite, guardrails, contexto, fontes e fingerprint.
- **M8.1 — Agent Handoffs:** executor/alvo, allowlist de ações, release explícito e trilha de auditoria.
- **M8.2 — Agent Executions:** progresso, referências observadas, eventos append-only e gate de evidências.
- **M8.3 — GitHub Verification:** commit/PR/check-runs verificados por leitura e evidência de CI somente por regra explícita.
- **M8.4 — Controlled Executor:** request de ação, release específico, política global, anti-replay e adapter injetável; o adapter padrão continua inerte.

## Agent Task Packs

Um `AgentTaskPack` aprovado está pronto para originar handoff, mas não autoriza execução. Critérios de aceite são explícitos e obrigatórios; o sistema não os inventa.

Veja `docs/AGENT_TASK_PACKS.md`.

## Agent Handoffs

Um handoff só nasce de pack `approved`. Ações reconhecidas:

```text
read_context
read_repository
modify_worktree
run_tests
create_branch
create_commit
create_pull_request
```

Merge, deploy, publicação e escrita em serviços externos nunca são implicitamente autorizados.

Veja `docs/AGENT_HANDOFFS.md`.

## Agent Executions

Uma execução rastreada só nasce de handoff `released`. Progresso, referências técnicas, verificações e evidências são registrados em `AgentExecutionEvent` append-only.

A conclusão é bloqueada enquanto qualquer critério estiver `pending` ou `failed`.

Veja `docs/AGENT_EXECUTIONS.md`.

## GitHub Verification

O M8.3 verifica commit, PR e check-runs em modo somente leitura. O repositório é derivado de uma fonte GitHub ativa do projeto.

`verified` confirma identidade/proveniência; não significa que um critério passou. A regra `checks_green` só gera evidência `passed` quando o solicitante informa explicitamente o `criterion_index`.

Veja `docs/GITHUB_VERIFICATION.md`.

## Controlled Executor

O M8.4 adiciona `ExecutorRequest` como unidade explícita de autorização operacional:

```text
prepared
   ├── cancel → cancelled
   └── release → released
                    └── execute → running
                                     ├── completed
                                     └── failed
```

Para uma request ser criada, a ação precisa:

1. pertencer à política global do executor;
2. estar na allowlist do handoff;
3. estar vinculada a uma execução `running` e handoff `released`.

O executor **não oferece shell arbitrário**. Payloads com chaves como `command`, `cmd`, `shell`, `script`, `argv` ou `executable` são rejeitados, inclusive de forma aninhada.

O adapter padrão `manual` tem `available = false`: ele registra autorização e auditoria, mas não executa processos externos. Testes usam adapters fake injetados.

Um request concluído não produz automaticamente `criterion_evidence` e não conclui o `AgentExecution`.

Veja `docs/CONTROLLED_EXECUTOR.md`.

## Recuperação e economia de tokens

No baseline sintético M7.0, o cenário de pressão `minimal` produziu:

```text
13.926 tokens candidatos
 1.794 tokens selecionados
87,12% de compressão aproximada
recall@2 = 1,0 no fixture
```

Esse resultado valida o mecanismo de budget em fixture sintético; não é garantia de desempenho em dados reais.

```bash
python scripts/context_benchmark.py benchmarks/context_cases.json
```

A busca semântica/pgvector do M7.1 continua condicionada a benchmark privado com consultas reais.

## Redaction e privacidade

O repositório é público. Memória real, `.env`, credenciais, conversas, dumps do banco e documentos privados não devem ser versionados.

Payloads estruturados também passam por redaction de chaves sensíveis como `token`, `secret`, `password`, `access_token`, `refresh_token`, `api_key` e `authorization`.

## Executar

```bash
git clone https://github.com/douglassnake/douglassnake-super-chat.git
cd douglassnake-super-chat
git checkout codex/m8-4-controlled-executor
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

POST   /agent-task-packs
POST   /agent-task-packs/{pack_id}/approve
POST   /agent-task-packs/{pack_id}/handoffs
POST   /agent-handoffs/{handoff_id}/release
POST   /agent-handoffs/{handoff_id}/execution

GET    /agent-executions/{execution_id}
GET    /agent-executions/{execution_id}/events
POST   /agent-executions/{execution_id}/progress
POST   /agent-executions/{execution_id}/technical-refs
POST   /agent-executions/{execution_id}/evidence
POST   /agent-executions/{execution_id}/verify-github
POST   /agent-executions/{execution_id}/complete
POST   /agent-executions/{execution_id}/fail
POST   /agent-executions/{execution_id}/cancel

POST   /agent-executions/{execution_id}/executor-requests
GET    /agent-executions/{execution_id}/executor-requests
GET    /executor-requests/{request_id}
POST   /executor-requests/{request_id}/release
POST   /executor-requests/{request_id}/execute
POST   /executor-requests/{request_id}/cancel
```

## Próxima etapa

Um **M8.5 — adapter real isolado** pode ser considerado apenas com política por ação, worker isolado, diretório de trabalho restrito, timeout, limites de recurso e auditoria de artefatos. Merge, deploy e publicação permanecem fora da autorização padrão.
