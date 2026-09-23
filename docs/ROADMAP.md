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
Status: **concluído**.

`modify_worktree` opera em cópia temporária e devolve unified diff + `patch_digest` sem alterar o fonte.

### M8.9 — aprovação por digest e branch Git dedicado
Status: **concluído**.

`GitChangeApproval` exige confirmação exata do digest. `create_branch` cria somente ref local `superchat/*`, sem checkout/push e sem sobrescrita.

### M8.10 — aplicar proposta aprovada em staging Git
Status: **concluído**.

`apply_git_change` resolve conteúdo server-side, verifica base/digest e mantém a mudança em worktree Git dedicado não commitado.

### M8.11 — commit controlado do staging aprovado
Status: **concluído funcionalmente na branch `codex/m8-11-explicit-commit` após suíte completa verde**.

Entregas:
- `create_commit` real no adapter `isolated-local`;
- payload público limitado a `apply_request_id` + `commit_message`;
- resolução server-side de staging, branch, `base_sha`, `patch_digest` e inventário;
- identidade Git exclusiva definida somente no servidor;
- staging e branch precisam continuar exatamente na base aprovada;
- inspeção do worktree sem `git diff`/`git status` para evitar filtros de conteúdo;
- comparação de arquivos rastreados com índice e `hash-object --no-filters`;
- arquivos adicionais, ignored/untracked extras e alterações pre-staged bloqueiam o commit;
- índice temporário iniciado com `read-tree base_sha`;
- somente paths aprovados entram no índice temporário;
- blobs criados por `hash-object --no-filters`;
- árvore validada por `diff-tree` contra o inventário aprovado;
- commit criado com `commit-tree`, sem hooks;
- ref movida atomicamente com `update-ref <novo> <base>` compare-and-swap;
- índice do staging sincronizado por `read-tree`, sem `reset --mixed` e sem filtros;
- pós-verificação de parent, branch, staging limpo e `patch_digest`;
- rollback da ref quando a pós-verificação falha;
- ambiente Git sem credenciais herdadas, hooks e fsmonitor desabilitados;
- teste com pre-commit hook e clean filter maliciosos confirma que nenhum executa;
- `push_performed=false` e `pull_request_created=false`;
- documentação `docs/EXPLICIT_COMMIT.md`.

Capacidades reais atuais:
- `read_repository` → metadata;
- `run_tests` → pytest;
- `modify_worktree` → proposta efêmera + diff;
- `create_branch` → branch local `superchat/*`;
- `apply_git_change` → staging Git dedicado;
- `create_commit` → commit local controlado.

Continuam sem implementação real:
- push remoto;
- `create_pull_request`.

Continuam proibidos:
- merge;
- deploy;
- publicação em produção;
- escrita em Drive/Calendar;
- escrita externa genérica;
- shell/comando/binário/argv arbitrário.

### M8.12 — publicação remota controlada
Status: **futuro/condicional**.

Próximos efeitos deverão permanecer separados:
1. publicar somente uma branch `superchat/*` já commitada e verificada;
2. criar pull request somente depois da publicação confirmada;
3. credencial/remote/repositório devem ser definidos pelo servidor, não pelo agente;
4. push deve usar atualização não destrutiva e rejeitar remote ref divergente;
5. PR deve registrar base/head/commit verificados;
6. merge, deploy e publish de produção continuam fora.

## Regra de evolução

Cada novo efeito externo deve ter autorização própria, input resolvido pelo servidor, prova de estado anterior, verificação pós-efeito e rollback quando possível. Conteúdo aprovado, branch, aplicação, commit, push, PR e merge são etapas distintas.
