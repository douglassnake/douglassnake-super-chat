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
Isolated Local Adapter
  ↓
WorkerAttempt
leased → running → completed | failed
  ↓
WorkerJob JSON v1
  ↓
ProcessWorkerClient
  ↓ processo separado da API
Worker Runtime
  ├── read_repository
  ├── run_tests
  └── modify_worktree → workspace efêmero → diff revisável
  ↓
Proveniência
worker_id + job_digest + result_digest
```

A autorização é separada por camada. Aprovar Task Pack não libera execução; liberar handoff não libera qualquer ação; cada `ExecutorRequest` exige release próprio. Merge, deploy e publicação nunca são implícitos.

## Marcos

- **M1** memória operacional;
- **M2** Context Engine com budget de tokens;
- **M3** GitHub somente leitura;
- **M4** Session Memory;
- **M5** interface web;
- **M6** Google Drive/Calendar somente leitura;
- **M7.0** benchmark de recuperação;
- **M8.0** Agent Task Packs;
- **M8.1** Agent Handoffs;
- **M8.2** Agent Executions e evidências;
- **M8.3** verificação GitHub somente leitura;
- **M8.4** Controlled Executor;
- **M8.5** adapter local isolado;
- **M8.6** worker endurecido e separado da API;
- **M8.7** proveniência, leases, heartbeat, reconciliação e retry;
- **M8.8** alteração efêmera + diff revisável.

## Política de ações

Ações reconhecidas:

```text
read_context
read_repository
modify_worktree
run_tests
create_branch
create_commit
create_pull_request
```

Capacidades **reais** atuais:

```text
read_repository → somente metadata
run_tests       → somente preset server-side pytest
modify_worktree → somente cópia temporária + unified diff
```

Ainda sem efeito real:

```text
create_branch
create_commit
create_pull_request
```

Continuam proibidos: merge, deploy, publicação, escrita em Drive/Calendar, escrita externa genérica e shell/comando/binário/argv arbitrário.

## M8.8 — alteração efêmera

`modify_worktree` aceita somente operações semânticas:

```json
{"op":"write_text","path":"src/example.py","content":"..."}
{"op":"delete_file","path":"docs/old.md"}
```

Fluxo:

```text
worktree original (somente leitura por design)
        ↓
cópia temporária
        ↓
write_text / delete_file
        ↓
unified diff
        ↓
redaction
        ↓
patch_digest SHA-256
        ↓
resultado auditável
        ↓
workspace temporário removido
```

O resultado inclui inventário de arquivos `added/modified/deleted`, `patch`, `patch_digest`, tamanho, indicação de redaction e proveniência M8.7. O worktree original não é persistido nem alterado pelo contrato M8.8.

Limites padrão, definidos apenas no servidor:

```text
20 arquivos distintos
40 operações
64 KiB escritos
64 KiB de patch persistido
```

Paths absolutos, `..`, paths por symlink, arquivos binários/non-UTF-8 e payloads de comando são rejeitados. Conteúdo sensível detectável é bloqueado/redigido antes da persistência.

Veja `docs/WORKTREE_DIFF.md`.

## Worker e proveniência

O worker roda em processo separado da API. `run_tests` usa cópia temporária, ambiente mínimo, timeout e limites de CPU/memória/PIDs/NOFILE/FSIZE quando suportados. O backend container possui contrato com `--network none`, `--read-only`, `--cap-drop ALL` e `no-new-privileges`; o Docker socket nunca é montado.

Cada execução `isolated-local` possui `WorkerAttempt` numerado com lease/heartbeat. A API valida `job_digest` e `result_digest` SHA-256 antes de aceitar o resultado. Isso é verificação de integridade, **não assinatura criptográfica**.

Veja `docs/WORKER_HARDENING.md` e `docs/WORKER_PROVENANCE.md`.

## Recuperação e economia de tokens

No baseline sintético M7.0, o cenário de pressão `minimal` produziu 13.926 tokens candidatos → 1.794 selecionados, com compressão aproximada de 87,12% e `recall@2 = 1,0` no fixture. Esse resultado não é garantia de desempenho em dados reais.

```bash
python scripts/context_benchmark.py benchmarks/context_cases.json
```

## Privacidade

O repositório é público. Memória real, `.env`, credenciais, conversas, dumps do banco e documentos privados não devem ser versionados.

## Executar

```bash
git clone https://github.com/douglassnake/douglassnake-super-chat.git
cd douglassnake-super-chat
git checkout codex/m8-8-ephemeral-diff
cp .env.example .env
docker compose up --build
```

Interface: `http://localhost:8000/app/`

OpenAPI: `http://localhost:8000/docs`

O executor real permanece desligado até configuração explícita de `EXECUTOR_ISOLATED_ENABLED=true` e `EXECUTOR_WORKTREE_ROOT`.

## Próxima fronteira

Depois do M8.8, a próxima etapa deverá persistir uma proposta **já revisada/aprovada** em um branch Git dedicado, mantendo `create_branch`, `create_commit` e `create_pull_request` como autorizações independentes. Merge, deploy e publicação continuam fora da política padrão.
