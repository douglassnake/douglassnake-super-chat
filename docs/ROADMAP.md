# Roadmap

## M0–M6 — Fundação, memória, contexto, interface e conectores
Status: **concluído e integrado em `main`**.

Memória operacional, Context Engine, GitHub somente leitura, Session Memory, interface web e Google Drive/Calendar somente leitura.

## M7 — Qualidade de recuperação

### M7.0 — benchmark de contexto
Status: **concluído e integrado**.

Baseline sintético: 13.926 tokens candidatos → 1.794 selecionados, compressão 0,871176 e recall@2 de 1,0 no fixture.

### M7.1 — busca híbrida/semântica
Status: **adiado por evidência — 08/10/2026**.

O benchmark real do M13.4 atingiu média de recall@k de 1,0 e recall crítico de 1,0 nos três projetos ativos. Embeddings/pgvector permanecem fora do escopo até um benchmark futuro demonstrar falha relevante do mecanismo lexical ou ganho mensurável de uma alternativa semântica.

## M8 — Automação e agentes
Status: **M8.0–M8.15 concluídos e integrados em `main`**.

A pilha M8 implementou Task Packs, handoffs, tracking, verificação GitHub, executor controlado, isolamento, worker endurecido, proveniência/reconciliação, alteração efêmera + diff, aprovação por digest, branch dedicada, aplicação em staging, commit explícito, publicação em bare local, publicação GitHub via credential broker e criação controlada de PR.

O M8.15 adicionou integration readiness e validou a pilha completa em PostgreSQL 17 limpo.

## M9 — Segurança e operação self-hosted
Status: **M9.0–M9.3 concluídos**.

### M9.0
Autenticação single-admin, PBKDF2-SHA256, sessão opaca server-side, CSRF, cookie seguro e migration `0009_auth_sessions`.

### M9.1
`X-Request-ID`, logs HTTP JSON sanitizados, `/ops/status`, `/ops/summary` e `/ops/failures`.

### M9.2
`SecretStore` allowlisted, backend `files`, recovery scripts, backup/restore e fail-closed em produção.

### M9.3
Preflight self-hosted, overlays Compose de produção, bind local, rotação de logs e critérios de go/no-go para ZimaOS/NAS.

O checkpoint real que inicialmente ficou separado do M9.3 foi concluído no M12.4 e a Issue #57 foi fechada.

## M10 — Operação do Segundo Cérebro pela Web
Status: **M10.2–M10.3.1 concluídos e integrados**.

### M10.2 — CRUD operacional
Entregas:
- CRUD Web de projetos;
- CRUD de tarefas, decisões e memórias;
- conclusão de tarefas;
- inclusão de fonte GitHub;
- refresh do dashboard sem operar diretamente a API.

### M10.3 — onboarding GitHub
Entregas:
- fluxo de onboarding em `/projects/{project_id}/github/onboarding`;
- preservação de revisão humana;
- retomada do projeto com contexto suficiente para configurar a fonte;
- polimento de UX em M10.3.1.

## M11 — Grafo do conhecimento
Status: **M11.1–M11.6 concluídos e integrados**.

### M11.1 — visualização
Painel e Grafo, filtros, zoom, pan, foco por vizinhança e inspector lateral.

### M11.2 — relações semânticas tipadas
Migration `0010_semantic_graph_relations`.

Tabelas:
- `knowledge_entities`;
- `project_relations`.

Relações:
`USES`, `RUNS_ON`, `DEPENDS_ON`, `PART_OF`, `CREATED_FROM`, `SUPPORTS`, `BLOCKS`, `IMPLEMENTS`, `DECIDED_BY`, `RELATED_TO`, `HAS_DOCUMENT`.

### M11.3 — documentos e arquivos
Documentos passam a ser entidades de conhecimento e podem se ligar a projetos com `HAS_DOCUMENT`.

### M11.4 — descoberta + revisão humana
Migration `0011_graph_suggestion_batches`.

Sugestões carregam evidência, confiança e estado de revisão. Relações persistentes só aparecem após ação explícita de aplicar; também é possível descartar ou revisar depois.

### M11.5 — relações documento → entidade
Migration `0012_cross_knowledge_relations`.

Nova tabela `knowledge_relations` e relações `MENTIONS`, `DESCRIBES` e `CREATED_FROM` entre entidades de conhecimento.

### M11.5.1 / M11.6 — direção semântica
Inspector distingue relações de saída e entrada, e o grafo desenha setas somente nas arestas semânticas direcionadas.

## M12 — Operação real contínua no ZimaOS/NAS
Issue principal: #76.

### M12.1 — backup automático + retenção
Status: **concluído**.

- `scripts/ops_backup.sh`;
- dump PostgreSQL custom-format;
- SHA-256;
- promoção atômica;
- retenção restrita ao namespace automático;
- cron diário às 03:15 no host real.

### M12.2 — restore periódico
Status: **concluído**.

- `scripts/ops_restore_check.sh`;
- banco descartável;
- validação de Alembic/tabelas/dados;
- `integration_readiness.py --database`;
- cleanup no `trap EXIT`;
- cron semanal aos domingos às 04:00.

