# M14.5 — Auditoria final da operação contínua no ZimaOS

Issue principal: #94. Este runbook completa M14 depois de M14.1 (baseline), M14.2 (health-check), M14.3 (logger/cron) e M14.4 (restore descartável e teste negativo). **Não confundir conclusão do exercício manual com a execução semanal agendada.**

## Resumo das evidências já obtidas em 08/10/2026

- Git no ZimaOS atualizado via fast-forward para `1f2a91e1cd460778c27d90527d5f2786fb0fb2ed`, sem alterações locais.
- Quatro entradas únicas de cron: backup diário 03:15; restore domingo 04:00; GitHub sync a cada 30 minutos; health-alert todo horário no minuto 45.
- Monitoramento M14.3 validado: `logger`/journal local, estado privado (diretório 0700, arquivo 0600), execução manual saudável e **primeiro registro do cron horário** `status=healthy/action=none/dry_run=false`.
- Preflight M14.4: containers `app-db-1` e `app-api-1` running/healthy; backup de 08/10, idade 10,4 h e checksum válido; discos app 92,76% e backup 91,61% livres.
- Restore manual descartável: `DRILL_EXIT=0`, `DRILL_ELAPSED_SECONDS=7`, integration readiness aprovado, nenhum banco órfão ou lock. Métricas são proxies observados, **não garantias de RPO/RTO**.
- Teste negativo de backup-root sintético vazio: `NEGATIVE_EXIT=1`, `NEGATIVE_LOCK_CLEAN`, 0 bases órfãs.
- **Pendente essencial:** comprovar primeira execução automática do restore semanal no domingo **11/10/2026, 04:00 horário America/Sao_Paulo**. O log do drill manual tem nome distinto e **não** comprova a execução dominical.

## Quando concluir

Auditar após a janela de execução de domingo 11/10/2026 às 04:00 -03. O health-check tolera até 2 horas após o primeiro vencimento para não alertar falsamente; a auditoria humana deve inspecionar o log real e confirmar sucesso, não apenas ausência de alerta. Se o domingo ainda não ocorreu, manter M14.5 em aberto.

## 1. Git, serviços, cron

Comandos somente leitura:

    cd /DATA/AppData/superchat/app
    export DOCKER_CONFIG=/DATA/AppData/superchat/docker-config
    git rev-parse HEAD
    git status --short

    docker inspect -f '{{.Name}} running={{.State.Running}} health={{if .State.Health}}{{.State.Health.Status}}{{else}}unknown{{end}}' app-db-1 app-api-1

    crontab -l | awk '
      /scripts\/ops_backup.sh/ {backup++}
      /scripts\/ops_restore_check.sh/ {restore++}
      /scripts\/ops_github_sync.sh/ {github++}
      /scripts\/ops_health_alert.py/ {health++}
      END {
        print "BACKUP_COUNT:", backup+0
        print "RESTORE_COUNT:", restore+0
        print "GITHUB_COUNT:", github+0
        print "HEALTH_COUNT:", health+0
      }'

Esperado: working tree limpa, dois containers healthy, contagens 1/1/1/1. Não recriar containers para solucionar divergências; registrar e investigar.

## 2. Comprovar execução automática do domingo

Verificar somente o arquivo do cron agendado, **não** o log privado do exercício manual:

    LOG=/DATA/Backup/superchat/automatic/restore-check.log
    if [ -f "$LOG" ]; then
      grep -E 'restore-check: (validating SHA-256|integration readiness passed|completed successfully|dropping disposable database)|ERROR:' "$LOG" | tail -n 16
    else
      echo "RESTORE_CRON_LOG_MISSING"
    fi

Aceite: eventos com data explícita do domingo esperado, integração aprovada e `restore-check: completed successfully` seguido de cleanup. A expressão aceita linhas de execuções anteriores; conferir a data e **não** usar uma mensagem antiga para confirmar a execução nova. Se houver `ERROR:` após o último sucesso, investigar e manter M14.5 aberto.

Não induzir o job manualmente no mesmo arquivo para preencher artificialmente a evidência. Não editar o cron de restore.

## 3. Check completo de integridade, frescor e espaço

    cd /DATA/AppData/superchat/app
    ./.venv/bin/python scripts/ops_health_check.py --restore-first-due 2026-10-11T04:00:00-03:00

Esperado após sucesso dominical: JSON `status=healthy`, backup `state=fresh` + `sha256_valid=true`, restore `state=fresh` + `last_success_utc` correspondente ao domingo, armazenamento app/backup `healthy`. Se ainda constar `not_due`, `pending`, `failed`, `unknown` ou `stale`, registrar e avaliar com a janela temporal; não declarar a execução automática aprovada.

Após restauração concluída e cleanup:

    docker exec app-db-1 sh -c 'psql -Atq -U "$POSTGRES_USER" -d postgres -c "SELECT count(*) FROM pg_database WHERE datname LIKE '\''superchat_restore_check_%'\'';"'

    if [ -d /DATA/Backup/superchat/automatic/.restore-check.lock ]; then
      echo "RESTORE_LOCK_PRESENT"
    else
      echo "RESTORE_LOCK_ABSENT"
    fi

Esperado: 0 e RESTORE_LOCK_ABSENT. Nunca apagar manualmente o lock ou dropar uma base sem investigação prévia.

## 4. Monitoramento local e cron

    if [ -f /DATA/AppData/superchat/private/m14-3/health-last-run.log ]; then
      tail -n 1 /DATA/AppData/superchat/private/m14-3/health-last-run.log
    else
      echo "HEALTH_CRON_OUTPUT_MISSING"
    fi

    ls -ld /DATA/AppData/superchat/private/m14-3 /DATA/AppData/superchat/private/m14-3/health-state.json

Resultado saudável e as mesmas permissões 0700/0600 são esperados. Um `action=none` após estado saudável é comportamento normal e não implica que eventos de falha nunca ocorreram. O journal com tag `superchat-ops-health` é a fonte para eventos locais; não ativar webhook/alerta externo automaticamente.

## 5. Fechamento

Marcar M14.5 concluído e fechar a Issue #94 **somente** se: CI pré/pós-merge do conjunto estiver verde; host na main validada; containers íntegros sem reinícios motivados pela implantação; quatro cron jobs únicos; último backup fresco e íntegro; restore dominical completo validado com integração e limpeza (ou evidência agendada posterior equivalente); monitoramento horário em execução; zero bancos temporários/locks; espaço livre acima do limite; evidências sanitizadas registradas.

Se o restore semanal falhar, manter a Issue aberta, preservar logs privados e investigar. Não expor dados de produção ou credenciais em comentários/issues. Nenhuma ação de recuperação automática é autorizada por este documento.
