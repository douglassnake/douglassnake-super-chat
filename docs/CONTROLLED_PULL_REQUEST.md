# M8.13 — Pull Request GitHub controlado

O M8.13 adiciona `create_pull_request` como efeito externo independente. Ele não publica branch no GitHub, não faz merge, não dispara deploy e não altera produção.

## Separação de efeitos

O fluxo continua explícito:

```text
patch aprovado
  ↓
branch local
  ↓
staging
  ↓
commit local
  ↓
publicação M8.12 em bare local
  ↓
branch GitHub deve existir no mesmo SHA por efeito separado
  ↓
create_pull_request M8.13
```

M8.12 não publica em GitHub. Portanto M8.13 verifica, antes de criar o PR, que o `head_branch` já existe no repositório GitHub configurado exatamente em `head_sha`. Se não existir ou tiver drift, a operação termina sem efeito.

## Payload público

Somente estes campos são aceitos:

```json
{
  "publish_request_id": "<uuid>",
  "title": "opcional",
  "body": "opcional"
}
```

Repositório, base branch, head branch, head SHA, draft policy e source do projeto são resolvidos pelo servidor. Token, repository, URL, base/head SHA, remote, refspec, headers, SSH command e outros campos de controle não são aceitos do cliente.

## Gate de origem

`publish_request_id` precisa apontar para um `publish_branch` M8.12:

- concluído;
- da mesma execução/projeto;
- com `status=published_remote`;
- `remote_publication_performed=true`;
- `remote_sha == commit_sha`;
- branch `superchat/*`.

O projeto também precisa possuir uma source GitHub ativa que corresponda ao repositório configurado para escrita.

## Credencial separada do worker

O adapter do PR é `github-pr`, separado do `isolated-local`.

A credencial de escrita GitHub:

- fica desativada por padrão;
- é carregada apenas da configuração privada do servidor;
- não entra no `ExecutorRequest`;
- não entra no `WorkerJob`;
- não entra no fingerprint;
- não entra em eventos/resultados;
- não é usada nos testes.

O writer real é habilitado somente quando há configuração explícita e token dedicado.

## Pré-verificação GitHub

Antes do POST do PR, o adapter:

1. consulta o branch GitHub;
2. exige `observed_head_sha == head_sha`;
3. procura PR aberto existente para o mesmo head/base;
4. só então cria o PR.

Branch ausente retorna `head_not_published_to_github`. SHA divergente retorna `head_drift_detected`. PR aberto existente retorna `pull_request_already_exists`.

## Pós-verificação

Depois da criação, o adapter lê o PR novamente e exige:

- repository correto;
- base branch correta;
- head branch correta;
- head SHA exato.

Se o PR foi criado mas a pós-verificação falha, o resultado exige reconciliação manual e nunca marca a operação como sucesso.

## Resultado seguro

Em sucesso são persistidos apenas dados operacionais não secretos:

- repository;
- PR number;
- URL derivada do repositório/número;
- base branch;
- head branch;
- head SHA;
- draft;
- `pull_request_created=true`;
- `merge_performed=false`;
- `deploy_performed=false`.

## Configuração

```env
EXECUTOR_GITHUB_WRITE_ENABLED=false
EXECUTOR_GITHUB_WRITE_TOKEN=
EXECUTOR_GITHUB_WRITE_REPOSITORY=owner/repository
EXECUTOR_GITHUB_PR_BASE_BRANCH=main
EXECUTOR_GITHUB_PR_DRAFT=true
```

O token real nunca deve ser versionado.

## Testes

A suíte M8.13 usa writer fake e não faz chamadas de rede. Ela cobre:

- sucesso com release explícito;
- token server-side não serializado;
- branch GitHub ausente;
- drift do head SHA;
- injeção de repository/SHA/token pelo cliente;
- replay para a mesma publicação;
- writer desabilitado.

## Fora do M8.13

- publicar branch autenticada no GitHub;
- atualizar ref GitHub existente;
- auto-merge;
- merge manual pelo executor;
- deploy;
- publicação em produção.

Um credential broker/publicador GitHub autenticado permanece necessário para fechar o caminho entre o bare local M8.12 e o head GitHub exigido pelo M8.13.