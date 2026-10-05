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
9. executa `scripts/integration_readiness.py --database` dentro do container da API, apontando somente aquela execução para o banco descartável;
10. remove o banco descartável no `trap EXIT`, inclusive quando a validação falha.

O script nunca usa o banco `POSTGRES_DB` como alvo de restore, não recria o container e não reinicia o PostgreSQL. O valor real de `DATABASE_URL` permanece dentro do container da API; o host só informa o nome não sensível do banco temporário via `RESTORE_CHECK_DB`.

### Execução manual

```bash
cd /DATA/AppData/superchat/app

BACKUP_ROOT=/DATA/Backup/superchat/automatic \
DB_CONTAINER=app-db-1 \
API_CONTAINER=app-api-1 \
/bin/bash scripts/ops_restore_check.sh
```

O resultado esperado inclui `restore-check: integration readiness passed` e termina com:

```text
restore-check: completed successfully
```

Após a execução, confirme que não restou banco descartável:

```bash
docker exec app-db-1 sh -c 'psql -Atq -U "$POSTGRES_USER" -d postgres -c "SELECT datname FROM pg_database WHERE datname LIKE '\''superchat_restore_check_%'\'';"'
```

Nenhuma linha deve ser retornada.

### Agendamento semanal

Como o backup diário roda às 03:15, o restore-check foi ativado no host real para domingo às 04:00:

```text
0 4 * * 0 cd /DATA/AppData/superchat/app && BACKUP_ROOT=/DATA/Backup/superchat/automatic DB_CONTAINER=app-db-1 /bin/bash scripts/ops_restore_check.sh >> /DATA/Backup/superchat/automatic/restore-check.log 2>&1
```

`API_CONTAINER` possui default `app-api-1`, portanto o cron existente continua válido após a ampliação do restore-check.

## M12.3 — rotação de logs Docker + espaço em disco

O overlay `docker-compose.production.yml` já define logs limitados para `db` e `api` com driver `json-file`, `max-size=10m` e `max-file=5` por padrão. O M12.3 não altera esses limites: ele comprova que os containers reais foram criados com a configuração esperada e verifica espaço livre nos filesystems usados pelo aplicativo e pelos backups.

A rotina `scripts/ops_storage_check.sh` é somente leitura. Ela:

- confirma que `app-db-1` e `app-api-1` estão em execução;
- lê a configuração efetiva de logging dos containers;
- exige `json-file`, `10m` e `5` por padrão, ou os valores informados por ambiente;
- informa o caminho e o tamanho do arquivo de log ativo quando o host permite leitura;
- verifica espaço livre em `/DATA/AppData/superchat` e `/DATA/Backup/superchat`;
- falha quando houver menos de 15% de espaço livre por padrão;
- mostra `docker system df` apenas como diagnóstico;
- nunca executa `restart`, `stop`, `rm`, `compose up/down` ou qualquer prune.

### Execução manual

Após merge e CI verde:

```bash
cd /DATA/AppData/superchat/app

DB_CONTAINER=app-db-1 \
API_CONTAINER=app-api-1 \
SUPERCHAT_LOG_MAX_SIZE=10m \
SUPERCHAT_LOG_MAX_FILES=5 \
MIN_FREE_PERCENT=15 \
APP_ROOT=/DATA/AppData/superchat \
BACKUP_ROOT=/DATA/Backup/superchat \
/bin/bash scripts/ops_storage_check.sh
```

O resultado esperado termina com:

```text
storage-check: completed successfully
```

Se houver diferença entre a configuração real de logging e o Compose, não recrie o PostgreSQL automaticamente. Primeiro registre a divergência, confirme backup recente e restore-check verde e planeje a recriação controlada do container. Se a configuração real já estiver correta, nenhum restart é necessário.

### Valores de produção

Os defaults versionados são:

```text
SUPERCHAT_LOG_MAX_SIZE=10m
SUPERCHAT_LOG_MAX_FILES=5
MIN_FREE_PERCENT=15
```

Com `max-size=10m` e `max-file=5`, cada container mantém no máximo aproximadamente cinco segmentos do log `json-file`, sujeitos ao comportamento do driver Docker. A checagem de espaço em disco continua necessária porque imagens, camadas, volumes e backups também consomem armazenamento.

## M12.4 — checkpoint operacional do host real

A Issue #57 só deve ser encerrada quando cada item tiver evidência do ZimaOS/NAS. Este checkpoint não presume sucesso por CI.

### 1. Preflight real

