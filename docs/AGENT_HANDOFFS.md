# Agent Handoffs — M8.1

## Objetivo

O `AgentHandoff` registra a entrega de um `AgentTaskPack` aprovado a um executor sem ampliar permissões implicitamente e sem executar ferramentas externas automaticamente.

Fluxo:

```text
AgentTaskPack approved
        ↓
AgentHandoff prepared
        ↓
release explícito
        ↓
AgentHandoff released
        ↓
executor trabalha somente no escopo declarado
        ↓
completed | failed | cancelled
```

O M8.1 é uma camada de autorização e auditoria. Os endpoints registram intenção, escopo e resultado; eles não iniciam Codex, não escrevem em GitHub/Drive/Calendar e não fazem merge/deploy/publicação.

## Criação

Um handoff só pode ser criado a partir de um pack `approved`.

Exemplo:

```json
{
  "executor_type": "codex",
  "executor_target": "local-worktree",
  "allowed_actions": [
    "read_repository",
    "modify_worktree",
    "run_tests",
    "create_commit"
  ],
  "notes": "Não criar PR nesta execução."
}
```

Quando `allowed_actions` é omitido, o handoff nasce sem permissões operacionais explícitas.

## Allowlist de ações

O M8.1 reconhece somente:

```text
read_context
read_repository
modify_worktree
run_tests
create_branch
create_commit
create_pull_request
```

Ações desconhecidas retornam `422`.

Estas ações nunca são autorizadas implicitamente pelo handoff:

```text
merge
deploy
publish
write_drive
write_calendar
write_external_service
```

O fato de um handoff estar `released` libera apenas os itens presentes em `allowed_actions`.

## Snapshot e fingerprint

O handoff grava:

- `pack_id` e `project_id`;
- fingerprint SHA-256 do pack entregue;
- snapshot compacto do objetivo, projeto, critérios de aceite, guardrails, áreas sugeridas, fontes e orçamento;
- executor e alvo;
- ações permitidas;
- timestamps de transição;
- resultado ou erro final.

O contexto textual completo não é duplicado na tabela de handoff. Na exportação Markdown, ele é recuperado do `AgentTaskPack` original e o fingerprint é validado antes da entrega. Como o conteúdo do pack não possui endpoint de edição, o fingerprint funciona como âncora de integridade.

## Estados

### `prepared`

Envelope criado, mas ainda não liberado.

```text
execution_released = false
```

### `released`

Liberação explícita registrada.

```text
execution_released = true
```

Somente as ações listadas em `allowed_actions` estão liberadas.

### `completed`

Resultado estruturado registrado após um handoff `released`.

### `failed`

Falha estruturada registrada após um handoff `released`.

### `cancelled`

Pode encerrar um handoff `prepared` ou `released`. Um handoff concluído ou falho não pode ser cancelado pelo mesmo endpoint.

Repetir a mesma transição terminal é idempotente e não sobrescreve os dados já registrados.

## Endpoints

```text
POST /agent-task-packs/{pack_id}/handoffs
GET  /agent-task-packs/{pack_id}/handoffs
GET  /agent-handoffs/{handoff_id}
POST /agent-handoffs/{handoff_id}/release
POST /agent-handoffs/{handoff_id}/complete
POST /agent-handoffs/{handoff_id}/fail
POST /agent-handoffs/{handoff_id}/cancel
GET  /agent-handoffs/{handoff_id}/markdown
```

## Exportação Markdown

O Markdown de handoff contém:

- IDs e fingerprint;
- executor/alvo;
- projeto e objetivo;
- critérios de aceite;
- ações explicitamente permitidas;
- ações nunca implicitamente autorizadas;
- guardrails;
- áreas sugeridas;
- contexto selecionado do Task Pack;
- fontes;
- orçamento de tokens;
- observações;
- regra de execução.

A exportação valida que o fingerprint atual do pack ainda corresponde ao fingerprint congelado no handoff.

## Redaction e resultados

Campos textuais do handoff e resultados estruturados passam pela mesma barreira de redaction usada nos Task Packs. O resultado JSON é limitado a aproximadamente 100 kB serializados.

Isso não substitui a regra operacional principal: secrets reais não devem ser fornecidos deliberadamente ao sistema nem versionados no repositório público.

## Fora do escopo

O M8.1 não:

- inicia um executor;
- chama Codex automaticamente;
- cria branch, commit ou PR por conta própria;
- faz merge;
- faz deploy;
- publica conteúdo;
- escreve em Drive/Calendar;
- transforma uma permissão declarada em chamada externa.

O próximo marco pode acompanhar uma execução real, mas deverá manter as permissões explícitas e a separação entre **planejar**, **liberar**, **executar** e **aprovar efeitos externos**.
