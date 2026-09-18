# Douglas Snake — Super Chat

O **Super Chat** é a interface operacional do **Segundo Cérebro**: memória persistente, continuidade de projetos, recuperação seletiva de contexto e preparação segura de trabalho para agentes.

## Arquitetura atual

```text
Usuário
  ↓
Web / API
  ↓
Projeto
  ├── memória operacional (PostgreSQL)
  ├── Session Memory
  ├── GitHub
  ├── Google Drive
  └── Google Calendar
        ↓
Context Engine
  ├── minimal   1.800 tokens
  ├── standard  5.000 tokens
  └── deep     15.000 tokens
        ↓
Pacote mínimo e rastreável de contexto
        ↓
Agent Task Pack
  ├── objetivo
  ├── critérios de aceite explícitos
  ├── guardrails
  ├── fontes
  ├── orçamento de tokens
  └── fingerprint SHA-256
        ↓
preview → pending → aprovação humana → approved
        ↓
Handoff para Codex / agente
```

Um `AgentTaskPack` aprovado está pronto para handoff, mas **não autoriza por si só merge, deploy, publicação ou escrita em serviços externos**.

## Marcos M1–M8.0

- **M1 — Memória operacional:** projetos, decisões, tarefas, resumos, PostgreSQL, Alembic e Docker.
- **M2 — Context Engine:** ranking, deduplicação, compactação, orçamento de tokens e `continue`.
- **M3 — GitHub Connector:** commits, PRs, Issues e Actions em modo somente leitura.
- **M4 — Session Memory:** `SessionDelta` revisável e aplicação somente após confirmação.
- **M5 — Interface Web:** dashboard, Health Score, contexto/tokens e revisão visual dos deltas.
- **M6 — Google Context:** Drive sob demanda + Calendar normalizado em eventos.
- **M7.0 — Retrieval Benchmark:** precision/recall, cobertura, compressão, latência e baseline reproduzível.
- **M8.0 — Agent Task Packs:** preparação rastreável de tarefas para agentes com critérios de aceite, guardrails, redaction de secrets e aprovação humana.

## Agent Task Packs

O M8.0 transforma o contexto selecionado em um artefato determinístico para Codex/agentes. Os critérios de aceite são obrigatórios e devem ser fornecidos explicitamente; o sistema não os inventa.

Estados:

```text
preview
   ↓
pending
   ├── approve → approved
   └── cancel  → cancelled
```

O pack inclui snapshot do projeto, objetivo, critérios de aceite, restrições, áreas sugeridas pelo solicitante, contexto selecionado, referências de origem, orçamento de tokens e fingerprint SHA-256.

Antes de persistir/exportar, o sistema aplica redaction determinística para padrões de credenciais, bearer tokens, prefixes conhecidos e parâmetros sensíveis em URLs. A proteção é complementar: secrets reais continuam proibidos no repositório e não devem ser deliberadamente inseridos no contexto.

Endpoints:

```text
POST /agent-task-packs/preview
POST /agent-task-packs
GET  /agent-task-packs/{pack_id}
GET  /projects/{project_id}/agent-task-packs
POST /agent-task-packs/{pack_id}/approve
POST /agent-task-packs/{pack_id}/cancel
GET  /agent-task-packs/{pack_id}/markdown
```

Veja `docs/AGENT_TASK_PACKS.md`.

## Recuperação e economia de tokens

O Context Engine mede o conjunto candidato e o pacote efetivamente selecionado. No baseline sintético M7.0, o cenário de pressão do perfil `minimal` produziu:

```text
13.926 tokens candidatos
 1.794 tokens selecionados
87,12% de compressão aproximada
recall@2 = 1,0 no fixture
```

Esse resultado valida o funcionamento do budgeter em um cenário artificial. Ele não deve ser interpretado como garantia de desempenho em projetos reais.

Para executar o benchmark:

```bash
python scripts/context_benchmark.py benchmarks/context_cases.json
```

A avaliação também está disponível pela API:

```text
POST /evaluation/context
```

O gabarito (`expected_source_refs`) é explícito, permitindo medir `precision@k`, `recall@k`, coverage, tokens candidatos/selecionados e latência.

Veja `docs/RETRIEVAL_BENCHMARK.md`.

## Google Drive

Uma fonte documental usa:

```json
{
  "source_type": "google_drive",
  "external_id": "GOOGLE_FILE_ID",
  "label": "Documento do projeto"
}
```

O sistema persiste somente referência e metadados do arquivo. Quando o Context Engine precisa responder, o texto é recuperado sob demanda, dividido em janelas e somente os trechos lexicalmente relevantes competem pelo orçamento de tokens.

A versão M6 extrai texto diretamente de:
- Google Docs, por exportação `text/plain`;
- arquivos `text/*`;
- JSON e XML.

Outros formatos permanecem referenciados por metadados nesta versão. O conteúdo integral do Drive **não é gravado** em `context_items`.

## Google Calendar

Uma fonte temporal usa:

```json
{
  "source_type": "google_calendar",
  "external_id": "primary",
  "label": "Agenda principal"
}
```

A sincronização:

```text
POST /projects/{project_id}/google/sync
```

normaliza compromissos como eventos compactos `google_calendar.event`. O sync é idempotente: eventos existentes são ignorados quando não mudaram e atualizados quando o conteúdo realmente mudou.

## OAuth Google

O conector é somente leitura. As credenciais ficam exclusivamente no ambiente da instalação privada.

Pode-se fornecer `GOOGLE_ACCESS_TOKEN` temporário ou `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` e `GOOGLE_REFRESH_TOKEN`.

Nenhum access token, refresh token ou client secret deve ser persistido no banco, no contexto, em logs de teste ou no repositório.

Se uma fonte Drive estiver vinculada mas OAuth não estiver disponível, o comando `continue` continua funcionando com a memória local; apenas o contexto remoto do Drive é omitido.

## Executar

```bash
git clone https://github.com/douglassnake/douglassnake-super-chat.git
cd douglassnake-super-chat
git checkout codex/m8-agent-task-packs
cp .env.example .env
docker compose up --build
```

Interface: `http://localhost:8000/app/`

OpenAPI: `http://localhost:8000/docs`

## Endpoints centrais

```text
GET    /dashboard
GET    /projects/{project_id}/overview
GET    /projects/{project_id}/snapshot
GET    /projects/{project_id}/continue
POST   /context/build
POST   /evaluation/context

POST   /projects/{project_id}/sources
POST   /projects/{project_id}/github/sync
POST   /projects/{project_id}/google/sync

POST   /projects/{project_id}/session-deltas
GET    /session-deltas/{delta_id}/preview
POST   /session-deltas/{delta_id}/apply
POST   /session-deltas/{delta_id}/discard

POST   /agent-task-packs/preview
POST   /agent-task-packs
GET    /agent-task-packs/{pack_id}
POST   /agent-task-packs/{pack_id}/approve
POST   /agent-task-packs/{pack_id}/cancel
GET    /agent-task-packs/{pack_id}/markdown
```

## Privacidade

O repositório é público. Código, templates e dados fictícios podem ser versionados; memória real, `.env`, credenciais, conversas, dumps do banco e documentos privados não.

## Próximas etapas

O **M7.1** (embeddings/pgvector) continua condicional a um benchmark privado com consultas reais.

Após M8.0, a automação deve evoluir em incrementos com autorização explícita: primeiro handoff assistido/auditável para agentes; depois, se necessário, acompanhamento de execução. Merge, deploy, publicação e escrita externa continuam exigindo políticas de autorização próprias.
