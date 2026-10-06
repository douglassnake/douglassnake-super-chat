# Interface Web — M5 → M11

## Objetivo

Disponibilizar o núcleo do Segundo Cérebro sem exigir consumo direto da API. A interface é servida pela própria FastAPI em `/app/` e não depende de build frontend separado.

Desde M10/M11, a UI deixou de ser apenas consulta operacional e passou a permitir edição controlada e navegação pelo grafo do conhecimento.

## Navegação principal

A interface oferece duas visões complementares:

- **Painel** — operação diária de projetos, tarefas, decisões, memórias e fontes;
- **Grafo** — exploração das relações entre projetos, entidades, documentos e demais nós de conhecimento.

O Painel é a visão primária. O Grafo é uma visão secundária para retomada, entendimento de dependências e navegação contextual.

## Dashboard

Exibe:
- total de projetos;
- projetos que precisam de atenção;
- SessionDeltas pendentes;
- Health Score de cada projeto;
- atalhos para CRUD operacional;
- alternância Painel/Grafo.

## CRUD operacional — M10.2

Pela Web é possível:
- criar e editar projetos;
- criar tarefas;
- concluir tarefas;
- registrar decisões;
- registrar memórias;
- adicionar fonte GitHub;
- atualizar o dashboard após mudanças.

As operações continuam passando pelas regras da API e não transformam o navegador em um executor externo genérico.

## Projeto

A visão de projeto apresenta:
- status;
- próxima ação;
- descrição;
- última atualização;
- tarefas;
- decisões;
- memórias;
- fontes vinculadas;
- eventos técnicos recentes;
- SessionDeltas pendentes;
- acesso ao onboarding GitHub.

## Onboarding GitHub — M10.3

Quando necessário, o projeto pode abrir:

```text
/projects/{project_id}/github/onboarding
```

O fluxo ajuda a:
- identificar a fonte GitHub;
- vincular o repositório correto;
- preservar revisão humana;
- retomar o projeto sem depender de edição manual da base.

M10.3.1 refinou legibilidade e continuidade do fluxo.

## Continuar projeto

A UI chama:

```text
GET /projects/{project_id}/continue
```

O usuário escolhe o perfil `minimal`, `standard` ou `deep`.

O resultado apresenta:
- itens selecionados;
- tokens selecionados;
- tokens candidatos;
- orçamento máximo;
- referências relevantes.

## Session Memory

Cada delta pendente possui preview. A UI permite:
- revisar efeitos;
- aplicar;
- descartar.

Aplicar ou descartar exige confirmação explícita no navegador.

## Grafo — M11

### Nós

O grafo pode exibir:
- projetos;
- tarefas;
- decisões;
- memórias;
- fontes;
- documentos/arquivos;
- entidades de conhecimento;
- itens pendentes de revisão quando aplicável.

Projetos recebem maior destaque visual para preservar a hierarquia operacional.

### Interação

A visão suporta:
- zoom;
- pan;
- filtros por tipo;
- foco em um nó;
- vizinhança do nó selecionado;
- inspector lateral;
- labels periféricos sob interação;
- relações semânticas direcionadas.

### Inspector

O inspector distingue:
- relações de saída: `RELATION → Target`;
- relações de entrada: `← RELATION · Source`.

Isso evita tratar relações direcionadas como conexões simétricas.

### Documentos

Documentos podem ser cadastrados como entidades do grafo com metadados como:
- título;
- tipo;
- fonte;
- external ID;
- path/URL;
- descrição;
- rationale.

Um projeto pode se ligar a um documento via `HAS_DOCUMENT`.

### Sugestões e revisão humana

Descobertas automáticas não são persistidas silenciosamente.

Cada suggestion batch pode carregar:
- relação sugerida;
- evidência;
- confiança;
- estado.

A UI permite:
- **Aplicar**;
- **Descartar**;
- **Revisar depois**.

Somente **Aplicar** cria a relação persistente.

## Health Score

O score é determinístico, explicável e limitado ao intervalo 0–100.

Penalidades atuais:
- ausência de próxima ação: até 20 pontos;
- tarefas vencidas: até 24 pontos;
- tarefas bloqueadas: até 24 pontos;
- inatividade: até 25 pontos;
- SessionDeltas pendentes: até 15 pontos;
- falhas recentes de CI: até 20 pontos.

Faixas:
- `healthy`: 85–100;
- `attention`: 65–84;
- `risk`: 40–64;
- `critical`: 0–39.

O score não é uma avaliação subjetiva de qualidade do projeto. É um indicador operacional.

## Segurança

- conteúdo textual vindo da API é escapado antes de entrar no HTML;
- URLs são aceitas apenas com protocolos HTTP/HTTPS;
- SessionDelta não é aplicado sem confirmação;
- relações sugeridas não são aplicadas automaticamente;
- credenciais GitHub não são expostas na interface;
- a UI não contém secrets reais;
- ações externas permanecem fora do fluxo CRUD comum.

Veja também `docs/KNOWLEDGE_GRAPH.md`.
