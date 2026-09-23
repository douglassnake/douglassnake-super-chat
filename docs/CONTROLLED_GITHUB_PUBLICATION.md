# M8.14 — Publicação GitHub autenticada via credential broker

O M8.14 fecha o elo entre a publicação local/bare do M8.12 e a criação de Pull Request do M8.13. A publicação GitHub é um efeito independente: não cria PR, não faz merge e não dispara deploy.

## Payload público

A ação `publish_github_branch` aceita somente:

```json
{
  "publish_request_id": "<uuid>"
}
```

Repository, ProjectSource, branch e SHA são resolvidos pelo servidor a partir de um `publish_branch` M8.12 concluído e verificado.

## Credential broker

O token de publicação não pertence ao `ExecutorRequest` ou ao `WorkerJob`.

```text
ExecutorRequest
  ↓ release
adapter github-publish
  ↓
CredentialBroker.acquire(...)
  ↓
SecretLease em memória
  ↓
publisher autenticado
```

`SecretLease` não revela o segredo em `str()`/`repr()`. O backend inicial lê a credencial da configuração privada do servidor, mas a interface do broker permite futura substituição por Vault/KMS/OIDC sem alterar os contratos persistidos.

O token nunca entra em:

- payload público;
- payload resolvido;
- fingerprint;
- `ExecutorRequest`;
- `WorkerJob`;
- eventos;
- resultado.

## Pré-condições

Antes de adquirir a credencial, o adapter verifica o bare local M8.12:

- o source configurado é um repositório bare;
- `refs/heads/superchat/*` existe;
- a ref continua apontando exatamente para `head_sha` aprovado.

Drift local encerra a operação sem usar o broker.

Depois de adquirir a credencial, o publisher verifica que:

- a branch GitHub final ainda não existe;
- a ref temporária única ainda não existe.

## Publicação em duas fases

A transferência do commit exato é separada da criação da branch final:

```text
bare local M8.12
  ↓
ref temporária única superchat-staging/<request-id>
  ↓
verificação do SHA temporário
  ↓
POST GitHub git/refs (branch final only-if-absent)
  ↓
verificação head final == head_sha
  ↓
DELETE ref temporária
```

Para transportar o objeto, o publisher real usa `git push` somente contra a ref temporária única, com `--force-with-lease=<ref>:` para exigir que ela não exista. O branch final nunca é atualizado por esse push.

A ref final é criada pela API GitHub. Se ela aparecer em corrida, a API rejeita a criação em vez de sobrescrevê-la.

## Autenticação do transporte

O transporte Git usa URL sem segredo e um `GIT_ASKPASS` efêmero. O token é fornecido ao subprocesso somente por variável de ambiente em memória. O script askpass não contém o token e é removido com o diretório temporário.

O comando é fixo pelo servidor; o cliente não fornece URL, argv, refspec, header, SSH command ou `force`.

## Reconciliação

Se a branch final for criada mas a pós-verificação falhar, o resultado exige reconciliação manual.

A ref temporária é removida no `finally`. Se esse cleanup falhar, a execução retorna `temporary_ref_cleanup_failed`, mesmo que a branch final esteja correta, e exige reconciliação manual.

## Resultado de sucesso

O resultado seguro contém:

- repository;
- head branch;
- head SHA;
- identidade lógica do bare local;
- `temporary_ref_cleaned=true`;
- `github_publication_performed=true`;
- `pull_request_created=false`;
- `merge_performed=false`;
- `deploy_performed=false`;
- política de credencial/publicação.

## Configuração

```env
EXECUTOR_GITHUB_PUBLISH_ENABLED=false
EXECUTOR_GITHUB_PUBLISH_TOKEN=
EXECUTOR_GITHUB_PUBLISH_REPOSITORY=owner/repository
```

O token deve possuir apenas o escopo mínimo necessário e nunca deve ser versionado.

## Testes

A suíte M8.14 usa broker e publisher falsos, sem rede. Ela cobre:

- release explícito;
- segredo presente apenas no handoff efêmero broker → factory;
- ausência do segredo em request/result;
- injeção de repository/SHA/token/refspec bloqueada;
- drift do bare local antes de usar o broker;
- branch GitHub já existente;
- cleanup da ref temporária falhando com reconciliação manual.

## Fora do M8.14

- atualizar branch GitHub existente;
- criar PR implicitamente;
- merge;
- deploy;
- publicação em produção.

Com M8.14 concluído, o M8.13 pode operar de ponta a ponta: ele continuará fazendo sua própria pré-verificação do head GitHub antes de criar o Pull Request.