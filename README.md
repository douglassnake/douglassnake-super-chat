# Douglas Snake — Super Chat

O **Super Chat** é a interface operacional do **Segundo Cérebro**: memória persistente, continuidade de projetos, recuperação seletiva de contexto e execução técnica auditável com autorização humana por efeito.

## Arquitetura atual

```text
Usuário
  ↓
Web / API
  ↓
Projeto + memória operacional
  ↓
Context Engine
  ↓
Task Pack → Handoff → Agent Execution
  ↓
Controlled Executor
  ├── isolated-local → worktree/worker Git local
  └── github-pr      → writer GitHub separado, opt-in
  ↓
Proveniência + auditoria
```

Cada efeito exige autorização própria. Aprovar digest, criar branch, aplicar patch, criar commit, publicar branch e criar PR são gates independentes. Merge/deploy não são autorizados implicitamente.

## Marcos

M1–M7 constroem memória, contexto, integrações e métricas. M8 adiciona autonomia incremental:

- **M8.0–M8.7** Task Packs, handoffs, tracking, verificação, executor, isolamento e proveniência;
- **M8.8** alteração efêmera + diff revisável;
- **M8.9** aprovação por digest + branch Git local dedicado;
- **M8.10** aplicação em worktree Git dedicado;
- **M8.11** commit Git local explícito por plumbing;
- **M8.12** primeira publicação em remote bare local sem `git push`/`receive-pack`;
- **M8.13** criação controlada de Pull Request GitHub, com writer separado do worker.

## Capacidades reais atuais

```text
read_repository     → somente metadata
run_tests           → preset server-side pytest
modify_worktree     → cópia temporária + unified diff
create_branch       → branch local superchat/*
apply_git_change    → staging Git dedicado
create_commit       → commit local verificado
publish_branch      → primeira publicação em bare local controlado
create_pull_request → PR GitHub somente após verificação exata do head
```

Continuam sem implementação real:

```text
publicação autenticada de branch para GitHub
atualização de ref GitHub existente
merge
deploy
publicação em produção
```

Também permanecem proibidos shell/comando/binário/argv arbitrário, escrita Drive/Calendar e escrita externa genérica.

## Fluxo Git controlado

```text
modify_worktree
   ↓ diff + patch_digest
aprovação humana do digest
   ↓
create_branch
   ↓
apply_git_change
   ↓
create_commit
   ↓
publish_branch (bare local M8.12)
   ↓
[efeito separado publica/verifica head no GitHub]
   ↓
create_pull_request (M8.13)
```

### M8.11 — commit explícito

O commit usa Git plumbing com índice temporário:

```text
read-tree → hash-object --no-filters → update-index → write-tree
→ commit-tree → update-ref compare-and-swap → read-tree
```

Não há `git add -A` nem `git commit`; hooks e clean filters ficam fora do caminho. Veja `docs/EXPLICIT_COMMIT.md`.

### M8.12 — publicação bare controlada

`publish_branch` aceita publicamente apenas `commit_request_id`. Remote/path/ref/digest são resolvidos pelo servidor. O transporte usa bundle local + `update-ref` CAS; não usa `git push` nem `receive-pack`.

A primeira publicação exige ref remota ausente. Drift, staging sujo e conflito bloqueiam o efeito. Veja `docs/CONTROLLED_REMOTE_PUBLICATION.md`.

### M8.13 — Pull Request GitHub controlado

`create_pull_request` exige adapter próprio `github-pr`, autorização e release independentes. O payload público aceita somente:

```text
publish_request_id
title (opcional)
body  (opcional)
```

Repository, base, head, SHA e draft policy são resolvidos no servidor. O writer fica **desativado por padrão** e usa credencial de escrita separada, somente em memória. O token não entra em `ExecutorRequest`, `WorkerJob`, fingerprint, logs ou resultados.

Antes de criar o PR, o adapter consulta o GitHub e exige que `head_branch` já exista exatamente em `head_sha`. O M8.13 **não publica o branch implicitamente**. Branch ausente ou SHA divergente falham sem criar PR.

Depois da criação, repository/base/head/head SHA são relidos e verificados. Merge e deploy permanecem `false`. Testes usam writer fake offline; CI não cria PR externo.

Veja `docs/CONTROLLED_PULL_REQUEST.md`.

## Worker e proveniência

O worker `isolated-local` roda separado da API. Cada execução possui `WorkerAttempt` numerado com lease/heartbeat, `job_digest` e `result_digest` SHA-256. Isso é integridade/proveniência, não assinatura criptográfica.

O adapter `github-pr` não usa `WorkerJob`; isso mantém a credencial GitHub fora do processo/contrato persistível do worker. Ele continua passando pelos mesmos gates de Handoff → ExecutorRequest → release → auditoria.

## Recuperação e tokens

No baseline sintético M7.0, o cenário `minimal` reduziu 13.926 tokens candidatos para 1.794 selecionados, cerca de 87,12% de compressão, mantendo `recall@2 = 1,0` no fixture. Não é garantia de desempenho em dados reais.

```bash
python scripts/context_benchmark.py benchmarks/context_cases.json
```

## Privacidade

O repositório é público. Memória real, `.env`, tokens, credenciais, conversas, dumps do banco e documentos privados não devem ser versionados. Worktrees, staging, bare remotes e configuração de escrita GitHub devem permanecer privados.

## Executar

```bash
git clone https://github.com/douglassnake/douglassnake-super-chat.git
cd douglassnake-super-chat
git checkout codex/m8-13-controlled-pull-request
cp .env.example .env
docker compose up --build
```

Interface: `http://localhost:8000/app/`

OpenAPI: `http://localhost:8000/docs`

Executores com efeito externo permanecem desligados até configuração explícita.

## Próxima fronteira

O próximo gargalo é fechar o elo entre M8.12 e M8.13 com uma **publicação GitHub autenticada e controlada por credential broker**, ainda como efeito separado. Merge, deploy e publicação em produção permanecem fora da política padrão.
