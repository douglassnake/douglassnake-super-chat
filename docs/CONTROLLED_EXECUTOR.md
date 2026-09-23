# M8.4 — Executor Controlado

## Objetivo

O M8.4 introduz a primeira fronteira de execução do Super Chat sem transformar o Segundo Cérebro em um executor autônomo irrestrito.

A autorização continua em camadas:

```text
Task Pack approved
        ↓
Handoff prepared
        ↓ release explícito
Handoff released + allowlist
        ↓
Agent Execution running
        ↓
Executor Request prepared
        ↓ release explícito
Executor Request released
        ↓ adapter explicitamente configurado
running → completed | failed
```

A conclusão de um `ExecutorRequest` **não** aprova automaticamente critérios de aceite e não conclui o `AgentExecution`. Evidências continuam seguindo o gate do M8.2/M8.3.

## Ações reconhecidas

A política inicial aceita somente ações semânticas já reconhecidas pelo handoff:

```text
read_context
read_repository
modify_worktree
run_tests
create_branch
create_commit
create_pull_request
```

A ação solicitada precisa passar por dois gates:

1. pertencer à política global `EXECUTOR_POLICY_ACTIONS`;
2. estar explicitamente presente em `AgentHandoff.allowed_actions`.

## Ações proibidas

O executor não aceita implicitamente:

```text
merge
deploy
publish
write_drive
write_calendar
write_external_service
shell
command
```

Novas capacidades de escrita exigem política própria em marco posterior.

## Sem shell arbitrário

O payload não é um wrapper para comandos livres. Chaves que permitem transportar um comando genérico são rejeitadas, inclusive quando aparecem aninhadas:

```text
argv
cmd
command
executable
script
shell
shell_command
```

Um adapter futuro para `run_tests`, por exemplo, deve interpretar campos semânticos como `test_target`, não receber `pytest -q ...` como string de shell.

## ExecutorRequest

Campos principais:

```text
execution_id
handoff_id
project_id
action
adapter_type
status
payload_json
fingerprint
notes
result_json
error_text
created_at
released_at
started_at
completed_at
failed_at
cancelled_at
```

O fingerprint SHA-256 é calculado deterministicamente a partir de:

```text
execution_id + action + adapter_type + payload sanitizado
```

Requests idênticos na mesma execução são rejeitados para reduzir replay acidental.

## Estados

```text
prepared
   ├── cancel → cancelled
   └── release → released
                    ├── cancel → cancelled
                    └── execute → running
                                     ├── completed
                                     └── failed
```

Requests `completed`, `failed` ou `cancelled` não podem ser executados novamente.

## Adapter padrão

O adapter `manual` é propositalmente inerte:

```text
available = false
```

Ele permite preparar e liberar um envelope auditável, mas o endpoint de execução retorna conflito e não executa nenhum processo externo.

Adapters reais devem implementar o contrato:

```python
class ExecutorAdapter(Protocol):
    name: str
    available: bool

    def execute(self, command: ExecutorCommand) -> ExecutorOutcome: ...
```

Os testes usam um adapter fake injetado; não dependem de shell, worker, rede ou credenciais externas.

## Eventos de auditoria

Toda transição relevante entra no log append-only do `AgentExecution`:

```text
executor_request
executor_released
executor_started
executor_result
```

O request cancelado também gera `executor_result` com `status=cancelled`.

## Redaction

Payload, notas, resultado e erro passam pelas barreiras existentes de redaction. Valores sob chaves sensíveis como `token`, `secret`, `password`, `api_key`, `authorization`, `access_token` e `refresh_token` são substituídos por `[REDACTED]`.

Redaction não torna seguro fornecer secrets deliberadamente; credenciais continuam fora dos requests.

## Endpoints

```text
POST /agent-executions/{execution_id}/executor-requests
GET  /agent-executions/{execution_id}/executor-requests
GET  /executor-requests/{request_id}
POST /executor-requests/{request_id}/release
POST /executor-requests/{request_id}/execute
POST /executor-requests/{request_id}/cancel
```

## Garantias do M8.4

- não existe endpoint de shell arbitrário;
- não existe adapter automático real habilitado por padrão;
- nenhuma ação pode escapar da allowlist do handoff;
- merge/deploy/publicação permanecem proibidos;
- request precisa de release explícito;
- terminal request não sofre replay;
- resultado do executor não vira evidência automaticamente;
- toda transição é auditável no `AgentExecutionEvent`.

## Próximo passo possível

Um marco posterior pode introduzir um adapter real executado em worker isolado, com política específica por ação, diretório de trabalho restrito, timeouts, limites de recurso e auditoria de artefatos. Essa etapa deve continuar sem autorização implícita para merge, deploy ou publicação.
