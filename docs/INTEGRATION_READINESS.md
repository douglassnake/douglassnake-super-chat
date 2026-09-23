# Integration Readiness — M8.15

Este documento define como integrar a pilha do Super Chat sem transformar a integração de código em autorização de deploy, merge automático, publicação de produção ou execução externa.

## Estado de partida

A pilha foi construída em PRs empilhados. O topo M8.14 contém cumulativamente os marcos anteriores, mas cada PR mantém uma base explícita no PR imediatamente anterior. A integração deve ocorrer de baixo para cima, nunca começando pelo topo.

O M8.15 adiciona apenas estabilização, checks e documentação. Ele não adiciona efeito externo novo.

## Ordem de integração

| Bloco | PR | Marco |
| --- | ---: | --- |
| Fundação | #1 | Fundação do Segundo Cérebro |
| Memória | #3 | M1 memória operacional |
| Contexto | #5 | M2 Context Engine v1 |
| GitHub leitura | #7 | M3 GitHub Connector |
| Sessão | #9 | M4 Session Memory |
| Interface | #11 | M5 interface web |
| Google | #13 | M6 Drive/Calendar somente leitura |
| Qualidade | #15 | M7 benchmark de recuperação |
| Agentes | #17 | M8.0 Agent Task Packs |
| Agentes | #19 | M8.1 handoff auditável |
| Agentes | #21 | M8.2 execution tracking |
| Agentes | #23 | M8.3 verificação GitHub somente leitura |
| Executor | #25 | M8.4 Controlled Executor |
| Executor | #27 | M8.5 adapter isolado |
| Executor | #29 | M8.6 worker hardening |
| Executor | #31 | M8.7 proveniência/reconciliação |
| Git controlado | #33 | M8.8 diff efêmero |
| Git controlado | #35 | M8.9 aprovação + branch |
| Git controlado | #37 | M8.10 apply em staging |
| Git controlado | #39 | M8.11 commit explícito |
| Publicação local | #41 | M8.12 bare local controlado |
| GitHub | #43 | M8.13 PR controlado |
| GitHub | #45 | M8.14 publicação via credential broker |
| Estabilização | próximo PR | M8.15 integration readiness |

## Procedimento por PR

Para cada PR da tabela, na ordem:

1. confirmar que o PR continua mergeável e que o head não mudou inesperadamente;
2. confirmar todos os checks verdes no head atual;
3. integrar apenas esse PR;
4. retargetar o PR seguinte para `main`;
5. revisar o diff novamente: após o retarget, ele deve conter apenas o delta daquele marco;
6. aguardar novo CI verde antes de avançar;
7. interromper a sequência diante de conflito, diff inesperado, migration head múltiplo ou guardrail vermelho.

Não habilitar auto-merge para consumir a pilha inteira. A passagem entre marcos é um checkpoint humano.

## Checkpoints de segurança

Antes de iniciar a integração:

- `python scripts/integration_readiness.py` deve retornar `status=pass`;
- pytest e benchmark devem estar verdes;
- o grafo Alembic deve ter um único base e um único head;
- `isolated-local`, `github-pr` e `github-publish` devem permanecer indisponíveis com configuração padrão;
- `merge`, `deploy` e `publish` devem continuar na fronteira global proibida;
- secrets não podem aparecer em serialização de `Settings`.

No CI do M8.15, um PostgreSQL limpo executa `alembic upgrade head` e depois `python scripts/integration_readiness.py --database`. O segundo check confirma que a tabela `alembic_version` aponta para o único head e que as tabelas críticas esperadas existem.

## Credenciais

As credenciais permanecem separadas por finalidade:

- `GITHUB_TOKEN`: leitura/sincronização;
- `EXECUTOR_GITHUB_WRITE_TOKEN`: criação controlada de PR;
- `EXECUTOR_GITHUB_PUBLISH_TOKEN`: publicação controlada de branch via broker.

Esses valores permanecem acessíveis em memória aos consumidores autorizados, mas são excluídos da serialização de `Settings`. `DATABASE_URL` e credenciais Google sensíveis recebem a mesma proteção contra serialização acidental.

## Rollback lógico

Enquanto não houver deploy e nenhuma migration tiver sido aplicada em ambiente persistente, rollback significa interromper a sequência e reverter o PR problemático em Git. Não fazer downgrade de banco apenas para desfazer integração de código que ainda não foi implantada.

Se migrations já tiverem sido executadas em um ambiente persistente, rollback passa a ser um procedimento operacional separado: preservar backup, validar reversibilidade da revisão específica e testar restore/downgrade fora de produção antes de qualquer ação. O M8.15 não autoriza esse efeito.

## Condição para sair da estabilização

A pilha está pronta para integração controlada quando o head do M8.15 possuir simultaneamente:

- pytest verde;
- benchmark verde;
- integration-readiness estático verde;
- migration smoke em PostgreSQL limpo verde;
- PR draft mergeável sobre M8.14;
- nenhum novo efeito externo introduzido.
