# Douglas Snake — Super Chat

O **Super Chat** é a interface operacional do **Segundo Cérebro**: memória persistente, recuperação seletiva de contexto e execução técnica auditável com autorização humana por efeito.

## Arquitetura atual

```text
Usuário autenticado
  ↓
Super Chat Web / API
  ↓ observabilidade local
request-id + logs JSON + /ops/*
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
  │    └── publish_branch → bare local M8.12
  ├── github-publish
  │    └── publish_github_branch → GitHub M8.14
  └── github-pr
       └── create_pull_request → PR M8.13
```

Cada efeito tem autorização e release próprios. Nenhuma etapa autoriza implicitamente a seguinte.

## Marcos M8

- **M8.0–M8.7** Task Packs, handoffs, execução/evidências, executor, isolamento e proveniência;
- **M8.8** alteração efêmera + diff revisável;
- **M8.9** aprovação por digest + branch local;
- **M8.10** aplicação em staging Git dedicado;
- **M8.11** commit local por Git plumbing;
- **M8.12** publicação em bare local sem `git push`/`receive-pack`;
- **M8.13** criação controlada de Pull Request GitHub;
- **M8.14** publicação autenticada da branch GitHub via credential broker;
- **M8.15** estabilização, migration smoke e integration readiness.

## M9.0 — autenticação single-admin

O M9.0 protege `/app`, APIs, OpenAPI e endpoints operacionais com sessão server-side.

Características:

- senha configurada apenas por hash PBKDF2-SHA256;
- token de sessão aleatório e opaco;
- somente hash do token é persistido em `auth_sessions`;
- cookie de sessão `HttpOnly` + `SameSite=Strict`;
- CSRF double-submit vinculado à sessão para métodos mutáveis;
- logout revoga a sessão no banco;
- `production` falha no startup sem autenticação e cookie `Secure`;
- `GET /health` permanece público e retorna apenas `status`;
- nenhum novo efeito externo é habilitado.

Gere o hash localmente:

```bash
python scripts/generate_password_hash.py
```

Configuração mínima de produção:

```env
ENVIRONMENT=production
AUTH_ENABLED=true
AUTH_USERNAME=admin
AUTH_PASSWORD_HASH=<pbkdf2_sha256$...>
AUTH_COOKIE_SECURE=true
```

Produção pressupõe HTTPS. Veja `docs/AUTHENTICATION.md`.

## M9.1 — observabilidade operacional

A API `0.9.1` adiciona observabilidade local sem exportar dados para serviços externos.

Cada resposta HTTP normal recebe `X-Request-ID`. O middleware registra uma linha JSON por requisição contendo apenas método, path sem query string, status, duração, request ID e principal autenticado quando disponível.

Não são registrados body, query string, cookies, `Authorization`, tokens nem mensagens de exceção não tratada.

Endpoints operacionais protegidos:

```text
GET /ops/status    → readiness do banco, versão, ambiente e uptime
GET /ops/summary   → estados e sinais agregados
GET /ops/failures  → falhas recentes sanitizadas
```

`/health` continua sendo somente liveness público mínimo. `/ops/status` é a readiness detalhada e exige autenticação quando M9.0 está habilitado.

Os sinais incluem leases expirados, aprovações Git pendentes e falhas de execução/request/worker nas últimas 24 horas. Nenhum `payload_json` ou `result_json` é exposto pelos endpoints de observabilidade.

Veja `docs/OBSERVABILITY.md`.

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
publish_branch          # bare local M8.12
   ↓
publish_github_branch   # GitHub M8.14, release separado
   ↓
