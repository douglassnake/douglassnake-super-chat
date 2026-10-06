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

Descubra os paths montados sem imprimir qualquer segredo e execute o preflight com o virtualenv do projeto. Em uma instalação já existente, o diretório do PostgreSQL pode ser gravável apenas pelo serviço/container; `--data-managed-by-service` valida o path sem exigir escrita pelo operador. Como o checkpoint é pós-deploy, `--bind-port 0` usa uma porta efêmera livre para validar a capacidade de bind local; a exposição real de `8010` é validada separadamente abaixo.

```bash
export DOCKER_CONFIG="/DATA/AppData/superchat/docker-config"
cd /DATA/AppData/superchat/app

SECRET_DIR="$(docker inspect -f '{{range .Mounts}}{{if eq .Destination "/run/superchat-secrets"}}{{.Source}}{{end}}{{end}}' app-api-1)"
DATA_DIR="$(docker inspect -f '{{range .Mounts}}{{if eq .Destination "/var/lib/postgresql/data"}}{{.Source}}{{end}}{{end}}' app-db-1)"
BACKUP_DIR="/DATA/Backup/superchat"

./.venv/bin/python scripts/self_hosted_preflight.py \
  --secret-dir "$SECRET_DIR" \
  --data-dir "$DATA_DIR" \
  --backup-dir "$BACKUP_DIR" \
  --min-free-gib 5 \
  --bind-host 127.0.0.1 \
  --bind-port 0 \
  --data-managed-by-service \
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
LAN_IP="$(ip -4 route get 1.1.1.1 | awk '{for(i=1;i<=NF;i++) if($i=="src"){print $(i+1); exit}}')"
curl -kfsS --resolve "superchat.home.arpa:443:${LAN_IP}" \
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

A Issue #57 exige que o destino de backup fique fora do volume primário de dados. No host validado, o PostgreSQL está em `/dev/sdc8` e `/DATA/Backup/superchat` está em `/dev/md0`, um RAID1 em discos físicos distintos. Essa separação satisfaz o requisito do checkpoint.

Confirme a topologia com:

```bash
df -hT
lsblk -o NAME,TYPE,FSTYPE,SIZE,MOUNTPOINTS
```

Um `SECONDARY_ROOT` adicional em NAS remoto, USB ou outro destino independente continua recomendado como defesa em profundidade, mas não é requisito adicional para fechar a Issue #57 quando `sdc8` versus `md0` estiver comprovado.

Checkpoint concluído em 06/10/2026. As evidências finais foram registradas na Issue #57, que foi fechada como completed no commit validado `dd9eab884deed3865e51ffa68ac3cc9ddb37986f`.

## M12.6 — onboarding controlado de projetos reais

O onboarding real usa `scripts/onboard_projects.py`, que lê um manifesto JSON privado e faz upsert idempotente de:

- projetos;
- fontes;
- decisões;
- tarefas;
- memórias/context items;
- entidades canônicas e relações projeto → entidade.

O script não recebe token, senha ou secret no schema. Campos extras são recusados por validação `extra=forbid`. Manifestos reais devem permanecer fora do Git. Arquivos com sufixo `*.onboarding.private.json` também são ignorados pelo repositório como proteção adicional.

Exemplo sanitizado:

```text
docs/M12_6_ONBOARDING_EXAMPLE.json
```

### Execução segura no host

1. confirmar backup automático recente e restore-check verde;
2. sincronizar o `main`;
3. gravar o manifesto real em diretório privado fora do repositório;
4. copiar temporariamente o script e o manifesto para o container da API;
5. executar primeiro em dry-run;
6. revisar somente contagens/slugs retornados;
7. repetir com `--apply`;
8. validar projeto/snapshot/grafo;
9. remover os arquivos temporários do container.

Modelo:

```bash
PRIVATE_DIR=/DATA/AppData/superchat/private
MANIFEST="$PRIVATE_DIR/m12-6.onboarding.private.json"

chmod 600 "$MANIFEST"

docker cp scripts/onboard_projects.py app-api-1:/tmp/onboard_projects.py
docker cp "$MANIFEST" app-api-1:/tmp/m12-6.onboarding.private.json

docker exec -w /app app-api-1 \
  python /tmp/onboard_projects.py \
  --manifest /tmp/m12-6.onboarding.private.json

docker exec -w /app app-api-1 \
  python /tmp/onboard_projects.py \
  --manifest /tmp/m12-6.onboarding.private.json \
  --apply

docker exec app-api-1 rm -f \
  /tmp/onboard_projects.py \
  /tmp/m12-6.onboarding.private.json
```

Sem `--apply`, todas as alterações são revertidas. O relatório não imprime corpos de decisões, tarefas ou memórias; mostra apenas slugs, IDs e contagens.

### Critério de conclusão

M12.6 só é concluído quando:

- pelo menos três projetos reais estiverem presentes no banco;
- cada projeto tiver próxima ação coerente;
- projetos com GitHub conhecido tiverem fonte ativa;
- o grafo tiver relações canônicas úteis sem duplicação óbvia;
- `/continue` ou snapshot recuperar contexto suficiente para retomada;
- a execução idempotente do manifesto não criar duplicatas;
- nenhum dado real ou manifesto privado tiver sido versionado no Git.

## Estado dos marcos

- M12.1 — concluído;
- M12.2 — concluído;
- M12.3 — concluído;
- M12.4 — concluído; Issue #57 fechada;
- M12.5 — concluído;
- M12.6 — em andamento: onboarding dos projetos reais.
