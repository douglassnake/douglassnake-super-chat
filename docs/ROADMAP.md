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

### M8.3 — verificação externa GitHub somente leitura
Status: **concluído na branch `codex/m8-3-github-verification`**.

Entregas:
- reutilização do GitHub Connector em modo somente leitura;
- leituras pontuais de commit, PR e check-runs;
- `GitHubAPIError` com status HTTP observável e degradação de falhas de rede;
- repositório derivado exclusivamente de `ProjectSource` GitHub ativo;
- validação de que `pr_url` pertence a repositório vinculado ao projeto;
- commit isolado só é resolvido automaticamente quando existe exatamente uma fonte GitHub ativa;
- status normalizados `verified`, `mismatch`, `not_found`, `unavailable`;
- detecção de divergência entre commit registrado, SHA observado e `head.sha` do PR;
- resumo estrito de check-runs;
- `checks_green` somente quando existe check e todos estão `completed/success`;
- evento append-only `external_verification` com timestamp/proveniência;
- endpoint `POST /agent-executions/{execution_id}/verify-github`;
- verificação sem regra explícita não altera critérios;
- regra explícita `checks_green` pode gerar `criterion_evidence = passed` para índice informado;
- checks não verdes nunca promovem evidência `passed`;
- reader injetável e testes sem rede/credenciais;
- documentação `docs/GITHUB_VERIFICATION.md`.

O M8.3 não cria/edita branch, commit ou PR, não comenta/aprova PR, não reexecuta CI e não faz merge/deploy/publicação.

### M8.4 — executor controlado
Status: **futuro/condicional**.

Somente após definição de políticas específicas por ação. Um adapter de execução real deverá:
- validar a allowlist do handoff antes de cada efeito;
- registrar pedido, efeito e resultado;
- possuir idempotência e trilha de auditoria;
- separar leitura de escrita;
- exigir política própria para criar branch/commit/PR;
- manter merge, deploy, publicação e outras ações de alto impacto em autorização separada;
- nunca ampliar permissões a partir de contexto inferido.

Antes do M8.4, também é recomendável calibrar M7.0 com consultas reais privadas para decidir M7.1 com dados, não por suposição.

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
