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

Entregas:
- `AgentTaskPack` persistente;
- snapshot do projeto;
- objetivo e critérios de aceite explícitos;
- guardrails e áreas sugeridas;
- contexto, fontes e budget;
- redaction;
- fingerprint SHA-256;
- `pending`, `approved`, `cancelled`;
- preview e Markdown;
- migration/testes/documentação.

`approved` significa pronto para handoff, não autorizado para execução.

### M8.1 — handoff assistido e auditável
Status: **concluído na branch `codex/m8-1-agent-handoffs`**.

Entregas:
- `AgentHandoff` persistente;
- somente a partir de pack aprovado;
- executor/alvo e allowlist explícita;
- nenhuma permissão por padrão;
- fingerprint congelado;
- `prepared`, `released`, `completed`, `failed`, `cancelled`;
- release explícito;
- resultado/falha estruturados;
- Markdown com contexto do pack;
- migration/testes/documentação.

Ações nunca implicitamente autorizadas incluem merge, deploy, publicação e escrita em serviços externos.

### M8.2 — acompanhamento de execução e evidências
Status: **concluído na branch `codex/m8-2-execution-tracking`**.

Entregas:
- `AgentExecution` com um registro único por handoff;
- criação somente para handoff `released`;
- `AgentExecutionEvent` append-only com sequência crescente;
- estados `running`, `completed`, `failed`, `cancelled`;
- progresso percentual e etapa atual;
- referências opcionais de branch/commit/PR sem criação ou escrita externa;
- eventos `started`, `progress`, `technical_refs`, `criterion_evidence` e `status`;
- evidência por índice real de critério de aceite;
- evidência explícita `passed`/`failed`;
- estado atual do critério calculado pela evidência mais recente;
- cobertura agregada `passed/failed/pending`;
- conclusão bloqueada até todos os critérios estarem `passed`;
- bloqueio dos endpoints terminais diretos do handoff quando existe execução rastreada;
- sincronização transacional execução ↔ handoff em conclusão/falha/cancelamento;
- redaction recursiva por padrão textual e por chave sensível em JSON;
- migration `0005_agent_executions`;
- testes automatizados;
- documentação `docs/AGENT_EXECUTIONS.md`.

O M8.2 não inicia agente, não executa comandos e não cria/modifica branch, commit, PR ou CI.

### M8.3 — verificação externa somente leitura
Status: **próximo marco**.

Objetivo: transformar referências técnicas já registradas em evidências verificáveis por leitura de fontes externas já conectadas, sem ampliar permissões de escrita.

Possíveis entregas:
- correlacionar `commit_sha` e `pr_url` com o GitHub Connector;
- ler estado atual de PR e checks/Actions associados;
- registrar observações como eventos de verificação;
- anexar evidência verificável de CI a um critério somente por regra explícita;
- detectar referência ausente, divergente ou stale;
- manter proveniência e timestamp da leitura;
- nenhuma criação/edição de branch, commit ou PR;
- nenhum merge/deploy/publicação;
- nenhuma promoção automática de evidência ambígua.

### M8.4 — executor controlado
Status: **futuro/condicional**.

Somente após M8.3 e definição de políticas específicas por ação. Qualquer adapter de execução deverá respeitar a allowlist do handoff, registrar cada efeito e manter merge/deploy/publicação em autorização separada.

## Regra de evolução

Não adicionar complexidade de IA ou autonomia antes de existir:
1. fonte de verdade;
2. modelo de dados;
3. rastreabilidade;
4. teste de recuperação;
5. métrica de contexto;
6. autorização humana explícita para efeitos externos;
7. evidência verificável antes de marcar execução como concluída;
8. política específica para cada nova capacidade de escrita.
