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
- processo de worker separado da API;
- backend `subprocess-sandbox` e contrato `container` opcional;
- cópia temporária do worktree para testes;
- limites de CPU, memória, PIDs, NOFILE e FSIZE quando suportados;
- ambiente mínimo sem secrets;
- timeout interno + deadline externo;
- stdout/stderr limitados e redigidos;
- `--network none`, filesystem read-only, cap-drop e no-new-privileges no contrato container;
- nenhum Docker socket;
- ações de escrita permanecem `unsupported`.

### M8.7 — proveniência e reconciliação do worker
Status: **concluído na branch `codex/m8-7-worker-provenance` após CI final verde**.

Entregas:
- migration `0007_worker_attempts`;
- `WorkerAttempt` persistente com tentativas numeradas;
- identidade de worker, PID e fingerprint de host;
- `job_digest` e `result_digest` SHA-256;
- validação dos digests pela API antes de aceitar resultado;
- lease com token aleatório e somente hash persistido;
- heartbeat autenticado;
- reconciliação de leases `expired/orphaned`;
- request em execução fica `failed` quando sua tentativa órfã é reconciliada;
- retry explícito separado de replay;
- retry cria nova tentativa e preserva tentativa terminal anterior;
- máximo de tentativas definido server-side;
- eventos append-only de lease, início, resultado, órfão e retry;
- documentação `docs/WORKER_PROVENANCE.md`;
- imagem container deve ser pinada por digest antes de qualquer capacidade futura de escrita.

Continuam sem implementação real:
- `modify_worktree`;
- `create_branch`;
- `create_commit`;
- `create_pull_request`.

Continuam proibidos:
- merge;
- deploy;
- publicação;
- escrita em Drive/Calendar;
- escrita externa genérica;
- shell/comando/binário/argv arbitrário.

### M8.8 — preparação para escrita Git controlada
Status: **futuro/condicional**.

Antes de habilitar qualquer escrita real:
- imagem/container pinado por digest e verificado;
- identidade Git exclusiva do executor;
- worktree efêmero dedicado por tentativa;
- patch/diff como artefato antes de persistir mudanças;
- política de path allowlist/denylist por projeto;
- limite de quantidade/tamanho de arquivos modificados;
- proibição explícita de secrets, `.env`, chaves e arquivos fora do projeto;
- `modify_worktree` separado de `create_branch` e `create_commit`;
- aprovação humana entre diff gerado e persistência Git;
- `create_pull_request` em etapa separada;
- merge, deploy e publish continuam fora.

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
10. proveniência/reconciliação;
11. diff revisável antes de escrita Git real.
