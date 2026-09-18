# Douglas Snake — Super Chat

O **Super Chat** é a interface operacional do **Segundo Cérebro**: memória persistente, recuperação seletiva de contexto, continuidade de projetos e integração com fontes técnicas sem depender do histórico bruto das conversas.

## Fluxo atual

```text
Usuário
  ↓
Interface Web / API
  ↓
Projeto
  ├── status e próxima ação
  ├── tarefas e decisões
  ├── Session Memory
  └── fontes técnicas
        ↓
Context Engine
  ├── minimal   1.800 tokens
  ├── standard  5.000 tokens
  └── deep     15.000 tokens
        ↓
Pacote de contexto rastreável
        ↓
Modelo de IA / agente
```

Uma sessão longa pode ser consolidada em um `SessionDelta`. O delta nasce como `pending`, pode ser pré-visualizado e somente altera a memória operacional depois de confirmação explícita em `apply`.

## Marcos implementados

### M1 — Memória operacional

- FastAPI;
- PostgreSQL + SQLAlchemy 2;
- Alembic;
- projetos, decisões, tarefas e resumos;
- snapshot consolidado;
- Docker Compose;
- testes automatizados.

### M2 — Context Engine v1

- perfis `minimal`, `standard` e `deep`;
- ranking determinístico;
- deduplicação;
- compactação;
- orçamento estimado de tokens;
- rastreabilidade de fontes;
- auditoria em `context_runs`;
- endpoint `continue`.

### M3 — GitHub Connector

- vínculo projeto ↔ repositório;
- leitura somente de GitHub;
- commits recentes;
- PRs abertos;
- Issues abertas;
- Actions recentes;
- sincronização idempotente;
- normalização técnica para `events`;
- eventos GitHub recuperáveis pelo Context Engine.

### M4 — Session Memory

- `SessionDelta` persistente;
- estados `pending`, `applied` e `discarded`;
- preview;
- decisões/tarefas propostas;
- conclusão de tarefas existentes;
- mudança de status e próxima ação;
- aplicação transacional;
- idempotência por `project_id + session_key`;
- confirmação humana antes de alterar a memória.

### M5 — Interface Web

A branch `codex/m5-web-interface` entrega a primeira interface utilizável do Super Chat:

- dashboard responsivo em `/app/`;
- lista e seleção de projetos;
- Health Score determinístico;
- status, próxima ação e tarefas abertas;
- fontes vinculadas e eventos técnicos recentes;
- comando **Continuar projeto**;
- escolha de perfil de contexto;
- visualização de tokens selecionados/candidatos;
- SessionDeltas pendentes;
- preview visual;
- aplicar/descartar somente após confirmação;
- sincronização manual do GitHub.

## Health Score

O Health Score começa em 100 e aplica penalidades determinísticas. Os fatores atuais incluem:

- projeto sem próxima ação;
- tarefas vencidas;
- tarefas bloqueadas;
- inatividade;
- SessionDeltas aguardando revisão;
- falhas recentes de CI registradas pelo GitHub Connector.

Faixas:

| Score | Estado |
|---:|---|
| 85–100 | `healthy` |
| 65–84 | `attention` |
| 40–64 | `risk` |
| 0–39 | `critical` |

O score é explicável: a API devolve os motivos e o impacto de cada penalidade.

## Executar com Docker

```bash
git clone https://github.com/douglassnake/douglassnake-super-chat.git
cd douglassnake-super-chat
git checkout codex/m5-web-interface
cp .env.example .env

docker compose up --build
```

Interface Web:

```text
http://localhost:8000/app/
```

OpenAPI:

```text
http://localhost:8000/docs
```

Health check:

```bash
curl http://localhost:8000/health
```

## GitHub Connector

Para repositórios públicos, a leitura pode funcionar sem token, sujeita aos limites públicos do GitHub. Para repositórios privados ou maior limite de API, configure localmente:

```dotenv
GITHUB_TOKEN=seu_token_local
```

O token é lido apenas do ambiente. Ele não deve ser persistido no banco, nos eventos, no contexto ou no repositório.

Depois de vincular uma fonte `github`:

```text
POST /projects/{project_id}/github/sync
```

## Endpoints principais

```text
GET    /health
GET    /dashboard
GET    /projects/{project_id}/overview

POST   /projects
GET    /projects
GET    /projects/{project_id}
PATCH  /projects/{project_id}
GET    /projects/{project_id}/snapshot

POST   /projects/{project_id}/decisions
GET    /projects/{project_id}/decisions
POST   /projects/{project_id}/tasks
GET    /projects/{project_id}/tasks
PATCH  /tasks/{task_id}
POST   /projects/{project_id}/summaries

POST   /projects/{project_id}/context-items
GET    /projects/{project_id}/context-items
POST   /context/build
GET    /projects/{project_id}/continue

POST   /projects/{project_id}/sources
GET    /projects/{project_id}/sources
POST   /projects/{project_id}/github/sync

POST   /projects/{project_id}/session-deltas
GET    /projects/{project_id}/session-deltas
GET    /session-deltas/{delta_id}/preview
POST   /session-deltas/{delta_id}/apply
POST   /session-deltas/{delta_id}/discard
```

## Testes

```bash
python -m venv .venv
source .venv/bin/activate   # Linux/macOS
# .venv\Scripts\activate   # Windows
pip install -r requirements.txt
pytest -q
```

A suíte usa SQLite em memória e dados fictícios. Testes do GitHub usam leitor simulado; não dependem de rede nem de credenciais reais.

## Privacidade

O repositório é público. Portanto:

- não versionar `.env`, tokens ou senhas;
- não versionar conversas pessoais;
- não versionar dumps reais do PostgreSQL;
- não versionar documentos privados;
- usar apenas dados fictícios nos testes.

A memória real deve permanecer no PostgreSQL da instalação privada.

## Próximo marco

**M6 — Google Drive + Calendar**: associar documentos e compromissos aos projetos e recuperar somente o necessário pelo Context Engine.
