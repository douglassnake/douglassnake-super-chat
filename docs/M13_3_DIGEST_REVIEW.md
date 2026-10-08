# M13.3 — digest de mudanças com revisão humana

O M13.3 transforma novos eventos GitHub em uma fila de revisão, sem promover automaticamente conteúdo para a memória operacional.

## Fluxo

1. A sincronização GitHub continua read-only no serviço externo.
2. Eventos novos são persistidos como antes.
3. O sincronizador cria um SessionDelta com prefixo `github-digest:` somente para a nova janela de eventos.
4. O digest fica com status `pending`.
5. O usuário revisa o resumo e as tarefas sugeridas.
6. Somente uma ação explícita de aplicar cria resumo/tarefas; descartar mantém a memória operacional inalterada.

## Regras

- a primeira execução após ativação estabelece um cursor de baseline e não reabre todo o histórico anterior;
- apenas um digest GitHub pode ficar pendente por projeto;
- eventos incluídos em um digest aplicado ou descartado não são sugeridos novamente;
- commits entram no resumo;
- novas issues e pull requests podem gerar tarefas agregadas de revisão;
- falhas de workflow podem gerar tarefa de investigação;
- runs de sucesso repetitivos não geram tarefa;
- nenhuma decisão ou relação semântica é criada automaticamente;
- o GraphSuggestionBatch continua sendo o fluxo separado para relações do grafo.

## Interface

Quando existe um digest pendente, o painel do projeto mostra `Revisar mudanças`. O botão reutiliza o preview existente do SessionDelta, com opções de aplicar ou descartar.

## Observabilidade

O runner operacional informa somente:

- digest criado ou já pendente;
- quantidade de eventos;
- quantidade de tarefas sugeridas.

O log não inclui corpos de eventos, tokens ou conteúdo privado detalhado.
