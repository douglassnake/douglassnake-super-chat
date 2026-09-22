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
Status: **concluído**.

Entregas principais:
- `create_commit` real no adapter `isolated-local`;
- payload público limitado a `apply_request_id` + `commit_message`;
- resolução server-side de staging, branch, `base_sha`, `patch_digest` e inventário;
- identidade Git exclusiva definida somente no servidor;
- staging e branch precisam continuar exatamente na base aprovada;
- inspeção sem `git diff`/`git status` contra conteúdo;
- comparação por índice + `hash-object --no-filters`;
- índice temporário iniciado por `read-tree`;
- commit criado por `commit-tree`;
- ref local movida por `update-ref` compare-and-swap;
- hooks/filtros não executados;
- `push_performed=false` e `pull_request_created=false`.

### M8.12 — publicação remota controlada
Status: **concluído funcionalmente na branch `codex/m8-12-publish-branch` após pytest + benchmark verdes**.

Entregas:
- nova ação semântica `publish_branch`;
- handoff, `ExecutorRequest` e release próprios;
- payload público limitado a `commit_request_id`;
- branch, `commit_sha`, `base_sha`, `patch_digest`, staging e inventário resolvidos server-side;
- remote bare local absoluto definido somente pelo servidor;
- URL/refspec/force/credenciais/token/header/SSH command/argv fornecidos pelo cliente são rejeitados;
- exigir `create_commit` M8.11 concluído no mesmo projeto;
- branch local e staging precisam continuar exatamente no commit aprovado;
- staging precisa permanecer limpo;
- primeira publicação exige ref remota ausente;
- detecção de ref ausente usa consulta `--quiet`, evitando o exit 128 de `show-ref --verify --hash` em bare vazio;
- transporte de objetos por bundle local;
- sem `git push` e sem `receive-pack`;
- verificação do commit e parent importados antes de criar a ref;
- criação remota por `update-ref <ref> <commit_sha> <zero-oid>` compare-and-swap;
- nenhuma sobrescrita/force update;
- pós-verificação exige `remote_sha == commit_sha`;
- path físico do remote mascarado;
- `remote_publication_performed=true`;
- `push_performed=false`;
- `receive_pack_used=false`;
- `pull_request_created=false`;
- testes com `pre-push`, `pre-receive` e `reference-transaction` maliciosos;
- documentação `docs/CONTROLLED_REMOTE_PUBLICATION.md`.

Capacidades reais atuais:
- `read_repository` → metadata;
- `run_tests` → pytest;
- `modify_worktree` → proposta efêmera + diff;
- `create_branch` → branch local `superchat/*`;
- `apply_git_change` → staging Git dedicado;
- `create_commit` → commit local controlado;
- `publish_branch` → primeira publicação em remote bare local controlado.

Continuam sem implementação real:
- remote HTTPS/SSH autenticado;
- atualização de ref remota já existente;
- `create_pull_request`.

Continuam proibidos:
- merge;
- deploy;
- publicação em produção;
- escrita em Drive/Calendar;
- escrita externa genérica;
- shell/comando/binário/argv arbitrário.

### M8.13 — pull request controlado
Status: **futuro/condicional**.

Próximos requisitos:
1. `create_pull_request` deve ter autorização/release próprios;
2. payload público deve referenciar somente uma publicação M8.12 concluída;
3. repositório/base/head/commit devem ser resolvidos e verificados server-side;
4. criação de PR não pode implicar merge, deploy ou publicação de produção;
5. autenticação GitHub deve usar broker/credencial dedicada fora do `WorkerJob`;
6. pós-verificação deve registrar número/URL/head SHA do PR criado.

## Regra de evolução

Cada novo efeito externo deve ter autorização própria, input resolvido pelo servidor, prova de estado anterior, verificação pós-efeito e rollback quando possível. Conteúdo aprovado, branch, aplicação, commit, publicação remota, PR e merge são etapas distintas.
