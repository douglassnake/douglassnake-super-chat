# M14.4 — exercício controlado de recuperação, ZimaOS/NAS

Issue principal: #94. A rotina preexistente M12.2, scripts/ops_restore_check.sh, é a única responsável pelo ensaio de restauração. Este runbook não introduz um segundo mecanismo nem autoriza restaurar sobre a base principal.

## Objetivos e limites das métricas

- **RPO observável / idade do ponto de recuperação**: idade, em horas, do último dump automático íntegro no instante do exercício, obtida de scripts/ops_health_check.py. É um *proxy* de RPO, não um RPO garantido após incidente.
- **RTO de exercício / tempo técnico de verificação**: duração total (segundos) de scripts/ops_restore_check.sh, incluindo validação do backup, criação da base descartável, restauração, testes, e tentativa de cleanup. É um *proxy*, não o RTO de recuperação da aplicação e infraestrutura completa após pane.
- **Integridade e isolamento**: SHA-256, pg_restore, Alembic, tabelas críticas e leituras, integration_readiness.py --database isolado, e ausência de bases temporárias após o teste.
- **Falha segura**: executar uma vez com diretório de backups de teste vazio, para validar retorno não-zero e remoção do lock **antes de qualquer base ser criada**. Não corromper dumps reais nem fazer injeção de falhas na base de produção.
- **Segurança**: toda saída preservada apenas em diretório privado no host; nunca versionar dumps/logs contendo dados operacionais.

## Preconditions no host

Antes do ensaio:

1. Conferir se app-db-1 e app-api-1 estão running/healthy (M14.1); se não, parar e investigar.
2. Certificar-se de que nenhum restore agendado está em andamento: não executar durante domingo por volta de 04:00; o script possui lock.
3. Confirmar que o dump mais recente tem SHA-256 íntegro e que os volumes têm espaço; a auditoria de 08/10 aprovou ambos.
4. Não executar docker compose, rebuild, docker prune, dropdb ou createdb manual.
5. Conferir HEAD/working tree antes da operação. Se a única mudança foi documentação, um git pull --ff-only basta, sem restart.

## Passo A — preflight (somente leitura)

    cd /DATA/AppData/superchat/app
    export DOCKER_CONFIG=/DATA/AppData/superchat/docker-config
    git rev-parse HEAD
    git status --short

    docker inspect -f '{{.Name}} running={{.State.Running}} health={{if .State.Health}}{{.State.Health.Status}}{{else}}unknown{{end}}' app-db-1 app-api-1

    ./.venv/bin/python scripts/ops_health_check.py --restore-first-due 2026-10-11T04:00:00-03:00

O diagnóstico deve ser healthy, com backup fresh, SHA válido e discos saudáveis. Restore not_due até 11/10/2026 não é prova de sucesso do agendamento semanal.

## Passo B — restauração completa em banco DESCARTÁVEL

Este passo **grava exclusivamente no banco descartável com prefixo superchat_restore_check_** e o remove no trap EXIT. A base principal não é o alvo do restore. O ensaio de integração executa consultas contra a base descartável.

Executar preferencialmente fora da janela de cron (domingo às 04:00):

    (
      umask 077
      cd /DATA/AppData/superchat/app || exit 1
      export DOCKER_CONFIG=/DATA/AppData/superchat/docker-config
      DIR=/DATA/AppData/superchat/private/m14-3
      LOG="$DIR/m14-4-restore-manual-$(date -u +%Y%m%dT%H%M%SZ).log"
      START=$(date -u +%s)
      BACKUP_ROOT=/DATA/Backup/superchat/automatic \
        DB_CONTAINER=app-db-1 API_CONTAINER=app-api-1 \
        /bin/bash scripts/ops_restore_check.sh > "$LOG" 2>&1
      RC=$?
      END=$(date -u +%s)
      echo "DRILL_EXIT=$RC"
      echo "DRILL_ELAPSED_SECONDS=$((END-START))"
      grep -E 'restore-check: (validating SHA-256|integration readiness passed|completed successfully|dropping disposable database)' "$LOG" | tail -n 8
    )

