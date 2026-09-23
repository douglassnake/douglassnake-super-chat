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

Cada seta externa continua exigindo release próprio.

Continuam fora da política:
- atualização/force de branch GitHub final;
- merge;
- deploy;
- publicação em produção;
- shell/comando/binário/argv arbitrário;
- escrita externa genérica.

## M9 — Segurança operacional da interface

### M9.0 — autenticação single-admin e controle de acesso
Status: **em implementação na branch `codex/m9-auth-access-control`**.

Objetivo: proteger `/app`, APIs, OpenAPI e endpoints operacionais antes de qualquer deploy externo.

Entregas previstas/implementadas:
- autenticação single-admin configurada por ambiente;
- PBKDF2-SHA256 com salt aleatório;
- sessão opaca server-side em `auth_sessions`;
- persistência somente de hashes do token de sessão e CSRF;
- cookie de sessão HttpOnly + SameSite=Strict;
- CSRF vinculado à sessão para métodos mutáveis;
- login/logout/status;
- expiração e revogação de sessão;
- tela de login integrada;
- modo `production` fail-closed;
- `AUTH_COOKIE_SECURE=true` obrigatório em produção;
- hash de senha e demais segredos excluídos da serialização de `Settings`;
- migration `0009_auth_sessions`;
- testes e readiness atualizados;
- nenhum novo efeito externo habilitado.

Fora do M9.0:
- múltiplos usuários;
- MFA;
- OAuth/OIDC/SSO;
- recuperação de senha por e-mail;
- RBAC granular.

### M9.1 — observabilidade operacional
Status: **não iniciado**.

Prioridades:
- métricas de autenticação sem PII/segredos;
- auditoria de execuções e falhas operacionais;
- health/readiness separados;
- retenção e rotação de logs;
- alertas para tentativas órfãs, falhas de reconciliação e adapters indisponíveis.

### M9.2 — credenciais dedicadas e recuperação self-hosted
Status: **não iniciado**.

Prioridades:
- backend de segredos dedicado fora do banco operacional;
- rotação de credenciais;
- runbook de backup/restore;
- teste real de recuperação em ambiente self-hosted.

## Regra de evolução

Cada efeito externo deve ter autorização própria, input resolvido pelo servidor, prova de estado anterior, verificação pós-efeito, segredo fora do estado persistido e reconciliação explícita quando rollback total não for possível.

Nenhum deploy externo deve ocorrer antes de M9.0 estar integrado, CI verde e HTTPS/reverse proxy estarem configurados no ambiente alvo.
