# Benchmark de Recuperação — M7.0

## Objetivo

O M7.0 mede a qualidade e a eficiência do Context Engine **antes** de adicionar embeddings ou pgvector. A intenção é evitar complexidade sem evidência de necessidade.

O benchmark atual é um baseline sintético e determinístico. Ele valida o mecanismo de medição e cria uma referência reproduzível para futuras comparações. Ele **não representa desempenho em dados reais de produção**.

## Métricas

### Precision@k

Proporção das primeiras `k` referências recuperadas que pertencem ao conjunto esperado.

```text
precision@k = acertos nas primeiras k posições / k
```

Uma precision menor não implica, por si só, falha do sistema: quando existem menos fontes esperadas que `k`, itens adicionais reduzem a precisão mesmo que todas as fontes necessárias tenham sido recuperadas.

### Recall@k

Proporção das referências esperadas que apareceram nas primeiras `k` posições.

```text
recall@k = acertos nas primeiras k posições / total esperado
```

Para continuidade de projetos, recall é especialmente importante: uma decisão, bloqueio ou próxima ação relevante não deve desaparecer do pacote de contexto.

### Coverage

Proporção das referências esperadas encontradas em qualquer posição do pacote selecionado.

```text
coverage = refs esperadas recuperadas / total esperado
```

### Context efficiency

Fração dos tokens candidatos que chegou ao pacote final.

```text
context_efficiency = tokens selecionados / tokens candidatos
```

Valor baixo significa maior filtragem. Não é uma métrica de qualidade isolada: o objetivo é reduzir tokens **sem perder recall/cobertura**.

### Compression ratio

Complemento da eficiência:

```text
compression_ratio = 1 - context_efficiency
```

Exemplo: `0.87` significa que aproximadamente 87% dos tokens candidatos ficaram fora do pacote final.

### Latência

Tempo de construção do pacote em milissegundos. Os números do CI servem apenas como baseline relativo; hardware, banco e fontes remotas alteram a latência em produção.

## Baseline sintético v1

Dataset: `benchmarks/context_cases.json`.

A execução validada no CI usa quatro casos fictícios:

| Caso | Perfil | Precision@k | Recall@k | Coverage |
|---|---|---:|---:|---:|
| CFD pressure-loss | minimal | 0,333333 | 1,0 | 1,0 |
| Token pressure | minimal | 0,5 | 1,0 | 1,0 |
| Access control | standard | 0,666667 | 1,0 | 1,0 |
| Long-context | deep | 0,5 | 1,0 | 1,0 |

### Caso de pressão de tokens

O cenário `Token pressure minimal` foi criado especificamente para testar economia de contexto. Ele produziu:

```text
candidate_tokens : 13.926
selected_tokens  : 1.794
context_efficiency: 0,128824
compression_ratio : 0,871176
recall@2           : 1,0
coverage           : 1,0
```

Isso demonstra, no fixture, que o orçamento `minimal` conseguiu preservar a fonte esperada enquanto descartava/compactava grande parte do material candidato.

A interpretação correta é limitada: esse resultado comprova o funcionamento do budgeter e das métricas, mas não comprova que a busca lexical terá recall 1,0 em projetos reais.

## Executar localmente

```bash
python scripts/context_benchmark.py benchmarks/context_cases.json
```

Para salvar o relatório:

```bash
python scripts/context_benchmark.py \
  benchmarks/context_cases.json \
  --output /tmp/context-benchmark.json
```

O mesmo benchmark é executado no GitHub Actions depois da suíte `pytest`.

## Avaliar um projeto pela API

Endpoint:

```text
POST /evaluation/context
```

Exemplo:

```json
{
  "project_id": "UUID",
  "query": "pipeline testes falha workflow CI",
  "profile": "minimal",
  "expected_source_refs": [
    "github:https://example/ref"
  ],
  "k": 5
}
```

A resposta inclui precision@k, recall@k, coverage, tokens candidatos/selecionados e latência.

`expected_source_refs` é um gabarito fornecido explicitamente para avaliação; o sistema não tenta inferir sozinho o que deveria ser relevante.

## Critério para M7.1

Embeddings/pgvector não devem ser adicionados apenas porque busca vetorial é tecnicamente possível.

O próximo passo é construir um conjunto privado de consultas reais, mantendo apenas os resultados agregados fora do repositório. M7.1 será justificado quando ocorrerem casos consistentes como:

- recall insuficiente por sinônimos/paráfrases;
- documentos relevantes sem sobreposição lexical com a consulta;
- ranking lexical colocando fontes essenciais abaixo do orçamento;
- ganho mensurável de recall/precision com busca híbrida que compense latência, armazenamento e custo operacional.

Se a busca lexical continuar cobrindo adequadamente os casos reais, pgvector pode ser adiado.
