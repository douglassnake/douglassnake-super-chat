# M12 — operação real contínua

Este runbook cobre a passagem do Super Chat de uma implantação funcional para uma operação contínua no ZimaOS/NAS.

## M12.1 — backup automático + retenção

A rotina `scripts/ops_backup.sh` cria backups automáticos do PostgreSQL sem recriar, reiniciar ou publicar a porta do banco.

Características:

- usa `pg_dump -Fc` dentro do container PostgreSQL já em execução;
- valida o arquivo com `pg_restore -l` antes de promovê-lo a backup definitivo;
- calcula SHA-256 e grava sidecar `.sha256`;
- grava primeiro em arquivo temporário e só então faz `mv`, evitando backup parcialmente publicado;
- usa lock por diretório para impedir duas execuções simultâneas;
- retenção só remove arquivos do namespace `auto-superchat-*.dump`;
- dumps manuais de pré-deploy, como `pre-m11-*`, nunca entram na retenção automática;
- cópia secundária é opcional e só é promovida após validação do mesmo SHA-256;
- credenciais do PostgreSQL permanecem dentro do container e não são escritas em argumentos ou logs.

### Configuração usada no ZimaOS

Diretório principal recomendado:

```text
/DATA/Backup/superchat/automatic
```

Container PostgreSQL atual:

```text
app-db-1
```

Execução manual de validação:

```bash
cd /DATA/AppData/superchat/app

BACKUP_ROOT=/DATA/Backup/superchat/automatic \
DB_CONTAINER=app-db-1 \
KEEP_COUNT=14 \
/bin/bash scripts/ops_backup.sh
```

O resultado deve terminar com `backup: completed successfully` e imprimir o caminho do novo `.dump`.

### Segunda cópia

Quando houver um destino realmente separado do volume primário, configure `SECONDARY_ROOT`:

```bash
BACKUP_ROOT=/DATA/Backup/superchat/automatic \
SECONDARY_ROOT=/CAMINHO/EM/OUTRO/DISCO/superchat \
DB_CONTAINER=app-db-1 \
KEEP_COUNT=14 \
SECONDARY_KEEP_COUNT=30 \
/bin/bash scripts/ops_backup.sh
```

Não use o diretório de dados do PostgreSQL como destino de backup.

### Agendamento

O horário do cron deve chamar explicitamente `/bin/bash`, sem depender de `.venv` ativo ou de shell interativo.

Modelo:

```text
<MINUTO> <HORA> * * * cd /DATA/AppData/superchat/app && BACKUP_ROOT=/DATA/Backup/superchat/automatic DB_CONTAINER=app-db-1 KEEP_COUNT=14 /bin/bash scripts/ops_backup.sh >> /DATA/Backup/superchat/automatic/backup.log 2>&1
```

No host real, M12.1 foi validado manualmente e ativado para execução diária às 03:15, com retenção de 14 backups automáticos.

## M12.2 — restore periódico em banco descartável

A rotina `scripts/ops_restore_check.sh` comprova que o backup automático mais recente é realmente restaurável sem tocar no banco principal.

Fluxo:

1. seleciona o `auto-superchat-*.dump` mais recente;
2. valida o sidecar SHA-256;
3. valida o formato com `pg_restore -l`;
4. cria um banco temporário com prefixo `superchat_restore_check_`;
5. restaura o dump com `pg_restore --exit-on-error`;
6. compara o `alembic_version` restaurado com o banco principal;
7. valida tabelas críticas, incluindo memória operacional e grafo semântico;
8. executa leituras básicas em `projects` e `knowledge_entities`;
9. remove o banco descartável no `trap EXIT`, inclusive quando a validação falha.

O script nunca usa o banco `POSTGRES_DB` como alvo de restore, não recria o container e não reinicia o PostgreSQL.

### Execução manual

```bash
cd /DATA/AppData/superchat/app

BACKUP_ROOT=/DATA/Backup/superchat/automatic \
DB_CONTAINER=app-db-1 \
/bin/bash scripts/ops_restore_check.sh
```

O resultado esperado termina com:

```text
restore-check: completed successfully
```

Após a execução, confirme que não restou banco descartável:

```bash
docker exec app-db-1 sh -c 'psql -Atq -U "$POSTGRES_USER" -d postgres -c "SELECT datname FROM pg_database WHERE datname LIKE '\''superchat_restore_check_%'\'';"'
```

Nenhuma linha deve ser retornada.

### Agendamento semanal

O restore-check deve ser agendado somente depois da validação manual no ZimaOS. Como o backup diário roda às 03:15, o horário recomendado para o teste semanal é domingo às 04:00:

```text
0 4 * * 0 cd /DATA/AppData/superchat/app && BACKUP_ROOT=/DATA/Backup/superchat/automatic DB_CONTAINER=app-db-1 /bin/bash scripts/ops_restore_check.sh >> /DATA/Backup/superchat/automatic/restore-check.log 2>&1
```

Isso garante que o teste semanal use, em condições normais, um backup produzido menos de uma hora antes.

## Próximas etapas

- M12.3 — retenção/rotação de logs Docker;
- M12.4 — fechar o checkpoint do host real rastreado na Issue #57;
- M12.5 — atualizar documentação geral M10/M11/M12;
- M12.6 — onboarding dos projetos reais.
