# Modelo de Dados — estado atual

## Visão geral

O modelo começou como uma base operacional de projetos/contexto e evoluiu para incluir:
- memória operacional;
- sessões de autenticação;
- execução controlada de agentes;
- grafo semântico;
- documentos como entidades;
- batches de descoberta/revisão.

Este documento descreve as entidades principais, não cada coluna de todas as migrations.

## Núcleo operacional

### projects

- `id` UUID PK
- `slug` text unique
- `name` text
- `description` text nullable
- `status` text
- `priority` integer
- `next_action` text nullable
- `last_activity_at` timestamptz nullable
- `created_at` / `updated_at`

### project_sources

Relaciona um projeto às fontes externas.

Campos principais:
- `id`
- `project_id`
- `source_type`
- `external_id`
- `url`
- `label`
- `metadata`
- `is_active`
- timestamps

### decisions

Registra decisão operacional, rationale, status e referência de origem.

### tasks

Registra backlog operacional:
- status;
- prioridade;
- prazo;
- bloqueio;
- source ref;
- timestamps.

### memories

Memórias persistentes ligadas a projeto e usadas para retomada/contexto.

O modelo de memória é distinto de `session_deltas`: uma memória aprovada é estado persistente; um delta representa alteração de sessão ainda sujeita a revisão/aplicação.

## Context Engine

### context_items

Unidade recuperável do Context Engine.

Kinds incluem, entre outros:
- `summary`;
- `fact`;
- `note`;
- `decision`;
- `event`;
- `document_excerpt`.

Metadados incluem importância, fonte, timestamp de origem e validade.

### context_runs

Auditoria de cada pacote montado:
- projeto;
- perfil;
- query;
- candidatos;
- selecionados;
- estimativa de tokens;
- duração.

### session_deltas

Mantém mudanças extraídas de uma sessão antes de sua aplicação à memória operacional.

O fluxo é:
`preview → revisão humana → aplicar/descartar`.

## Eventos e sessões

### events

Normaliza eventos vindos de integrações externas.

### auth_sessions

Sessões server-side da autenticação single-admin.

Somente hash do token opaco é persistido; o token bruto não é armazenado.

## Execução controlada — M8

O banco também mantém estado necessário à automação auditável, incluindo:
- `agent_task_packs`;
- `agent_handoffs`;
- `agent_executions`;
- `executor_requests`;
- `worker_attempts`;
- `git_change_approvals`.

Essas tabelas permitem distinguir:
- intenção;
- autorização;
- execução;
- resultado;
- proveniência;
- reconciliação.

## Grafo semântico — M11

### knowledge_entities

Entidade canônica compartilhável entre projetos.

Usos atuais incluem:
- plataforma/serviço;
- infraestrutura;
- documento/arquivo;
- outros conceitos relevantes ao contexto.

Documentos são representados com `kind=document` e metadados próprios.

### project_relations

Liga um projeto a uma entidade de conhecimento.

Tipos suportados:
- `USES`
- `RUNS_ON`
- `DEPENDS_ON`
- `PART_OF`
- `CREATED_FROM`
- `SUPPORTS`
- `BLOCKS`
- `IMPLEMENTS`
- `DECIDED_BY`
- `RELATED_TO`
- `HAS_DOCUMENT`

A relação possui direção: projeto → entidade.

### knowledge_relations

Liga entidade de conhecimento → entidade de conhecimento.

Adicionada pela migration `0012_cross_knowledge_relations`.

Tipos usados para relações de conhecimento incluem:
- `MENTIONS`;
- `DESCRIBES`;
- `CREATED_FROM`.

A tabela permite, por exemplo:

```text
README — Super Chat
   ↓ CREATED_FROM
GitHub
```

### graph_suggestion_batches

Adicionada pela migration `0011_graph_suggestion_batches`.

Mantém descoberta pendente de revisão humana.

Um batch registra informação suficiente para:
- mostrar relação proposta;
- evidência;
- confiança;
- estado de revisão;
- aplicar/descartar/revisar depois.

A descoberta deve suprimir sugestões duplicadas e relações já persistidas.

## Migrations relevantes do grafo

- `0010_semantic_graph_relations` — `knowledge_entities` + `project_relations`;
- `0011_graph_suggestion_batches` — descoberta/revisão;
- `0012_cross_knowledge_relations` — relações entre entidades.

Head validado no checkpoint M12.4:

```text
0012_cross_knowledge_relations
```

## Índices e busca

O sistema começou com PostgreSQL full-text search + filtros determinísticos.

Embeddings/pgvector continuam condicionais: só entram se métricas com dados reais mostrarem ganho suficiente para justificar a complexidade.

## Fonte de verdade

O banco não substitui fontes externas.

Exemplos:
- código/PR/commit → GitHub;
- documento oficial → fonte documental correspondente;
- compromisso → Calendar;
- status/tarefa/decisão/memória → PostgreSQL;
- entidade canônica e relação revisada → PostgreSQL.

## Privacidade

Não persistir deliberadamente:
- tokens brutos;
- senha;
- secrets em Settings serializáveis;
- dumps dentro do Git;
- conteúdo privado desnecessário quando referência/metadado são suficientes.
