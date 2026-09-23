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
WorkerJob JSON v1
  ↓
ProcessWorkerClient
  ↓ processo separado da API
Worker Runtime
  ├── subprocess-sandbox
  └── container opcional
```

A autorização é separada por camada:

```text
Task Pack approved       = pronto para handoff
Handoff released         = ações listadas explicitamente foram liberadas
ExecutorRequest released = uma ação específica foi liberada para um adapter
Worker job               = execução técnica da ação já autorizada
Execution completed      = critérios de aceite possuem evidência explícita passed
```

Nenhuma dessas etapas autoriza implicitamente merge, deploy, publicação ou escrita em serviços externos.

## Marcos M1–M8.6

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
- **M8.6 — Worker Hardening:** processo de worker separado da API, workspace efêmero, limites de recurso auditáveis e backend de container com rede negada por padrão.

## Política de ações

Ações reconhecidas pelo sistema:

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

Continuam proibidos por padrão: merge, deploy, publicação, escrita em Drive/Calendar, escrita genérica em serviços externos e shell/comando arbitrário.

## Controlled Executor e adapter isolado

Um `ExecutorRequest` precisa estar na política global, na allowlist do handoff e vinculado a uma execução `running`. Depois ainda exige release explícito.

O adapter `manual` permanece inerte. O adapter `isolated-local` é **desabilitado por padrão** e só fica disponível com root privado de worktrees configurado.

`run_tests` é montado internamente como:

```text
<python-do-servidor> -m pytest -q <target-validado>
```

O cliente não escolhe binário, argv ou flags arbitrárias.

Veja `docs/CONTROLLED_EXECUTOR.md` e `docs/ISOLATED_EXECUTOR.md`.

## Worker Hardening — M8.6

O M8.6 move a execução técnica para um **processo de worker separado da API**. A comunicação usa `WorkerJob` JSON versionado; o worker recebe ambiente mínimo e não herda secrets por padrão.

Para `run_tests`, o worker:

1. valida root/worktree por path canônico;
2. rejeita symlink que escape do worktree;
3. cria cópia temporária por request;
4. executa o preset apenas nessa cópia;
5. aplica timeout e limites suportados;
6. trunca/redige stdout e stderr;
7. remove o workspace temporário ao final.

### Backend `subprocess-sandbox`

Aplica, em POSIX quando disponível:

- CPU (`RLIMIT_CPU`);
- memória (`RLIMIT_AS`);
- PIDs (`RLIMIT_NPROC`);
- arquivos abertos (`RLIMIT_NOFILE`);
- tamanho de arquivo (`RLIMIT_FSIZE`).

Ele **não isola rede**; isso aparece explicitamente no resultado como `network_policy=not_isolated_by_subprocess_backend`.

### Backend `container`

Opcional e administrado pelo servidor. O contrato monta o runtime com:

```text
--network none
--read-only
--cap-drop ALL
--security-opt no-new-privileges
--pids-limit ...
--memory ...
--cpus 1.0
--tmpfs /tmp:rw,noexec,nosuid
```

Somente a cópia temporária do worktree é montada em `/workspace`. O Docker socket nunca é montado.

Veja `docs/WORKER_HARDENING.md`.

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
git checkout codex/m8-6-worker-hardening
cp .env.example .env
docker compose up --build
```

Interface: `http://localhost:8000/app/`

OpenAPI: `http://localhost:8000/docs`

O executor real continua desligado até configuração explícita de `EXECUTOR_ISOLATED_ENABLED=true` e `EXECUTOR_WORKTREE_ROOT`.

## Próxima fronteira

Antes de escrita real em código/Git, ainda faltam contratos específicos e auditáveis para `modify_worktree`, `create_branch`, `create_commit` e `create_pull_request`, além de proveniência forte do worker e reconciliação de jobs órfãos. Merge, deploy e publicação continuam fora da política padrão.
