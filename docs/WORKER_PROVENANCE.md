# M8.7 — Worker Provenance & Reconciliation

## Objetivo

Adicionar identidade, integridade e reconciliação ao worker endurecido do M8.6 sem ampliar os efeitos reais permitidos.

## WorkerAttempt

Cada execução `isolated-local` possui uma tentativa persistente:

```text
leased -> running -> completed | failed
   |          |
   |          +-> orphaned
   +-> expired
```

Uma tentativa terminal nunca é reaberta. Retry cria `attempt_number + 1` para o mesmo `ExecutorRequest`.

## Proveniência

O processo do worker inclui no resultado sanitizado:

- `worker_id` aleatório por processo;
- PID;
- fingerprint SHA-256 truncado do hostname;
- versão do schema do `WorkerJob`;
- backend;
- `job_digest` SHA-256;
- `result_digest` SHA-256;
- timestamps de início e fim.

A API não aceita esse envelope cegamente. `ProcessWorkerClient` recalcula o digest do job normalizado e do resultado e rejeita divergências antes de entregar o `WorkerResult` ao adapter.

## Lease

Uma lease possui:

- `lease_expires_at`;
- `heartbeat_at`;
- token aleatório devolvido somente no momento da criação;
- somente SHA-256 do token persistido.

Heartbeat exige o token original e não renova tentativas terminais ou expiradas.

## Reconciliação

`POST /worker-attempts/reconcile` procura tentativas `leased/running` com lease vencida.

- `leased` vencida -> `expired`;
- `running` vencida -> `orphaned`;
- se o request relacionado ainda estava `running`, ele é marcado `failed`;
- evento append-only `worker_orphaned` é registrado.

A reconciliação nunca inventa sucesso.

## Retry

`POST /executor-requests/{id}/retry` é o único caminho de retry.

Requisitos:

1. adapter `isolated-local`;
2. request em `failed`;
3. nenhuma tentativa ativa;
4. histórico de tentativa existente;
5. quantidade abaixo de `EXECUTOR_WORKER_MAX_ATTEMPTS`.

O retry volta o request para `released`, mas não apaga as tentativas anteriores. A próxima chamada a `/execute` cria uma nova tentativa.

## Endpoints

```text
GET  /executor-requests/{request_id}/worker-attempts
POST /executor-requests/{request_id}/worker-attempts/lease
GET  /worker-attempts/{attempt_id}
POST /worker-attempts/{attempt_id}/heartbeat
POST /worker-attempts/reconcile
POST /executor-requests/{request_id}/retry
```

## Ações reais

Continuam limitadas a:

```text
read_repository -> metadata
run_tests       -> pytest
```

Continuam sem contrato real:

```text
modify_worktree
create_branch
create_commit
create_pull_request
```

Merge, deploy e publicação continuam proibidos.

## Imagem de container

O M8.7 registra a imagem configurada na execução, mas ainda não habilita escrita. Antes de qualquer contrato de escrita via container, a imagem deverá ser pinada por digest (`@sha256:`), além dos gates de autorização existentes.
