# M8.10 — Aplicar proposta aprovada em worktree Git dedicado

O M8.10 introduz a primeira persistência de **conteúdo** no Git local, mas mantém commit, push e pull request como etapas separadas.

## Pré-requisitos

A ação `apply_git_change` só pode ser preparada quando a API resolve, no banco:

- uma `GitChangeApproval` em estado `approved`;
- o `ExecutorRequest modify_worktree` que originou a proposta;
- as operações originais dessa proposta;
- o `patch_digest` aprovado;
- um `ExecutorRequest create_branch` concluído;
- branch `superchat/*` e `base_sha` observados na criação.

O payload público aceita somente:

```json
{
  "approval_id": "...",
  "branch_request_id": "..."
}
```

Operations, digest, worktree, branch e base SHA são reconstruídos server-side. O cliente não pode substituí-los.

## Fluxo

```text
proposta M8.8
   ↓
aprovação exata por digest M8.9
   ↓
branch superchat/* M8.9
   ↓
ExecutorRequest apply_git_change
   ↓ release explícito
branch ref == base_sha ?
   ↓ sim
cria worktree dedicado em staging
   ↓
reconstrói proposta a partir das operações originais
   ↓
digest reconstruído == digest aprovado ?
   ↓ sim
aplica arquivos no worktree de staging
   ↓
recalcula diff pós-aplicação
   ↓
digest pós-aplicação == digest aprovado ?
   ↓ sim
mantém staging não commitado
```

Qualquer divergência após a criação do staging executa `git worktree remove --force` e `git worktree prune`. O worktree fonte não recebe alterações de conteúdo.

## Drift

Antes de criar o staging, o worker resolve `refs/heads/<branch>` e exige igualdade com o `base_sha` registrado pelo request `create_branch`. Se o branch tiver se movido, retorna `drift_detected` sem criar conteúdo de staging.

## Staging

O diretório raiz é configurado exclusivamente pelo servidor em `EXECUTOR_GIT_STAGING_ROOT`. Cada aprovação usa um caminho determinístico `approval-<approval_id>`.

Em sucesso:

- o branch fica checkout apenas no worktree dedicado;
- arquivos aprovados ficam modificados/não commitados;
- `git status --porcelain=v1` é registrado no resultado;
- `HEAD` continua exatamente no `base_sha`;
- não há `git add`, commit, push ou PR.

## Resultado

O resultado de sucesso inclui:

- `status=applied_uncommitted`;
- `approval_id`;
- `branch_name`;
- `base_sha`;
- `patch_digest`;
- inventário de arquivos;
- `git_status`;
- `staging_id`;
- flags explícitas `commit_created=false`, `push_performed=false`, `pull_request_created=false`;
- proveniência M8.7.

## Limites

A aplicação reutiliza as mesmas políticas de alteração do M8.8: quantidade de arquivos/operações, bytes escritos, patch máximo, paths, symlinks, UTF-8 e secrets. O worker reconstrói a proposta antes da aplicação; portanto mudanças nas operações, no conteúdo base ou no digest fazem a execução falhar fechada.

## Fora do escopo

M8.10 não implementa:

- commit;
- identidade Git de autor para commit;
- push;
- pull request;
- merge;
- deploy/publicação.

O próximo estágio deve criar commit somente a partir de um staging M8.10 válido, com autorização independente e verificação final de HEAD/digest/status.