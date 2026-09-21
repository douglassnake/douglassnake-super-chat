# M8.9 — Aprovação por digest e branch Git dedicado

O M8.9 separa dois efeitos que não devem ser confundidos:

1. **aprovar uma proposta de alteração** pelo `patch_digest` do M8.8;
2. **criar um branch Git local dedicado** por um `ExecutorRequest create_branch` independente.

Nenhum dos dois aplica o patch, cria commit, faz push ou abre pull request.

## Gate 1 — aprovação do patch

Somente um `ExecutorRequest` `modify_worktree` concluído com `status=proposed`, `patch_digest` válido e arquivos alterados pode originar `GitChangeApproval`.

```text
modify_worktree completed
        ↓
patch_digest
        ↓
GitChangeApproval pending
        ↓ usuário repete exatamente o digest
approved | cancelled
```

A aprovação persiste:

- request/execution/project IDs;
- `patch_digest`;
- fingerprint da proposta;
- inventário mínimo de arquivos alterados;
- timestamps e estado.

A aprovação **não cria branch nem escreve Git**.

## Gate 2 — branch Git dedicado

`create_branch` continua sujeito ao fluxo normal:

```text
allowlist do handoff
        ↓
ExecutorRequest prepared
        ↓
release explícito
        ↓
WorkerAttempt
        ↓
Git argv fixo
        ↓
branch local
```

Restrições:

- somente namespace `superchat/`;
- caracteres seguros e lowercase;
- `git check-ref-format --branch` valida novamente;
- branch nasce do `HEAD` local observado no momento da execução;
- branch existente é conflito e nunca é sobrescrito;
- nenhum checkout;
- nenhum arquivo do worktree é alterado;
- nenhum commit;
- nenhum push;
- nenhuma operação de rede;
- ambiente Git mínimo, sem credenciais herdadas do processo pai;
- shell permanece desabilitado.

## Independência dos gates

A criação de branch não consome nem aplica uma `GitChangeApproval`. O objetivo do M8.9 é preparar os dois pré-requisitos separadamente e deixar a aplicação para um estágio posterior.

O próximo estágio deverá exigir simultaneamente:

- uma `GitChangeApproval` em estado `approved`;
- digest idêntico ao patch que será reaplicado;
- branch dedicado existente e compatível com o `base_sha` revisado;
- nova autorização específica para aplicar a mudança.

## Fora do escopo

M8.9 não implementa:

- aplicação persistente do patch;
- checkout do branch;
- `git add`;
- commit;
- push;
- criação de pull request;
- merge;
- deploy/publicação.
