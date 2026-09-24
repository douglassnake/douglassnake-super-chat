# Roadmap

## M0–M6 — Fundação, memória, contexto, interface e conectores
Status: **concluído e integrado em `main`**.

Memória operacional, Context Engine, GitHub somente leitura, Session Memory, interface web e Google Drive/Calendar somente leitura.

## M7 — Qualidade de recuperação

### M7.0 — benchmark de contexto
Status: **concluído e integrado**.

Baseline sintético: 13.926 tokens candidatos → 1.794 selecionados, compressão 0,871176 e recall@2 de 1,0 no fixture.

### M7.1 — busca híbrida/semântica
Status: **condicional — não iniciado**.

Embeddings/pgvector somente se benchmark privado demonstrar ganho mensurável.

## M8 — Automação e agentes
Status: **M8.0–M8.15 concluídos e integrados em `main`**.

A pilha M8 implementou Task Packs, handoffs, tracking, verificação GitHub, executor controlado, isolamento, worker endurecido, proveniência/reconciliação, alteração efêmera + diff, aprovação por digest, branch dedicada, aplicação em staging, commit explícito, publicação em bare local, publicação GitHub via credential broker e criação controlada de PR.

O M8.15 adicionou integration readiness e validou a pilha completa em PostgreSQL 17 limpo antes e depois da integração.

Fluxo controlado atual:

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

Continuam fora da política:
- atualização/force de branch GitHub final;
- merge;
- deploy;
- publicação em produção;
- shell/comando/binário/argv arbitrário;
- escrita externa genérica.

## M9 — Segurança e operação self-hosted

### M9.0 — autenticação single-admin e controle de acesso
Status: **concluído e integrado em `main`**.

Entregas: autenticação single-admin, PBKDF2-SHA256, sessão opaca server-side, CSRF, cookie HttpOnly/SameSite=Strict, logout/revogação, modo production fail-closed e migration `0009_auth_sessions`.

### M9.1 — observabilidade operacional
Status: **concluído e integrado em `main`**.

Entregas: API `0.9.1`, `X-Request-ID`, logs HTTP JSON sanitizados, `/ops/status`, `/ops/summary` e `/ops/failures`, sem telemetria externa.

### M9.2 — credenciais dedicadas e recuperação self-hosted
Status: **concluído e integrado em `main`**.

Merge: PR #54 → `7f1123bb0b5df4b42241bce42155bb91f624e045`.

Validação pós-merge no `main`:
- `pytest`: sucesso;
- benchmark CLI: sucesso;
- integration-readiness: sucesso;
- migrations em PostgreSQL 17 limpo: sucesso;
- backup com manifesto/checksum: sucesso;
- restore em banco descartável: sucesso;
- verificação do dado sentinela pós-restore: sucesso.

Entregas:
- API `0.9.2`;
- `SecretStore` allowlisted com backend `files`;
- produção exige `SECRET_BACKEND=files` e `SECRET_DIR`;
- secret files read-only, sem symlinks e com permissões restritas;
- rotação por substituição atômica;
- scripts de backup/restore PostgreSQL;
- manifesto com SHA-256 e Alembic head;
- restore somente para destino explicitamente vazio/descartável;
- nenhum novo efeito externo do Controlled Executor.

### M9.3 — deployment readiness no ZimaOS/NAS
Status: **implementado funcionalmente na branch `codex/m9-3-zimaos-readiness`; checkpoint real no host pendente**.

Objetivo:
- preflight read-only do host;
- overlay Compose de produção com bind local e rotação de logs;
- runbook de HTTPS/reverse proxy, persistência, backup/restore e rotação;
- critérios objetivos de go/no-go;
- evidência real do ZimaOS/NAS separada da validação de CI.

Validação da branch: pytest, benchmark, Compose de produção, integration-readiness e recovery smoke em PostgreSQL 17 estão verdes. O marco de código pode ser integrado sem acesso ao host. O **checkpoint operacional real permanece pendente** até que o preflight, backup→restore, HTTPS e retenção sejam executados no ZimaOS/NAS alvo.

## Regra de evolução

Cada efeito externo deve ter autorização própria, input resolvido pelo servidor, prova de estado anterior, verificação pós-efeito, segredo fora do estado persistido e reconciliação explícita quando rollback total não for possível.

Nenhum deploy externo deve ocorrer antes de:
1. M9.3 estar integrado e com CI verde;
2. preflight do host real estar `ready`;
3. backup/restore real ter sido comprovado no ZimaOS/NAS;
4. HTTPS/reverse proxy estar configurado;
5. destino secundário de backup e retenção de logs estarem definidos.
