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

- seleciona somente projetos `active`;
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

### Agendamento

Primeira cadência proposta: a cada 30 minutos.

O cron só será instalado no ZimaOS depois da primeira execução manual aprovada. Se o volume de eventos ou rate limit justificar outra frequência, a cadência deve ser alterada com evidência.

## M13.2 — frescor e saúde das fontes

### Objetivo

Distinguir claramente:

- nunca sincronizado;
- atualizado;
- atrasado;
- falhou recentemente.

### Regras

- `last_synced_at` permanece a referência primária para sucesso;
- falhas precisam de estado próprio e timestamp, sem sobrescrever a última sincronização bem-sucedida;
- limiar de stale configurável, inicialmente 2 horas para GitHub;
- dashboard/overview deve exibir estado por projeto sem revelar segredos.

Pode exigir migration aditiva se o estado de falha não puder ser representado de forma segura apenas em metadata.

## M13.3 — digest e revisão humana

Eventos novos devem alimentar uma camada de revisão, não memória definitiva.

O digest deve:

- agrupar mudanças por projeto e janela de sincronização;
- destacar PRs, issues e workflows relevantes;
- evitar transformar runs de sucesso repetitivos em ruído;
- sugerir, quando houver evidência suficiente, possíveis tarefas, decisões ou memórias;
- exigir revisão/aplicação explícita;
- não repetir item já revisado ou promovido.

A infraestrutura existente de `SessionDelta` e `GraphSuggestionBatch` deve ser reutilizada quando o contrato encaixar, em vez de criar uma segunda fila paralela sem necessidade.

## M13.4 — benchmark com projetos reais

O M7.0 validou o Context Engine com fixture sintética. Agora é possível medir recuperação com dados reais.

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

### Decisão M7.1

Busca híbrida/semântica só deve entrar se o benchmark real demonstrar ganho mensurável sobre o mecanismo lexical atual em consultas importantes. Caso o lexical continue suficiente, M7.1 permanece adiado.

## M13.5 — validação operacional

O marco encerra somente após:

- sync manual real bem-sucedido no ZimaOS;
- reexecução idempotente sem duplicar eventos;
- falha simulada de uma fonte sem impedir as demais;
- cron instalado e confirmado;
- estado de frescor visível;
- digest sem promoção automática;
- benchmark real executado;
- documentação atualizada;
- PostgreSQL principal sem restart causado pela rotina.

## Sequência proposta

1. M13.1 em PR próprio.
2. Validar manualmente no host.
3. Instalar cron e observar pelo menos uma execução agendada.
4. M13.2 com estado de frescor.
5. M13.3 com digest/revisão.
6. M13.4 benchmark real e decisão sobre M7.1.
7. M13.5 documentação e fechamento.

Nenhuma etapa do M13 autoriza escrita externa no GitHub. A integração continua sendo leitura para ingestão de contexto.
