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

### M8.11 — commit controlado
Status: **concluído**.

`create_commit` usa Git plumbing, índice temporário, blobs sem filtros e `update-ref` compare-and-swap. Hooks/filtros ficam fora do caminho; nenhuma publicação remota ocorre implicitamente.

### M8.12 — publicação remota bare controlada
Status: **concluído**.

`publish_branch` exige autorização/release próprios, recebe publicamente apenas `commit_request_id`, usa remote bare local server-side, transporta objetos sem `git push`/`receive-pack` e cria a primeira ref `superchat/*` por `update-ref` CAS contra zero OID. Nenhuma sobrescrita ou force update.

### M8.13 — Pull Request GitHub controlado
Status: **concluído funcionalmente na branch `codex/m8-13-controlled-pull-request` após suíte completa + benchmark verdes**.

Entregas:
- `create_pull_request` mantém autorização e release independentes;
- adapter dedicado `github-pr`, separado do worker `isolated-local`;
- payload público limitado a `publish_request_id`, `title` e `body`;
- repository, ProjectSource, base branch, head branch, head SHA e draft policy resolvidos server-side;
- origem exige `publish_branch` M8.12 concluído no mesmo projeto;
- `remote_publication_performed=true` e `remote_sha == commit_sha` são obrigatórios;
- branch precisa manter namespace `superchat/*`;
- ProjectSource GitHub ativa precisa corresponder ao repositório de escrita configurado;
- writer GitHub desativado por padrão;
- token de escrita separado do token de leitura e nunca serializado no `ExecutorRequest`, `WorkerJob`, fingerprint, log ou resultado;
- M8.13 não publica branch no GitHub implicitamente;
- antes de criar PR, GitHub precisa reportar `head_branch` exatamente em `head_sha`;
- branch ausente retorna `head_not_published_to_github` sem efeito;
- head divergente retorna `head_drift_detected` sem efeito;
- PR aberto já existente bloqueia nova criação;
- POST do PR seguido de pós-verificação de repository/base/head/head SHA;
- falha após criação exige reconciliação manual em vez de marcar sucesso;
- replay interno para a mesma publicação é bloqueado;
- testes usam writer fake/offline e nunca criam PR externo;
- documentação `docs/CONTROLLED_PULL_REQUEST.md`;
- API `0.8.13`.

Capacidades reais atuais:
- `read_repository` → metadata;
- `run_tests` → pytest;
- `modify_worktree` → proposta efêmera + diff;
- `create_branch` → branch local `superchat/*`;
- `apply_git_change` → staging Git dedicado;
- `create_commit` → commit local controlado;
- `publish_branch` → primeira publicação em bare local controlado;
- `create_pull_request` → PR GitHub somente quando o head já existe no GitHub no SHA esperado e o writer está explicitamente habilitado.

Continuam sem implementação real:
- publicação autenticada da branch para GitHub;
- atualização de ref GitHub existente;
- credential broker para publicação Git remota.

Continuam proibidos:
- merge;
- deploy;
- publicação em produção;
- escrita em Drive/Calendar;
- escrita externa genérica;
- shell/comando/binário/argv arbitrário.

### M8.14 — publicação GitHub autenticada via credential broker
Status: **futuro/condicional**.

Próximos requisitos:
1. efeito separado para publicar uma branch já commitada/verificada no repositório GitHub configurado;
2. credencial obtida por broker e nunca incluída no `WorkerJob`/request persistido;
3. head/ref/repository resolvidos server-side;
4. atualização não destrutiva com SHA remoto esperado e sem force implícito;
5. pós-verificação exige GitHub head SHA exato;
6. nenhum PR/merge/deploy implícito;
7. M8.13 deve continuar apenas criando PR depois de o head GitHub existir.

## Regra de evolução

Cada novo efeito externo deve ter autorização própria, input resolvido pelo servidor, prova de estado anterior, verificação pós-efeito e rollback quando possível. Conteúdo aprovado, branch, aplicação, commit, publicação remota, publicação GitHub autenticada, PR e merge são etapas distintas.
