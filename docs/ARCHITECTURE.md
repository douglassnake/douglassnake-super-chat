# Arquitetura — Super Chat / Segundo Cérebro

## 1. Objetivo arquitetural

O Super Chat deve transformar fontes dispersas em contexto mínimo, rastreável e reutilizável para humanos e agentes de IA.

O sistema separa quatro responsabilidades:

1. **fontes oficiais** — onde o dado realmente vive;
2. **memória operacional** — estado consolidado do Segundo Cérebro;
3. **recuperação de contexto** — seleção do que é necessário para cada pergunta;
4. **interface/agente** — conversa, comandos e execução.

## 2. Componentes

### Web UI

Responsável por:
- dashboard;
- lista de projetos;
- página de projeto;
- inbox;
- decisões;
- tarefas;
- histórico de sessões;
- visualização de contexto e estimativa de tokens.

### API

Responsável por:
- autenticação;
- CRUD de projetos;
- CRUD de decisões/tarefas/notas;
- ingestão de eventos;
- sincronização com conectores;
- montagem de contexto;
- geração de resumo incremental;
- endpoints para agentes.

### PostgreSQL

Fonte operacional do Segundo Cérebro.

Armazena entidades, relacionamentos, resumos e metadados. Não deve receber cópias integrais desnecessárias de documentos externos.

### Context Engine

Responsável por:
- resolver projeto/intenção;
- recuperar fatos relevantes;
- aplicar prioridade e recência;
- deduplicar conteúdo;
- respeitar orçamento de tokens;
- incluir referências para as fontes;
- produzir `ContextPackage`.

### Connectors

Primeira ordem:
- GitHub: leitura de commits, PRs, Issues, Actions e arquivos técnicos;
- Google Drive: metadados e conteúdo documental quando necessário;
- Google Calendar: compromissos/prazos associados;
- outras integrações entram depois da fundação.

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
    ├── status
    ├── decisões
    ├── tarefas
    ├── últimos eventos
    ├── GitHub/Drive sob demanda
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

## 4. Fontes de verdade

| Informação | Fonte de verdade |
|---|---|
| Código | GitHub |
| PR/commit/branch | GitHub |
| Documento oficial | Google Drive |
| Compromisso | Calendar |
| Status consolidado | PostgreSQL |
| Decisão operacional | PostgreSQL |
| Tarefa/backlog | PostgreSQL |
| Resumo de sessão | PostgreSQL |

## 5. Privacidade

O repositório é público. Portanto:
- não versionar conversas privadas;
- não versionar dados pessoais reais;
- não versionar tokens/chaves;
- não versionar dumps do PostgreSQL;
- não versionar documentos oficiais privados;
- usar apenas dados fictícios nos testes.

A instalação real deve manter banco e secrets no servidor privado.

## 6. Deploy alvo

```text
ZimaOS / servidor privado
├── reverse proxy
├── web
├── api
├── postgres
├── worker
└── backup

GitHub
└── código e contexto técnico público/não sensível

Google Drive
└── documentos oficiais
```

## 7. Critério de sucesso

Um projeto inativo por 30 dias deve ser retomável em poucos minutos com um pacote de contexto compacto contendo estado, decisões, fontes, pendências e próxima ação.
