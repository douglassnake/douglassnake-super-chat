# M8.7 — Worker Provenance & Reconciliation

Objetivo: tornar cada execução do worker identificável, verificável e reconciliável antes de ampliar efeitos reais.

## Escopo

- identidade estável do worker por processo;
- `job_digest` SHA-256 sobre o contrato serializado;
- `result_digest` SHA-256 sobre o resultado sanitizado;
- envelope de proveniência com backend, versão de schema, PID, host hash e timestamps;
- lease com expiração e heartbeat;
- registro persistente de tentativas por `ExecutorRequest`;
- detecção de tentativa órfã por lease expirada;
- reconciliação explícita de órfãos;
- retry controlado criando nova tentativa, sem reexecutar a tentativa anterior;
- limite configurável de tentativas;
- imagem de container documentada por referência pinável; tag flutuante não concede escrita;
- nenhuma ampliação de ações reais.

## Estados de tentativa

```text
leased -> running -> completed | failed
   |          |
   |          +-> orphaned
   +-> expired
```

Retry sempre cria um novo número de tentativa. Tentativas terminais permanecem imutáveis para auditoria.

## Segurança

- merge/deploy/publish seguem proibidos;
- `modify_worktree`, `create_branch`, `create_commit` e `create_pull_request` seguem sem efeito real;
- nenhum shell arbitrário;
- nenhum secret entra no envelope de proveniência;
- heartbeat nunca renova uma lease terminal;
- reconciliação não marca sucesso sem resultado verificável.
