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
        ↓ adapter
manual (inerte) | isolated-local (M8.5)
        ↓
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

## Marcos M1–M8.5

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
- **M8.4 — Controlled Executor:** request de ação, release específico, política global, anti-replay e adapter injetável.
- **M8.5 — Isolated Local Adapter:** execução real limitada de `run_tests` e leitura de metadados dentro de worktree restrito.

## Agent Task Packs e Handoffs

Um `AgentTaskPack` aprovado está pronto para originar handoff, mas não autoriza execução. Um handoff só libera as ações listadas explicitamente.

Ações reconhecidas pela política atual:

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

Veja `docs/AGENT_TASK_PACKS.md` e `docs/AGENT_HANDOFFS.md`.

## Agent Executions e verificação

Uma execução rastreada só nasce de handoff `released`. Progresso, referências técnicas, verificações e evidências são registrados em `AgentExecutionEvent` append-only.

A conclusão é bloqueada enquanto qualquer critério estiver `pending` ou `failed`.

O M8.3 verifica commit, PR e check-runs em modo somente leitura. `verified` confirma identidade/proveniência; não significa automaticamente que um critério passou.

Veja `docs/AGENT_EXECUTIONS.md` e `docs/GITHUB_VERIFICATION.md`.

## Controlled Executor

O M8.4 introduz `ExecutorRequest`:

```text
prepared
   ├── cancel → cancelled
   └── release → released
                    └── execute → running
                                     ├── completed
                                     └── failed
```

A ação precisa pertencer à política global, estar na allowlist do handoff e apontar para uma execução `running`.

O executor rejeita payloads com shell/comando arbitrário, incluindo chaves como `command`, `cmd`, `shell`, `script`, `argv` e `executable`.

O adapter `manual` permanece inerte.

Veja `docs/CONTROLLED_EXECUTOR.md`.

## Isolated Local Adapter — M8.5

O adapter `isolated-local` é **desabilitado por padrão** e só fica disponível quando um root privado de worktrees é configurado.

Capacidades reais atuais:

```text
read_repository   → apenas scope=metadata
run_tests         → apenas preset server-side pytest
```

`run_tests` é montado internamente como:

```text
<python-do-servidor> -m pytest -q <target-validado>
```

O cliente não escolhe binário, argv ou flags arbitrárias.

Proteções do M8.5:

- caminhos relativos e resolução canônica;
- bloqueio de `..` e symlink escape;
- `cwd` sempre dentro do root permitido;
- `shell=False`;
- `stdin=DEVNULL`;
- ambiente mínimo com allowlist de variáveis não sensíveis;
- timeout com encerramento de processo/grupo quando suportado;
- limite do volume persistido de stdout/stderr;
- redaction antes da persistência;
- ações sem contrato retornam `unsupported` sem efeito externo.

As ações `modify_worktree`, `create_branch`, `create_commit` e `create_pull_request` **ainda não possuem implementação real** nesse adapter.

Veja `docs/ISOLATED_EXECUTOR.md`.

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

Payloads estruturados e saídas do executor passam por redaction antes da persistência.

## Executar

```bash
git clone https://github.com/douglassnake/douglassnake-super-chat.git
cd douglassnake-super-chat
git checkout codex/m8-5-isolated-adapter
cp .env.example .env
docker compose up --build
```

Interface: `http://localhost:8000/app/`

OpenAPI: `http://localhost:8000/docs`

O adapter `isolated-local` continua desligado até configuração explícita de `EXECUTOR_ISOLATED_ENABLED=true` e `EXECUTOR_WORKTREE_ROOT`.

## Próxima etapa

O passo seguinte deve endurecer a execução antes de adicionar novas escritas: isolamento por container/cgroup ou worker dedicado, limites fortes de CPU/memória/processos e política de artefatos. Só depois faz sentido considerar contratos reais para modificar worktree, criar branch, commit ou PR.

Merge, deploy e publicação continuam fora da política padrão.
