# Douglas Snake — Super Chat

Interface central do **Segundo Cérebro**: memória operacional, recuperação seletiva de contexto e integração com fontes técnicas sem depender do histórico bruto das conversas.

## Objetivo

Permitir que um projeto fique semanas sem atividade e seja retomado em poucos minutos, respondendo com contexto rastreável:

- onde paramos;
- o que já foi decidido;
- qual é o estado atual;
- o que está pendente;
- qual é a próxima ação;
- o que mudou tecnicamente;
- quais fontes sustentam o contexto.

## Arquitetura atual

```text
Usuário / agente
  ↓
SessionDelta pendente ── preview / confirmação
  ↓ apply
Super Chat API
  ↓
Memória operacional (PostgreSQL)
  ├── projetos
  ├── decisões
  ├── tarefas
  ├── resumos
  ├── context_items
  ├── events
  └── session_deltas
  ↓
Context Engine
  ├── memória confirmada
  └── GitHub Connector
       ├── commits
       ├── PRs
       ├── Issues
       └── Actions
  ↓
Pacote mínimo de contexto
  ↓
Modelo de IA / agente
```

## Estado dos marcos

### M1 — Memória operacional

Implementado:
- FastAPI;
- PostgreSQL + SQLAlchemy 2;
- Alembic;
- projetos, decisões, tarefas e resumos;
- snapshot consolidado;
- Docker Compose;
- testes automatizados.

### M2 — Context Engine v1

Implementado:
- perfis `minimal`, `standard` e `deep`;
- ranking determinístico;
- deduplicação;
- orçamento estimado de tokens;
- compactação de itens grandes;
- rastreabilidade;
- auditoria em `context_runs`;
- comando/API `continue`.

| Perfil | Limite de memória injetada |
|---|---:|
| `minimal` | 1.800 tokens |
| `standard` | 5.000 tokens |
| `deep` | 15.000 tokens |

### M3 — GitHub Connector

Implementado:
- vínculo projeto ↔ repositório;
- GitHub somente leitura;
- commits recentes;
- PRs abertos;
- Issues abertas;
- Actions recentes;
- normalização em `events`;
- sincronização idempotente;
- eventos técnicos recuperáveis pelo Context Engine.

### M4 — Session Memory

Implementado na branch `codex/m4-session-memory`:
- `SessionDelta` persistente;
- estado `pending`, `applied` ou `discarded`;
- preview antes de persistir efeitos;
- decisões propostas;
- tarefas propostas;
- conclusão de tarefas existentes;
- alteração de status;
- próxima ação;
- aplicação transacional;
- idempotência por `project_id + session_key`;
- confirmação humana explícita antes de alterar a memória operacional.

## Executar com Docker

```bash
git clone https://github.com/douglassnake/douglassnake-super-chat.git
cd douglassnake-super-chat
git checkout codex/m4-session-memory
cp .env.example .env

docker compose up --build
```

API: `http://localhost:8000`

OpenAPI: `http://localhost:8000/docs`

Health:

```bash
curl http://localhost:8000/health
```

## GitHub Connector

Para repositórios públicos, a API pode funcionar sem token, sujeita aos limites públicos do GitHub. Para repositórios privados ou maior limite, configure localmente:

```dotenv
GITHUB_TOKEN=seu_token_local
```

O token é usado apenas no header de autenticação e não deve ser salvo no banco, em eventos, contexto ou no repositório.

Depois de vincular uma fonte `github` no projeto:

```text
POST /projects/{project_id}/github/sync
```

A sincronização transforma atividade técnica em eventos compactos; o código-fonte do repositório não é copiado para o PostgreSQL.

## Session Memory

Uma sessão longa pode ser consolidada em um delta:

```text
POST /projects/{project_id}/session-deltas
```

Antes de aplicar:

```text
GET /session-deltas/{delta_id}/preview
```

Após revisão explícita:

```text
POST /session-deltas/{delta_id}/apply
```

Ou descarte:

```text
POST /session-deltas/{delta_id}/discard
```

Um delta `pending` não modifica o status, decisões, tarefas ou resumo do projeto. Somente `apply` transforma as propostas em memória operacional.

## Endpoints principais

```text
GET    /health

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

## Continuar projeto

```text
GET /projects/{project_id}/continue?profile=standard
```

O Context Engine seleciona apenas memória útil para a consulta: status, próxima ação, resumos, decisões, tarefas, notas/fatos e eventos GitHub relevantes. O pacote também informa tokens candidatos, tokens selecionados, itens escolhidos e fontes.

## Testes

```bash
python -m venv .venv
source .venv/bin/activate   # Linux/macOS
# .venv\Scripts\activate   # Windows
pip install -r requirements.txt
pytest -q
```

A suíte usa SQLite em memória e dados fictícios. Os testes do GitHub usam um leitor simulado; não dependem de rede nem de credenciais reais.

## Privacidade

Este repositório é público. Portanto:
- não versionar `.env`;
- não versionar tokens ou senhas;
- não versionar conversas pessoais;
- não versionar dumps reais do PostgreSQL;
- não versionar documentos privados;
- usar dados fictícios nos testes.

A memória real deve ficar no PostgreSQL da instalação privada.

## Documentação

- `docs/ARCHITECTURE.md`
- `docs/DATA_MODEL.md`
- `docs/CONTEXT_ENGINE.md`
- `docs/SESSION_MEMORY.md`
- `docs/ROADMAP.md`

## Próxima evolução

A próxima etapa é a interface web: dashboard, projetos, tela de contexto, revisão visual de `SessionDelta`, Health Score e comando **Continuar projeto**.
