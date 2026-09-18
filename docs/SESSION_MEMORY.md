# Session Memory — M4

## Objetivo

A Session Memory reduz uma sessão longa a um `SessionDelta` pequeno e revisável. O delta não altera a memória operacional enquanto estiver `pending`.

A aplicação exige uma ação explícita de confirmação.

```text
conversa longa
   ↓
SessionDelta
   ↓
pending
   ├── preview
   ├── discard
   └── apply (confirmação explícita)
          ↓
      memória operacional
      ├── session_summary
      ├── decisions
      ├── tasks
      ├── tarefas concluídas
      ├── status
      └── próxima ação
```

## Por que isso economiza contexto

Em vez de reapresentar toda a conversa ao modelo em uma sessão futura, o Context Engine recupera os efeitos consolidados que foram confirmados:

- resumo;
- decisões;
- tarefas;
- status;
- próxima ação.

O texto bruto pode permanecer na origem, enquanto a memória operacional mantém apenas o estado necessário para continuidade.

## Estados

### `pending`

Delta criado, ainda sem efeitos na memória operacional.

### `applied`

Delta confirmado e aplicado. Não pode ser aplicado novamente.

### `discarded`

Delta rejeitado. Não pode ser aplicado posteriormente.

## Contrato de criação

```json
{
  "session_key": "chat-2026-09-18-001",
  "summary": "Resumo operacional da sessão.",
  "decisions": [
    {
      "title": "Decisão",
      "body": "Conteúdo da decisão",
      "rationale": "Motivo",
      "source_ref": "chat:..."
    }
  ],
  "tasks": [
    {
      "title": "Próxima tarefa",
      "description": "...",
      "priority": 100
    }
  ],
  "close_task_ids": [],
  "status_change": "implementation",
  "next_action": "Executar a próxima etapa",
  "source_refs": ["chat:2026-09-18"]
}
```

## Endpoints

Criar delta:

```text
POST /projects/{project_id}/session-deltas
```

Listar deltas:

```text
GET /projects/{project_id}/session-deltas
GET /projects/{project_id}/session-deltas?status=pending
```

Visualizar efeitos antes da confirmação:

```text
GET /session-deltas/{delta_id}/preview
```

Confirmar e aplicar:

```text
POST /session-deltas/{delta_id}/apply
```

Descartar:

```text
POST /session-deltas/{delta_id}/discard
```

## Garantias do M4

- `project_id + session_key` é único;
- um delta aplicado não é reaplicado;
- um delta descartado não é aplicado;
- tarefas a concluir precisam existir e pertencer ao projeto;
- referências inválidas impedem a aplicação antes das alterações;
- resumo, decisões, tarefas e atualização do projeto são persistidos na mesma transação;
- criação do delta pendente não modifica status, tarefas, decisões ou resumo do projeto.

## Limite deliberado

O M4 não chama um modelo de IA para gerar o delta. A API recebe um `SessionDelta` já estruturado. Isso separa duas responsabilidades:

1. **inferência** — agente/modelo propõe o delta;
2. **persistência** — Super Chat valida, apresenta preview e só aplica após confirmação.

Essa separação evita que uma inferência do modelo se torne memória permanente automaticamente.

## Próxima evolução

A interface web poderá mostrar um cartão de revisão como:

```text
Resumo da sessão
+ 2 decisões
+ 3 tarefas
- 1 tarefa concluída
Status: planning → implementation
Próxima ação: ...

[Aplicar à memória] [Descartar]
```
