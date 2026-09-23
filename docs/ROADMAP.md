# Roadmap

## M0 — Fundação documental
Status: **concluído**.

## M1 — Memória operacional
Status: **concluído**.

FastAPI, PostgreSQL, Alembic, projetos, decisões, tarefas, resumos, snapshot, Docker e testes.

## M2 — Context Engine v1
Status: **concluído**.

Perfis `minimal`, `standard` e `deep`, ranking determinístico, deduplicação, compactação, orçamento de tokens, auditoria e `continue`.

## M3 — GitHub Connector
Status: **concluído**.

GitHub somente leitura, commits, PRs, Issues, Actions, eventos normalizados e sync idempotente.

## M4 — Session Memory
Status: **concluído**.

`SessionDelta`, preview, confirmação humana, aplicação transacional e descarte.

## M5 — Interface web
Status: **concluído**.

Dashboard responsivo, Health Score explicável, projetos, tarefas, fontes, eventos, painel de tokens e revisão visual dos deltas.

## M6 — Google Drive e Calendar
Status: **concluído**.

Drive/Calendar somente leitura, metadados persistidos sem copiar documentos completos, recuperação sob demanda, eventos normalizados e sync idempotente.

## M7 — Qualidade de recuperação

### M7.0 — benchmark de contexto
Status: **concluído na branch `codex/m7-retrieval-benchmark`**.

Baseline sintético v1: cenário de pressão `minimal` com 13.926 tokens candidatos → 1.794 selecionados, compressão 0,871176 e recall@2 de 1,0 no fixture.

### M7.1 — busca híbrida/semântica
Status: **condicional — não iniciado**.

Embeddings/pgvector somente se benchmark privado com consultas reais demonstrar ganho mensurável.

## M8 — Automação e agentes

### M8.0 — Agent Task Packs
Status: **concluído na branch `codex/m8-agent-task-packs`**.

### M8.1 — handoff assistido e auditável
Status: **concluído na branch `codex/m8-1-agent-handoffs`**.

### M8.2 — acompanhamento de execução e evidências
Status: **concluído na branch `codex/m8-2-execution-tracking`**.

### M8.3 — verificação externa GitHub somente leitura
Status: **concluído na branch `codex/m8-3-github-verification`**.

### M8.4 — executor controlado
Status: **concluído na branch `codex/m8-4-controlled-executor`**.

### M8.5 — adapter local isolado
Status: **concluído na branch `codex/m8-5-isolated-adapter`**.

Capacidades reais: `read_repository` somente metadata e `run_tests` somente preset server-side `pytest`.

### M8.6 — hardening do worker
Status: **concluído na branch `codex/m8-6-worker-hardening`**.

Entregas:
- `WorkerJob` JSON versionado (`schema_version=1`);
- `ProcessWorkerClient` separando a execução técnica do processo da API;
- `worker_entry` com fronteira de erro estruturada;
- backend `subprocess-sandbox` compatível com CI;
- backend `container` opcional;
- cópia temporária do worktree por request para `run_tests`;
- validação de symlinks antes da cópia;
- limpeza automática do workspace temporário;
- ambiente mínimo e sem secrets do processo pai;
- timeout interno + deadline externo do worker;
- limites POSIX quando suportados: CPU, memória, PIDs, NOFILE e FSIZE;
- stdout/stderr limitados e redigidos;
- resultado com backend, motivo de terminação, limites efetivos e não suportados;
- backend subprocess registra explicitamente ausência de isolamento de rede;
- contrato de container com `--network none`, `--read-only`, `--cap-drop ALL`, `no-new-privileges`, limites de PIDs/memória/CPU e tmpfs restrito;
- Docker socket nunca é montado;
- ações de escrita continuam `unsupported`;
- testes de processo separado, workspace efêmero, não herança de secrets, symlink escape e política de container;
- documentação `docs/WORKER_HARDENING.md`.

Continuam sem implementação real:
- `modify_worktree`;
- `create_branch`;
- `create_commit`;
- `create_pull_request`.

Continuam proibidos por padrão:
- merge;
- deploy;
- publicação;
- escrita em Drive/Calendar;
- escrita genérica em serviços externos;
- shell/comando/binário/argv arbitrário.

### M8.7 — proveniência e reconciliação do worker
Status: **futuro/condicional**.

Antes de escrita real em código/Git, adicionar:
- imagem de worker pinada por digest;
- identidade/proveniência do executor;
- assinatura ou attestation do resultado;
- fila persistente/broker ou protocolo equivalente;
- lease/heartbeat de jobs;
- reconciliação de jobs órfãos;
- política de egress testável;
- quota de disco/IO quando suportada;
- inventário e retenção de artefatos;
- política de limpeza/retry idempotente.

Somente depois considerar contratos reais separados para `modify_worktree`, `create_branch`, `create_commit` e `create_pull_request`.

## Regra de evolução

Não ampliar autonomia antes de existir:
1. fonte de verdade;
2. modelo de dados;
3. rastreabilidade;
4. métrica de contexto;
5. autorização humana explícita;
6. evidência verificável;
7. política específica por efeito;
8. isolamento e limites de recurso;
9. worker separado e auditável;
10. proveniência/reconciliação antes de escrita Git real.
