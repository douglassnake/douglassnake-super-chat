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

`approved` significa pronto para handoff, não autorização para execução.

### M8.1 — handoff assistido e auditável
Status: **concluído na branch `codex/m8-1-agent-handoffs`**.

`AgentHandoff` persistente, allowlist explícita, fingerprint congelado, release separado, resultado/falha estruturados, Markdown auditável, testes e documentação.

### M8.2 — acompanhamento de execução e evidências
Status: **concluído na branch `codex/m8-2-execution-tracking`**.

`AgentExecution`, eventos append-only, progresso, referências técnicas, evidência por critério e gate de conclusão. A execução só pode ser concluída quando a evidência mais recente de todos os critérios é `passed`.

### M8.3 — verificação externa GitHub somente leitura
Status: **concluído na branch `codex/m8-3-github-verification`**.

Entregas:
- commit, PR e check-runs lidos por conector somente leitura;
- repositório derivado de fonte GitHub ativa do projeto;
- estados `verified`, `mismatch`, `not_found`, `unavailable`;
- evento `external_verification`;
- regra explícita `checks_green`;
- nenhum critério alterado sem mapeamento explícito;
- nenhum recurso GitHub criado ou modificado.

### M8.4 — executor controlado
Status: **concluído na branch `codex/m8-4-controlled-executor`**.

Entregas:
- `ExecutorRequest` persistente vinculado a `AgentExecution`;
- migration `0006_executor_requests`;
- estados `prepared`, `released`, `running`, `completed`, `failed`, `cancelled`;
- ação obrigatoriamente pertencente à política global e à allowlist do handoff;
- fingerprint determinístico por execução/ação/adapter/payload;
- prevenção de request idêntica na mesma execução;
- release explícito antes da execução;
- adapter interface injetável;
- adapter padrão `manual` inerte (`available = false`);
- payload sem shell/comando arbitrário;
- rejeição recursiva de `argv`, `cmd`, `command`, `executable`, `script`, `shell`, `shell_command`;
- redaction de payload, notas, resultado e erro;
- eventos append-only `executor_request`, `executor_released`, `executor_started`, `executor_result`;
- requests terminais protegidos contra replay;
- request concluído não gera evidência automaticamente e não conclui o `AgentExecution`;
- endpoints de criação, listagem, leitura, release, execução e cancelamento;
- testes offline com adapter fake;
- documentação `docs/CONTROLLED_EXECUTOR.md`.

Ações reconhecidas pela política inicial:
- `read_context`;
- `read_repository`;
- `modify_worktree`;
- `run_tests`;
- `create_branch`;
- `create_commit`;
- `create_pull_request`.

Continuam proibidos por padrão:
- merge;
- deploy;
- publicação;
- escrita em Drive/Calendar;
- escrita genérica em serviços externos;
- shell/comando arbitrário.

### M8.5 — adapter real isolado
Status: **futuro/condicional**.

Somente após definir o ambiente de execução e as políticas específicas por ação. Um adapter real deverá incluir:
- worker isolado;
- diretório de trabalho restrito ao projeto autorizado;
- validação de paths;
- timeout por ação;
- limites de CPU/memória/processos quando aplicável;
- sem shell arbitrário;
- contratos semânticos específicos para cada ação;
- captura e auditoria de artefatos/resultados;
- idempotência/replay protection;
- confirmação separada para qualquer ampliação de efeito externo;
- merge, deploy e publicação ainda fora da política padrão.

Antes de M8.5 também permanece recomendada a calibração privada do M7.0 com consultas reais para decidir M7.1 com dados.

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
9. isolamento e limites de recurso antes de executar código real.
