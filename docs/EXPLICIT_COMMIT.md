# M8.11 — commit Git explícito

O M8.11 transforma um staging M8.10 já aplicado e ainda íntegro em um **commit local**, sem push, pull request, merge, deploy ou publicação.

## Separação de autorização

```text
modify_worktree
   ↓ revisão
GitChangeApproval
   ↓
create_branch
   ↓
apply_git_change
   ↓
create_commit  ← nova autorização + release próprios
```

Nenhuma etapa autoriza a seguinte implicitamente.

## Payload público

O cliente pode informar somente:

```json
{
  "apply_request_id": "UUID",
  "commit_message": "feat: descrição curta"
}
```

A API recupera do banco, sem confiar no cliente:

- projeto;
- approval/staging id;
- worktree fonte;
- branch `superchat/*`;
- `base_sha`;
- `patch_digest`;
- inventário aprovado de arquivos.

A identidade Git também é exclusivamente server-side por `EXECUTOR_GIT_AUTHOR_NAME` e `EXECUTOR_GIT_AUTHOR_EMAIL`.

## Verificações antes do commit

O worker exige:

1. staging Git registrado e dentro de `EXECUTOR_GIT_STAGING_ROOT`;
2. branch e staging ainda apontando para `base_sha`;
3. nenhum path aprovado atravessando symlink;
4. índice real igual à árvore de `HEAD`;
5. conjunto de arquivos alterados exatamente igual ao inventário aprovado;
6. nenhum arquivo extra, inclusive ignored/untracked;
7. `patch_digest` atual igual ao digest aprovado.

A inspeção do worktree evita `git diff` e `git status` para não permitir execução indireta de filtros. Arquivos rastreados são comparados pelo índice e por `git hash-object --no-filters`; o índice é comparado à árvore de `HEAD` com plumbing Git.

## Construção do commit

O commit não usa `git add` genérico nem `git commit`.

```text
read-tree base_sha      → índice temporário
hash-object --no-filters→ blobs somente dos paths aprovados
update-index --cacheinfo→ inventário aprovado
write-tree              → árvore candidata
diff-tree               → paths precisam ser exatamente os aprovados
commit-tree             → objeto commit sem hooks
update-ref <ref> <novo> <base> → compare-and-swap atômico
read-tree <novo>        → sincroniza índice do staging sem filtros
```

O uso de índice temporário impede que arquivos não aprovados sejam incluídos acidentalmente. `hash-object --no-filters` evita clean filters. `commit-tree` não executa hooks; adicionalmente o ambiente Git força `core.hooksPath` para um caminho inerte e desabilita `core.fsmonitor`.

## Identidade e ambiente

O worker não herda tokens, credenciais ou configuração Git global/sistema. A identidade padrão é:

```text
Super Chat Executor <superchat-executor@localhost>
```

Ela pode ser alterada somente na configuração privada do servidor.

## Verificação pós-commit

Após o CAS da ref, o sistema verifica:

- `HEAD == commit_sha` no staging;
- `HEAD^ == base_sha`;
- branch local aponta para `commit_sha`;
- staging ficou limpo;
- conteúdo do commit reproduz o mesmo `patch_digest` aprovado;
- inventário pós-commit continua idêntico.

Se uma verificação posterior falhar, o worker tenta rollback da ref com compare-and-swap e restaura o índice por `read-tree base_sha`.

## Efeitos explicitamente ausentes

```text
push_performed = false
pull_request_created = false
merge = proibido
deploy = proibido
publish = proibido
```

O M8.11 cria somente um commit local na branch controlada.