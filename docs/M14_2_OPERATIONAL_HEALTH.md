# M14.2 — saúde operacional read-only

Issue principal: #94. **Código proposto no PR, ainda não implantado nem agendado.**

## Contexto preservado

O novo probe, scripts/ops_health_check.py, reutiliza os dumps gerados por scripts/ops_backup.sh e os logs de scripts/ops_restore_check.sh. Não substitui backup, restore ou scripts/ops_storage_check.sh do M12.

O probe é **somente leitura**: sem acesso ao PostgreSQL, Docker, cron, secret store, rede, escrita no disco ou execução de restore.

## Sinais e limites iniciais

- **Backup**: identifica o dump automático mais recente pelo timestamp UTC do nome, valida arquivo regular/não vazio, sidecar SHA-256 e digest do conteúdo; considera antigo após **36 horas**.
- **Restore semanal**: lê somente os registros timestampados em restore-check.log, identifica sucesso, erro mais recente ou execução iniciada sem conclusão; sucesso após **192 horas** (oito dias) passa a ser antigo.
- **Primeiro restore**: no ZimaOS, a primeira execução dominical após ativação M12 está prevista para **11/10/2026 às 04:00, UTC-03**. Para evitar falso positivo, informar essa data como --restore-first-due, com tolerância adicional padrão de duas horas. Antes dela, ausência do log é **not_due**; depois da tolerância, sem sucesso, passa a **failed**. Se a data inicial não for informada, ausência de log é **unknown**, e o estado global é **degraded**, nunca healthy.
- **Disco**: espaço livre em AppData e Backup, exigindo ao menos **15%**, configurável.

O probe verifica o SHA, **não comprova que o dump foi restaurado**. A validação de restauração permanece no procedimento descartável do M12.

## Execução manual, após CI pós-merge e atualização Git

No ZimaOS (não agendar ainda):

    cd /DATA/AppData/superchat/app
    ./.venv/bin/python scripts/ops_health_check.py --restore-first-due 2026-10-11T04:00:00-03:00

Se necessário, Python 3 da instalação pode substituir o interpretador do virtualenv: o probe usa somente biblioteca padrão.

Nunca usar --now na operação normal; esta opção destina-se a testes determinísticos. O resultado é **um JSON com estados, idades e porcentagens**, sem texto de logs ou dump. Estados:
- Backup: fresh, stale, missing, invalid.
- Restore: fresh, stale, failed, pending, not_due, unknown.
- Disco: healthy, low_space, missing_path, failed.
- Global: healthy, degraded, failed.

Exit code 1 para **failed**; 0 para healthy/degraded. Um degraded não pode ser tratado como confirmação de saúde plena; argumentos inválidos retornam 2.

## Gate antes do M14.3

1. Concluir auditoria read-only M14.1, incluindo ausência/presença de bancos temporários órfãos.
2. CI do PR e CI pós-merge aprovados.
3. Executar o probe manualmente e conferir seu resultado contra a evidência atual do host.
4. Só depois propor cron/alertas, sem duplicar agendamentos ou alterar banco/containers.
5. Alertas externos exigem aprovação separada.

Não reiniciar PostgreSQL/API; nenhuma alteração de Docker Compose ou migration é necessária para este probe.
