# M9.3 — ZimaOS/NAS deployment readiness

Este documento define o **checkpoint operacional** para executar o Super Chat em um host ZimaOS/NAS. Ele não é evidência de que o host real já foi validado. O go-live só é liberado depois que os checks abaixo forem executados no equipamento alvo.

## 1. Princípios

- O repositório é público: não versione `.env`, dumps, bancos, tokens, hashes reais, diretórios de secrets ou evidências contendo dados privados.
- Em produção, a aplicação exige `SECRET_BACKEND=files`, autenticação habilitada e cookie `Secure`.
- O serviço HTTP fica ligado em `127.0.0.1` por padrão. A exposição externa deve ocorrer somente por reverse proxy HTTPS.
- PostgreSQL não publica porta para a LAN/Internet na composição padrão.
- Backup no mesmo volume do banco é apenas uma cópia local, não uma estratégia de recuperação completa.

## 2. Layout sugerido no host

Exemplo conceitual:

```text
/srv/superchat/
  app/          # clone/build
  secrets/      # 0750 ou mais restritivo; nunca dentro do repo
  backups/      # destino local de backup
  evidence/     # opcional, somente relatórios sanitizados
```

Para recuperação contra falha física do disco, use também um **destino secundário** em outro filesystem/dispositivo/NAS.

Política POSIX mínima para secrets:

```bash
chmod 750 /srv/superchat/secrets
chmod 640 /srv/superchat/secrets/*
```

O diretório não pode ser symlink, não deve ter permissões para `others` e não pode ser gravável pelo grupo. Cada arquivo de segredo deve ser regular, UTF-8, não vazio e sem permissões para `others`.

## 3. Segredos

Gere o hash da senha administrativa localmente:

```bash
python scripts/generate_password_hash.py
```

Grave apenas o valor gerado no arquivo:

```text
/srv/superchat/secrets/auth_password_hash
```

Tokens opcionais usam os nomes definidos em `.env.example`, por exemplo `github_token` e `google_refresh_token`.

Para rotação, crie um arquivo temporário com permissões corretas e faça **substituição atômica** no mesmo filesystem. O broker relê o arquivo a cada aquisição privilegiada. Nunca copie o valor de um segredo para issue, PR, log ou evidência de implantação.

## 4. Ambiente privado

Use um arquivo de ambiente privado fora do Git ou com permissão `0600` para valores operacionais que não pertencem ao SecretStore, principalmente `POSTGRES_PASSWORD`.

Valores mínimos:

```env
POSTGRES_DB=superchat
POSTGRES_USER=superchat
POSTGRES_PASSWORD=<valor forte e exclusivo>
SUPERCHAT_SECRET_DIR_HOST=/srv/superchat/secrets
SUPERCHAT_BIND_HOST=127.0.0.1
SUPERCHAT_BIND_PORT=8000
SUPERCHAT_LOG_MAX_SIZE=10m
SUPERCHAT_LOG_MAX_FILES=5
```

A composição de produção força `ENVIRONMENT=production`, `AUTH_ENABLED=true`, `AUTH_COOKIE_SECURE=true` e limpa variáveis de ambiente usadas para segredos file-backed.

## 5. Preflight read-only

Antes de subir os containers:

```bash
python scripts/self_hosted_preflight.py \
  --secret-dir /srv/superchat/secrets \
  --data-dir /srv/superchat \
  --backup-dir /mnt/backup-superchat \
  --min-free-gib 5 \
  --bind-host 127.0.0.1 \
  --bind-port 8000 \
  --require-separate-backup-device
```

O preflight não altera o host. Ele verifica:

- Docker Engine e Docker Compose operacionais;
- diretórios existentes e graváveis quando necessário;
- política do diretório e arquivos de secrets;
- presença de `auth_password_hash`;
- espaço livre mínimo;
- separação entre dados e backup;
- disponibilidade da porta local.

Saída `status=blocked` é **no-go**. `warn` não bloqueia por si só, mas deve ser resolvido ou justificado antes do go-live. Com `--require-separate-backup-device`, backup no mesmo filesystem vira falha.

Não publique o JSON do preflight sem revisar caminhos e metadados do host.

