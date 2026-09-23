# Douglas Snake — Super Chat

Interface central do **Segundo Cérebro**: um sistema de memória, contexto e execução que conecta projetos, GitHub, documentos e IA sem depender do histórico bruto de conversas.

## Objetivo

Permitir que um projeto possa ficar semanas sem atividade e seja retomado em poucos minutos, com contexto suficiente para responder:

- onde paramos;
- o que já foi decidido;
- qual é o estado atual;
- o que está pendente;
- qual é a próxima ação;
- quais fontes sustentam esse contexto.

## Papel do Super Chat

O Super Chat é a interface inteligente do Segundo Cérebro. Ele não substitui as fontes oficiais; ele as indexa, resume, relaciona e recupera sob demanda.

```text
Usuário
  ↓
Super Chat
  ↓
Context Engine
  ├── Memória operacional (PostgreSQL)
  ├── GitHub (fonte técnica)
  ├── Google Drive (fonte documental)
  └── Calendar / integrações
  ↓
Pacote de contexto mínimo relevante
  ↓
Modelo de IA
  ↓
Resposta / próxima ação
```

## M1 — Memória operacional

O M1 entrega a primeira API executável do Segundo Cérebro:

- FastAPI;
- PostgreSQL + SQLAlchemy 2;
- migrations Alembic;
- projetos, decisões, tarefas e resumos;
- entidades preparadas para fontes, eventos e itens de contexto;
- snapshot consolidado de cada projeto;
- Docker Compose;
- testes automatizados.

### Executar com Docker

Pré-requisito: Docker com Compose.

```bash
git clone https://github.com/douglassnake/douglassnake-super-chat.git
cd douglassnake-super-chat
git checkout codex/m1-operational-memory

docker compose up --build
```

A API ficará disponível em:

```text
http://localhost:8000
```

Documentação OpenAPI:

```text
http://localhost:8000/docs
```

Health check:

```bash
curl http://localhost:8000/health
```

O container da API executa `alembic upgrade head` antes de iniciar o Uvicorn.

### Configuração

Para customizar credenciais locais:

```bash
cp .env.example .env
```

Nunca versionar `.env`, tokens, chaves ou dados pessoais. O repositório é público.

### Executar testes

```bash
python -m venv .venv
source .venv/bin/activate   # Linux/macOS
# .venv\Scripts\activate   # Windows
pip install -r requirements.txt
pytest -q
```

Os testes usam SQLite em memória e dados fictícios; não precisam do banco de produção.

## Endpoints M1

```text
GET    /health
POST   /projects
GET    /projects
GET    /projects/{project_id}
PATCH  /projects/{project_id}
POST   /projects/{project_id}/decisions
GET    /projects/{project_id}/decisions
POST   /projects/{project_id}/tasks
GET    /projects/{project_id}/tasks
PATCH  /tasks/{task_id}
POST   /projects/{project_id}/summaries
GET    /projects/{project_id}/snapshot
```

O endpoint `snapshot` é a base para o futuro comando **continuar projeto**.

Exemplo conceitual:

```json
{
  "project": {
    "name": "MeuNegocioIA",
    "status": "M2.6",
    "next_action": "Implementar confirmação financeira"
  },
  "summary": {},
  "decisions": [],
  "open_tasks": [],
  "generated_at": "..."
}
```

## Princípios

1. **Contexto mínimo suficiente** — não carregar histórico completo quando um resumo estruturado basta.
2. **Fonte rastreável** — cada fato relevante deve apontar para sua origem.
3. **Memória externa ao modelo** — trocar o modelo de IA não pode apagar a memória do sistema.
4. **Separação público/privado** — este repositório contém apenas código, arquitetura, templates e documentação não sensível.
5. **Atualização incremental** — cada sessão produz um delta: decisões, mudanças, pendências e próxima ação.
6. **Human-readable first** — contexto importante deve permanecer legível por humanos e por agentes.

## Camadas de memória

- **PostgreSQL:** estado operacional, tarefas, decisões, relações, resumos e metadados.
- **Arquivos estruturados:** projeção legível do contexto de cada projeto.
- **GitHub:** código, commits, branches, PRs, Issues, Actions e documentação técnica.
- **Google Drive:** documentos, PDFs, Word, planilhas e arquivos oficiais.

## Context Engine

O Context Engine será desenvolvido no M2 e montará pacotes de contexto em níveis:

- **mínimo:** ~1–2k tokens;
- **padrão:** ~3–6k tokens;
- **profundo:** ~10–20k tokens;
- **histórico ampliado:** somente quando necessário.

Veja `docs/ARCHITECTURE.md`, `docs/DATA_MODEL.md`, `docs/CONTEXT_ENGINE.md` e `docs/ROADMAP.md`.
