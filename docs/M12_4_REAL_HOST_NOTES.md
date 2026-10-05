# M12.4.1 — notas do host real ZimaOS

Estas notas registram ajustes encontrados durante a primeira execução do checkpoint M12.4 no host real.

## Preflight Python

O `python` do sistema ZimaOS pode não ter as dependências Python do projeto. O preflight deve ser executado com o virtualenv do projeto quando disponível:

```bash
cd /DATA/AppData/superchat/app
./.venv/bin/python scripts/self_hosted_preflight.py \
  --secret-dir "$SECRET_DIR" \
  --data-dir "$DATA_DIR" \
  --backup-dir "$BACKUP_DIR" \
  --min-free-gib 5 \
  --bind-host 127.0.0.1 \
  --bind-port 8000 \
  --require-separate-backup-device
```

Antes da execução, confirme `test -x .venv/bin/python`.

## Integration readiness no container de produção

O container da API usa `SECRET_BACKEND=files` em produção. Os checks sintéticos de `integration_readiness.py` foram escritos para validar também o comportamento fail-closed do backend `settings`; quando herdavam o ambiente real `files`, dois checks estáticos falhavam apesar de o banco descartável estar íntegro.

O `ops_restore_check.sh` agora mantém o `DATABASE_URL` temporário somente dentro do container, mas executa o subprocesso de readiness com `SECRET_BACKEND=settings` e sem `SECRET_DIR`. Isso isola apenas os checks sintéticos. O preflight do host continua responsável por validar o diretório e os arquivos reais de secrets.

## HTTPS no host

Não assuma que o proxy compartilhado publica 443 no loopback `127.0.0.1`. A validação deve usar o hostname normal ou o IP LAN do host:

```bash
curl -kfsS -o /dev/null -w 'HTTPS_STATUS=%{http_code}\n' \
  https://superchat.home.arpa/health
```

Se o próprio host não resolver o DNS local, derive o IPv4 da rota padrão e force somente a resolução do hostname:

```bash
LAN_IP="$(ip -4 route get 1.1.1.1 | awk '{for(i=1;i<=NF;i++) if($i=="src"){print $(i+1); exit}}')"
curl -kfsS --resolve "superchat.home.arpa:443:${LAN_IP}" \
  -o /dev/null -w 'HTTPS_STATUS=%{http_code}\n' \
  https://superchat.home.arpa/health
```

A API continua devendo aparecer somente em `127.0.0.1:8010` quando consultada com `docker port app-api-1 8000/tcp`.

## Destino de backup fora do volume primário

No host validado, os dados do PostgreSQL estão em `/dev/sdc8` e `/DATA/Backup/superchat` está em `/dev/md0`. O `/dev/md0` é um RAID1 formado por dois discos físicos e é um filesystem/dispositivo distinto do volume de dados da aplicação.

Isso satisfaz o item da Issue #57 que exige destino de backup fora do volume primário de dados. Um `SECONDARY_ROOT` adicional em NAS remoto, USB ou outro destino independente continua recomendado como defesa em profundidade, mas não é requisito adicional para o checkpoint #57 quando a separação `sdc8` versus `md0` estiver comprovada.

Avisos `Host is down` de shares de rede antigos devem ser tratados separadamente; não invalidam a separação entre `sdc8` e `md0`.