### M12.3 — logs e armazenamento
Status: **concluído**.

- Docker `json-file`;
- `max-size=10m`;
- `max-file=5`;
- auditoria read-only com `scripts/ops_storage_check.sh`;
- verificação de headroom em AppData e backup.

### M12.4 — checkpoint do host real
Status: **concluído em 06/10/2026**.

Commit validado:
`dd9eab884deed3865e51ffa68ac3cc9ddb37986f`.

Evidências:
- preflight `ready`;
- secret store e rotação atômica;
- HTTPS `200`;
- API direta somente em loopback;
- backup real com SHA-256;
- restore em banco descartável;
- integration readiness `pass`;
- PostgreSQL principal sem restart;
- dados em `/dev/sdc8` e backup em `/dev/md0` RAID1;
- Issue #57 fechada com GO para operação interna.

### M12.5 — documentação M10/M11/M12
Status: **concluído**.

Objetivo:
- atualizar README;
- alinhar arquitetura, UI, modelo de dados e roadmap;
- registrar o grafo M11 como componente de primeira classe;
- remover referências ao checkpoint real como pendente;
- consolidar runbooks M12.

### M12.6 — onboarding dos projetos reais
Status: **concluído em 07/10/2026**.

Entregas deste marco:
- importador idempotente por manifesto privado;
- dry-run como padrão e gravação somente com `--apply`;
- upsert de projetos, fontes, decisões, tarefas, memórias e relações semânticas;
- manifesto real mantido fora do Git;
- validação no host com pelo menos três projetos reais;
- recuperação de contexto suficiente para retomada;
- segunda execução sem duplicação.

Validação final no ZimaOS/NAS: três projetos reais ativos, retomada por snapshot, relações semânticas persistidas e segunda execução do mesmo manifesto sem duplicações. A Issue #76 foi encerrada como completed.

## M13 — atualização contínua e qualidade do Segundo Cérebro
Issue principal: #86.

Status: **M13.1–M13.5 concluídos em 08/10/2026**.

Entregas concluídas:
- M13.1 — sincronização periódica GitHub read-only, isolada por projeto, agendada a cada 30 minutos;
- M13.2 — frescor e saúde das fontes com estados visíveis no painel;
- M13.3 — digest de mudanças com revisão humana via SessionDelta;
- M13.4 — benchmark real dos três projetos, recall médio 1,0 e decisão `defer_m7_1`;
- M13.5 — validação operacional no ZimaOS/NAS e documentação final.

Evidências principais:
- cron real observado no host;
- idempotência de eventos e digest;
- falha de uma fonte sem bloquear outra;
- PostgreSQL principal sem restart causado pelas rotinas;
- benchmark read-only com `ContextRun` inalterado;
- nenhum efeito externo de escrita autorizado pelo M13.

Plano e fechamento: `docs/M13_CONTINUOUS_CONTEXT.md`.

## M14 — confiabilidade operacional e recuperação
Issue principal: #94.

Status em **08/10/2026**: **M14.1–M14.4 concluídos; M14.5 pendente** de evidência real do primeiro restore automático agendado para domingo **11/10/2026, 04h (-03)**. O exercício manual de restauração **não substitui** essa validação dominical.

- **M14.1 — auditoria real do host:** verificados Git, cron, backups, SHA-256, espaço, containers, logs e ausência de bancos temporários órfãos.
- **M14.2 — saúde e frescor:** `scripts/ops_health_check.py` validado no ZimaOS; distingue backup `fresh` e restore `not_due` antes da primeira execução.
- **M14.3 — observabilidade e alertas locais:** `scripts/ops_health_alert.py`, deduplicação, estado privado 0700/0600, logger/journal validados; cron horário `45 * * * *` instalado e primeira execução automática `healthy` comprovada. **Nenhum alerta externo está configurado.**
- **M14.4 — exercício de recuperação:** `scripts/ops_restore_check.sh` reutilizado em DB descartável; `DRILL_EXIT=0`, duração de 7 s, integration readiness aprovado, 0 bancos temporários restantes; teste negativo `NEGATIVE_EXIT=1`, lock limpo. Duração do ensaio e idade do dump são **proxies observados**, não SLAs de RTO/RPO.
- **M14.5 — validação final:** checklist versionado e CI aprovado. Encerramento depende de evidência da execução **automática** do restore dominical em log separado, `restore=fresh`, ausência de bancos/locks, cron único e serviços saudáveis. **Ainda não concluído.**

Runbooks: `docs/M14_1_REAL_HOST_AUDIT.md`, `docs/M14_3_LOCAL_ALERTS.md`, `docs/M14_4_RECOVERY_DRILL.md` e `docs/M14_5_FINAL_AUDIT.md`. Não reiniciar o PostgreSQL por operações documentais.

## Regra de evolução

Cada efeito externo deve ter autorização própria, input resolvido pelo servidor, prova de estado anterior, verificação pós-efeito, segredo fora do estado persistido e reconciliação explícita quando rollback total não for possível.

A mesma filosofia se aplica ao grafo: descoberta automática pode sugerir; persistência sem revisão humana não é permitida.
