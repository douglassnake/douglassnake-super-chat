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

## M9 — Segurança e operação self-hosted

### M9.0 — autenticação single-admin e controle de acesso
Status: **concluído e integrado em `main`**.

Entregas:
- autenticação single-admin configurada por ambiente;
- PBKDF2-SHA256 com salt aleatório;
- sessão opaca server-side em `auth_sessions`;
- persistência somente de hashes do token de sessão e CSRF;
- cookie de sessão HttpOnly + SameSite=Strict;
- CSRF double-submit vinculado à sessão para métodos mutáveis;
- login/logout/status;
- expiração e revogação de sessão;
- tela de login integrada;
- modo `production` fail-closed;
- `AUTH_COOKIE_SECURE=true` obrigatório em produção;
- hash de senha e demais segredos excluídos da serialização de `Settings`;
- migration `0009_auth_sessions`;
- testes e readiness atualizados;
- nenhum novo efeito externo habilitado.

Continuam fora do M9.0:
- múltiplos usuários;
- MFA;
- OAuth/OIDC/SSO;
- recuperação de senha por e-mail;
- RBAC granular.

### M9.1 — observabilidade operacional
Status: **concluído e integrado em `main`**.

Entregas:
- API `0.9.1`;
- `X-Request-ID` validado ou gerado server-side em cada resposta normal;
- logs HTTP estruturados em JSON para `stdout`;
- logs sem query string, body, cookies, Authorization ou tokens;
- exceções não tratadas registram apenas o tipo, não a mensagem;
- `GET /ops/status` protegido com readiness do banco, versão, ambiente e uptime;
- `GET /ops/summary` com status reais agrupados de execuções, requests, workers e aprovações;
- sinais de leases expirados, aprovações pendentes e falhas nas últimas 24 h;
- `GET /ops/failures` com falhas recentes sanitizadas e truncadas;
- nenhuma tabela/migration nova;
- nenhum serviço de telemetria externo;
- nenhum novo efeito externo habilitado.

### M9.2 — credenciais dedicadas e recuperação self-hosted
Status: **implementado funcionalmente na branch `codex/m9-2-self-hosted-recovery`; aguardando CI final/PR**.

Entregas:
- API `0.9.2`;
- `SecretStore` allowlisted com backend `settings` para desenvolvimento e `files` para produção;
- `FileSecretStore` somente leitura, sem symlinks, com limites de tamanho e permissões POSIX restritas;
- rotação observada em nova aquisição por substituição atômica de arquivo;
- backend `files` exclusivo: sem fallback silencioso para `.env`/settings;
- `production` exige `SECRET_BACKEND=files` e `SECRET_DIR`;
- broker de publicação GitHub integrado ao secret store sem persistir segredo;
- scripts de backup/restore PostgreSQL;
- backup custom-format com diretório privado, manifesto, tamanho, Alembic head e SHA-256;
- restore somente para banco explicitamente vazio/descartável e com confirmação explícita;
- verificação pós-restore do Alembic head e tabelas críticas;
- senha PostgreSQL passada por ambiente e não por argv;
- CI executa backup → restore em PostgreSQL 17 descartável e valida dado sentinela;
- nenhum novo efeito externo do Controlled Executor habilitado.

Checkpoint operacional ainda obrigatório antes de deploy externo:
- executar backup/restore real no ZimaOS/NAS alvo;
- definir destino físico secundário e política de retenção;
- validar permissões do diretório real de secrets e procedimento de rotação;
- validar rotação/retensão de logs no runtime escolhido.

## Regra de evolução

Cada efeito externo deve ter autorização própria, input resolvido pelo servidor, prova de estado anterior, verificação pós-efeito, segredo fora do estado persistido e reconciliação explícita quando rollback total não for possível.

Nenhum deploy externo deve ocorrer antes de M9.2 estar integrado, CI verde, HTTPS/reverse proxy estarem configurados e o procedimento de backup/restore ter sido testado no ambiente self-hosted alvo.
