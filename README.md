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
  ↓ release por ação
WorkerAttempt + WorkerJob
  ↓
Worker isolado
  ├── read_repository
  ├── run_tests
  ├── modify_worktree → cópia temporária → diff
  ├── create_branch → ref local superchat/*
  ├── apply_git_change → staging Git dedicado
  ├── create_commit → commit local por Git plumbing
  └── publish_branch → remote bare local controlado
  ↓
Proveniência + auditoria
```

Cada efeito exige autorização própria. Aprovar um digest não cria branch; criar branch não aplica o patch; aplicar o patch não cria commit; criar commit não publica remotamente; publicar a branch não cria pull request.

## Marcos

M1–M7 constroem memória, contexto, integrações e métricas. M8 adiciona autonomia de forma incremental:

- **M8.0–M8.7** task packs, handoffs, tracking, verificação, executor, isolamento e proveniência;
- **M8.8** alteração efêmera + diff revisável;
- **M8.9** aprovação por digest + branch Git local dedicado;
- **M8.10** aplicação da proposta aprovada em worktree Git dedicado;
- **M8.11** commit Git local explícito do staging aprovado;
- **M8.12** publicação controlada da branch em remote bare local, sem `git push`/`receive-pack`.

## Capacidades reais atuais

```text
read_repository   → somente metadata
run_tests         → somente preset server-side pytest
modify_worktree   → cópia temporária + unified diff
create_branch     → somente branch local superchat/*
apply_git_change  → staging persistente, não commitado
create_commit     → commit local verificado, sem publicação remota
publish_branch    → primeira publicação em bare local controlado
```

Ainda sem implementação real:

```text
create_pull_request
remote HTTPS/SSH autenticado
atualização de ref remota já existente
```

Continuam proibidos: merge, deploy, publicação em produção, escrita em Drive/Calendar, escrita externa genérica e shell/comando/binário/argv arbitrário.

## Fluxo Git controlado

```text
modify_worktree
   ↓ diff + patch_digest
aprovação humana do digest
   ↓
create_branch
   ↓
apply_git_change
   ↓ staging não commitado
create_commit
   ↓ commit local superchat/*
publish_branch
   ↓ remote bare local verificado
```

### M8.11 — commit explícito

O payload público de `create_commit` contém somente `apply_request_id` e uma mensagem curta. Branch, staging, `base_sha`, `patch_digest`, inventário e identidade são resolvidos ou injetados pelo servidor.

Antes do commit, o worker exige que branch/staging permaneçam na base aprovada, que o conjunto de arquivos alterados seja exatamente o inventário aprovado e que o digest atual continue idêntico. Arquivos extras, alterações pré-staged, symlinks e drift bloqueiam a operação.

O commit usa Git plumbing com índice temporário:

```text
read-tree → hash-object --no-filters → update-index → write-tree
→ commit-tree → update-ref compare-and-swap → read-tree
```

Não há `git add -A` nem `git commit`. Hooks são desabilitados; clean filters não são usados. O teste de segurança instala hook e filtro maliciosos e confirma que nenhum deles executa.

A identidade padrão é server-side:

```text
Super Chat Executor <superchat-executor@localhost>
```

Veja `docs/EXPLICIT_COMMIT.md`.

### M8.12 — publicação remota controlada

`publish_branch` recebe no payload público somente `commit_request_id`. Branch, `commit_sha`, `base_sha`, `patch_digest`, staging e remote são resolvidos ou injetados pelo servidor.

O primeiro contrato suporta apenas um **repositório bare local absoluto**. Não há URL, token, credencial, refspec ou `force` vindos do agente.

A publicação deliberadamente não usa `git push` nem `receive-pack`:

```text
bundle de objetos
  ↓
importação local no bare
  ↓
verificação commit/parent
  ↓
update-ref compare-and-swap contra zero OID
  ↓
pós-verificação da ref
```

A primeira publicação só ocorre se `refs/heads/superchat/*` ainda não existir. Remote já existente, drift local ou staging sujo bloqueiam o efeito. `pre-push`, `pre-receive` e `reference-transaction` são testados como inertes no caminho controlado.

Veja `docs/CONTROLLED_REMOTE_PUBLICATION.md`.

## Worker e proveniência

O worker roda em processo separado da API. Cada execução `isolated-local` possui `WorkerAttempt` numerado com lease/heartbeat. A API valida `job_digest` e `result_digest` SHA-256 antes de aceitar o resultado. Isso é integridade/proveniência, não assinatura criptográfica.

## Recuperação e tokens

No baseline sintético M7.0, o cenário de pressão `minimal` reduziu 13.926 tokens candidatos para 1.794 selecionados, cerca de 87,12% de compressão, mantendo `recall@2 = 1,0` no fixture. Não é garantia de desempenho em dados reais.

```bash
python scripts/context_benchmark.py benchmarks/context_cases.json
```

## Privacidade

O repositório é público. Memória real, `.env`, credenciais, conversas, dumps do banco e documentos privados não devem ser versionados. Worktrees, staging e remotes bare devem permanecer em diretórios privados do servidor.

## Executar

```bash
git clone https://github.com/douglassnake/douglassnake-super-chat.git
cd douglassnake-super-chat
git checkout codex/m8-12-publish-branch
cp .env.example .env
docker compose up --build
```

Interface: `http://localhost:8000/app/`

OpenAPI: `http://localhost:8000/docs`

O executor real permanece desligado até configuração explícita dos roots privados e das capacidades desejadas.

## Próxima fronteira

A próxima etapa é tratar **`create_pull_request`** como autorização independente, referenciando somente uma publicação M8.12 concluída e verificada. Um credential broker separado será necessário antes de remotes HTTPS/SSH autenticados. Merge, deploy e publicação em produção permanecem fora da política padrão.
