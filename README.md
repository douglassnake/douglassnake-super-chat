# Douglas Snake — Super Chat

O **Super Chat** é a interface operacional do **Segundo Cérebro**: memória persistente, recuperação seletiva de contexto e execução técnica auditável com autorização humana por efeito.

## Arquitetura atual

```text
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
- **M8.14** publicação autenticada da branch GitHub via credential broker.

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

## Segurança e credenciais

Os adapters de efeitos externos permanecem **desligados por padrão**. Tokens de publicação GitHub e criação de PR são configurações privadas distintas, permitindo menor privilégio.

O repositório é público. `.env`, memória real, tokens, conversas, worktrees privados, staging e bancos nunca devem ser versionados.

## Recuperação e tokens

No benchmark sintético M7.0, o cenário `minimal` reduziu 13.926 tokens candidatos para 1.794, aproximadamente 87,12% de compressão, mantendo `recall@2 = 1,0` no fixture.

```bash
python scripts/context_benchmark.py benchmarks/context_cases.json
```

## Executar

```bash
git clone https://github.com/douglassnake/douglassnake-super-chat.git
cd douglassnake-super-chat
git checkout codex/m8-14-github-publish-broker
cp .env.example .env
docker compose up --build
```

Interface: `http://localhost:8000/app/`

OpenAPI: `http://localhost:8000/docs`

## Próxima fronteira

A partir daqui o fluxo técnico chega até PR sem merge automático. O próximo trabalho deve priorizar **revisão/integração da pilha de PRs, autenticação da interface e observabilidade operacional** antes de considerar qualquer capacidade de merge/deploy.