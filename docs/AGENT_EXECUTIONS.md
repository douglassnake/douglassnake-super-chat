# Agent Executions — M8.2

## Objetivo

O `AgentExecution` acompanha uma execução já autorizada por um `AgentHandoff` em estado `released`.

Ele não inicia Codex, não executa comandos e não cria branch, commit ou PR. O papel do M8.2 é registrar progresso, referências observadas e evidências explícitas para os critérios de aceite do `AgentTaskPack`.

```text
AgentTaskPack approved
        ↓
AgentHandoff released
        ↓
AgentExecution running
        ├── progresso
        ├── referências técnicas
        ├── evidências por critério
        └── eventos append-only
                 ↓
         todos os critérios passed?
              ↙       ↘
            não        sim
          bloqueia   complete
```

## Criação

Uma execução pode ser criada somente quando:

- o handoff existe;
- o handoff está `released`;
- o fingerprint do Task Pack ainda corresponde ao snapshot congelado no handoff;
- não existe outra execução para o mesmo handoff.

A relação `handoff_id` é única no banco, portanto uma segunda criação para o mesmo handoff retorna conflito.

Ao criar a execução, o sistema registra automaticamente o primeiro evento append-only:

```text
sequence = 1
event_type = started
```

## Estado atual e log append-only

`AgentExecution` guarda a visão atual:

- status;
- percentual de progresso;
- etapa atual;
- branch observada;
- commit observado;
- URL de PR observada;
- sequência atual de eventos;
- resultado/erro final;
- timestamps.

`AgentExecutionEvent` preserva a trilha histórica. Cada evento recebe uma sequência crescente única por execução e nunca é editado pelos endpoints do M8.2.

Tipos atuais de evento:

```text
started
progress
technical_refs
criterion_evidence
status
```

## Referências técnicas

Branch, commit e PR são **referências informativas**. Registrar:

```json
{
  "branch_ref": "codex/m8-2-execution-tracking",
  "commit_sha": "abc123",
  "pr_url": "https://github.com/exemplo/repositorio/pull/1"
}
```

não cria nem altera nenhum desses recursos.

O M8.2 não chama GitHub para produzir efeitos externos a partir desses endpoints.

## Evidências por critério

Cada evidência referencia o índice de um critério de aceite existente no Task Pack:

```json
{
  "criterion_index": 0,
  "status": "passed",
  "evidence_type": "pytest",
  "summary": "Suíte concluída sem falhas",
  "reference": "actions:run-123",
  "payload": {
    "passed": 30,
    "failed": 0
  }
}
```

Estados permitidos de evidência:

```text
passed
failed
```

O sistema não usa LLM para decidir o resultado do critério. O status precisa ser fornecido explicitamente junto da evidência.

### Regra da evidência mais recente

Um critério pode receber várias evidências. A cobertura atual usa a evidência de maior sequência para aquele índice.

Exemplo:

```text
critério 0
  seq 4 → failed
  seq 7 → passed

estado atual = passed
```

O histórico anterior permanece preservado no log append-only.

## Gate de conclusão

`POST /agent-executions/{execution_id}/complete` só é aceito quando todos os critérios do Task Pack possuem evidência mais recente `passed`.

A API calcula:

```json
{
  "total": 2,
  "passed": 2,
  "failed": 0,
  "pending": 0,
  "complete_allowed": true
}
```

Se houver qualquer critério `pending` ou `failed`, a conclusão retorna conflito e inclui a cobertura atual.

Isso impede marcar uma execução como concluída apenas porque houve progresso ou porque um executor informou informalmente que terminou.

## Sincronização com o handoff

Enquanto existe uma `AgentExecution`, os endpoints diretos de `complete`, `fail` e `cancel` do handoff são bloqueados. Isso impede contornar o gate de evidências.

As transições devem ocorrer pela execução:

```text
AgentExecution complete → AgentHandoff completed
AgentExecution fail     → AgentHandoff failed
AgentExecution cancel   → AgentHandoff cancelled
```

A atualização dos dois registros ocorre na mesma transação.

## Estados

### `running`

Aceita progresso, referências e evidências.

### `completed`

Exige todos os critérios com evidência mais recente `passed`. Define progresso em 100% e sincroniza o handoff para `completed`.

### `failed`

Registra erro e resultado parcial, sincronizando o handoff para `failed`.

### `cancelled`

Encerra a execução e sincroniza o handoff para `cancelled`.

Repetir a mesma transição terminal é idempotente e não sobrescreve o resultado já registrado.

## Endpoints

```text
POST /agent-handoffs/{handoff_id}/execution
GET  /agent-handoffs/{handoff_id}/execution
GET  /agent-executions/{execution_id}
GET  /agent-executions/{execution_id}/events
POST /agent-executions/{execution_id}/progress
POST /agent-executions/{execution_id}/technical-refs
POST /agent-executions/{execution_id}/evidence
POST /agent-executions/{execution_id}/complete
POST /agent-executions/{execution_id}/fail
POST /agent-executions/{execution_id}/cancel
```

## Redaction

Mensagens, referências, payloads e resultados passam pela barreira de redaction.

Além de padrões textuais como `token=...`, o M8.2 fortaleceu a sanitização para JSON estruturado. Valores sob chaves sensíveis, por exemplo:

```json
{
  "token": "valor",
  "secret": "valor",
  "password": "valor"
}
```

são substituídos por `[REDACTED]` recursivamente.

A proteção continua complementar: secrets reais não devem ser fornecidos deliberadamente nem versionados.

## Fora do escopo

O M8.2 não:

- inicia agentes;
- executa comandos;
- cria branch, commit ou PR;
- modifica PR ou CI;
- aprova ou faz merge;
- faz deploy;
- publica conteúdo;
- escreve em Drive/Calendar;
- decide automaticamente se um critério passou;
- conclui execução sem evidência explícita.

Uma próxima etapa pode observar, em modo somente leitura, PRs e Actions já existentes vinculados às referências registradas e anexar evidências verificáveis sem ampliar permissões de escrita.