Descubra os paths montados sem imprimir qualquer segredo e execute o preflight. Como a API já ocupa `127.0.0.1:8010`, o teste de disponibilidade de bind usa `127.0.0.1:8000`; a exposição real de `8010` é validada separadamente abaixo.

```bash
export DOCKER_CONFIG="/DATA/AppData/superchat/docker-config"
cd /DATA/AppData/superchat/app

SECRET_DIR="$(docker inspect -f '{{range .Mounts}}{{if eq .Destination "/run/superchat-secrets"}}{{.Source}}{{end}}{{end}}' app-api-1)"
DATA_DIR="$(docker inspect -f '{{range .Mounts}}{{if eq .Destination "/var/lib/postgresql/data"}}{{.Source}}{{end}}{{end}}' app-db-1)"
BACKUP_DIR="/DATA/Backup/superchat"

python scripts/self_hosted_preflight.py \
  --secret-dir "$SECRET_DIR" \
  --data-dir "$DATA_DIR" \
  --backup-dir "$BACKUP_DIR" \
  --min-free-gib 5 \
  --bind-host 127.0.0.1 \
  --bind-port 8000 \
  --require-separate-backup-device
```

O JSON final precisa ter `"status": "ready"`. O preflight também valida Docker Engine, Docker Compose, policy do diretório de secrets, espaço livre e separação entre data e backup.

### 2. Prova de substituição atômica no filesystem privado de secrets

Não altere o secret ativo para provar o mecanismo. Faça uma rotação-probe no mesmo diretório privado e no mesmo filesystem:

```bash
ROT_DIR="$(mktemp -d "$SECRET_DIR/.rotation-probe.XXXXXX")"
umask 077
printf 'probe-v1\n' > "$ROT_DIR/current"
printf 'probe-v2\n' > "$ROT_DIR/new"
printf 'probe-v2\n' > "$ROT_DIR/expected"
chmod 600 "$ROT_DIR/current" "$ROT_DIR/new" "$ROT_DIR/expected"
mv -f "$ROT_DIR/new" "$ROT_DIR/current"
cmp -s "$ROT_DIR/current" "$ROT_DIR/expected" && echo 'SECRET_ROTATION_PROBE=PASS'
rm -rf "$ROT_DIR"
```

A evidência esperada é `SECRET_ROTATION_PROBE=PASS`, sem exibir valor de secret real.

### 3. HTTPS e isolamento da API

```bash
curl -kfsS --resolve superchat.home.arpa:443:127.0.0.1 \
  -o /dev/null -w 'HTTPS_STATUS=%{http_code}\n' \
  https://superchat.home.arpa/health

docker port app-api-1 8000/tcp
```

O health deve responder `HTTPS_STATUS=200` e a publicação direta da API deve aparecer apenas em `127.0.0.1`, atualmente `127.0.0.1:8010`. `0.0.0.0` ou `[::]` não satisfazem o checkpoint.

### 4. Backup/restore/readiness e cron

Execute novamente o restore-check ampliado e confira os dois agendamentos:

```bash
BACKUP_ROOT=/DATA/Backup/superchat/automatic \
DB_CONTAINER=app-db-1 \
API_CONTAINER=app-api-1 \
/bin/bash scripts/ops_restore_check.sh

crontab -l | grep -E 'scripts/ops_(backup|restore_check)\.sh'
```

O restore só é aceito quando também aparecer `restore-check: integration readiness passed`.

### 5. Destino secundário real de backup

A separação `/DATA/AppData/superchat` versus `/DATA/Backup/superchat` protege contra perda do filesystem primário de dados, mas não substitui uma segunda cópia independente. Para encerrar a Issue #57, defina `SECONDARY_ROOT` em outro disco, share de rede ou destino independente e valide uma cópia real com checksum.

Liste os filesystems montados antes de escolher o destino:

```bash
df -hT
lsblk -o NAME,TYPE,FSTYPE,SIZE,MOUNTPOINTS
```

Depois execute uma cópia de validação usando `scripts/ops_backup.sh` com `SECONDARY_ROOT` e confirme que o destino não resolve para o mesmo filesystem do backup principal. Não use GitHub público, o diretório de dados do PostgreSQL nem outro caminho no mesmo volume apenas com nome diferente.

Quando preflight, secret rotation probe, HTTPS/API isolation, restore + integration readiness e segunda cópia independente estiverem comprovados no host, registre commit/data/evidências e só então feche a Issue #57.

## Próximas etapas

- M12.4 — concluir e fechar o checkpoint do host real rastreado na Issue #57;
- M12.5 — atualizar documentação geral M10/M11/M12;
- M12.6 — onboarding dos projetos reais.
