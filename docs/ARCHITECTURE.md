# Arquitetura — Super Chat / Segundo Cérebro

## 1. Objetivo arquitetural

O Super Chat transforma fontes dispersas em contexto mínimo, rastreável e reutilizável para humanos e agentes de IA.

A arquitetura atual separa seis responsabilidades:

1. **fontes oficiais** — onde o dado externo realmente vive;
2. **memória operacional** — estado consolidado do Segundo Cérebro;
3. **grafo do conhecimento** — entidades compartilháveis e relações semânticas revisadas;
4. **recuperação de contexto** — seleção do que é necessário para cada pergunta;
5. **interface/agente** — navegação, CRUD, revisão e execução controlada;
6. **operação self-hosted** — autenticação, secrets, backup, restore, logs e HTTPS.

## 2. Componentes

### Web UI

Responsável por:
- dashboard;
- CRUD de projetos;
- tarefas, decisões e memórias;
- onboarding GitHub;
- Session Memory;
- visualização de contexto;
- painel do grafo;
- filtros, foco, zoom/pan e inspector;
- revisão humana de sugestões semânticas.

A interface é servida pela própria FastAPI em `/app/`.

### API

Responsável por:
- autenticação;
- CRUD de entidades operacionais;
- ingestão e sincronização;
- montagem de contexto;
- endpoints do grafo;
- criação e revisão de sugestões;
- endpoints para agentes;
- status/readiness operacional.

### PostgreSQL

Fonte operacional do Segundo Cérebro.

Armazena:
- projetos;
- tarefas;
- decisões;
- memórias;
- fontes;
- Session Memory;
- dados de execução dos agentes;
- sessões de autenticação;
- entidades e relações do grafo;
- batches de sugestões;
- relações entre entidades de conhecimento.

Não deve receber cópias integrais desnecessárias de documentos externos.

### Context Engine

Responsável por:
- resolver projeto/intenção;
- recuperar fatos relevantes;
- aplicar prioridade e recência;
- deduplicar conteúdo;
- respeitar orçamento de tokens;
- incluir referências para as fontes;
- produzir `ContextPackage`.

O grafo complementa o Context Engine; ele não substitui as fontes oficiais nem a memória operacional.

### Knowledge Graph

O M11 adiciona uma camada explícita de conhecimento relacional.

Núcleo:
- `knowledge_entities`;
- `project_relations`;
- `knowledge_relations`;
- `graph_suggestion_batches`.

Princípios:
- projetos permanecem o centro operacional;
- uma entidade canônica pode ser compartilhada por vários projetos;
- relações possuem tipo e direção;
- documentos podem ser entidades;
- descoberta automática produz sugestões, não fatos persistidos;
- aplicar uma relação exige revisão humana.

### Connectors

Fontes de primeira ordem:
- GitHub: commits, PRs, Issues, Actions e arquivos técnicos;
- Google Drive: documentos quando necessário;
- Google Calendar: compromissos/prazos;
- outras integrações entram somente com fronteira de autorização explícita.

## 3. Fluxo principal

```text
pergunta do usuário
    ↓
intent resolver
    ↓
project resolver
    ↓
Context Engine
    ├── project snapshot
    ├── tarefas/decisões/memórias
    ├── últimos eventos
    ├── relações semânticas relevantes
    ├── documentos relacionados
    ├── conectores sob demanda
    └── referências
    ↓
compressão / orçamento
    ↓
ContextPackage
    ↓
modelo de IA
    ↓
resposta
    ↓
session delta
    ├── decisões novas
    ├── alterações
    ├── tarefas
    └── próxima ação
    ↓
memória operacional
```

## 4. Fluxo do grafo

```text
projeto / documento / entidade
    ↓
descoberta determinística
    ↓
suggestion batch
    ├── evidência
    ├── confiança
    └── tipo sugerido
    ↓
revisão humana
    ├── aplicar
    ├── descartar
    └── revisar depois
    ↓
relação persistente tipada e direcionada
```

A descoberta deve suprimir duplicatas e relações já existentes.

## 5. Fontes de verdade

| Informação | Fonte de verdade |
|---|---|
| Código | GitHub |
| PR/commit/branch | GitHub |
| Documento oficial | fonte documental externa |
| Compromisso | Calendar |
| Status consolidado | PostgreSQL |
| Decisão operacional | PostgreSQL |
| Tarefa/backlog | PostgreSQL |
| Memória operacional | PostgreSQL |
| Entidade canônica do grafo | PostgreSQL |
| Relação semântica revisada | PostgreSQL |
| Conteúdo integral externo | fonte externa correspondente |

## 6. Execução controlada

O Controlled Executor não é um shell remoto genérico.

Sequência principal:

```text
Task Pack
  ↓
Handoff
  ↓
Agent Execution
  ↓
modify_worktree
  ↓
diff + digest
  ↓ aprovação
create_branch
  ↓
apply_git_change
  ↓
create_commit
  ↓
publish_branch / publish_github_branch
  ↓
create_pull_request
```

Cada efeito tem release próprio.

## 7. Privacidade e secrets

O repositório é público. Portanto:
- não versionar conversas privadas;
- não versionar dados pessoais reais;
- não versionar tokens/chaves/hashes reais;
- não versionar dumps do PostgreSQL;
- não versionar documentos oficiais privados;
- usar somente fixtures sanitizados nos testes.

Em produção:
- secrets ficam em arquivos privados montados read-only;
- `SECRET_BACKEND=files`;
- autenticação e cookies seguros são obrigatórios.

## 8. Deploy real validado

Topologia atual:

```text
ZimaOS / NAS
├── app
│   ├── FastAPI / Web UI
│   └── 127.0.0.1:8010
├── PostgreSQL 17
│   └── dados persistentes em /dev/sdc8
├── secrets privados
├── backup
│   └── /dev/md0 RAID1
└── Docker logs limitados

Caddy compartilhado
└── https://superchat.home.arpa
     ↓
     api:8000 via rede Docker
```

PostgreSQL não publica porta para a LAN.

O checkpoint real foi concluído em 06/10/2026:
- preflight `ready`;
- HTTPS `200`;
- API somente em loopback;
- backup automático validado;
- restore em banco descartável;
- integration readiness `pass`;
- banco principal sem restart;
- log rotation/storage audit aprovado.

## 9. Critério de sucesso

Um projeto inativo por 30 dias deve ser retomável em poucos minutos com:
- estado operacional;
- decisões;
- tarefas;
- memórias;
- fontes;
- documentos;
- relações relevantes;
- próxima ação;
- referências suficientes para auditoria.

O grafo deve melhorar retomada e navegação sem criar relações persistentes silenciosamente.
