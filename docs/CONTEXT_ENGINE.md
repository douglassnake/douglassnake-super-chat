# Context Engine

## Propósito

Montar o menor pacote de contexto capaz de responder corretamente à intenção atual, preservando rastreabilidade e reduzindo repetição de histórico.

## Níveis de contexto

### `minimal`
Uso: perguntas simples e leitura rápida.

Inclui:
- identificação do projeto;
- status atual;
- próxima ação;
- até 3 decisões recentes;
- até 5 tarefas abertas.

Meta: 1–2k tokens.

### `standard`
Uso: continuidade normal do projeto.

Inclui:
- tudo do `minimal`;
- resumo consolidado;
- decisões relevantes;
- backlog prioritário;
- últimos eventos técnicos;
- referências externas necessárias.

Meta: 3–6k tokens.

### `deep`
Uso: arquitetura, debugging e revisão de decisões.

Inclui:
- histórico resumido ampliado;
- decisões correlatas;
- documentação técnica;
- eventos e fontes adicionais.

Meta: 10–20k tokens.

### `expanded`
Uso excepcional.

Recupera histórico/artefatos maiores somente quando os níveis menores não bastam.

## Pipeline

```text
UserMessage
  ↓
IntentResolver
  ↓
ProjectResolver
  ↓
CandidateRetriever
  ↓
Scorer
  ↓
Deduplicator
  ↓
TokenBudgeter
  ↓
ContextPackageBuilder
```

## Ranking

Cada item candidato recebe uma pontuação composta por:

- relevância semântica;
- prioridade da entidade;
- recência;
- força da fonte;
- relação direta com o projeto;
- estado aberto/pendente;
- penalidade por redundância.

Uma implementação inicial pode usar pesos determinísticos antes de adicionar embeddings.

## Estrutura de saída

```json
{
  "project": {
    "id": "...",
    "name": "...",
    "status": "...",
    "next_action": "..."
  },
  "summary": "...",
  "decisions": [],
  "tasks": [],
  "events": [],
  "sources": [],
  "budget": {
    "profile": "standard",
    "estimated_tokens": 4200,
    "max_tokens": 6000
  }
}
```

## Resumo incremental de sessão

Ao encerrar ou consolidar uma sessão, gerar um `SessionDelta`:

```json
{
  "project_id": "...",
  "summary": "...",
  "decisions_created": [],
  "tasks_created": [],
  "tasks_closed": [],
  "status_change": null,
  "next_action": "...",
  "source_refs": []
}
```

O delta atualiza a memória operacional sem exigir reprocessamento completo da conversa.

## Regras de segurança

- não incluir secrets no contexto;
- não persistir credenciais recebidas em texto;
- não indexar automaticamente arquivos privados sem autorização do conector;
- manter referência para a origem de cada item relevante;
- separar `source_text` de `generated_summary`;
- permitir invalidar/resumir novamente memória derivada.

## Métricas

Registrar por montagem de contexto:
- perfil solicitado;
- quantidade de candidatos;
- itens selecionados;
- tokens estimados;
- fontes usadas;
- tempo de recuperação;
- taxa de compressão aproximada.

A métrica central é `context_efficiency = selected_tokens / candidate_tokens`.
