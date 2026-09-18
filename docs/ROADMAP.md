# Roadmap

## M0 — Fundação documental

Status: **concluído**.

Entregas:
- objetivo e princípios;
- arquitetura;
- Context Engine;
- modelo de dados;
- roadmap inicial.

## M1 — Memória operacional

Status: **concluído**.

Entregas:
- FastAPI;
- PostgreSQL;
- migrations;
- CRUD de projetos;
- CRUD de decisões;
- CRUD de tarefas;
- resumo por projeto;
- snapshot consolidado;
- testes;
- Docker Compose.

## M2 — Context Engine v1

Status: **concluído**.

Entregas:
- perfis `minimal`, `standard` e `deep`;
- ranking determinístico;
- deduplicação;
- orçamento estimado de tokens;
- auditoria em `context_runs`;
- endpoint `/context/build`;
- endpoint `/projects/{id}/continue`.

## M3 — GitHub Connector

Status: **concluído**.

Entregas:
- vínculo projeto ↔ repositório;
- commits recentes;
- branch padrão;
- PRs abertos;
- Issues abertas;
- Actions recentes;
- normalização em `events`;
- sync idempotente.

## M4 — Session Memory

Status: **concluído**.

Entregas:
- `SessionDelta` persistente;
- preview;
- confirmação humana;
- decisões e tarefas propostas;
- conclusão de tarefas existentes;
- resumo incremental;
- alteração de status e próxima ação;
- aplicação transacional;
- descarte e proteção contra reaplicação.

## M5 — Interface web

Status: **concluído na branch `codex/m5-web-interface`**.

Entregas:
- dashboard responsivo servido pela FastAPI;
- projetos ativos;
- Health Score explicável;
- status e próxima ação;
- tarefas abertas;
- fontes e eventos recentes;
- painel de contexto/tokens;
- comando `continuar`;
- revisão visual de `SessionDelta`;
- aplicar/descartar com confirmação explícita;
- sincronização manual do GitHub;
- testes da UI e do Health Score.

## M6 — Google Drive e Calendar

Status: **próximo marco**.

Objetivo: incorporar contexto documental e temporal sem duplicar arquivos inteiros na memória operacional.

Entregas planejadas:
- referências de documentos do Drive;
- recuperação de trechos sob demanda;
- metadados e proveniência;
- prazos/compromissos do Calendar;
- associação a projetos;
- seleção pelo Context Engine;
- sincronização incremental.

## M7 — Busca semântica

Somente após métricas do M2–M6.

Entregas possíveis:
- pgvector;
- embeddings;
- busca híbrida lexical + vetorial;
- re-ranking.

## M8 — Automação e agentes

Entregas planejadas:
- geração de prompts Codex;
- preparação de tarefas técnicas;
- acompanhamento de PRs;
- rotinas de revisão;
- regras explícitas de aprovação humana para ações de escrita.

## Regra de evolução

Não adicionar complexidade de IA antes de existir:
1. fonte de verdade;
2. modelo de dados;
3. rastreabilidade;
4. teste de recuperação;
5. métrica de contexto.
