# Douglas Snake — Super Chat

O **Super Chat** é a interface operacional do **Segundo Cérebro**: memória persistente, continuidade de projetos, recuperação seletiva de contexto e preparação/auditoria segura de trabalho para agentes.

## Arquitetura atual

```text
Usuário
  ↓
Web / API
  ↓
Projeto + memória operacional
  ↓
Context Engine
  ↓
Agent Task Pack
  ↓ aprovação humana
Agent Handoff
  ↓ release explícito
Agent Execution
  ↓
Controlled Executor
  ↓ release por ação
Isolated Local Adapter
  ↓
WorkerAttempt
leased → running → completed | failed
  ↓
WorkerJob JSON v1
  ↓
ProcessWorkerClient
  ↓ processo separado da API
Worker Runtime
  ├── subprocess-sandbox
  └── container opcional
  ↓
Proveniência
worker_id + job_digest + result_digest
```

A autorização é separada por camada:

```text
Task Pack approved       = pronto para handoff
Handoff released         = ações listadas explicitamente foram liberadas
ExecutorRequest released = uma ação específica foi liberada para um adapter
WorkerAttempt             = tentativa auditável com lease/retry
Execution completed      = critérios de aceite possuem evidência explícita passed
```

Nenhuma dessas etapas autoriza implicitamente merge, deploy, publicação ou escrita em serviços externos.

## Marcos M1–M8.7

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
- **M8.6 — Worker Hardening:** worker separado da API, workspace efêmero, limites de recurso e container com rede negada por padrão.
- **M8.7 — Worker Provenance & Reconciliation:** identidade do worker, digests, leases, heartbeat, reconciliação de órfãos e retry controlado.

## Política de ações

Ações reconhecidas:

```text
read_context
read_repository
modify_worktree
run_tests
create_branch
create_commit
create_pull_request
```

Capacidades **reais** atualmente implementadas:

```text
read_repository → somente metadata
run_tests       → somente preset server-side pytest
```

Ainda sem efeito real:

```text
modify_worktree
create_branch
create_commit
create_pull_request
```

Continuam proibidos: merge, deploy, publicação, escrita em Drive/Calendar, escrita genérica em serviços externos e shell/comando arbitrário.

## Controlled Executor e Worker Hardening

Um `ExecutorRequest` precisa estar na política global, na allowlist do handoff e vinculado a uma execução `running`. Depois ainda exige release explícito.

O adapter `manual` permanece inerte. O adapter `isolated-local` é **desabilitado por padrão** e só fica disponível com root privado de worktrees configurado.

Para `run_tests`, o worker recebe apenas um contrato semântico e monta internamente o preset `pytest`; o cliente não escolhe shell, executável ou argv arbitrário.

O M8.6 executa testes em **cópia temporária do worktree**, com processo separado da API, ambiente mínimo, timeout, truncamento/redaction de saída e limites de CPU/memória/PIDs/NOFILE/FSIZE quando suportados.

No backend `container`, o contrato inclui:

```text
--network none
--read-only
--cap-drop ALL
--security-opt no-new-privileges
--pids-limit ...
--memory ...
--cpus 1.0
```

O Docker socket nunca é montado.

Veja `docs/CONTROLLED_EXECUTOR.md`, `docs/ISOLATED_EXECUTOR.md` e `docs/WORKER_HARDENING.md`.

## Worker Provenance & Reconciliation — M8.7

Cada execução `isolated-local` passa a possuir um `WorkerAttempt` persistente e numerado.

```text
leased → running → completed | failed
   |          |
   |          └→ orphaned
   └→ expired
```

O processo do worker devolve um envelope de proveniência com:

- `worker_id`;
- PID;
- fingerprint não reversível do host;
- backend e schema do job;
- `job_digest` SHA-256;
- `result_digest` SHA-256;
- timestamps de início e fim.

A API recalcula `job_digest` e `result_digest` antes de aceitar o resultado. Isso fornece verificação de integridade do transporte/processo; **não é uma assinatura criptográfica com chave privada**.

### Lease e heartbeat

Uma tentativa possui lease e heartbeat. O token bruto é devolvido somente uma vez; no banco fica apenas seu SHA-256. A lease efetiva nunca é menor que o maior timeout permitido mais uma margem operacional, evitando reconciliação prematura de uma execução síncrona válida.

### Reconciliação

`POST /worker-attempts/reconcile` transforma leases vencidas em `expired` ou `orphaned`, registra evento auditável e nunca inventa sucesso.

### Retry

Retry não é replay. `POST /executor-requests/{id}/retry` só funciona após falha, respeita limite server-side e cria uma **nova** tentativa na próxima execução. As tentativas anteriores permanecem imutáveis para auditoria.

Veja `docs/WORKER_PROVENANCE.md`.

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

## Privacidade

O repositório é público. Memória real, `.env`, credenciais, conversas, dumps do banco e documentos privados não devem ser versionados. Payloads estruturados e saídas do executor passam por redaction antes da persistência.

## Executar

```bash
git clone https://github.com/douglassnake/douglassnake-super-chat.git
cd douglassnake-super-chat
git checkout codex/m8-7-worker-provenance
cp .env.example .env
docker compose up --build
```

Interface: `http://localhost:8000/app/`

OpenAPI: `http://localhost:8000/docs`

O executor real continua desligado até configuração explícita de `EXECUTOR_ISOLATED_ENABLED=true` e `EXECUTOR_WORKTREE_ROOT`.

## Próxima fronteira

O próximo marco é o **M8.8 — preparação para escrita Git controlada**. Antes de habilitar `modify_worktree`, `create_branch`, `create_commit` ou `create_pull_request`, o sistema deve produzir diff/patch revisável, aplicar allowlist/denylist de paths, limitar quantidade/tamanho de mudanças, usar identidade Git exclusiva e exigir nova aprovação humana antes de persistir alterações.

Merge, deploy e publicação continuam fora da política padrão.
