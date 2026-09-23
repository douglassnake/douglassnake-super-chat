# Douglas Snake — Super Chat

O **Super Chat** é a interface operacional do **Segundo Cérebro**: memória persistente, continuidade de projetos e recuperação seletiva de contexto para evitar o carregamento repetido de históricos longos.

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
Modelo de IA / agente
```

## Marcos M1–M6

- **M1 — Memória operacional:** projetos, decisões, tarefas, resumos, PostgreSQL, Alembic e Docker.
- **M2 — Context Engine:** ranking, deduplicação, compactação, orçamento de tokens e `continue`.
- **M3 — GitHub Connector:** commits, PRs, Issues e Actions em modo somente leitura.
- **M4 — Session Memory:** `SessionDelta` revisável e aplicação somente após confirmação.
- **M5 — Interface Web:** dashboard, Health Score, contexto/tokens e revisão visual dos deltas.
- **M6 — Google Context:** Drive sob demanda + Calendar normalizado em eventos.

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

Pode-se fornecer um access token temporário:

```dotenv
GOOGLE_ACCESS_TOKEN=
```

ou refresh token:

```dotenv
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
GOOGLE_REFRESH_TOKEN=
```

Nenhum access token, refresh token ou client secret deve ser persistido no banco, no contexto, em logs de teste ou no repositório.

Se uma fonte Drive estiver vinculada mas OAuth não estiver disponível, o comando `continue` continua funcionando com a memória local; apenas o contexto remoto do Drive é omitido.

## Executar

```bash
git clone https://github.com/douglassnake/douglassnake-super-chat.git
cd douglassnake-super-chat
git checkout codex/m6-google-context
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

POST   /projects/{project_id}/sources
POST   /projects/{project_id}/github/sync
POST   /projects/{project_id}/google/sync

POST   /projects/{project_id}/session-deltas
GET    /session-deltas/{delta_id}/preview
POST   /session-deltas/{delta_id}/apply
POST   /session-deltas/{delta_id}/discard
```

## Privacidade

O repositório é público. Código, templates e dados fictícios podem ser versionados; memória real, `.env`, credenciais, conversas, dumps do banco e documentos privados não.

## Próxima etapa

Antes de introduzir embeddings/pgvector no M7, o projeto deve medir a qualidade e a eficiência da recuperação atual com casos reais. A busca semântica entra somente onde a busca lexical demonstrar insuficiência mensurável.