## 6. Validar a composição sem iniciar serviços

```bash
docker compose \
  --env-file /caminho/privado/superchat.env \
  -f docker-compose.yml \
  -f docker-compose.secrets.yml \
  -f docker-compose.production.yml \
  config >/dev/null
```

Não copie a saída de `docker compose config` para locais públicos: ela pode expandir valores do arquivo de ambiente.

## 7. Subir a aplicação

```bash
docker compose \
  --env-file /caminho/privado/superchat.env \
  -f docker-compose.yml \
  -f docker-compose.secrets.yml \
  -f docker-compose.production.yml \
  up -d --build
```

Verifique:

```bash
curl --fail http://127.0.0.1:8000/health
```

`/health` é apenas liveness mínimo. Depois do login, valide também `/ops/status`.

## 8. HTTPS e reverse proxy

O reverse proxy deve:

- terminar TLS com certificado válido;
- encaminhar para `http://127.0.0.1:8000`;
- preservar `Host` e informações de proxy necessárias;
- não encaminhar a porta do PostgreSQL;
- não expor diretamente `8000` para a Internet.

Caddy, Nginx e Traefik são opções possíveis; o projeto não instala nem altera automaticamente o proxy. A escolha depende do ambiente ZimaOS e da infraestrutura existente.

Critério mínimo: o navegador deve acessar somente `https://...`, o cookie de sessão deve permanecer `Secure` e o acesso HTTP externo deve redirecionar para HTTPS ou ficar indisponível.

## 9. Backup antes de qualquer upgrade

Antes de atualizar imagem, código ou migration:

```bash
python scripts/backup_postgres.py \
  --output-root /mnt/backup-superchat
```

Guarde juntos `database.dump` e `manifest.json`. O manifesto registra tamanho, SHA-256 e Alembic head.

O backup só é considerado comprovado após um restore em destino descartável.

## 10. Teste de restore

Crie um banco **descartável e vazio**, diferente do banco de produção. Depois:

```bash
python scripts/restore_postgres.py \
  --backup-dir /mnt/backup-superchat/<backup> \
  --target-database-url '<URL DO BANCO DESCARTÁVEL>' \
  --confirm-empty-target
```

Após o restore:

```bash
DATABASE_URL='<URL DO BANCO DESCARTÁVEL>' \
python scripts/integration_readiness.py --database
```

Não execute restore sobre o banco de produção existente. O procedimento foi desenhado para exigir um destino explícito e vazio.

## 11. Retenção

Defina a política real antes do go-live. Baseline sugerido para começar, ajustável ao espaço disponível:

- backups diários: 7;
- backups semanais: 4;
- backups mensais: 3;
- ao menos uma cópia em outro dispositivo/filesystem;
- logs Docker: `10m × 5` por container como limite inicial.

A retenção deve ser confirmada no host; a configuração do Compose limita os arquivos JSON do Docker, mas não substitui monitoramento de espaço livre.

## 12. Evidências do checkpoint real

Registre, sem segredos:

| Evidência | Resultado |
| --- | --- |
| commit de `main` testado | pendente |
| Docker Engine/Compose | pendente |
| preflight `ready` | pendente |
| secrets/permissões | pendente |
| destino secundário de backup | pendente |
| backup + SHA-256 | pendente |
| restore em banco descartável | pendente |
| `integration_readiness --database` pós-restore | pendente |
| HTTPS/certificado válido | pendente |
| `/ops/status` autenticado | pendente |
| rotação/retenção de logs | pendente |

O M9.3 de código **não transforma automaticamente esses itens em concluídos**.

## 13. Go / no-go

**GO** somente quando todos os itens abaixo forem verdadeiros:

1. CI do commit implantado está verde.
2. Preflight do host real retorna `ready`.
3. Backup e restore foram executados com sucesso no ZimaOS/NAS.
4. Existe cópia de backup em outro dispositivo/filesystem.
5. HTTPS está ativo e o serviço não está exposto diretamente.
6. Secrets reais estão fora do repo e com permissões verificadas.
7. Retenção de logs/backups está definida e há espaço livre suficiente.

Qualquer falha acima mantém o estado **NO-GO** para exposição externa.
