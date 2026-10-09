# M13.7 — Reconciliação de tarefas e contexto operacional

Estado: planejamento técnico, sem aprovação para merge ou deploy.

## Diagnóstico confirmado no código

- `app/context_engine.py::_task_candidates` inclui tarefas com status diferente de `done` e `cancelled`, ordenadas por prioridade e atualização; não confronta a tarefa com execuções GitHub posteriores.
- `score_candidate` considera relevância, importância, recência, tipo e fonte, mas não avalia se uma falha histórica já foi superada por evidência específica.
- `app/github_digest.py` já organiza digests com revisão humana; a M13.7 deverá reutilizar essa disciplina, sem fechar tarefas automaticamente.
- A M13.6 separa visualmente cadastro atual de registros históricos. Preservar essa distinção.

## Regras de segurança obrigatórias

1. Nenhum `Task.status`, `Project.next_action` ou registro histórico será atualizado por sincronização GitHub ou avaliação heurística.
2. Toda sugestão deverá citar o evento originador e a evidência posterior, com URL, horário, repositório, workflow/job, commit SHA e conclusão, quando disponíveis.
3. Uma execução verde somente contradiz uma falha antiga quando o mesmo workflow e o mesmo escopo são comprováveis; não basta pertencer ao mesmo repositório.
4. Uma falha recente não deve ser ocultada por sucesso mais antigo, e sucesso de CI não prova publicação, deploy nem estabilidade.
5. Ambiguidade => estado `needs_review`, nunca `resolved`.
6. Falhas de consulta, sincronização incompleta ou metadados ausentes => evidência insuficiente.
7. Efeitos de reconciliação devem requerer revisão explícita, com registro de ator, data, justificativa e referências.
8. A próxima ação específica prevalece sobre sugestões genéricas de onboarding.

## Contrato de avaliação proposto

Entrada: projeto, tarefa aberta, evento(s) relacionados, snapshot de evidências GitHub e timestamp de avaliação.

Saída somente leitura:
- `classification`: `open`, `possibly_stale`, `needs_review`, `insufficient_evidence`
- `reason`: justificativa legível em português
- `evidence_refs`: referências verificáveis e sem segredos
- `evaluated_at` e `source_freshness`
- `recommended_action`: manter, revisar ou propor atualização manual (nunca executar)

Não deduzir classificação `resolved` só porque um PR foi merged ou um CI passou.

## Casos de aceite obrigatórios

1. Falha V5 antiga + execução V5 subsequente aprovada no mesmo workflow: `possibly_stale`, aguardando revisão da estabilidade, sem encerrar tarefa.
2. PR #38 do MeuNegócio IA com CI aprovada mas ainda draft: não declarar M3.2 concluído nem sugerir merge/deploy.
3. Falha de workflow A + sucesso de workflow B: manter falha como aberta/insuficiente, não reconciliar por semelhança do título.
4. Falha mais recente que o último sucesso: não marcar obsoleta.
5. Dados GitHub ausentes ou sync desatualizada: `insufficient_evidence`.
6. Tarefa genérica de onboarding: apenas sugerir consolidação com próxima ação específica; não editar automaticamente.
7. Troca rápida entre projetos: nenhuma resposta assíncrona do projeto anterior aparece no atual.
8. Perfis mínimo, padrão e profundo preservam a próxima ação oficial e metadados de proveniência.
9. Regressão das proteções M13.6 e autorização/auditoria de alterações.
10. Nenhuma migração ou deploy involuntário durante testes.

## Sequência de implementação

- **Fase A:** avaliador determinístico, somente leitura, com testes unitários de pares tarefa/evidência.
- **Fase B:** API de sugestões por projeto, com autorização de leitura e proveniência, sem mutações.
- **Fase C:** painel de revisão explícita e operação separada de atualização/encerramento auditável.
- **Fase D:** benchmark com os 14 projetos e os 16 registros abertos do checkpoint; ensaios sem mutação do banco de produção.

## Condições para merge

Testes Python e front-end, integração read-only, regressões M13.6, CI verde, revisão do diff, segurança de dados e autorização expressa. Implantação ZimaOS somente após aprovação separada, backup verificado e plano de rollback. A auditoria M14.5 permanece independente até o restore programado de 11/10/2026.
