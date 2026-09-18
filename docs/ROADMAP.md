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
Status: **concluído na branch `codex/m6-google-context`**.

Entregas:
- fontes `google_drive` e `google_calendar`;
- OAuth somente por ambiente;
- Drive somente leitura;
- metadados persistidos sem copiar documentos completos;
- texto de Google Docs/textos recuperado sob demanda;
- seleção lexical de janelas relevantes;
- trechos Drive disputando o orçamento normal do Context Engine;
- Calendar normalizado para `events`;
- sync de Calendar idempotente com create/update/skip;
- degradação segura quando OAuth Drive não está disponível;
- testes com Google simulado e sem credenciais reais.

## M7 — Avaliação de recuperação + busca semântica
Status: **próximo marco**.

Antes de ativar embeddings, medir a recuperação atual.

### M7.0 — benchmark de contexto
- conjunto de consultas de referência por projeto fictício;
- `expected_source_refs` / itens esperados;
- precision@k e recall@k;
- taxa de cobertura da resposta;
- tokens candidatos x selecionados;
- eficiência de contexto;
- latência;
- comparação entre perfis.

### M7.1 — busca híbrida, somente se justificada
Possíveis entregas:
- pgvector;
- embeddings;
- lexical + vetorial;
- re-ranking;
- comparação A/B contra M7.0.

Critério: embeddings só permanecem se melhorarem de forma mensurável a recuperação sem custo desproporcional de tokens/latência.

## M8 — Automação e agentes
Planejado:
- geração de prompts Codex;
- preparação de tarefas técnicas;
- acompanhamento de PRs;
- rotinas de revisão;
- aprovações humanas explícitas para ações de escrita.

## Regra de evolução

Não adicionar complexidade de IA antes de existir:
1. fonte de verdade;
2. modelo de dados;
3. rastreabilidade;
4. teste de recuperação;
5. métrica de contexto.
