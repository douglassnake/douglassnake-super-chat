# M14.3 — alertas locais e observabilidade

Issue principal: #94. Reutiliza o diagnóstico read-only já validado em M14.2. **Não substitui** backup, restore, cron existente nem supervisão de infraestrutura.

## Entrega

O script scripts/ops_health_alert.py executa o diagnóstico existente e converte mudanças de estado em eventos locais via comando do host logger, com tag superchat-ops-health (journal/syslog).

- Estados: healthy, degraded, failed. Retorno 0 = healthy; 2 = degraded (não é sucesso pleno); 1 = failed; 3 = erro interno de avaliação, persistência ou entrega do evento.
- Primeiro estado saudável: não emite evento, evitando ruído.
- Primeiro degraded/failed: emite evento local com prioridade warning/error.
- Persistência: JSON mínimo contendo fingerprint, estado e timestamp da última emissão. Local padrão fora do Git: /DATA/AppData/superchat/private/m14-3/health-state.json. Diretório 0700, arquivo 0600, gravação atômica e lock não bloqueante.
- Repetição: mesma falha é silenciada por até 24 horas (configurável); depois emite lembrete. Mudança de causa ou estado produz novo evento.
- Recuperação: transição de problema para saudável produz evento user.info.
- Evento: JSON allowlisted com estados e códigos de motivo, jamais dump, texto de logs, variáveis de ambiente, URLs, tokens ou segredos.
- Falha do logger: não avança o estado como se a entrega tivesse ocorrido.
- Sem rede, serviço novo, migration nem alteração do PostgreSQL.
- --dry-run: simula a decisão e pode consultar o estado anterior, mas não cria diretório/lock, não escreve arquivos e não executa logger.

## Teste manual no ZimaOS — somente após merge e CI pós-merge verde

Executar:

    cd /DATA/AppData/superchat/app
    ./.venv/bin/python scripts/ops_health_alert.py --restore-first-due 2026-10-11T04:00:00-03:00 --dry-run

Enquanto o host mantiver a saúde constatada no M14.2, espera-se JSON com status=healthy e action=would_none. Não ativar cron nesta etapa. Não inventar falhas na base, nem editar backups ou logs para simular incidentes; fixtures isoladas em CI validam esse comportamento.

## Agendamento no ZimaOS (ativado manualmente em 08/10/2026)

Após validação em produção de `logger`/journal, `dry-run`, execução normal, estado privado 0700/0600 e confirmação de ausência de entrada duplicada, o operador instalou uma quarta linha no crontab, sem alterar as três anteriores:

    45 * * * * cd /DATA/AppData/superchat/app && umask 077 && ./.venv/bin/python scripts/ops_health_alert.py --restore-first-due 2026-10-11T04:00:00-03:00 > /DATA/AppData/superchat/private/m14-3/health-last-run.log 2>&1; rc=$?; if [ "$rc" -gt 2 ]; then /usr/bin/logger -t superchat-ops-health -p user.err "health-cron: internal-error"; fi

A alteração foi precedida por backup privado do crontab e confirmação, após instalação, de **exatamente 1 entrada** para backup, restore-check, GitHub sync e health-alert. **A primeira execução automática ainda não foi comprovada**; isso deve ser verificado no `health-last-run.log` após o próximo minuto 45. Falhas internas (exit > 2) disparam mensagem local; estados failed/degraded são emitidos no journal pelo wrapper. Nenhum webhook, e-mail, WhatsApp ou alerta externo foi configurado.

## Limitações

- O evento é enviado exclusivamente ao logger local, não a um canal de notificação externa.
- Antes da primeira janela de domingo 11/10/2026 às 04:00 (-03) mais duas horas de tolerância, restore not_due não é falha, mas também não comprova sucesso de restore.
- Status degraded retorna 2 e não deve ser entendido como sucesso.
- Em execução periódica futura, falha persistente gera novo evento somente após o período de lembrete, evitando spam.
