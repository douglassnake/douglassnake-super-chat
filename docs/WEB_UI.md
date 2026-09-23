# Interface Web — M5

## Objetivo

Disponibilizar o núcleo do Segundo Cérebro sem exigir consumo direto da API. A interface é servida pela própria FastAPI em `/app/` e não depende de build frontend separado.

## Componentes

### Dashboard

Exibe:
- total de projetos;
- projetos que precisam de atenção;
- SessionDeltas pendentes;
- Health Score de cada projeto.

### Projeto

Exibe:
- status;
- próxima ação;
- descrição/última atualização;
- tarefas abertas;
- fontes vinculadas;
- eventos técnicos recentes;
- SessionDeltas pendentes.

### Continuar projeto

A UI chama:

```text
GET /projects/{project_id}/continue
```

O usuário escolhe o perfil `minimal`, `standard` ou `deep`. O resultado apresenta itens selecionados, tokens selecionados, tokens candidatos e orçamento máximo.

### Session Memory

Cada delta pendente possui preview. A UI permite:
- revisar efeitos;
- aplicar;
- descartar.

Aplicar ou descartar exige confirmação explícita no navegador.

### GitHub

Quando existe fonte GitHub ativa, a UI expõe sincronização manual via:

```text
POST /projects/{project_id}/github/sync
```

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

O score não é uma avaliação subjetiva de qualidade do projeto. Ele é um indicador operacional baseado somente nas regras acima.

## Segurança

- conteúdo textual vindo da API é escapado antes de entrar no HTML;
- URLs são aceitas apenas com protocolos HTTP/HTTPS;
- SessionDelta não é aplicado sem confirmação;
- credenciais GitHub não são expostas na interface;
- a UI não contém dados pessoais fixos ou de teste reais.
