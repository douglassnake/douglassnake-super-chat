# M8.8 — Alteração efêmera e diff revisável

O M8.8 é a primeira capacidade real de escrita do Super Chat, mas **não persiste alterações no repositório original**. A escrita ocorre somente em uma cópia temporária do worktree e o único artefato persistido é a proposta de patch/diff revisável.

## Fluxo

```text
ExecutorRequest: modify_worktree
        ↓ release explícito
WorkerAttempt
        ↓
WorkerJob
        ↓
cópia temporária do worktree
        ↓
operações semânticas
        ↓
unified diff + digest
        ↓
resultado auditável
        ↓
workspace temporário removido
```

## Operações aceitas

```json
{"op":"write_text","path":"src/example.py","content":"..."}
{"op":"delete_file","path":"docs/old.md"}
```

Não há suporte a shell, script, executável, argv, patch arbitrário fornecido pelo cliente ou edição binária.

## Limites server-side padrão

- máximo de 20 arquivos distintos;
- máximo de 40 operações;
- máximo de 64 KiB de conteúdo escrito;
- máximo de 64 KiB de patch persistido.

O worker possui hard caps adicionais. O cliente/agente não pode aumentar os limites pelo payload público.

## Paths

Todos os paths devem ser relativos, em estilo POSIX, sem `..`, path absoluto, NUL ou `\\`. Escritas através de symlink são rejeitadas. O pai de um novo arquivo precisa existir no worktree temporário.

Arquivos binários/não UTF-8 não podem ser modificados ou removidos pelo contrato M8.8.

## Secrets

Conteúdo detectado como credencial/token/secret é redigido pela camada comum do executor e também validado dentro do worker. Caso um secret preexistente apareça apenas como contexto de uma remoção, o patch persistido é redigido e `patch_redacted=true`.

O digest é calculado sobre o **patch persistido após redaction**.

## Resultado

O resultado inclui:

- `status=proposed`;
- `changed_files` com `added`, `modified` ou `deleted`;
- unified `patch`;
- `patch_digest` SHA-256;
- `patch_bytes`;
- `patch_redacted`;
- `workspace_persistence=ephemeral_only`;
- `external_effects=false`;
- política efetiva aplicada;
- proveniência M8.7 do worker.

## O que M8.8 não faz

O M8.8 não:

- altera o worktree original;
- cria branch;
- cria commit;
- faz push;
- cria pull request;
- faz merge;
- executa deploy/publicação;
- executa código contido na proposta.

O próximo estágio de escrita Git deve consumir apenas uma proposta previamente revisada/aprovada e manter branch, commit e PR como autorizações independentes.