# Observabilidade operacional — M9.1

O M9.1 adiciona observabilidade local e protegida ao Super Chat sem criar novo efeito externo, serviço de telemetria ou banco de auditoria.

## Correlação de requisições

Toda resposta HTTP normal recebe:

```text
X-Request-ID: <id>
```

Se o cliente enviar `X-Request-ID`, o valor só é reutilizado quando respeita o formato restrito de 8 a 128 caracteres ASCII (`A-Z`, `a-z`, `0-9`, `.`, `_`, `:`, `-`). Valores ausentes ou inválidos são substituídos por um identificador aleatório gerado pelo servidor.

O mesmo ID aparece no evento estruturado da requisição e pode ser usado para correlacionar uma resposta observada no navegador/reverse proxy com o log da API.

## Logs HTTP estruturados

O middleware emite uma linha JSON por requisição para `stdout`.

Exemplo:

```json
{"event":"http.request","request_id":"...","method":"GET","path":"/ops/status","status":200,"duration_ms":4.12,"username":"admin"}
```

O logger **não registra**:

- query string;
- body da requisição;
- cookies;
- `Authorization`;
- headers em geral;
- token de sessão ou CSRF;
- payloads/resultados do executor;
- texto de exceção não tratado.

Quando há exceção não tratada, o evento contém somente `exception_type`, nunca `str(exception)`.

A retenção/rotação do `stdout` continua responsabilidade do runtime/container no M9.1. Não há envio automático a serviço externo.

## Liveness x readiness

### `GET /health`

Público e mínimo:

```json
{"status":"ok"}
```

Serve apenas como **liveness** do processo. Não revela versão, ambiente ou banco.

### `GET /ops/status`

Protegido pelo M9.0 quando autenticação está habilitada. Retorna:

- `status`: `ready` ou `degraded`;
- versão da API;
- ambiente;
- estado da conexão com o banco;
- uptime aproximado do processo;
- horário da verificação.

Retorna HTTP `503` quando o banco não responde ao probe `SELECT 1`.

## Resumo operacional

`GET /ops/summary` retorna contagens derivadas **somente do estado já persistido**:

- `agent_executions` agrupadas pelo status real;
- `executor_requests` agrupadas pelo status real;
- `worker_attempts` agrupadas pelo status real;
- `git_change_approvals` agrupadas pelo status real;
- sessões de autenticação ativas/revogadas.

Sinais derivados:

- `stale_worker_leases`: tentativa cujo lease expirou e que ainda não está concluída, falhada ou marcada órfã;
- `pending_git_approvals`: aprovações de alteração Git ainda pendentes;
- falhas de `AgentExecution`, `ExecutorRequest` e `WorkerAttempt` nas últimas 24 horas.

O M9.1 não cria um estado fictício de “reconciliação”. Ele expõe os estados reais existentes para que o operador identifique divergências.

## Falhas recentes

`GET /ops/failures?limit=20` combina as falhas mais recentes de:

- `AgentExecution`;
- `ExecutorRequest`;
- `WorkerAttempt`, incluindo tentativas órfãs.

O endpoint nunca devolve `payload_json`, `result_json`, cookies, headers ou credenciais. `error_text` passa por sanitização e truncamento antes de ser retornado; formatos comuns de `Bearer`, senha/token/secret, credencial embutida em URL, token GitHub e JWT são substituídos por marcadores `[REDACTED]`.

## Segurança

Com `AUTH_ENABLED=true`, todo `/ops/*` exige sessão válida. Como os endpoints são `GET`, não há requisito de CSRF para consulta, mas continuam protegidos pelo cookie de sessão HttpOnly.

O M9.1 não altera nenhuma autorização do Controlled Executor. `merge`, `deploy`, publicação em produção e escrita externa genérica continuam fora da política.

## Limites intencionais

Ainda não há:

- Prometheus/Grafana;
- OpenTelemetry collector;
- exportação para SaaS de logs/APM;
- alertas externos;
- retenção centralizada de logs;
- novo banco de auditoria.

Essas integrações só devem ser avaliadas depois que o ambiente self-hosted estiver definido e sem permitir que dados sensíveis saiam da instalação por padrão.
