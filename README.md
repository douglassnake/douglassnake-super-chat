# Douglas Snake — Super Chat

O **Super Chat** é a interface operacional do **Segundo Cérebro**: memória persistente, recuperação seletiva de contexto, conectores somente leitura e execução técnica auditável com autorização humana por efeito.

## Arquitetura atual

```text
Usuário autenticado
  ↓
Super Chat Web / API
  ↓ observabilidade local
request-id + logs JSON + /ops/*
  ↓
Context Engine + memória operacional
  ↓
Task Pack → Handoff → Agent Execution
  ↓
Controlled Executor
  ├── isolated-local
  │    ├── read_repository / run_tests
  │    ├── modify_worktree → diff
  │    ├── create_branch
  │    ├── apply_git_change
  │    ├── create_commit
  │    └── publish_branch → bare local
  ├── github-publish
  │    └── publish_github_branch
  └── github-pr
       └── create_pull_request
```

Cada efeito tem autorização e release próprios. Nenhuma etapa autoriza implicitamente a seguinte.

## Marcos

- **M0–M6** — fundação, memória operacional, Context Engine, interface e conectores GitHub/Google somente leitura;
- **M7.0** — benchmark determinístico de recuperação de contexto;
- **M8.0–M8.15** — Task Packs, handoffs, tracking, executor controlado, isolamento, proveniência, diff/aprovação, Git local, publicação de branch e PR controlados;
- **M9.0** — autenticação single-admin;
- **M9.1** — observabilidade operacional;
- **M9.2** — secret files e recuperação self-hosted;
- **M9.3** — deployment readiness para ZimaOS/NAS, em desenvolvimento.

## M9.0 — autenticação single-admin

O M9.0 protege `/app`, APIs, OpenAPI e endpoints operacionais com sessão server-side.

Características:

- senha configurada apenas por hash PBKDF2-SHA256;
- token de sessão aleatório e opaco;
- somente hash do token é persistido em `auth_sessions`;
- cookie `HttpOnly` + `SameSite=Strict`;
- CSRF double-submit vinculado à sessão;
- logout revoga a sessão;
- `production` falha sem autenticação e cookie `Secure`;
- `GET /health` permanece público e mínimo.

Gere o hash localmente:

```bash
python scripts/generate_password_hash.py
```

Veja `docs/AUTHENTICATION.md`.

## M9.1 — observabilidade

Cada resposta HTTP normal recebe `X-Request-ID`. Logs HTTP estruturados vão para `stdout` sem body, query string, cookies, `Authorization`, tokens ou mensagens brutas de exceção.

Endpoints protegidos:

```text
GET /ops/status    → readiness do banco, versão, ambiente e uptime
GET /ops/summary   → estados e sinais agregados
GET /ops/failures  → falhas recentes sanitizadas
```

Veja `docs/OBSERVABILITY.md`.

## M9.2 — secrets e recuperação

O M9.2 está integrado em `main` e validado pós-merge.

Em `production`:

- `SECRET_BACKEND=files` é obrigatório;
- `SECRET_DIR` deve apontar para diretório privado montado read-only;
- não existe fallback silencioso para `.env` nos secrets allowlisted;
- arquivos inseguros, symlinks, vazios ou excessivamente grandes falham fechados;
- rotação por substituição atômica é observada em nova aquisição.

Overlay de secrets:

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.secrets.yml \
  ...
```

Recuperação:

```bash
python scripts/backup_postgres.py --output-root /caminho/de/backups
python scripts/restore_postgres.py \
  --backup-dir /caminho/de/backups/<backup> \
  --target-database-url '<banco descartável vazio>' \
  --confirm-empty-target
```

O CI executa backup → restore em PostgreSQL 17 descartável e valida um dado sentinela, além de migrations e `integration_readiness`.

## M9.3 — ZimaOS/NAS deployment readiness

O M9.3 prepara o host sem declarar que o equipamento real já foi testado.

Preflight read-only:

```bash
python scripts/self_hosted_preflight.py \
  --secret-dir /srv/superchat/secrets \
  --data-dir /srv/superchat \
  --backup-dir /mnt/backup-superchat \
  --min-free-gib 5 \
  --bind-host 127.0.0.1 \
  --bind-port 8000 \
  --require-separate-backup-device
```

Ele verifica Docker/Compose, diretórios, permissões de secrets, espaço livre, separação do backup e disponibilidade da porta sem modificar o host.

Produção deve usar as três camadas:

```bash
docker compose \
  --env-file /caminho/privado/superchat.env \
  -f docker-compose.yml \
  -f docker-compose.secrets.yml \
  -f docker-compose.production.yml \
  up -d --build
```

O bind padrão é `127.0.0.1:8000`; a publicação deve ocorrer por reverse proxy HTTPS.

Veja `docs/ZIMAOS_SELF_HOSTED.md`.

## Fluxo Git controlado

```text
modify_worktree
   ↓
diff + patch_digest
   ↓ aprovação humana
create_branch
   ↓
apply_git_change
   ↓
create_commit
   ↓
publish_branch          # bare local
   ↓
publish_github_branch   # release separado
   ↓
create_pull_request      # release separado
```

Continuam fora da política:

```text
atualizar branch GitHub existente
force push final
merge
deploy
publicação em produção
shell/comando/binário/argv arbitrário
escrita externa genérica
```

## Integration readiness

```bash
python scripts/integration_readiness.py
```

O check exige, entre outros:

- grafo Alembic com base/head únicos;
- migrations críticas presentes;
- executores externos indisponíveis por padrão;
- produção sem autenticação bloqueada;
- produção sem secret backend dedicado bloqueada;
- `merge`, `deploy` e `publish` proibidos globalmente;
- versão da API coerente;
- credenciais e `DATABASE_URL` fora de serializações de `Settings`.

No CI, PostgreSQL 17 limpo recebe `alembic upgrade head`, readiness de banco e o smoke de recuperação.

## Desenvolvimento local

```bash
git clone https://github.com/douglassnake/douglassnake-super-chat.git
cd douglassnake-super-chat
cp .env.example .env
docker compose up --build
```

Interface: `http://127.0.0.1:8000/app/`

OpenAPI: `http://127.0.0.1:8000/docs`

Em `development`, autenticação permanece desabilitada por padrão para DX/testes.

## Segurança

O repositório é público. Nunca versione:

- `.env` real;
- tokens ou hashes reais;
- dumps/bancos;
- conversas ou memória privada;
- worktrees/staging privados;
- diretórios de secrets;
- evidências operacionais com dados sensíveis.

As credenciais GitHub permanecem separadas por finalidade: leitura, criação de PR e publicação de branch.

## Próxima fronteira

Concluir o **M9.3** em código e, depois, executar o checkpoint real no ZimaOS/NAS: preflight, backup→restore, HTTPS/reverse proxy, destino secundário de backup e política de retenção. Nenhum deploy externo é considerado liberado antes dessa evidência real.
