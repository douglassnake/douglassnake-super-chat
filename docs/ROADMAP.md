# Roadmap

## M0–M6 — Fundação, memória, contexto, interface e conectores
Status: **concluído**.

Incluem memória operacional, Context Engine, GitHub somente leitura, Session Memory, interface web e Google Drive/Calendar somente leitura.

## M7 — Qualidade de recuperação

### M7.0 — benchmark de contexto
Status: **concluído**.

Baseline sintético: 13.926 tokens candidatos → 1.794 selecionados, compressão 0,871176 e recall@2 de 1,0 no fixture.

### M7.1 — busca híbrida/semântica
Status: **condicional — não iniciado**.

Embeddings/pgvector somente se benchmark privado demonstrar ganho mensurável.

## M8 — Automação e agentes

### M8.0–M8.7
Status: **concluído**.

Task Packs, handoffs, execução/evidências, verificação GitHub, Controlled Executor, adapter isolado, worker endurecido e proveniência/reconciliação.

### M8.8 — alteração efêmera e diff revisável
Status: **concluído na branch `codex/m8-8-ephemeral-diff`**.

`modify_worktree` opera somente em cópia temporária, aceita `write_text`/`delete_file` e devolve unified diff + `patch_digest` sem alterar o fonte.

### M8.9 — aprovação por digest e branch Git dedicado
Status: **concluído na branch `codex/m8-9-reviewed-git-branch`**.

`GitChangeApproval` exige confirmação exata do digest. `create_branch` cria somente ref local `superchat/*`, sem checkout, commit, push ou rede e nunca sobrescreve branch existente.

### M8.10 — aplicar proposta aprovada em staging Git
Status: **concluído na branch `codex/m8-10-apply-approved-change` após CI funcional verde**.

Entregas:
- nova ação `apply_git_change` na política de handoff/executor;
- payload público limitado a `approval_id` + `branch_request_id`;
- resolução server-side de operations, digest, worktree, branch e `base_sha`;
- exige `GitChangeApproval=approved`;
- exige `create_branch` concluído no mesmo projeto/worktree;
- `EXECUTOR_GIT_STAGING_ROOT` privado e administrado pelo servidor;
- drift de branch detectado antes da criação do staging;
- worktree Git dedicado criado com argv fixo e sem rede;
- proposta reconstruída no staging e comparada ao `patch_digest` aprovado antes da escrita;
- paths, symlinks, UTF-8, secrets e limites revalidados;
- pós-aplicação recalcula o diff e exige exatamente o mesmo digest;
- falha pós-criação remove o staging com `git worktree remove --force` + prune;
- fonte não recebe alteração de conteúdo;
- sucesso mantém arquivos modificados/untracked no staging sem commit;
- `HEAD` do staging continua no `base_sha`;
- resultado registra `git_status`, inventário, digest e flags `commit_created=false`, `push_performed=false`, `pull_request_created=false`;
- proveniência e `WorkerAttempt` preservados;
- documentação `docs/APPLY_APPROVED_CHANGE.md`.

Capacidades reais atuais:
- `read_repository` → metadata;
- `run_tests` → pytest;
- `modify_worktree` → proposta efêmera + diff;
- `create_branch` → branch local `superchat/*`;
- `apply_git_change` → staging Git dedicado, não commitado.

Continuam sem implementação real:
- `create_commit`;
- `create_pull_request`.

Continuam proibidos:
- merge;
- deploy;
- publicação;
- escrita em Drive/Calendar;
- escrita externa genérica;
- shell/comando/binário/argv arbitrário.

### M8.11 — commit controlado do staging aprovado
Status: **futuro/condicional**.

Antes de criar commit:
- exigir um `apply_git_change` concluído;
- verificar `staging_id`, branch, `HEAD`, `base_sha` e `patch_digest`;
- provar que o status/diff atual ainda corresponde à aplicação aprovada;
- identidade Git de autor/committer definida no servidor, nunca no payload público;
- mensagem de commit limitada e sanitizada;
- `git add` restrito ao inventário aprovado;
- commit criado sem push;
- registrar `commit_sha` e verificar árvore/parent;
- nenhuma alteração adicional após aprovação;
- push/PR continuam etapas independentes;
- merge/deploy/publish permanecem fora.

## Regra de evolução

Cada novo efeito externo deve ter autorização própria, input resolvido pelo servidor, prova de estado anterior, verificação pós-efeito e rollback quando possível. Conteúdo aprovado, branch, aplicação, commit, push/PR e merge são etapas distintas.