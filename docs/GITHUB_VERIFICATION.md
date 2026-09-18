# GitHub Verification — M8.3

## Objetivo

O M8.3 transforma referências técnicas já registradas em `AgentExecution` em observações verificáveis por leitura do GitHub.

Ele não cria nem altera recursos externos. O fluxo é deliberadamente separado:

```text
AgentExecution running
        ↓
commit_sha / pr_url já registrados
        ↓
GitHub Verification (somente leitura)
        ↓
external_verification append-only
        ↓
regra explícita de evidência?
      ↙                  ↘
    não                  sim
observação apenas   valida condição
                         ↓
                  criterion_evidence passed
                  somente se a regra for satisfeita
```

## Fonte de verdade do repositório

O repositório não é inferido livremente nem fornecido pelo endpoint de verificação.

Ele precisa existir como `ProjectSource` ativo:

```json
{
  "source_type": "github",
  "external_id": "owner/repository"
}
```

Quando há `pr_url`, o repositório da URL precisa corresponder a uma dessas fontes ativas. Uma URL para outro repositório gera:

```text
status = mismatch
reason = pr_repository_not_linked_to_project
```

Quando existe somente `commit_sha`:

- exatamente uma fonte GitHub ativa → ela é usada;
- nenhuma fonte → `unavailable`;
- mais de uma fonte → `unavailable` por ambiguidade.

O sistema não escolhe arbitrariamente um repositório.

## Leituras realizadas

O conector existente foi ampliado somente com métodos GET:

```text
GET /repos/{repository}/commits/{sha}
GET /repos/{repository}/pulls/{number}
GET /repos/{repository}/commits/{sha}/check-runs
```

Nenhum método de escrita é usado pelo M8.3.

Os testes usam reader simulado e não dependem de rede ou credenciais reais.

## Estados normalizados

### `verified`

A identidade da referência foi confirmada no repositório esperado.

`verified` não significa, por si só, que CI está verde nem que o critério de aceite passou.

### `mismatch`

A referência diverge da fonte de verdade esperada. Exemplos:

- PR aponta para repositório não vinculado;
- SHA observado não corresponde ao SHA registrado;
- commit registrado não corresponde ao `head.sha` do PR.

### `not_found`

O GitHub respondeu 404 para o recurso consultado.

### `unavailable`

A leitura não pôde ser concluída, por exemplo:

- nenhuma fonte GitHub ativa;
- múltiplos repositórios tornam um commit isolado ambíguo;
- erro de autenticação/rate limit/rede/serviço.

A indisponibilidade não altera o estado da execução e é registrada como observação append-only.

## Check-runs

O M8.3 calcula um resumo dos checks:

```json
{
  "count": 2,
  "completed": 2,
  "successful": 2,
  "pending": 0,
  "non_success": 0,
  "checks_green": true
}
```

A regra é conservadora:

```text
checks_green =
  existe pelo menos um check
  AND todos estão completed
  AND todos têm conclusion = success
```

`failure`, `cancelled`, `timed_out`, `neutral`, `skipped`, checks pendentes ou lista vazia não satisfazem `checks_green`.

Isso é intencional: um estado não estritamente verde não pode virar evidência `passed` automaticamente.

## Observação versus evidência

Uma chamada sem mapeamento explícito:

```json
{}
```

registra somente:

```text
external_verification
```

Mesmo quando todos os checks estão verdes, nenhum critério muda.

Para converter a verificação em evidência é obrigatório informar conjuntamente:

```json
{
  "criterion_index": 0,
  "evidence_rule": "checks_green"
}
```

A regra atual aceita somente:

```text
checks_green
```

Uma evidência `passed` é criada somente quando:

1. o critério existe;
2. a regra foi informada explicitamente;
3. a verificação ficou `verified`;
4. `checks_green = true`.

Caso contrário, a resposta informa por que nenhuma evidência foi anexada, sem promover `failed` ou `passed` implicitamente.

## Proveniência

Cada verificação gera um `AgentExecutionEvent`:

```text
event_type = external_verification
```

O payload inclui:

- provider `github`;
- status normalizado;
- repositório;
- referências registradas;
- metadados compactos do commit/PR;
- resumo dos checks;
- `verified_at`;
- provenance `github_api_read_only`.

O evento permanece no log append-only mesmo se uma verificação posterior produzir resultado diferente.

## Endpoint

```text
POST /agent-executions/{execution_id}/verify-github
```

Verificação sem evidência:

```json
{}
```

Verificação com regra explícita:

```json
{
  "criterion_index": 0,
  "evidence_rule": "checks_green"
}
```

A resposta inclui:

```text
verification
evidence_attached
evidence_reason
execution
```

## Segurança

O M8.3:

- usa somente leituras GET;
- deriva o repositório de fontes ativas do projeto;
- não aceita repositório arbitrário no payload;
- não cria branch/commit/PR;
- não comenta/aprova PR;
- não reexecuta Actions;
- não faz merge/deploy/publicação;
- aplica redaction ao resultado registrado;
- degrada falhas externas para estados observáveis sem corromper a execução.

## Fora do escopo

O M8.3 não é executor e não amplia a allowlist do handoff. Uma etapa futura de execução real deverá ter política separada para cada capacidade de escrita e continuar tratando merge, deploy e publicação como autorizações distintas.
