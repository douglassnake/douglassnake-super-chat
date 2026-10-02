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

O horário do cron deve ser decidido no host antes da ativação. A linha final deverá chamar explicitamente `/bin/bash`, sem depender de `.venv` ativo ou de shell interativo.

Modelo:

```text
<MINUTO> <HORA> * * * cd /DATA/AppData/superchat/app && BACKUP_ROOT=/DATA/Backup/superchat/automatic DB_CONTAINER=app-db-1 KEEP_COUNT=14 /bin/bash scripts/ops_backup.sh >> /DATA/Backup/superchat/automatic/backup.log 2>&1
```

Antes de instalar o cron:

1. executar a rotina manualmente;
2. validar o `.dump` e seu `.sha256`;
3. executar uma segunda vez para provar idempotência operacional e lock liberado;
4. confirmar espaço livre;
5. só então adicionar o agendamento.

## Próximas etapas

- M12.2 — restore periódico em banco descartável;
- M12.3 — retenção/rotação de logs Docker;
- M12.4 — fechar o checkpoint do host real rastreado na Issue #57;
- M12.5 — atualizar documentação geral M10/M11/M12;
- M12.6 — onboarding dos projetos reais.
