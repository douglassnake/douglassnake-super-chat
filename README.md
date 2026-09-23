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
Agent Task Pack
  ↓ aprovação humana
Agent Handoff
  ↓ release explícito
Agent Execution
  ↓
Controlled Executor
  ↓ release por ação
WorkerAttempt + WorkerJob
  ↓
Worker isolado
  ├── read_repository
  ├── run_tests
  ├── modify_worktree → cópia temporária → diff
  └── create_branch → ref local superchat/*
  ↓
Proveniência + auditoria
```

Aprovações são deliberadamente separadas. Aprovar um Task Pack não libera execução; liberar um handoff não libera qualquer ação; cada `ExecutorRequest` exige release próprio. Aprovar um `patch_digest` não cria branch, e criar branch não aplica o patch.

## Marcos

M1–M7 constroem memória, contexto, integrações e métricas. M8 adiciona automação progressivamente controlada:

- **M8.0** Agent Task Packs;
- **M8.1** handoffs auditáveis;
- **M8.2** execution tracking e evidências;
- **M8.3** verificação GitHub somente leitura;
- **M8.4** Controlled Executor;
- **M8.5** adapter local isolado;
- **M8.6** worker endurecido separado da API;
- **M8.7** proveniência, lease/heartbeat, reconciliação e retry;
- **M8.8** alteração efêmera + diff revisável;
- **M8.9** aprovação por digest + branch Git local dedicado.

## Capacidades reais atuais

```text
read_repository → somente metadata
run_tests       → somente preset server-side pytest
modify_worktree → cópia temporária + unified diff
create_branch   → somente branch local superchat/*
```

Ainda sem implementação real:

```text
aplicar proposta aprovada no branch
create_commit
create_pull_request
```

Continuam proibidos: merge, deploy, publicação, escrita em Drive/Calendar, escrita externa genérica e shell/comando/binário/argv arbitrário.

## M8.8 — proposta revisável

`modify_worktree` aceita apenas operações semânticas `write_text` e `delete_file`. As mudanças ocorrem em cópia temporária e geram inventário de arquivos + unified diff + `patch_digest` SHA-256. O worktree original não é alterado.

Limites padrão do servidor: 20 arquivos, 40 operações, 64 KiB escritos e 64 KiB de patch persistido. Paths absolutos, `..`, symlink, arquivos binários/non-UTF-8 e conteúdo sensível detectável são bloqueados/redigidos.

Veja `docs/WORKTREE_DIFF.md`.

## M8.9 — aprovação por digest e branch dedicado

Uma proposta M8.8 concluída pode originar `GitChangeApproval`:

```text
patch_digest
   ↓
pending
   ↓ confirmação do digest exato
approved | cancelled
```

A aprovação não escreve Git.

`create_branch` é uma ação independente e precisa estar na allowlist do handoff, possuir `ExecutorRequest` próprio e receber release explícito. O worker aceita somente nomes `superchat/...`, valida novamente com `git check-ref-format`, cria a ref a partir do `HEAD` local e não faz checkout, commit, push ou rede. Branch existente gera conflito e nunca é sobrescrito.

O ambiente Git é mínimo e não herda credenciais do processo pai.

Veja `docs/GIT_CHANGE_APPROVAL.md`.

## Worker e proveniência

O worker roda em processo separado da API. Cada execução `isolated-local` possui `WorkerAttempt` numerado com lease/heartbeat. A API valida `job_digest` e `result_digest` SHA-256 antes de aceitar o resultado. Isso é integridade/proveniência, não assinatura criptográfica.

`run_tests` usa cópia temporária, ambiente mínimo, timeout e limites de CPU/memória/PIDs/NOFILE/FSIZE quando suportados. O contrato container inclui `--network none`, `--read-only`, `--cap-drop ALL`, `no-new-privileges` e nunca monta Docker socket.

Veja `docs/WORKER_HARDENING.md` e `docs/WORKER_PROVENANCE.md`.

## Recuperação e tokens

No baseline sintético M7.0, o cenário de pressão `minimal` reduziu 13.926 tokens candidatos para 1.794 selecionados, cerca de 87,12% de compressão, mantendo `recall@2 = 1,0` no fixture. Não é garantia de desempenho em dados reais.

```bash
python scripts/context_benchmark.py benchmarks/context_cases.json
```

## Privacidade

O repositório é público. Memória real, `.env`, credenciais, conversas, dumps do banco e documentos privados não devem ser versionados.

## Executar

```bash
git clone https://github.com/douglassnake/douglassnake-super-chat.git
cd douglassnake-super-chat
git checkout codex/m8-9-reviewed-git-branch
cp .env.example .env
docker compose up --build
```

Interface: `http://localhost:8000/app/`

OpenAPI: `http://localhost:8000/docs`

O executor real permanece desligado até configuração explícita de `EXECUTOR_ISOLATED_ENABLED=true` e `EXECUTOR_WORKTREE_ROOT`.

## Próxima fronteira

O M8.10 deverá aplicar uma proposta **já aprovada por digest** em um branch dedicado, detectando drift e revalidando paths/secrets antes da escrita persistente. Aplicar arquivos não criará commit implicitamente: `create_commit`, push/PR, merge e deploy permanecem etapas separadas ou fora da política.
