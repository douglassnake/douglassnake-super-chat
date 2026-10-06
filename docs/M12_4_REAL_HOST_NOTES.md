# M12.4.2 — notas do host real ZimaOS

Estas notas registram ajustes encontrados durante a validação do checkpoint M12.4 no host real.

## Preflight Python em instalação já existente

O `python` do sistema ZimaOS pode não ter as dependências Python do projeto. Execute o preflight com o virtualenv do projeto.

No host em produção, o diretório persistente do PostgreSQL é gerenciado pelo serviço/container e não é gravável pelo usuário operador. Isso é esperado e não deve levar à alteração de permissões do banco só para satisfazer o preflight. Use `--data-managed-by-service`: o path continua sendo validado quanto a existência, tipo, espaço livre e separação do backup, mas a escrita pelo operador deixa de ser requisito.

Como o checkpoint é pós-deploy, a disponibilidade de uma porta fixa de implantação também não é necessária. `--bind-port 0` pede ao kernel uma porta efêmera livre e comprova apenas que o host consegue fazer bind local. A exposição efetiva da API é validada separadamente.

```bash
cd /DATA/AppData/superchat/app
test -x .venv/bin/python

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

O resultado esperado é `"status": "ready"`.

## Integration readiness no container de produção

O container da API possui variáveis reais de produção, incluindo autenticação e backend de secrets. O restore-check precisa validar o banco descartável sem deixar esses valores contaminarem os checks sintéticos de `integration_readiness.py`.

O `ops_restore_check.sh` mantém a URL real do PostgreSQL dentro do container e cria um ambiente filho mínimo para o subprocesso de readiness. Somente variáveis operacionais não sensíveis essenciais são preservadas; o banco descartável recebe seu `DATABASE_URL` internamente e os checks sintéticos rodam em modo de desenvolvimento, com autenticação desabilitada e `SECRET_BACKEND=settings`.

Isso evita herdar `AUTH_PASSWORD_HASH`, `SECRET_DIR`, tokens ou outras configurações de produção. A configuração real de secrets continua sendo validada pelo preflight do host.

## HTTPS no host

O proxy compartilhado não precisa publicar 443 no loopback `127.0.0.1`. A validação deve usar o hostname normal ou o IP LAN do host:

```bash
LAN_IP="$(ip -4 route get 1.1.1.1 | awk '{for(i=1;i<=NF;i++) if($i=="src"){print $(i+1); exit}}')"
curl -kfsS --resolve "superchat.home.arpa:443:${LAN_IP}" \
  -o /dev/null -w 'HTTPS_STATUS=%{http_code}\n' \
  https://superchat.home.arpa/health
```

No host real, a rota respondeu `HTTPS_STATUS=200`. A API direta permanece limitada a `127.0.0.1:8010` quando consultada com:

```bash
docker port app-api-1 8000/tcp
```

## Destino de backup fora do volume primário

Os dados do PostgreSQL estão em `/dev/sdc8` e `/DATA/Backup/superchat` está em `/dev/md0`. O `/dev/md0` é um RAID1 formado por dois discos físicos e é um filesystem/dispositivo distinto do volume de dados da aplicação.

Isso satisfaz o item da Issue #57 que exige um destino secundário de backup fora do volume primário. Um `SECONDARY_ROOT` adicional em NAS remoto, USB ou outro destino independente continua recomendado como defesa em profundidade, mas não é requisito adicional do checkpoint #57.

## Evidência parcial já confirmada em 2026-10-06

- virtualenv do projeto presente;
- secret store e separação de backup aprovados pelo preflight;
- mais de 400 GiB livres no volume de dados;
- Docker Engine e Compose operacionais;
- HTTPS em `superchat.home.arpa` retornou 200 via IP LAN;
- API publicada apenas em `127.0.0.1:8010`;
- backup automático mais recente passou em SHA-256, formato e restore no banco descartável;
- banco descartável foi removido mesmo após falha de readiness;
- PostgreSQL principal permaneceu `healthy` e sem restart.

O M12.4 só deve ser fechado após repetir o preflight com o modo de dados gerenciado pelo serviço e repetir o restore-check com o ambiente filho isolado, ambos com sucesso.
