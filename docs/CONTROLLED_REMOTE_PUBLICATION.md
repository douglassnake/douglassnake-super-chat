# M8.12 — Publicação remota controlada

O M8.12 adiciona o primeiro efeito de publicação remota do fluxo Git, mantendo a publicação separada de criação de pull request, merge, deploy e publicação em produção.

## Contrato

A ação semântica é `publish_branch`.

O payload público aceita somente:

```json
{
  "commit_request_id": "<uuid>"
}
```

A API resolve server-side o projeto, branch `superchat/*`, `commit_sha`, `base_sha`, `patch_digest`, staging e inventário. URL/path de remote, refspec, force, credenciais, tokens, headers, SSH command, executável ou argv fornecidos pelo cliente são rejeitados.

A ação exige um `create_commit` M8.11 concluído, do mesmo projeto, seguido de `ExecutorRequest` e `release` próprios para `publish_branch`.

## Remote inicial

Nesta etapa o remote precisa ser um repositório **bare local absoluto** configurado exclusivamente pelo servidor:

```env
EXECUTOR_GIT_PUBLISH_REMOTE=/srv/superchat/remotes/projeto.git
EXECUTOR_GIT_PUBLISH_REMOTE_ID=controlled-bare
```

Não há HTTPS/SSH autenticado no M8.12. Nenhuma credencial entra no payload público ou no `WorkerJob`.

## Pré-condições fail-closed

Antes do efeito, o worker verifica:

1. o remote configurado é bare e separado dos worktrees;
2. branch local e staging ainda apontam exatamente para `commit_sha`;
3. o parent do commit continua sendo `base_sha`;
4. staging permanece limpo;
5. a ref remota `refs/heads/superchat/*` ainda não existe.

Qualquer drift ou ref já existente encerra a operação sem sobrescrita.

## Transporte local sem push

O M8.12 deliberadamente não usa `git push` nem `receive-pack`.

O transporte é:

```text
branch local verificado
  ↓
git bundle create
  ↓
importação local de objetos no bare
  ↓
verificação do commit/parent
  ↓
git update-ref <ref> <commit_sha> <zero-oid>
  ↓
pós-verificação da ref
```

A criação da ref usa compare-and-swap contra zero OID, portanto uma ref criada concorrentemente não é sobrescrita.

O ambiente Git desabilita hooks e fsmonitor. Os testes instalam `pre-push`, `pre-receive` e `reference-transaction` maliciosos e exigem que nenhum deles seja executado pelo caminho controlado.

## Resultado auditável

Em sucesso, o resultado registra:

- `remote_id`;
- `branch_name`;
- `remote_ref`;
- `base_sha`;
- `commit_sha`;
- `remote_sha` observado;
- `patch_digest`;
- `remote_publication_performed=true`;
- `push_performed=false`;
- `receive_pack_used=false`;
- `force_used=false`;
- `pull_request_created=false`;
- transporte e política de rede/credenciais.

O path físico do remote é mascarado e não é persistido no `ExecutorRequest`.

## Limites desta etapa

M8.12 não implementa:

- remote HTTPS/SSH autenticado;
- atualização de uma ref remota já existente;
- force push;
- criação de pull request;
- merge;
- deploy;
- publicação em produção.

A próxima etapa deve tratar `create_pull_request` como autorização independente, referenciando somente uma publicação remota M8.12 já concluída e verificada.