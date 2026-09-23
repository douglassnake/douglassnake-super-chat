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
Status: **concluído funcionalmente na branch `codex/m8-14-github-publish-broker` após suíte completa + benchmark verdes**.

Entregas:
- nova ação `publish_github_branch`;
- handoff, `ExecutorRequest` e release próprios;
- adapter `github-publish` separado do worker;
- payload público limitado a `publish_request_id`;
- linhagem exige `publish_branch` M8.12 concluído e verificado;
- repository, ProjectSource, head branch e head SHA resolvidos server-side;
- branch restrita a `superchat/*`;
- bare local M8.12 é revalidado antes de adquirir a credencial;
- drift local bloqueia o efeito antes do broker;
- `CredentialBroker` + `SecretLease` efêmero em memória;
- backend inicial de broker por Settings substituível futuramente por Vault/KMS/OIDC;
- token de publicação separado do token de PR;
- token nunca entra em payload, fingerprint, `ExecutorRequest`, `WorkerJob`, log ou resultado;
- publisher real desativado por padrão;
- transporte autenticado usa URL sem token + `GIT_ASKPASS` efêmero;
- commit exato é publicado primeiro em ref temporária única `superchat-staging/<request-id>`;
- ref temporária usa compare-and-swap de ausência por `--force-with-lease=<ref>:`;
- SHA temporário é verificado antes da ref final;
- ref final `superchat/*` é criada pela API GitHub somente se ausente;
- branch final já existente bloqueia primeira publicação;
- pós-verificação exige head SHA exato;
- ref temporária é removida em cleanup;
- cleanup falho retorna `temporary_ref_cleanup_failed` e exige reconciliação manual;
- resultado de sucesso registra `github_publication_performed=true`, `pull_request_created=false`, `merge_performed=false`, `deploy_performed=false`;
- testes usam broker/publisher fake, sem rede ou segredo real;
- API `0.8.14`;
- documentação `docs/CONTROLLED_GITHUB_PUBLICATION.md`.

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

## Próxima fase — estabilização operacional

Antes de qualquer merge/deploy automatizado, priorizar:
1. revisar e integrar a pilha de PRs de forma ordenada;
2. autenticação/controle de acesso da interface web;
3. observabilidade, métricas e alertas do executor;
4. gestão de credenciais por backend dedicado (Vault/KMS/OIDC) em produção;
5. testes de recuperação/reconciliação em ambiente self-hosted;
6. somente depois avaliar novos efeitos externos.

## Regra de evolução

Cada efeito externo deve ter autorização própria, input resolvido pelo servidor, prova de estado anterior, verificação pós-efeito, segredo fora do estado persistido e reconciliação explícita quando rollback total não for possível.