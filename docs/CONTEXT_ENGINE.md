# Context Engine

## Propósito

Montar o menor pacote de memória capaz de responder à intenção atual, preservando rastreabilidade e evitando carregar o histórico bruto do projeto.

## Perfis implementados no M2

| Perfil | Orçamento de memória | Máximo de itens | Uso |
|---|---:|---:|---|
| `minimal` | 1.800 tokens | 10 | perguntas simples e retomada rápida |
| `standard` | 5.000 tokens | 25 | continuidade normal de projeto |
| `deep` | 15.000 tokens | 60 | arquitetura, debugging e revisão profunda |

O orçamento é aplicado ao **contexto injetado**. A pergunta original do usuário não é contabilizada duas vezes, pois já faz parte da requisição ao modelo.

## Fontes recuperadas

O M2 usa:
- identificação/status/próxima ação do projeto;
- resumos de sessão;
- decisões ativas;
- tarefas abertas;
- `context_items` válidos.

GitHub, Drive e Calendar entram como conectores nas próximas etapas; quando normalizados em memória, passam pelo mesmo mecanismo de seleção.

## Pipeline v1

```text
Pergunta
  ↓
Projeto
  ↓
Candidate Retriever
  ├── summaries
  ├── decisions
  ├── tasks
  └── context_items
  ↓
Scorer determinístico
  ↓
Deduplicator
  ↓
Token Budgeter
  ↓
Context Package
  ↓
Auditoria em context_runs
```

## Ranking determinístico

Cada candidato recebe score a partir de:
- sobreposição lexical com a consulta;
- importância;
- recência;
- força do tipo de memória;
- força da fonte.

Pesos atuais:

```text
relevância lexical  40%
importância          25%
recência             15%
tipo de memória      10%
força da fonte       10%
```

Embeddings/pgvector não fazem parte do M2. Primeiro serão coletadas métricas reais do ranking determinístico.

## Deduplicação

Itens com conteúdo normalizado idêntico são reduzidos a uma única ocorrência. Quando há duplicatas, permanece o candidato de maior score.

## Controle de tokens

A estimativa v1 é conservadora e independente de provedor:

```text
ceil((caracteres / 4) × 1,15)
```

O projeto recebe uma pequena reserva estrutural. Itens são adicionados por score enquanto houver orçamento. Um item relevante que exceda o espaço restante pode ser truncado deterministicamente; caso ainda não caiba, é omitido.

## Endpoints

### Criar memória recuperável

```text
POST /projects/{project_id}/context-items
```

### Inspecionar memória

```text
GET /projects/{project_id}/context-items
```

### Montar contexto para uma consulta

```text
POST /context/build
```

Exemplo:

```json
{
  "project_id": "...",
  "query": "onde paramos e qual a próxima ação?",
  "profile": "standard"
}
```

### Retomar projeto

```text
GET /projects/{project_id}/continue?profile=standard
```

Esse endpoint usa uma consulta operacional padrão voltada para status, próxima ação, decisões, tarefas, pendências e bloqueios.

## Estrutura de saída

```json
{
  "project": {
    "id": "...",
    "name": "...",
    "status": "...",
    "next_action": "..."
  },
  "query": "...",
  "profile": "standard",
  "items": [
    {
      "kind": "decision",
      "title": "...",
      "content": "...",
      "source_type": "decision",
      "source_ref": "...",
      "score": 0.91,
      "estimated_tokens": 120
    }
  ],
  "sources": [],
  "budget": {
    "max_tokens": 5000,
    "estimated_tokens": 1840,
    "candidate_tokens": 9200,
    "candidate_count": 37,
    "selected_count": 12,
    "remaining_tokens": 3160
  }
}
```

## Auditoria

Cada construção gera um registro em `context_runs` com:
- perfil;
- consulta;
- quantidade de candidatos;
- quantidade selecionada;
- tokens candidatos;
- tokens selecionados;
- duração aproximada.

Isso permitirá medir compressão e decidir, com dados, quando busca vetorial realmente for necessária.

## Métrica central

```text
context_efficiency = selected_tokens / candidate_tokens
```

Quanto menor essa razão sem perda de qualidade na retomada do projeto, melhor o mecanismo está comprimindo a memória.

## Próxima evolução

O M3 adicionará o GitHub como fonte técnica real, normalizando commits, PRs, Issues e Actions para que o Context Engine selecione apenas os eventos relevantes.
