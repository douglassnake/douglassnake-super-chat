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
Usuário
  ↓
Super Chat API
  ↓
Context Engine
  ├── PostgreSQL
  │    ├── projetos
  │    ├── decisões
  │    ├── tarefas
  │    ├── resumos
  │    ├── context_items
  │    └── events
  ├── GitHub Connector (somente leitura)
  │    ├── commits
  │    ├── PRs
  │    ├── Issues
  │    └── Actions
  └── futuras fontes: Drive / Calendar
  ↓
Pacote mínimo de memória
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
- rastreabilidade de fontes;
- auditoria em `context_runs`;
- comando/API `continue`.

Orçamentos atuais de memória injetada:

| Perfil | Limite |
|---|---:|
| `minimal` | 1.800 tokens |
| `standard` | 5.000 tokens |
| `deep` | 15.000 tokens |

### M3 — GitHub Connector

Em implementação na branch `codex/m3-github-connector`:
- vínculo projeto ↔ repositório;
- leitura somente de GitHub;
- commits recentes;
- PRs abertos;
- Issues abertas;
- Actions recentes;
- normalização para `events`;
- sincronização idempotente;
- eventos GitHub selecionáveis pelo Context Engine.

## Executar com Docker

```bash
git clone https://github.com/douglassnake/douglassnake-super-chat.git
cd douglassnake-super-chat
git checkout codex/m3-github-connector
cp .env.example .env

docker compose up --build
```

API:

```text
http://localhost:8000
```

OpenAPI:

```text
http://localhost:8000/docs
```

Health:

```bash
curl http://localhost:8000/health
```

## GitHub Connector

Para repositórios públicos, a API pode funcionar sem token, sujeita aos limites públicos do GitHub.

Para repositórios privados ou maior limite de API, configure localmente:

```dotenv
GITHUB_TOKEN=seu_token_local
```

O token é lido apenas do ambiente e usado no header de autenticação. Ele **não deve ser salvo no banco, em eventos, logs de contexto ou no repositório**.

Exemplo de fonte:

```json
{
  "source_type": "github",
  "external_id": "owner/repository",
  "url": "https://github.com/owner/repository",
  "label": "Código principal"
}
```

Depois de vincular a fonte:

```text
POST /projects/{project_id}/github/sync
```

A sincronização transforma os dados técnicos em eventos compactos. O código-fonte do repositório não é copiado para o banco.

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
```

## Exemplo: continuar projeto

```text
GET /projects/{project_id}/continue?profile=standard
```

O Context Engine pode devolver uma combinação compacta de:
- status e próxima ação;
- resumos recentes;
- decisões ativas;
- tarefas pendentes;
- fatos/notas recuperáveis;
- commits, PRs, Issues e Actions relevantes.

Ele informa também:
- tokens candidatos;
- tokens selecionados;
- quantidade de itens selecionados;
- fontes utilizadas.

## Testes

```bash
python -m venv .venv
source .venv/bin/activate   # Linux/macOS
# .venv\Scripts\activate   # Windows
pip install -r requirements.txt
pytest -q
```

A suíte usa SQLite em memória e dados fictícios. Os testes do GitHub usam um leitor simulado e não dependem da rede nem de credenciais reais.

## Privacidade

Este repositório é público. Portanto:
- não versionar `.env`;
- não versionar tokens ou senhas;
- não versionar conversas pessoais;
- não versionar dumps reais da memória operacional;
- não versionar documentos privados;
- usar apenas dados fictícios nos testes.

A memória real deve ficar no PostgreSQL da instalação privada.

## Documentação

- `docs/ARCHITECTURE.md`
- `docs/DATA_MODEL.md`
- `docs/CONTEXT_ENGINE.md`
- `docs/ROADMAP.md`

## Próximo marco

Após o M3, o M4 será a **Session Memory**: transformar uma sessão longa em um `SessionDelta` pequeno, contendo decisões, tarefas, alterações de status e próxima ação para reutilização futura.
