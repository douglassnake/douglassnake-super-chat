# M13 — atualização contínua e qualidade do Segundo Cérebro

Issue principal: #86.

## Objetivo

Depois do M12, o Segundo Cérebro já opera no ZimaOS/NAS e contém projetos reais. O M13 transforma esse estado em operação continuamente atualizada, sem depender de sincronização manual por projeto.

O foco é manter contexto fresco, tornar a defasagem visível e preservar revisão humana antes de qualquer promoção de informação para memória operacional, tarefas, decisões ou relações semânticas.

## Estado atual que o M13 aproveita

- projetos reais já cadastrados;
- fontes GitHub ativas por projeto;
- `sync_project_github` idempotente por evento;
- metadata de fonte com `last_synced_at` e `last_sync`;
- eventos GitHub armazenados no PostgreSQL;
- Context Engine já lê eventos, tarefas, decisões, resumos e memórias;
- onboarding e sugestões já exigem revisão humana;
- operação self-hosted com cron, backup e restore-check comprovados.

## Princípios de segurança

1. sincronização externa permanece read-only;
2. um erro em um projeto não bloqueia os demais;
3. token GitHub nunca aparece em argumento, saída ou arquivo rastreado;
4. a rotina não reinicia API ou PostgreSQL;
5. eventos repetidos não criam duplicatas;
6. nenhuma descoberta cria tarefa, decisão, memória ou relação automaticamente;
7. execução agendada só entra no host depois de merge, CI verde e validação manual;
8. dados reais e relatórios com conteúdo privado permanecem fora do Git.

## M13.1 — sincronização periódica das fontes GitHub

### Entrega

Adicionar uma rotina operacional que:

- seleciona projetos `active`, `implementation` e `planning` com fonte GitHub ativa; exclui `paused` e `done`;
- seleciona somente fontes GitHub ativas;
- reutiliza `sync_project_github`;
- usa lock para impedir concorrência;
- continua para os demais projetos quando um falha;
- produz resumo saneado por projeto;
- retorna exit code não-zero se houver falha relevante;
- não modifica tarefas, decisões, memórias ou grafo.

### Saída operacional

Por projeto:

- slug;
- status `success`, `skipped` ou `failure`;
- número de fontes;
- eventos novos;
- eventos já conhecidos;
- duração;
- erro saneado, quando existir.

A saída nunca deve incluir token, cabeçalho Authorization, corpo completo de eventos ou conteúdo privado desnecessário.

### Implementação M13.1

A rotina é composta por:

- `scripts/ops_github_sync.py` — seleciona projetos/fontes elegíveis, executa a sincronização e emite relatório JSON saneado;
- `scripts/ops_github_sync.sh` — wrapper do host que executa o runner dentro do container da API, onde o secret backend e a conexão com o banco já estão disponíveis.

A elegibilidade usa **o status do projeto** e **a ativação da fonte** como controles independentes:
fontes GitHub `is_active=true` de projetos `active`, `implementation` ou `planning`
entram no agendamento; projetos `paused` e `done` ficam fora. A seleção não
muda o status do projeto, não cria fonte nova e não concede acesso adicional ao
repositório. O conector ainda depende das permissões GitHub configuradas no host.
Essa ampliação deve ser validada com `--check` após deploy antes da primeira
sincronização real das fontes adicionais.

O modo de diagnóstico não chama GitHub e não grava no banco:

```bash
cd /DATA/AppData/superchat/app
API_CONTAINER=app-api-1 /bin/bash scripts/ops_github_sync.sh --check
```

A execução real faz somente leitura externa no GitHub e grava internamente eventos idempotentes e metadata da fonte:

```bash
API_CONTAINER=app-api-1 /bin/bash scripts/ops_github_sync.sh
```

O runner usa lock advisory dentro do container para impedir sobreposição. Falhas são isoladas por projeto: os demais projetos continuam sendo processados. O relatório não serializa mensagem bruta de exceção, token, header Authorization nem conteúdo de evento.

Como o runner passa a fazer parte da imagem da API, a primeira implantação do M13.1 exige rebuild/recriação somente do serviço `api`; o PostgreSQL não deve ser recriado ou reiniciado.

### Agendamento

Primeira cadência proposta: a cada 30 minutos.

O cron só será instalado no ZimaOS depois da primeira execução manual aprovada e de uma segunda execução que confirme idempotência. A forma final de persistência/rotação do log será validada antes de ativar o cron; não deve ser introduzido um arquivo de log ilimitado.

Se o volume de eventos ou rate limit justificar outra frequência, a cadência deve ser alterada com evidência.

