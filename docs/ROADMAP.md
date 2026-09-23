# Roadmap

## M0 — Fundação documental

Status: **em andamento neste PR**.

Entregas:
- objetivo e princípios;
- arquitetura;
- Context Engine;
- modelo de dados;
- roadmap;
- backlog inicial.

## M1 — Memória operacional

Objetivo: colocar o Segundo Cérebro em funcionamento sem depender de IA generativa para organizar tudo.

Entregas:
- API FastAPI;
- PostgreSQL;
- migrations;
- CRUD de projetos;
- CRUD de decisões;
- CRUD de tarefas;
- contexto/resumo por projeto;
- endpoint de snapshot do projeto;
- testes;
- Docker Compose local.

Critério de aceite:
- cadastrar projeto;
- registrar decisão e tarefa;
- atualizar status/próxima ação;
- solicitar snapshot e receber estado consolidado.

## M2 — Context Engine v1

Entregas:
- perfis `minimal`, `standard`, `deep`;
- ranking determinístico;
- deduplicação;
- orçamento estimado de tokens;
- auditoria em `context_runs`;
- endpoint `/context/build`;
- endpoint `/projects/{id}/continue`.

Critério de aceite:
- montar pacote abaixo do orçamento configurado;
- informar fontes e tokens estimados;
- produzir contexto suficiente para retomar um projeto.

## M3 — GitHub Connector

Entregas:
- vínculo projeto ↔ repositório;
- commits recentes;
- branch padrão;
- PRs abertos;
- Issues abertas;
- Actions recentes;
- normalização em `events`;
- sync incremental.

Critério de aceite:
- `continuar projeto` inclui estado técnico recente sem copiar o repositório inteiro.

## M4 — Session Memory

Entregas:
- `SessionDelta`;
- decisões detectadas para confirmação;
- tarefas detectadas para confirmação;
- resumo incremental;
- atualização da próxima ação;
- trilha de origem.

Critério de aceite:
- uma sessão longa é reduzida a um resumo operacional pequeno e reaproveitável.

## M5 — Interface web

Entregas:
- dashboard;
- projetos ativos;
- health score;
- inbox;
- página de projeto;
- decisões;
- tarefas;
- histórico;
- painel de contexto/tokens;
- comando `continuar`.

## M6 — Google Drive e Calendar

Entregas:
- referências de documentos do Drive;
- recuperação sob demanda;
- prazos/compromissos do Calendar;
- associação a projetos.

## M7 — Busca semântica

Somente após métricas do M2–M6.

Entregas possíveis:
- pgvector;
- embeddings;
- busca híbrida lexical + vetorial;
- re-ranking.

## M8 — Automação e agentes

Entregas:
- geração de prompts Codex;
- preparação de tarefas técnicas;
- acompanhamento de PRs;
- rotinas de revisão;
- regras explícitas de aprovação humana para ações de escrita.

## Regra de evolução

Não adicionar complexidade de IA antes de existir:
1. fonte de verdade;
2. modelo de dados;
3. rastreabilidade;
4. teste de recuperação;
5. métrica de contexto.
