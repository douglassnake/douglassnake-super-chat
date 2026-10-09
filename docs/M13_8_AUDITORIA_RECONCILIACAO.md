# M13.8 — Contrato de decisão humana auditável

Status: especificação de segurança, **sem endpoint de escrita habilitado**.

## Diagnóstico do código existente

- `app/auth.py` estabelece `request.state.auth_principal` quando a sessão é validada.
- `PATCH /tasks/{task_id}` altera diretamente a tarefa, usando `db.commit()`; **não é um fluxo de reconciliação com justificativa/evidência e bloqueio otimista**.
- `Decision` registra texto e origem, mas não possui identificação própria de ator nem vínculo imutável com a versão da tarefa.
- `Task.updated_at` pode servir como indicador de conflito, mas não é suficiente sem comparação transacional e controle de idempotência.
- As sugestões da M13.7 são somente leitura e não fazem prova de resolução; uma execução de CI aprovada pode não cobrir o job ou problema da falha original.

## Requisitos antes de habilitar a escrita

1. Autenticação obrigatória, sem modo dev/desabilitado no fluxo produtivo; ator derivado da sessão, nunca enviado pelo cliente.
2. Solicitação explícita com task ID, ação, justificativa não vazia, referências GitHub validadas e token de idempotência.
3. Revalidar projeto/tarefa, status, revisão/timestamp e evidências **dentro de transação**; concorrência => HTTP 409 sem efeito parcial.
4. Persistir um evento de auditoria append-only com ator, momento UTC, estado anterior/novo, justificativa, URLs e identificador da decisão; sem tokens/cookies/segredos.
5. Uma única transação para alteração de tarefa, auditoria e eventual próxima ação, com rollback integral em falha.
6. Replay da mesma chave devolve o resultado registrado; chave com payload divergente => conflito.
7. Ações separadas: registrar revisão sem alteração, manter tarefa, concluir tarefa explicitamente e atualizar próxima ação explicitamente. **Nenhuma conclusão implícita.**
8. Negar conclusões sem evidência atualizada, eventos com escopo divergente, falha mais recente e sessão sem permissão.
9. Restringir a interface de aprovação a controles autenticados com confirmação visível e justificativa.
10. Introduzir revisão de schema/migração aditiva, rollback e testes PostgreSQL antes do merge da fase de escrita.

## Critérios de aceite

- Duas aprovações concorrentes não criam estados inconsistentes nem auditorias duplas.
- Sessão vencida/revogação de papel bloqueia a ação.
- Incapacidade de persistir a auditoria impede mudança de tarefa.
- Todas as tarefas reais continuam intactas durante consultas e prévias.
- O endpoint de prévia `GET /ops/task-reconciliation` permanece sem gravação.
- O fechamento das 16 tarefas históricas depende de avaliação individual, não de contagem ou CI verde.

## Limites desta entrega

A M13.8 inicial oferece explicações em português e diagnósticos somente leitura. O workflow transacional de escrita acima exige implementação e homologação próprias antes de ser exposto no painel. Não marcar concluído apenas por existir esta especificação.