## M13.2 — frescor e saúde das fontes

### Objetivo

Distinguir claramente:

- nunca sincronizado;
- atualizado;
- atrasado;
- falhou recentemente.

### Regras

- `last_synced_at` permanece a referência primária para sucesso;
- falhas têm `last_sync_attempt_at`, `last_sync_status` e erro saneado, sem sobrescrever a última sincronização bem-sucedida;
- limiar de stale configurável por `SUPERCHAT_GITHUB_STALE_AFTER_SECONDS`, com padrão de 2 horas;
- estados expostos: `fresh`, `stale`, `failed`, `never`, `inactive` e `unknown`;
- dashboard/overview expõe frescor por fonte sem credenciais nem mensagem bruta de exceção;
- o estado permanece em metadata da própria fonte; M13.2 não exige migration.

### Implementação M13.2

- `app/source_health.py` deriva o estado de frescor;
- sincronizações bem-sucedidas registram tentativa/sucesso e limpam erro anterior;
- falhas agendadas e manuais registram apenas tipo/status HTTP saneados;
- a interface mostra um badge de frescor e a data da última sincronização.

## M13.3 — digest e revisão humana

Status: **concluído em 08/10/2026**.

Eventos novos alimentam uma fila de revisão via `SessionDelta`, nunca memória definitiva diretamente.

Validação no host:
- digest criado somente para eventos novos da janela;
- apenas um digest pendente por projeto;
- preview mostrou explicitamente tarefas/decisões/status/próxima ação antes de qualquer aplicação;
- descarte humano manteve a memória operacional inalterada;
- o mesmo digest descartado não foi recriado na sincronização seguinte;
- runs de sucesso repetitivos não geram tarefas.

Detalhes: `docs/M13_3_DIGEST_REVIEW.md`.

## M13.4 — benchmark com projetos reais

Status: **concluído em 08/10/2026**.

O M7.0 validou o Context Engine com fixture sintética. O M13.4 mediu recuperação com dados reais sem exportar conteúdo privado para o repositório.

### Corpus mínimo

Usar os projetos ativos cadastrados no ambiente real, sem exportar seu conteúdo privado para o repositório.

### Consultas

Cada projeto deve ter perguntas representativas de retomada, por exemplo:

- qual é a próxima ação?;
- quais tarefas estão pendentes?;
- quais decisões recentes alteram o caminho?;
- houve falha recente de CI?;
- qual infraestrutura ou dependência está relacionada ao projeto?;
- o que mudou desde a última retomada?

### Métricas

- recall esperado dos itens essenciais;
- quantidade de candidatos;
- quantidade selecionada;
- tokens candidatos;
- tokens selecionados;
- taxa de compressão;
- presença de ruído;
- latência.

### Resultado e decisão M7.1

No host real:
- `camara360`: recall@5 = 1,0;
- `meunegocio-ia`: recall@5 = 1,0;
- `super-chat-segundo-cerebro`: recall@5 = 1,0;
- média de recall@k = 1,0;
- latência média = 17,9 ms;
- `critical_failures=[]`;
- `missing_projects=[]`;
- benchmark read-only: `ContextRun` permaneceu 8 → 8;
- decisão: `defer_m7_1`.

M7.1 permanece adiado até nova evidência mensurável justificar busca híbrida/semântica.

## M13.5 — validação operacional

Status: **concluído em 08/10/2026**.

Critérios validados no ZimaOS/NAS:

- sync manual real bem-sucedido;
- reexecução idempotente sem duplicar eventos;
- falha de uma fonte isolada sem impedir as demais;
- cron `*/30 * * * *` instalado e observado em execução real;
- logging via `logger -t superchat-github-sync` no journal;
- estado de frescor visível para as fontes GitHub;
- digest com revisão humana e sem promoção automática;
- descarte de digest sem recriação posterior;
- benchmark real read-only executado;
- PostgreSQL principal sem restart causado pelas rotinas;
- M7.1 adiado por evidência objetiva.

O M13 não autoriza escrita externa no GitHub e não altera a política de revisão humana.

## Sequência proposta

1. M13.1 em PR próprio.
2. Validar manualmente no host.
3. Instalar cron e observar pelo menos uma execução agendada.
4. M13.2 com estado de frescor.
5. M13.3 com digest/revisão.
6. M13.4 benchmark real e decisão sobre M7.1.
7. M13.5 documentação e fechamento.

Nenhuma etapa do M13 autoriza escrita externa no GitHub. A integração continua sendo leitura para ingestão de contexto.
