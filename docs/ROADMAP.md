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

`SessionDelta`, preview, confirmação humana, aplicação transacional, decisões/tarefas propostas, alteração de status/próxima ação e descarte.

## M5 — Interface web
Status: **concluído**.

Dashboard responsivo, Health Score explicável, projetos, tarefas, fontes, eventos, painel de tokens, `continuar`, SessionDelta visual e sync GitHub.

## M6 — Google Drive e Calendar
Status: **concluído**.

- fontes `google_drive` e `google_calendar`;
- OAuth somente por ambiente;
- Drive somente leitura;
- metadados persistidos sem copiar documentos completos;
- Google Docs/textos recuperados sob demanda;
- seleção lexical de janelas relevantes;
- trechos Drive disputando o orçamento normal do Context Engine;
- Calendar normalizado para `events`;
- sync idempotente com create/update/skip;
- degradação segura quando OAuth Drive não está disponível;
- testes sem credenciais reais.

## M7 — Qualidade de recuperação

### M7.0 — benchmark de contexto
Status: **concluído na branch `codex/m7-retrieval-benchmark`**.

Entregas:
- `precision@k` e `recall@k`;
- cobertura de fontes esperadas;
- eficiência e compressão de tokens;
- latência;
- endpoint `POST /evaluation/context`;
- dataset sintético versionável;
- runner CLI;
- execução automática no CI;
- cenário de pressão de tokens;
- documentação de interpretação.

Baseline sintético v1:
- 4 casos;
- recall e coverage de 1,0 nos fixtures;
- cenário `Token pressure minimal`: 13.926 tokens candidatos → 1.794 selecionados, compressão de 0,871176, preservando recall@2 de 1,0.

Esses números validam o mecanismo e o orçamento, mas não são evidência de desempenho em dados reais.

### M7.1 — busca híbrida/semântica
Status: **condicional — não iniciado**.

Possíveis entregas, somente se benchmark real justificar:
- pgvector;
- embeddings;
- lexical + vetorial;
- re-ranking;
- comparação A/B contra o baseline M7.0.

Critério: manter embeddings somente se houver melhoria mensurável de recuperação que compense custo, latência e complexidade operacional.

### Próxima validação

Criar um conjunto **privado** de consultas reais dos projetos, com gabaritos de `source_ref`. Dados e documentos privados não entram no repositório público; somente métricas agregadas podem ser registradas.

## M8 — Automação e agentes

### M8.0 — Agent Task Packs
Status: **concluído na branch `codex/m8-agent-task-packs`**.

Entregas:
- estrutura persistente `AgentTaskPack`;
- snapshot do projeto, objetivo, contexto, fontes e budget;
- critérios de aceite explícitos e obrigatórios;
- guardrails padrão + restrições do solicitante;
- áreas/arquivos sugeridos sem inventar paths;
- redaction determinística de padrões de secrets;
- fingerprint SHA-256 canônico;
- prevenção de duplicação de pack idêntico;
- estados `pending`, `approved` e `cancelled`;
- aprovação e cancelamento protegidos por estado;
- preview sem persistência;
- exportação Markdown determinística;
- endpoints de criação, consulta, aprovação, cancelamento e exportação;
- migration Alembic;
- testes automatizados;
- documentação `docs/AGENT_TASK_PACKS.md`.

Regra de autorização: `approved` significa **pronto para handoff**. O pack continua com `authorized_for_execution = false`; a liberação operacional ocorre somente no handoff do M8.1.

### M8.1 — handoff assistido e auditável
Status: **concluído na branch `codex/m8-1-agent-handoffs`**.

Entregas:
- estrutura persistente `AgentHandoff`;
- vínculo obrigatório a Task Pack aprovado;
- executor e alvo declarados;
- allowlist explícita de ações;
- nenhuma permissão operacional por padrão;
- fingerprint do pack congelado no handoff;
- snapshot compacto de objetivo, critérios, guardrails, fontes e budget;
- estados `prepared`, `released`, `completed`, `failed` e `cancelled`;
- release explícito antes de considerar execução liberada;
- transições protegidas e idempotentes quando repetidas no mesmo estado;
- resultado/falha estruturados com redaction;
- limite para resultado serializado;
- exportação Markdown com contexto do Task Pack e validação de fingerprint;
- migration Alembic `0004_agent_handoffs`;
- testes automatizados;
- documentação `docs/AGENT_HANDOFFS.md`.

Allowlist do marco:
- `read_context`;
- `read_repository`;
- `modify_worktree`;
- `run_tests`;
- `create_branch`;
- `create_commit`;
- `create_pull_request`.

Nunca implicitamente autorizados:
- merge;
- deploy;
- publicação;
- escrita em Drive/Calendar;
- escrita em outros serviços externos.

O M8.1 ainda não chama um executor real; ele registra e exporta o envelope auditável.

### M8.2 — acompanhamento de execução
Status: **próximo marco**.

Objetivo: acompanhar uma execução real iniciada por fluxo autorizado sem transformar o Segundo Cérebro em executor autônomo irrestrito.

Possíveis entregas:
- associação do handoff a branch/commit/PR existentes;
- acompanhamento de CI e estado do PR;
- heartbeat/progresso estruturado;
- comparação entre critérios aprovados e resultado observado;
- registro de evidências de conclusão;
- follow-ups sugeridos;
- nenhuma promoção automática para merge/deploy/publicação;
- política separada para qualquer efeito externo adicional.

## Regra de evolução

Não adicionar complexidade de IA ou autonomia antes de existir:
1. fonte de verdade;
2. modelo de dados;
3. rastreabilidade;
4. teste de recuperação;
5. métrica de contexto;
6. autorização humana explícita para ações com efeito externo;
7. evidência verificável antes de marcar execução como concluída.
