# Modelo de Dados Inicial

## Entidades principais

### projects

- `id` UUID PK
- `slug` text unique
- `name` text
- `description` text nullable
- `status` text
- `priority` integer
- `next_action` text nullable
- `last_activity_at` timestamptz nullable
- `created_at` timestamptz
- `updated_at` timestamptz

### project_sources

Relaciona um projeto às fontes externas.

- `id` UUID PK
- `project_id` UUID FK
- `source_type` text (`github`, `drive`, `calendar`, `url`, `local`)
- `external_id` text nullable
- `url` text nullable
- `label` text
- `metadata` jsonb
- `is_active` boolean
- `created_at` timestamptz
- `updated_at` timestamptz

### decisions

- `id` UUID PK
- `project_id` UUID FK nullable
- `title` text
- `body` text
- `rationale` text nullable
- `status` text (`active`, `superseded`, `reversed`)
- `decided_at` timestamptz
- `source_ref` text nullable
- `created_at` timestamptz

### tasks

- `id` UUID PK
- `project_id` UUID FK nullable
- `title` text
- `description` text nullable
- `status` text (`todo`, `doing`, `blocked`, `done`, `cancelled`)
- `priority` integer
- `due_at` timestamptz nullable
- `blocked_by` text nullable
- `source_ref` text nullable
- `created_at` timestamptz
- `updated_at` timestamptz

### context_items

Unidade recuperável do Context Engine.

- `id` UUID PK
- `project_id` UUID FK nullable
- `kind` text (`summary`, `fact`, `note`, `decision`, `event`, `document_excerpt`)
- `title` text nullable
- `content` text
- `importance` numeric
- `source_type` text
- `source_ref` text nullable
- `source_timestamp` timestamptz nullable
- `generated` boolean
- `valid_from` timestamptz nullable
- `valid_to` timestamptz nullable
- `created_at` timestamptz
- `updated_at` timestamptz

### session_summaries

- `id` UUID PK
- `project_id` UUID FK nullable
- `session_key` text nullable
- `summary` text
- `next_action` text nullable
- `source_ref` text nullable
- `started_at` timestamptz nullable
- `ended_at` timestamptz nullable
- `created_at` timestamptz

### events

Normaliza eventos vindos de integrações.

- `id` UUID PK
- `project_id` UUID FK nullable
- `source_type` text
- `event_type` text
- `external_id` text nullable
- `title` text
- `body` text nullable
- `occurred_at` timestamptz
- `url` text nullable
- `metadata` jsonb
- `created_at` timestamptz

### context_runs

Auditoria de cada pacote montado.

- `id` UUID PK
- `project_id` UUID FK nullable
- `profile` text
- `query_text` text
- `candidate_count` integer
- `selected_count` integer
- `estimated_candidate_tokens` integer nullable
- `estimated_selected_tokens` integer nullable
- `duration_ms` integer nullable
- `created_at` timestamptz

## Índices iniciais

- `projects(slug)` unique
- `tasks(project_id, status, priority)`
- `decisions(project_id, decided_at desc)`
- `context_items(project_id, kind, updated_at desc)`
- `events(project_id, occurred_at desc)`
- `project_sources(project_id, source_type)`

## Busca

M1 começa com PostgreSQL full-text search + filtros determinísticos.

Embeddings/pgvector entram somente depois de validarmos o fluxo com dados reais e métricas de contexto. Isso evita complexidade prematura.