Saída esperada: DRILL_EXIT=0, mensagem integration readiness passed, completed successfully, e linha dropping disposable database. Não expor o arquivo de log inteiro ou publicar em repositório. Se o resultado for diferente, **não limpar ou dropar bancos manualmente**; trazer o resumo sanitizado para análise.

## Passo C — cleanup comprovado (somente leitura)

    docker exec app-db-1 sh -c 'psql -Atq -U "$POSTGRES_USER" -d postgres -c "SELECT count(*) FROM pg_database WHERE datname LIKE '\''superchat_restore_check_%'\'';"'

    if [ -d /DATA/Backup/superchat/automatic/.restore-check.lock ]; then
      echo "RESTORE_LOCK_PRESENT"
    else
      echo "RESTORE_LOCK_ABSENT"
    fi

Esperado: contagem 0 e RESTORE_LOCK_ABSENT. Uma falha de cleanup é bloqueadora de M14.4; reportar antes de qualquer remoção.

## Passo D — teste de falha segura, sem tocar em backup real

Usa um diretório temporário **vazio e privado** como BACKUP_ROOT. O script verifica os containers e cria um lock nesse diretório, mas aborta antes de criar qualquer base por ausência de dumps. A trap deve remover o lock.

    (
      umask 077
      cd /DATA/AppData/superchat/app || exit 1
      export DOCKER_CONFIG=/DATA/AppData/superchat/docker-config
      ROOT=$(mktemp -d /DATA/AppData/superchat/private/m14-3/m14-4-empty.XXXXXX) || exit 1
      LOG="$ROOT/failure-check.log"
      BACKUP_ROOT="$ROOT" DB_CONTAINER=app-db-1 API_CONTAINER=app-api-1 \
        /bin/bash scripts/ops_restore_check.sh > "$LOG" 2>&1
      RC=$?
      echo "NEGATIVE_EXIT=$RC"
      if [ -d "$ROOT/.restore-check.lock" ]; then
        echo "NEGATIVE_LOCK_LEFTOVER"
      else
        echo "NEGATIVE_LOCK_CLEAN"
      fi
      grep -E '(no automatic backups found|another restore check)' "$LOG" | tail -n 2
      # O diretório contém somente o log sintético deste ensaio.
      rm -f "$LOG"
      rmdir "$ROOT" || echo "NEGATIVE_DIR_NOT_EMPTY"
    )

Esperado: NEGATIVE_EXIT não-zero, NEGATIVE_LOCK_CLEAN, no automatic backups found. Em seguida, repetir Passo C para confirmar 0 bancos temporários. Este teste é uma falha **anterior à criação de banco**; não cobre falhas pós-create e não deve ser descrito como tal.

## Passo E — registrar métricas sem confundir RPO/RTO de produção

Depois do ensaio, executar novamente o diagnóstico M14.2, anotando backup.age_hours e sha256_valid no instante da medição. Registrar também DRILL_ELAPSED_SECONDS. Esses são valores observados para o drill **e não SLA nem tempo de recuperação operacional garantido**.

Comprovar separadamente o primeiro restore semanal automático agendado para domingo, 11/10/2026, às 04:00 horário local, por leitura do arquivo de cron. **Não misturar o log manual com restore-check.log**: a checagem automática de saúde deve continuar distinguindo execuções agendadas e manuais.

## Critérios de conclusão M14.4

- Ensaio restaurado e validado integralmente no banco descartável, exit 0.
- Tempo técnico total observado, frescor do dump, SHA e leitura do backup anotados.
- Nenhum banco temporário órfão e nenhum lock remanescente.
- Teste negativo interrompido com exit não-zero, lock removido, sem banco criado.
- Evidências sanitizadas documentadas em Issue #94.
- Sem reiniciar/recriar banco/API, sem substituir produção, sem expor dump/credenciais.
