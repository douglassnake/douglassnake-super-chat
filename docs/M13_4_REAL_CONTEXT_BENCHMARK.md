# M13.4 — benchmark de recuperação com projetos reais

O M13.4 mede o Context Engine contra projetos reais no ZimaOS/NAS sem exportar conteúdo privado para o repositório.

## Manifesto privado

O benchmark recebe um JSON mantido fora do Git. O arquivo define:

- projeto real por `project_slug`;
- consulta representativa;
- perfil `minimal`, `standard` ou `deep`;
- valor de `k`;
- expectativas de recuperação por tipo e fragmentos de título/conteúdo/source ref;
- se o caso é crítico.

Arquivos `*.benchmark.private.json` são ignorados pelo Git.

## Métricas

Por caso:

- recall@k;
- proxy de precisão@k;
- quantidade de candidatos e selecionados;
- tokens candidatos e selecionados;
- taxa de compressão;
- latência;
- expectativas não recuperadas.

## Gate de M7.1

Padrão:

- média de recall@k >= 0,90;
- todo caso crítico deve ter recall@k = 1,0;
- nenhum projeto esperado pode estar ausente.

Se o gate passar, a decisão é `defer_m7_1`: não há evidência suficiente para adicionar embeddings/pgvector.

Se o gate falhar, a decisão é `prototype_semantic_and_compare`: um protótipo semântico deverá ser medido contra os mesmos casos antes de qualquer adoção.

O benchmark não grava `ContextRun` e não altera tarefa, decisão, memória, fonte ou grafo.

## Execução no host

Exemplo:

```bash
docker exec -i -w /app -e PYTHONPATH=/app app-api-1 \
  python scripts/real_context_benchmark.py \
  /run/private/m13-4.benchmark.private.json
```

No host real, o manifesto deverá ser copiado temporariamente para o container ou montado de forma privada e removido após a execução.
