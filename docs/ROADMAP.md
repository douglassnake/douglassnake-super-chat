# Roadmap

## M0 — Fundação documental
Status: **concluído**.

## M1 — Memória operacional
Status: **concluído**.

FastAPI, PostgreSQL, Alembic, projetos, decisões, tarefas, resumos, snapshot, Docker e testes.

## M2 — Context Engine v1
Status: **concluído**.

Perfis `minimal`, `standard` e `deep`, ranking determinístico, deduplicação, compactação, orçamento de tokens, auditoria e `continue`.

## M3 — GitHub Connector
Status: **concluído**.

GitHub somente leitura, commits, PRs, Issues, Actions, eventos normalizados e sync idempotente.

## M4 — Session Memory
Status: **concluído**.

`SessionDelta`, preview, confirmação humana, aplicação transacional e descarte.

## M5 — Interface web
Status: **concluído**.

Dashboard responsivo, Health Score explicável, projetos, tarefas, fontes, eventos, painel de tokens e revisão visual dos deltas.

## M6 — Google Drive e Calendar
Status: **concluído**.

Drive/Calendar somente leitura, metadados persistidos sem copiar documentos completos, recuperação sob demanda, eventos normalizados e sync idempotente.

## M7 — Qualidade de recuperação

### M7.0 — benchmark de contexto
Status: **concluído na branch `codex/m7-retrieval-benchmark`**.

Baseline sintético v1: cenário de pressão `minimal` com 13.926 tokens candidatos → 1.794 selecionados, compressão 0,871176 e recall@2 de 1,0 no fixture.

### M7.1 — busca híbrida/semântica
Status: **condicional — não iniciado**.

Embeddings/pgvector somente se benchmark privado com consultas reais demonstrar ganho mensurável.

## M8 — Automação e agentes

### M8.0 — Agent Task Packs
Status: **concluído**.

### M8.1 — handoff assistido e auditável
Status: **concluído**.

### M8.2 — acompanhamento de execução e evidências
Status: **concluído**.

### M8.3 — verificação externa GitHub somente leitura
Status: **concluído**.

### M8.4 — executor controlado
Status: **concluído**.

### M8.5 — adapter local isolado
Status: **concluído**.

Capacidades reais iniciais: `read_repository` somente metadata e `run_tests` somente preset server-side `pytest`.

### M8.6 — hardening do worker
Status: **concluído**.

Worker separado da API, workspace efêmero para testes, limites de recurso, ambiente mínimo, timeout, redaction e contrato container sem rede por padrão.

### M8.7 — proveniência e reconciliação do worker
Status: **concluído na branch `codex/m8-7-worker-provenance`**.

Entregas principais:
- `WorkerAttempt` persistente e numerado;
- identidade do worker;
- `job_digest` e `result_digest` SHA-256;
- lease/heartbeat;
- reconciliação `expired/orphaned`;
- retry explícito com nova tentativa;
- máximo de tentativas server-side;
- eventos append-only.

### M8.8 — alteração efêmera e diff revisável
Status: **concluído na branch `codex/m8-8-ephemeral-diff` após CI funcional verde**.

Entregas:
- `modify_worktree` como primeira escrita real do executor;
- escrita somente em cópia temporária do worktree;
- operações permitidas: `write_text` e `delete_file`;
- nenhum shell, script, executável, argv ou patch arbitrário fornecido pelo cliente;
- paths relativos POSIX; bloqueio de absoluto, `..`, NUL, backslash e symlink;
- arquivos binários/non-UTF-8 fora do contrato;
- limites server-side de arquivos, operações, bytes escritos e patch;
- hard caps adicionais dentro do worker;
- unified diff revisável;
- inventário `added/modified/deleted`;
- `patch_digest` SHA-256 calculado após redaction;
- secrets detectáveis bloqueados/redigidos;
- resultado marcado `external_effects=false` e `workspace_persistence=ephemeral_only`;
- worktree original permanece sem escrita por design;
- proveniência, lease e tentativa do M8.7 preservados;
- documentação `docs/WORKTREE_DIFF.md`.

Capacidades reais atuais:
- `read_repository` → metadata;
- `run_tests` → pytest;
- `modify_worktree` → proposta efêmera + diff.

Continuam sem implementação real:
- `create_branch`;
- `create_commit`;
- `create_pull_request`.

Continuam proibidos:
- merge;
- deploy;
- publicação;
- escrita em Drive/Calendar;
- escrita externa genérica;
- shell/comando/binário/argv arbitrário.

### M8.9 — persistência Git de proposta aprovada
Status: **futuro/condicional**.

Antes de persistir qualquer patch no Git:
- proposta M8.8 deve possuir digest estável e aprovação humana específica;
- branch deve ser criado por autorização independente;
- identidade Git do executor deve ser exclusiva e configurada no servidor;
- aplicar somente o patch aprovado, rejeitando digest divergente;
- validar novamente paths, secrets, tamanho e estado-base do worktree;
- detectar drift entre base revisada e base atual;
- commit deve exigir autorização separada da alteração;
- push/PR em etapas distintas;
- imagem de worker/container deve ser pinada por digest antes de qualquer execução de código ligada à persistência Git;
- merge/deploy/publish permanecem fora.

## Regra de evolução

Não ampliar autonomia antes de existir:
1. fonte de verdade;
2. modelo de dados;
3. rastreabilidade;
4. métrica de contexto;
5. autorização humana explícita;
6. evidência verificável;
7. política específica por efeito;
8. isolamento e limites de recurso;
9. worker separado e auditável;
10. proveniência/reconciliação;
11. diff revisável;
12. aprovação por digest antes de escrita Git persistente.
