# Roadmap

## M0–M6 — Fundação, memória, contexto, interface e conectores
Status: **concluído**.

Memória operacional, Context Engine, GitHub somente leitura, Session Memory, interface web e Google Drive/Calendar somente leitura.

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

Task Packs, handoffs, tracking, verificação GitHub, executor, isolamento, worker endurecido e proveniência/reconciliação.

### M8.8–M8.12
Status: **concluído**.

- M8.8: alteração efêmera + diff;
- M8.9: aprovação por digest + branch local;
- M8.10: aplicação em staging Git;
- M8.11: commit local por plumbing;
- M8.12: primeira publicação em bare local por CAS.

### M8.13 — Pull Request GitHub controlado
Status: **concluído**.

`create_pull_request` é efeito independente, usa adapter `github-pr`, resolve repositório/base/head/SHA server-side, exige head GitHub exato antes do PR e mantém token fora dos contratos persistidos. Testes são offline.

### M8.14 — publicação GitHub autenticada via credential broker
Status: **concluído**.

Entregas principais:
- ação `publish_github_branch` com handoff, `ExecutorRequest` e release próprios;
- adapter `github-publish` separado do worker;
- payload público limitado a `publish_request_id`;
- repository, ProjectSource, head branch e head SHA resolvidos server-side;
- bare local M8.12 revalidado antes da credencial;
- `CredentialBroker` + `SecretLease` somente em memória;
- token de publicação separado do token de PR;
- transporte autenticado por `GIT_ASKPASS` efêmero;
- commit exato publicado primeiro em ref temporária única;
- ref final `superchat/*` criada somente se ausente;
- pós-verificação de SHA e cleanup explícito;
- nenhuma atualização/force de branch final;
- nenhum PR, merge ou deploy implícito.

### M8.15 — estabilização e integration readiness
Status: **concluído funcionalmente na branch `codex/m8-15-integration-readiness` após suite, benchmark e migration smoke verdes**.

Objetivo: congelar a expansão de efeitos externos e provar que o topo M8.14 pode ser integrado de forma controlada.

Entregas:
- API `0.8.15`;
- `scripts/integration_readiness.py` com saída JSON e exit code fail-closed;
- validação dinâmica de um único base/head Alembic e ausência de merge revisions;
- validação dos defaults fail-closed de `isolated-local`, `github-pr` e `github-publish`;
- validação da fronteira global que mantém `merge`, `deploy` e `publish` proibidos;
- hardening de `Settings`: `DATABASE_URL`, tokens GitHub e credenciais Google sensíveis são excluídos de `model_dump()`, `model_dump_json()` e repr, preservando acesso em memória;
- separação comprovada das credenciais de leitura GitHub, criação de PR e publicação de branch;
- testes automatizados do readiness;
- job CI dedicado com PostgreSQL 17 limpo;
- `alembic upgrade head` real sobre banco vazio;
- pós-verificação de `alembic_version` contra o único head e presença das tabelas críticas;
- runbook `docs/INTEGRATION_READINESS.md` com ordem de integração da pilha e checkpoints humanos;
- nenhum novo efeito externo, merge ou deploy.

Validação funcional antes do fechamento documental:
- pytest: sucesso;
- benchmark CLI: sucesso;
- integration-readiness estático: sucesso;
- upgrade das 8 migrations em PostgreSQL 17 limpo: sucesso;
- verificação pós-migration: sucesso.

Fluxo real atual:

```text
modify_worktree
 ↓
aprovação digest
 ↓
create_branch
 ↓
apply_git_change
 ↓
create_commit
 ↓
publish_branch            # bare local
 ↓
publish_github_branch     # GitHub autenticado
 ↓
create_pull_request        # PR GitHub
```

Cada seta externa continua exigindo release próprio.

Continuam fora da política:
- atualização de branch GitHub existente;
- force push da branch final;
- merge;
- deploy;
- publicação em produção;
- shell/comando/binário/argv arbitrário;
- escrita externa genérica.

## Próxima fase — integração controlada

A próxima atividade não é um novo efeito. A prioridade é consumir a pilha de PRs de baixo para cima conforme `docs/INTEGRATION_READINESS.md`:

1. confirmar mergeabilidade e CI do PR atual;
2. integrar um único PR;
3. retargetar o próximo para `main`;
4. revisar o diff resultante;
5. aguardar CI verde;
6. interromper diante de qualquer divergência.

Depois da integração, priorizar autenticação/controle de acesso da interface web, observabilidade do executor, backend de credenciais dedicado e testes de recuperação no ambiente self-hosted antes de avaliar novos efeitos externos.

## Regra de evolução

Cada efeito externo deve ter autorização própria, input resolvido pelo servidor, prova de estado anterior, verificação pós-efeito, segredo fora do estado persistido e reconciliação explícita quando rollback total não for possível.