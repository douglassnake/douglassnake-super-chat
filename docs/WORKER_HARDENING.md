# M8.6 — Worker Hardening

## Objetivo

O M8.6 separa a execução real do processo da API e cria uma fronteira de worker com contrato versionado. A API continua responsável por autorização/auditoria; o worker recebe somente um job já validado e sem shell arbitrário.

```text
API
 ↓
ExecutorRequest released
 ↓
IsolatedLocalExecutorAdapter
 ↓
WorkerJob JSON v1
 ↓
ProcessWorkerClient
 ↓ processo separado
worker_entry
 ↓
backend de sandbox
 ├── subprocess-sandbox
 └── container (opcional)
```

## Contrato de job

`WorkerJob` contém apenas dados server-side necessários:

- `request_id`;
- ação semântica;
- root de worktrees configurado;
- worktree relativo;
- payload fechado do contrato;
- limites de execução;
- backend;
- allowlist de ambiente não sensível;
- configuração server-side do runtime/imagem de container.

A versão atual é `schema_version = 1`. Jobs com versão desconhecida são rejeitados.

## Ações reais

Continuam apenas:

- `read_repository` com `scope=metadata`;
- `run_tests` com preset server-side `pytest`.

As ações abaixo continuam sem contrato real e retornam `unsupported`:

- `modify_worktree`;
- `create_branch`;
- `create_commit`;
- `create_pull_request`.

Merge, deploy, publicação e shell arbitrário permanecem proibidos.

## Processo separado

`ProcessWorkerClient` inicia `python -m app.worker_entry` em subprocesso separado da API e troca apenas JSON via stdin/stdout. O processo do worker recebe ambiente mínimo e não herda secrets do processo da API.

O worker possui um deadline externo superior ao timeout interno. Se o worker inteiro travar, a API recebe falha controlada.

## Workspace efêmero

Para `run_tests`, o worker:

1. valida o root e worktree por path canônico;
2. valida todos os symlinks antes da cópia;
3. rejeita symlink que resolve para fora do worktree;
4. cria diretório temporário por request;
5. copia o worktree, excluindo `.git`, `.venv` e caches conhecidos;
6. executa o preset somente na cópia;
7. remove automaticamente o workspace temporário no retorno, inclusive em falha/timeout.

Assim, os testes não escrevem no worktree original.

## Backend `subprocess-sandbox`

Compatível com CI e sem dependência externa. Usa:

- `shell=False`;
- `stdin=DEVNULL`;
- grupo/sessão de processo para kill em timeout quando suportado;
- ambiente mínimo;
- saída em arquivos temporários e persistência truncada;
- redaction antes de retornar à API;
- `rlimit` em POSIX quando disponível.

Limites POSIX aplicados quando suportados:

- CPU (`RLIMIT_CPU`);
- memória virtual (`RLIMIT_AS`);
- processos (`RLIMIT_NPROC`);
- arquivos abertos (`RLIMIT_NOFILE`);
- tamanho de arquivo (`RLIMIT_FSIZE`).

O resultado registra `effective_limits` e `unsupported_limits`.

### Limite importante

`subprocess-sandbox` **não isola a rede**. O resultado registra explicitamente:

```text
network_policy = not_isolated_by_subprocess_backend
```

Para negar rede deve ser usado o backend de container em host administrado.

## Backend `container`

Opcional e desabilitado por configuração até existir runtime no servidor. O comando é montado exclusivamente pelo worker, não pelo cliente.

Política mínima:

- `--network none`;
- `--read-only` para o root do container;
- `--cap-drop ALL`;
- `no-new-privileges`;
- limite de PIDs;
- limite de memória;
- limite de CPU;
- `/tmp` em tmpfs com `noexec,nosuid`;
- somente a cópia temporária do worktree montada em `/workspace`;
- nunca montar `/var/run/docker.sock`.

O container continua executando apenas o preset `pytest` nesta etapa.

## Variáveis de configuração

```env
EXECUTOR_WORKER_BACKEND=subprocess-sandbox
EXECUTOR_WORKER_CPU_SECONDS=120
EXECUTOR_WORKER_MEMORY_MB=1024
EXECUTOR_WORKER_PIDS=128
EXECUTOR_WORKER_NOFILE=256
EXECUTOR_WORKER_FILE_SIZE_MB=64
EXECUTOR_CONTAINER_RUNTIME=docker
EXECUTOR_CONTAINER_IMAGE=python:3.13-slim
```

`EXECUTOR_ISOLATED_ENABLED=false` continua sendo o padrão.

## Auditoria

O resultado persistido pelo executor inclui, conforme aplicável:

- backend usado;
- status;
- motivo de terminação;
- duração;
- exit code;
- timeout;
- stdout/stderr truncados e redigidos;
- limites efetivos;
- limites não suportados;
- política de rede;
- confirmação lógica de cleanup do workspace.

## Não implica evidência automática

Um worker job concluído continua não aprovando automaticamente critério de aceite. A promoção de evidência permanece separada pelo mecanismo M8.2/M8.3.

## Próxima fronteira

Antes de habilitar escrita real em worktree/Git, o próximo marco deve exigir:

- imagem de worker pinada por digest;
- filesystem/base image imutáveis;
- política de egress explicitamente testada;
- limites de disco/IO quando o runtime suportar;
- fila/worker persistente ou broker;
- limpeza e reconciliação de jobs órfãos;
- identidade do executor e assinatura/proveniência do resultado;
- contratos separados para `modify_worktree`, `create_branch`, `create_commit` e `create_pull_request`.
