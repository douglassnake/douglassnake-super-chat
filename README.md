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
  └── apply_git_change → staging Git dedicado, não commitado
  ↓
Proveniência + auditoria
```

Cada efeito exige autorização própria. Aprovar um `patch_digest` não cria branch; criar branch não aplica o patch; aplicar o patch não cria commit, push ou PR.

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
- **M8.9** aprovação por digest + branch Git local dedicado;
- **M8.10** aplicação da proposta aprovada em worktree Git dedicado.

## Capacidades reais atuais

```text
read_repository   → somente metadata
run_tests         → somente preset server-side pytest
modify_worktree   → cópia temporária + unified diff
create_branch     → somente branch local superchat/*
apply_git_change  → staging persistente, não commitado
```

Ainda sem implementação real:

```text
create_commit
create_pull_request
```

Continuam proibidos: merge, deploy, publicação, escrita em Drive/Calendar, escrita externa genérica e shell/comando/binário/argv arbitrário.

## M8.8 — proposta revisável

`modify_worktree` aceita apenas `write_text` e `delete_file`. As mudanças ocorrem em cópia temporária e geram inventário + unified diff + `patch_digest` SHA-256. O worktree original não é alterado.

Veja `docs/WORKTREE_DIFF.md`.

## M8.9 — aprovação e branch

Uma proposta pode originar `GitChangeApproval`; o usuário precisa confirmar exatamente o `patch_digest`. A aprovação não escreve Git.

`create_branch` é uma ação separada, limitada a `superchat/*`, criada do `HEAD` local sem checkout, commit, push ou rede. Branch existente nunca é sobrescrito.

Veja `docs/GIT_CHANGE_APPROVAL.md`.

## M8.10 — aplicação aprovada

O payload público de `apply_git_change` contém somente:

```json
{
  "approval_id": "...",
  "branch_request_id": "..."
}
```

A API resolve server-side as operações originais, digest aprovado, branch, worktree e `base_sha`. O worker exige que o branch ainda aponte para essa base, cria um worktree dedicado em `EXECUTOR_GIT_STAGING_ROOT`, reconstrói a proposta e compara o digest antes da escrita.

Depois da aplicação, o diff é recalculado e precisa reproduzir o mesmo `patch_digest`. Em qualquer divergência o staging é removido. Em sucesso, os arquivos ficam alterados **sem commit**, o branch continua no mesmo `HEAD` e o worktree fonte não recebe alteração de conteúdo.

Veja `docs/APPLY_APPROVED_CHANGE.md`.

## Worker e proveniência

O worker roda em processo separado da API. Cada execução `isolated-local` possui `WorkerAttempt` numerado com lease/heartbeat. A API valida `job_digest` e `result_digest` SHA-256 antes de aceitar o resultado. Isso é integridade/proveniência, não assinatura criptográfica.

`run_tests` usa cópia temporária, ambiente mínimo, timeout e limites de CPU/memória/PIDs/NOFILE/FSIZE quando suportados. O contrato container inclui `--network none`, `--read-only`, `--cap-drop ALL`, `no-new-privileges` e nunca monta Docker socket.

## Recuperação e tokens

No baseline sintético M7.0, o cenário de pressão `minimal` reduziu 13.926 tokens candidatos para 1.794 selecionados, cerca de 87,12% de compressão, mantendo `recall@2 = 1,0` no fixture. Não é garantia de desempenho em dados reais.

```bash
python scripts/context_benchmark.py benchmarks/context_cases.json
```

## Privacidade

O repositório é público. Memória real, `.env`, credenciais, conversas, dumps do banco e documentos privados não devem ser versionados. `EXECUTOR_GIT_STAGING_ROOT` deve apontar para diretório privado no servidor.

## Executar

```bash
git clone https://github.com/douglassnake/douglassnake-super-chat.git
cd douglassnake-super-chat
git checkout codex/m8-10-apply-approved-change
cp .env.example .env
docker compose up --build
```

Interface: `http://localhost:8000/app/`

OpenAPI: `http://localhost:8000/docs`

O executor real permanece desligado até configuração explícita de `EXECUTOR_ISOLATED_ENABLED=true`, `EXECUTOR_WORKTREE_ROOT` e, para aplicação Git, `EXECUTOR_GIT_STAGING_ROOT`.

## Próxima fronteira

O próximo marco deverá implementar `create_commit` **somente** sobre um staging M8.10 válido, com autorização independente, identidade Git server-side, verificação de `HEAD`, `patch_digest` e status do worktree. Push/PR, merge e deploy continuam separados ou fora da política.