create_pull_request      # M8.13, release separado
```

## Capacidades reais

```text
read_repository       → metadata
run_tests             → pytest server-side
modify_worktree       → workspace efêmero + diff
create_branch         → branch local superchat/*
apply_git_change      → staging Git dedicado
create_commit         → commit local verificado
publish_branch        → primeira publicação em bare local
publish_github_branch → primeira publicação no GitHub
create_pull_request   → PR GitHub após verificar head SHA
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

## M8.12 — bare local

O M8.12 transporta objetos via bundle local e cria a ref bare final por `update-ref` compare-and-swap. Não usa `git push` nem `receive-pack`.

Veja `docs/CONTROLLED_REMOTE_PUBLICATION.md`.

## M8.13 — Pull Request controlado

`create_pull_request` aceita publicamente apenas `publish_request_id`, título e corpo opcionais. Repositório/base/head/SHA são resolvidos server-side. O writer fica desligado por padrão e o token não entra em `ExecutorRequest`, `WorkerJob`, fingerprint, logs ou resultados.

Antes do PR, o GitHub precisa reportar o head exatamente no SHA esperado. Veja `docs/CONTROLLED_PULL_REQUEST.md`.

## M8.14 — publicação GitHub via credential broker

`publish_github_branch` aceita publicamente somente `publish_request_id` M8.12. O bare local, repository, branch e SHA são resolvidos pelo servidor.

A credencial é obtida somente em memória:

```text
adapter github-publish
  ↓
CredentialBroker
  ↓
SecretLease [REDACTED]
  ↓
publisher autenticado
```

O segredo não entra em nenhum contrato persistível.

A publicação usa duas fases:

```text
commit exato do bare local
  ↓
ref temporária única superchat-staging/<request-id>
  ↓
verificação do SHA
  ↓
criação atômica da ref final pela API GitHub
  ↓
verificação final
  ↓
remoção da ref temporária
```

O transporte autenticado usa `GIT_ASKPASS` efêmero e URL sem token. A ref temporária só pode ser criada se estiver ausente; a ref final é criada pela API e nunca atualizada se já existir.

Veja `docs/CONTROLLED_GITHUB_PUBLICATION.md`.

## M8.15 — estabilização e integration readiness

O M8.15 transforma guardrails de integração em checks executáveis:

```bash
python scripts/integration_readiness.py
```

O check exige:

- grafo Alembic com um único base e um único head;
- migrations críticas presentes, incluindo `auth_sessions`;
- executores `isolated-local`, `github-pr` e `github-publish` indisponíveis por padrão;
- produção sem autenticação bloqueada;
- `merge`, `deploy` e `publish` ainda proibidos globalmente;
- versão da API coerente;
- credenciais e `DATABASE_URL` fora de `Settings.model_dump()` / `model_dump_json()`.

O GitHub Actions também inicia **PostgreSQL 17 limpo**, executa:

```bash
alembic upgrade head
python scripts/integration_readiness.py --database
```

e confirma o head da migration e a presença das tabelas críticas.

## Segurança e credenciais

Os adapters de efeitos externos permanecem **desligados por padrão**. As credenciais GitHub continuam separadas por finalidade:

- `GITHUB_TOKEN` → leitura/sincronização;
- `EXECUTOR_GITHUB_WRITE_TOKEN` → criação controlada de PR;
- `EXECUTOR_GITHUB_PUBLISH_TOKEN` → publicação controlada de branch.

`AUTH_PASSWORD_HASH`, tokens GitHub, credenciais Google e `DATABASE_URL` são excluídos da serialização de `Settings`.

O repositório é público. `.env`, memória real, tokens, conversas, worktrees privados, staging, bancos e hashes reais da instalação nunca devem ser versionados.

## Recuperação e tokens

No benchmark sintético M7.0, o cenário `minimal` reduziu 13.926 tokens candidatos para 1.794, aproximadamente 87,12% de compressão, mantendo `recall@2 = 1,0` no fixture.

```bash
python scripts/context_benchmark.py benchmarks/context_cases.json
```

## Executar

```bash
git clone https://github.com/douglassnake/douglassnake-super-chat.git
cd douglassnake-super-chat
cp .env.example .env
docker compose up --build
```

Interface: `http://localhost:8000/app/`

OpenAPI: `http://localhost:8000/docs`

Em `development`, autenticação continua desabilitada por padrão para DX/testes. Para ambiente exposto, use `ENVIRONMENT=production`, HTTPS e a configuração M9.0.

## Próxima fronteira

Depois do M9.1, a prioridade é **M9.2: backend dedicado de credenciais, rotação de segredos e teste real de backup/restore no ambiente self-hosted**, incluindo a política de retenção/rotação de logs do runtime escolhido, antes de qualquer capacidade de merge/deploy.
