# Roadmap

## M0 — Fundação documental
Status: **concluído**.

## M1 — Memória operacional
Status: **concluído**.

FastAPI, PostgreSQL, Alembic, projetos, decisões, tarefas, resumos, snapshot, Docker e testes.

## M2 — Context Engine v1
Status: **concluído**.

Perfis `minimal`, `standard` e `deep`, ranking determinístico, deduplicação, compactação, orçamento de tokens, auditoria e `continue`.

## M3 — GitHub Connector
Status: **concluído**.

GitHub somente leitura, commits, PRs, Issues, Actions, eventos normalizados e sync idempotente.

## M4 — Session Memory
Status: **concluído**.

`SessionDelta`, preview, confirmação humana, aplicação transacional e descarte.

## M5 — Interface web
Status: **concluído**.

Dashboard responsivo, Health Score explicável, projetos, tarefas, fontes, eventos, painel de tokens e revisão visual dos deltas.

## M6 — Google Drive e Calendar
Status: **concluído**.

Drive/Calendar somente leitura, metadados persistidos sem copiar documentos completos, recuperação sob demanda, eventos normalizados e sync idempotente.

## M7 — Qualidade de recuperação

### M7.0 — benchmark de contexto
Status: **concluído na branch `codex/m7-retrieval-benchmark`**.

Baseline sintético v1: cenário de pressão `minimal` com 13.926 tokens candidatos → 1.794 selecionados, compressão 0,871176 e recall@2 de 1,0 no fixture.

### M7.1 — busca híbrida/semântica
Status: **condicional — não iniciado**.

Embeddings/pgvector somente se benchmark privado com consultas reais demonstrar ganho mensurável.

## M8 — Automação e agentes

### M8.0 — Agent Task Packs
Status: **concluído**.

### M8.1 — handoff assistido e auditável
Status: **concluído**.

### M8.2 — acompanhamento de execução e evidências
Status: **concluído**.

### M8.3 — verificação externa GitHub somente leitura
Status: **concluído**.

### M8.4 — executor controlado
Status: **concluído**.

### M8.5 — adapter local isolado
Status: **concluído**.

### M8.6 — hardening do worker
Status: **concluído**.

Worker separado da API, workspace efêmero, limites de recurso, ambiente mínimo, timeout, redaction e contrato container sem rede por padrão.

### M8.7 — proveniência e reconciliação do worker
Status: **concluído na branch `codex/m8-7-worker-provenance`**.

`WorkerAttempt`, identidade, digests, lease/heartbeat, reconciliação, retry explícito e eventos append-only.

### M8.8 — alteração efêmera e diff revisável
Status: **concluído na branch `codex/m8-8-ephemeral-diff`**.

`modify_worktree` opera somente em cópia temporária, aceita `write_text`/`delete_file`, aplica limites/path policy/redaction e devolve unified diff + `patch_digest`, sem alterar o worktree original.

### M8.9 — aprovação por digest e branch Git dedicado
Status: **concluído na branch `codex/m8-9-reviewed-git-branch` após CI funcional verde**.

Entregas:
- migration `0008_git_change_approvals`;
- `GitChangeApproval` persistente, uma por proposta M8.8;
- snapshot mínimo de request/execution/project, `patch_digest`, fingerprint e arquivos alterados;
- estados `pending`, `approved` e `cancelled`;
- aprovação exige repetição exata do `patch_digest`;
- aprovação não produz efeito Git;
- eventos append-only de preparação, aprovação e cancelamento;
- `create_branch` como efeito independente sujeito à allowlist, `ExecutorRequest` e release próprios;
- namespace obrigatório `superchat/`;
- validação adicional com `git check-ref-format --branch`;
- branch criado a partir do `HEAD` local observado;
- branch já existente é conflito e nunca é sobrescrito;
- nenhum checkout, alteração de arquivo, commit ou push;
- Git executado por argv fixo, `shell=False`, ambiente mínimo e sem secrets herdados;
- nenhuma operação de rede no contrato de branch;
- proveniência e `WorkerAttempt` preservados;
- documentação `docs/GIT_CHANGE_APPROVAL.md`.

Capacidades reais atuais:
- `read_repository` → metadata;
- `run_tests` → pytest;
- `modify_worktree` → proposta efêmera + diff;
- `create_branch` → branch local `superchat/*` sem checkout/push.

Continuam sem implementação real:
- aplicar proposta aprovada no branch;
- `create_commit`;
- `create_pull_request`.

Continuam proibidos:
- merge;
- deploy;
- publicação;
- escrita em Drive/Calendar;
- escrita externa genérica;
- shell/comando/binário/argv arbitrário.

### M8.10 — aplicar proposta aprovada no branch
Status: **futuro/condicional**.

Antes de alterar arquivos persistentes:
- exigir `GitChangeApproval=approved`;
- reconstruir/revalidar a proposta e exigir o mesmo `patch_digest`;
- exigir branch `superchat/*` dedicado e verificar seu `base_sha`;
- detectar drift da base antes de aplicar;
- aplicar somente arquivos presentes no inventário aprovado;
- repetir validação de paths, symlinks, secrets, tamanho e UTF-8;
- mudança deve ocorrer no branch/worktree dedicado, sem commit implícito;
- produzir novo diff pós-aplicação e provar equivalência com o digest aprovado;
- rollback seguro em qualquer divergência;
- `create_commit` permanece autorização/etapa separada;
- push/PR, merge/deploy/publish continuam fora.

## Regra de evolução

Não ampliar autonomia antes de existir:
1. fonte de verdade;
2. modelo de dados;
3. rastreabilidade;
4. métrica de contexto;
5. autorização humana explícita;
6. evidência verificável;
7. política específica por efeito;
8. isolamento e limites de recurso;
9. worker separado e auditável;
10. proveniência/reconciliação;
11. diff revisável;
12. aprovação por digest;
13. efeito Git mínimo separado da aplicação de conteúdo;
14. aplicação somente após prova de digest/base sem drift.
