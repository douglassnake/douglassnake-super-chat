# M14.1 — auditoria operacional read-only no ZimaOS/NAS

Issue principal: #94. Estado: **planejado; evidências atuais do host ainda pendentes**.

## Objetivo

Antes de criar monitoramento/alerta novo, verificar as rotinas já implementadas pelo M12 e pelo M13, sem reexecutar implantação, mexer no banco de produção nem expor secrets. Este procedimento apenas coleta evidências; **não encerra M14.1 por si só**.

## Baseline conhecido (M12/M13)

- `scripts/ops_backup.sh`: `pg_dump -Fc`, verificação `pg_restore -l`, SHA-256, retenção dos 14 dumps automáticos; cron documentado para **03:15 diariamente**.
- `scripts/ops_restore_check.sh`: restore semanal aos **domingos às 04:00**, usando um banco descartável, com limpeza automática e integration readiness.
- `scripts/ops_storage_check.sh`: valida containers, configuração `json-file` 10m × 5 e no mínimo 15% livre.
- PostgreSQL principal: `app-db-1`; API: `app-api-1`; proxy HTTPS Caddy compartilhado. Dados em `/dev/sdc8`; backups em `/dev/md0` (conforme checkpoint M12.4).
- Cron do GitHub M13.1: `*/30 * * * *`, separado das rotinas de backup.

Os itens acima foram validados no passado; **confirmar situação atual no host**, sem presumir sucesso do cron.

## Execução — SSH no host, blocos curtos

Os comandos abaixo não reiniciam containers, não executam restore nem modificam cron. Não compartilhar dumps, conteúdos de arquivos `.sha256`, configuração de secrets ou logs brutos de produção.

### 1. Git e diretório (não alterar o checkout)

```bash
export DOCKER_CONFIG=/DATA/AppData/superchat/docker-config
cd /DATA/AppData/superchat/app
git rev-parse HEAD
git status --short
```

A revisão de M13 a confirmar, após `git pull --ff-only` previamente autorizado, é `58793c4a5ee92c2b78a55acb89779575826a2100`. Se o host estiver numa revisão anterior ou apresentar modificações locais, registrar a diferença antes de prosseguir com qualquer novo deploy.

### 2. Cron: apenas contagens e horários

```bash
crontab -l 2>/dev/null | awk '/scripts\/ops_backup.sh/ {print "backup:", $1,$2,$3,$4,$5}'
crontab -l 2>/dev/null | awk '/scripts\/ops_restore_check.sh/ {print "restore:", $1,$2,$3,$4,$5}'
crontab -l 2>/dev/null | awk '/scripts\/ops_github_sync.sh/ {print "github:", $1,$2,$3,$4,$5}'
```

Esperado: **uma linha por rotina**. Ausência, duplicidade ou horário divergente exigem investigação, não edição automática. Os comandos não imprimem o corpo das entradas do cron.

### 3. Backups: existência, idade e verificação de integridade

```bash
B=/DATA/Backup/superchat/automatic
find "$B" -maxdepth 1 -type f -name 'auto-superchat-*.dump' | sort | tail -n 3 | xargs -r ls -lh
```

Para verificar somente o SHA do dump mais recente:

```bash
LATEST=$(find "$B" -maxdepth 1 -type f -name 'auto-superchat-*.dump' | sort | tail -n 1)
if [ -n "$LATEST" ]; then (cd "$B" && sha256sum -c "$(basename "$LATEST").sha256"); else echo NO_BACKUP_FOUND; fi
```

A idade do último dump deve ser comparada com o cron diário observado (M14.2 definirá os thresholds automáticos). Não reproduzir o conteúdo do dump.

### 4. Histórico mínimo do restore-check

```bash
grep 'restore-check: completed successfully' "$B/restore-check.log" | tail -n 3
```

Se o arquivo não existir ou não houver linhas de sucesso, registrar como **evidência ausente** e investigar; não confundir log vazio com restore bem-sucedido. Em M14.4 será realizado um novo exercício controlado no banco descartável.

### 5. Auditoria de containers, logs e espaço (já existente)

```bash
/bin/bash scripts/ops_storage_check.sh
```

A execução é somente leitura. Em caso de discrepância na rotação real de logs, **não recriar o PostgreSQL** para ajustar a configuração; registrar um risco com plano separado.

### 6. Guardrails de recuperação

- Verificar que não existem bancos temporários `superchat_restore_check_*` somente quando necessário e por consulta de leitura no `pg_database`; nunca eliminá-los automaticamente.
- Não executar `docker compose up/down`, `restart`, `prune`, `dropdb`, `createdb` ou migration durante a auditoria.
- Nenhuma senha, token, `DATABASE_URL`, dump ou outro conteúdo privado em Issues/PRs.
- Não habilitar alerta externo ou novo cron nesta etapa.

## Critério de saída M14.1

Registrar na Issue #94 apenas evidências sanitizadas:

1. revisão Git e estado de working tree;
2. presença e horários dos três cron jobs;
3. carimbo de tempo/tamanho do dump mais recente e SHA-256 válido/inválido;
4. data do último restore-check concluído ou ausência de evidência;
5. `ops_storage_check.sh`: PASS/FAIL, espaço mínimo observado e divergências de logging;
6. confirmação de que banco principal e containers não foram reiniciados por esta auditoria.

Somente após esses dados planejar thresholds, status operacionais e alertas M14.2/M14.3. Não exigir rollback ou alterar cron quando a auditoria for inconclusiva.
