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

## Arquivos de contexto por projeto

```text
/context/
  PROJECT.md
  STATUS.md
  CONTEXT.md
  DECISIONS.md
  BACKLOG.md
  SUMMARY.md
  CODEX.md
```

Esses arquivos são projeções/artefatos de contexto. Conteúdo privado real não deve ser versionado neste repositório público.

## Context Engine

O Context Engine monta pacotes de contexto em níveis:

- **mínimo:** ~1–2k tokens;
- **padrão:** ~3–6k tokens;
- **profundo:** ~10–20k tokens;
- **histórico ampliado:** somente quando necessário.

## Primeira entrega

A primeira etapa implementa a fundação do Segundo Cérebro:

- modelo de dados;
- cadastro de projetos;
- memória de status/decisões/backlog;
- Context Engine;
- resumo incremental de sessões;
- integração somente-leitura com GitHub;
- endpoint `continuar projeto`;
- observabilidade do tamanho estimado do contexto.

Veja `docs/ARCHITECTURE.md`, `docs/CONTEXT_ENGINE.md` e `docs/ROADMAP.md`.
