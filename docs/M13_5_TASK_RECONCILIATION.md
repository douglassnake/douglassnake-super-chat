# M13.5 — Indícios de tarefas de CI potencialmente obsoletas

## Escopo

Diagnóstico **estritamente somente leitura** das tarefas abertas denominadas
`Investigar novas falhas de CI`, derivadas de eventos GitHub já sincronizados.
O processo não consulta a API externa, não escreve no PostgreSQL, não cria
`SessionDelta`, não marca tarefas como concluídas e não altera cron ou deploy.

Para cada tarefa, o diagnóstico exige uma referência `event:<UUID>` que
identifique a execução original com conclusão de falha. Só apresenta um
**indício para revisão humana** quando a execução mais recente conhecida do
**mesmo repositório, workflow e branch** é `completed/success`, com data
posterior à falha de origem. Uma falha mais recente, workflow ou branch
distintos, execução incompleta ou metadados insuficientes bloqueiam o indício.

Mesmo com um resultado positivo, isso **não prova** que todas as falhas
agregadas à tarefa estejam resolvidas: o evento associado pode representar
somente parte do problema. O usuário deve conferir links, PR e execução
mais recente antes de mudar o estado da tarefa.

## Comando no ZimaOS, após implantação

```bash
cd /DATA/AppData/superchat/app
docker exec -i -w /app -e PYTHONPATH=/app app-api-1 \
  python scripts/ops_task_reconcile.py --check
```

Opcional, restringindo ao projeto:

```bash
docker exec -i -w /app -e PYTHONPATH=/app app-api-1 \
  python scripts/ops_task_reconcile.py --check --project meunegocio-ia
```

A saída JSON contém `mode=check`, `changes_applied=0`,
`open_tasks_examined`, `ci_tasks_examined`, `suggestion_count` e
`suggestions`, cada uma acompanhada de URLs e datas da falha e do
sucesso posterior. `suggestion_count=0` significa apenas ausência de
**indícios suficientemente correlacionados**, não ausência de problemas.

## Limites de segurança

- Nenhum `UPDATE`, `INSERT`, `DELETE` ou `commit`.
- Tarefas `done`/`cancelled` são ignoradas; referências inválidas ou
  eventos de outro projeto nunca geram sugestões.
- Não executa ações sobre GitHub e não contém credenciais em logs.
- Não compara a totalidade das execuções remotas: depende do histórico
  efetivamente capturado na base local.
- Não detecta finalização de tarefas de implementação a partir de títulos
  de PR. Esse cenário requer correlação adicional explícita e revisão.
- A integração dos indícios na UI pode ser feita posteriormente, sempre
  com confirmação humana; este PR **não** altera a interface nem o fluxo
  de aplicar/descartar digests.

## Verificação

```bash
pytest -q tests/test_m13_5_task_reconciliation.py
```

Exercícios de sucesso posterior, falha posterior, diferença de branch,
repositório e workflow, execução incompleta, tarefas já concluídas,
referências sem evidência e filtro entre projetos.
