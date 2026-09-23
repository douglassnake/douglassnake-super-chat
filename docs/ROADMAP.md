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

Entregas:
- `precision@k`, `recall@k` e cobertura;
- eficiência/compressão de tokens;
- latência;
- endpoint de avaliação;
- dataset sintético;
- runner CLI e CI.

Baseline sintético v1: cenário de pressão `minimal` com 13.926 tokens candidatos → 1.794 selecionados, compressão 0,871176 e recall@2 de 1,0 no fixture.

### M7.1 — busca híbrida/semântica
Status: **condicional — não iniciado**.

Embeddings/pgvector somente se benchmark privado com consultas reais demonstrar ganho mensurável que compense custo, latência e complexidade.

## M8 — Automação e agentes

### M8.0 — Agent Task Packs
Status: **concluído na branch `codex/m8-agent-task-packs`**.

`AgentTaskPack` persistente, objetivo, critérios de aceite explícitos, guardrails, contexto, fontes, budget, fingerprint, preview, aprovação humana, testes e documentação.

### M8.1 — handoff assistido e auditável
Status: **concluído na branch `codex/m8-1-agent-handoffs`**.

`AgentHandoff` persistente, allowlist explícita, fingerprint congelado, release separado, resultado/falha estruturados, Markdown auditável, testes e documentação.

### M8.2 — acompanhamento de execução e evidências
Status: **concluído na branch `codex/m8-2-execution-tracking`**.

`AgentExecution`, eventos append-only, progresso, referências técnicas, evidência por critério e gate de conclusão.

### M8.3 — verificação externa GitHub somente leitura
Status: **concluído na branch `codex/m8-3-github-verification`**.

Commit, PR e check-runs somente leitura, proveniência, estados normalizados, `external_verification` e regra explícita `checks_green`.

### M8.4 — executor controlado
Status: **concluído na branch `codex/m8-4-controlled-executor`**.

`ExecutorRequest`, migration `0006_executor_requests`, política global + allowlist de handoff, release específico, adapter interface, anti-replay, redaction, eventos append-only e rejeição de shell/comando arbitrário.

Ações reconhecidas pela política:
- `read_context`;
- `read_repository`;
- `modify_worktree`;
- `run_tests`;
- `create_branch`;
- `create_commit`;
- `create_pull_request`.

### M8.5 — adapter local isolado
Status: **concluído na branch `codex/m8-5-isolated-adapter`**.

Entregas:
- adapter opcional `isolated-local`, desabilitado por padrão;
- root de worktrees configurável e obrigatório;
- resolução canônica de paths;
- bloqueio de path traversal e symlink escape;
- primeiro contrato real `read_repository` limitado a `scope=metadata`;
- primeiro contrato real `run_tests` limitado ao preset server-side `pytest`;
- cliente não escolhe executável, argv ou flags arbitrárias;
- subprocesso com `shell=False` e `stdin=DEVNULL`;
- `cwd` restrito ao worktree validado;
- ambiente mínimo com allowlist e filtro adicional de nomes sensíveis;
- timeout limitado por máximo global;
- encerramento do grupo de processos em timeout quando suportado;
- captura de stdout/stderr em arquivo temporário;
- limite do volume persistido por stream;
- redaction de saída antes da persistência;
- ações sem contrato real retornam `unsupported` sem efeito externo;
- testes reais de pytest em diretório temporário;
- teste de timeout, traversal, symlink escape, ambiente mínimo, truncamento e integração via API;
- documentação `docs/ISOLATED_EXECUTOR.md`.

Ações que continuam **sem implementação real** no adapter `isolated-local`:
- `read_context`;
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

### M8.6 — hardening do worker
Status: **futuro/condicional**.

Antes de ampliar as ações reais, endurecer o ambiente com:
- worker/processo dedicado separado da API;
- isolamento por container ou mecanismo equivalente;
- cgroups/limites fortes de CPU, memória, PIDs e filesystem quando disponíveis;
- quota de disco/artefatos;
- política de rede (idealmente sem egress por padrão);
- identidade de execução não privilegiada;
- lifecycle e limpeza de worktrees temporários;
- observabilidade e auditoria do worker;
- testes de escape/abuso;
- nenhum secret no ambiente padrão.

Somente depois do hardening considerar contratos reais separados para `modify_worktree`, `create_branch`, `create_commit` e `create_pull_request`.

Antes do M8.6 permanece recomendada a calibração privada do M7.0 com consultas reais para decidir M7.1 com dados.

## Regra de evolução

Não adicionar complexidade de IA ou autonomia antes de existir:
1. fonte de verdade;
2. modelo de dados;
3. rastreabilidade;
4. teste de recuperação;
5. métrica de contexto;
6. autorização humana explícita para efeitos externos;
7. evidência verificável antes de marcar execução como concluída;
8. política específica para cada nova capacidade de escrita;
9. isolamento e limites de recurso antes de executar código real;
10. hardening do worker antes de ampliar efeitos externos reais.
