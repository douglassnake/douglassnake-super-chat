# M8.5 — Isolated Local Executor

## Objetivo

O adapter `isolated-local` é a primeira capacidade de execução real do Super Chat. Ele permanece **desabilitado por padrão** e só opera dentro de um root de worktrees configurado pelo servidor.

Ele não recebe shell, binário ou argv arbitrários do cliente. A API continua autorizando ações semânticas e o adapter converte somente contratos conhecidos em operações locais.

## Configuração

```env
EXECUTOR_ISOLATED_ENABLED=false
EXECUTOR_WORKTREE_ROOT=/srv/superchat/worktrees
EXECUTOR_TIMEOUT_SECONDS=60
EXECUTOR_MAX_TIMEOUT_SECONDS=300
EXECUTOR_OUTPUT_MAX_BYTES=65536
EXECUTOR_ENV_ALLOWLIST=SYSTEMROOT,TEMP,TMP,TMPDIR
```

O adapter só fica `available = true` quando:

1. `EXECUTOR_ISOLATED_ENABLED=true`;
2. `EXECUTOR_WORKTREE_ROOT` está definido;
3. o root existe e é diretório.

## Fronteira de path

Todo `worktree` e todo alvo de teste são recebidos como caminhos **relativos**.

O adapter resolve o caminho canônico e exige que o resultado permaneça dentro do root permitido. Isso bloqueia:

- caminhos absolutos;
- `..` que saia do root;
- symlink cujo destino real esteja fora do root;
- alvo inexistente.

Exemplo aceito:

```json
{
  "worktree": "meunegocioia",
  "preset": "pytest",
  "test_target": "tests/test_billing.py"
}
```

Exemplos rejeitados:

```text
/etc
../outro-projeto
worktree/link-para-fora
```

## Contratos reais do M8.5

### `read_repository`

Contrato:

```json
{
  "worktree": "projeto",
  "scope": "metadata"
}
```

Somente `scope=metadata` é aceito. O resultado contém metadados limitados, como nomes de entradas do primeiro nível, presença de `.git` e indícios de projeto Python. O adapter não lê conteúdo arbitrário de arquivos por esse contrato.

### `run_tests`

Contrato:

```json
{
  "worktree": "projeto",
  "preset": "pytest",
  "test_target": "tests/test_api.py",
  "timeout_seconds": 60
}
```

No M8.5 existe apenas o preset server-side `pytest`. O comando é construído internamente:

```text
<python-do-servidor> -m pytest -q <target-validado>
```

O cliente **não** escolhe executável, flags ou argv.

O subprocesso é criado com:

- `shell=False`;
- `stdin=DEVNULL`;
- `cwd` dentro do worktree validado;
- nova sessão de processo em POSIX;
- timeout configurável, limitado pelo máximo global;
- encerramento do grupo de processos em timeout, quando suportado;
- ambiente mínimo;
- captura de stdout/stderr em arquivo temporário;
- persistência limitada a `EXECUTOR_OUTPUT_MAX_BYTES` por stream.

## Ambiente

O adapter não herda `os.environ` integralmente.

Ele cria um ambiente mínimo e só copia variáveis presentes em `EXECUTOR_ENV_ALLOWLIST`. Mesmo na allowlist, nomes contendo marcadores sensíveis como `TOKEN`, `SECRET`, `PASSWORD`, `API_KEY` ou `AUTHORIZATION` são ignorados.

Isso reduz o risco de um teste enxergar credenciais do processo da API.

## Redaction

Antes de retornar/persistir resultado:

- stdout e stderr passam por redaction textual;
- resultado estruturado passa pela sanitização recursiva já usada pelo M8.4;
- a API continua aplicando uma segunda barreira antes da persistência.

A redaction é defesa adicional; não substitui o isolamento do ambiente.

## Ações ainda sem contrato real

As ações abaixo continuam reconhecidas pela política do M8.4, mas `isolated-local` retorna `unsupported` sem efeito externo:

```text
read_context
modify_worktree
create_branch
create_commit
create_pull_request
```

Elas só devem ganhar implementação após contrato específico por ação.

## O que continua proibido

```text
merge
deploy
publish
write_drive
write_calendar
write_external_service
shell arbitrário
comando/binário/argv arbitrário
```

## Estado e auditoria

O adapter não altera o protocolo do M8.4:

```text
ExecutorRequest prepared
        ↓ release explícito
released
        ↓ execute
running
        ↓
completed | failed
```

Cada transição continua produzindo eventos append-only no `AgentExecution`.

Uma request `completed` **não** transforma automaticamente critério de aceite em `passed`. Evidência continua sendo uma etapa separada do M8.2/M8.3.

## Limites desta versão

O M8.5 ainda não é sandbox de container ou VM. O isolamento desta versão é composto por:

- root de filesystem restrito e resolução canônica de paths;
- contratos semânticos fechados;
- ausência de shell arbitrário;
- ambiente mínimo;
- timeout/process-group kill;
- limite do volume persistido de saída;
- dupla autorização do M8.4.

Limites de CPU/memória via cgroups/container e filesystem realmente isolado devem entrar em uma etapa posterior antes de executar cargas não confiáveis.
