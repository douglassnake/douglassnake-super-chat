# Agent Task Packs — M8.0

## Objetivo

O `AgentTaskPack` transforma o contexto recuperado pelo Segundo Cérebro em um artefato de execução legível por Codex ou outro agente, sem conceder automaticamente permissão para executar ações externas.

Ele separa três etapas:

```text
contexto do projeto
      ↓
preview do pack
      ↓
persistir como pending
      ↓
aprovação humana
      ↓
approved / pronto para handoff
```

`approved` significa que o pacote foi revisado para handoff. Não significa autorização automática para merge, deploy, publicação ou escrita em serviços externos.

## Conteúdo do pack

Um pack registra um snapshot do momento de criação:

- projeto, slug, status e próxima ação;
- objetivo;
- perfil de contexto;
- consulta usada na recuperação;
- critérios de aceite explícitos;
- guardrails/restrições;
- áreas ou arquivos sugeridos pelo solicitante;
- itens de contexto selecionados;
- fontes/rastreabilidade;
- orçamento de tokens;
- fingerprint SHA-256.

O snapshot do projeto é persistido para que alterações futuras no status do projeto não modifiquem retroativamente o conteúdo do pack.

## Critérios de aceite

Os critérios de aceite são obrigatórios e vêm do solicitante. O M8.0 não usa LLM para inventá-los.

Exemplo:

```json
{
  "project_id": "UUID",
  "objective": "Implementar o endpoint de exportação",
  "acceptance_criteria": [
    "Endpoint retorna Markdown",
    "Testes cobrem o fluxo de autorização"
  ],
  "constraints": [
    "Não alterar endpoints existentes"
  ],
  "suggested_areas": [
    "app/agent_routes.py",
    "tests/test_m8_agent_task_packs.py"
  ],
  "profile": "standard"
}
```

O sistema não inventa paths adicionais. `suggested_areas` contém somente os valores fornecidos pelo solicitante.

## Guardrails padrão

Todo pack recebe automaticamente regras de segurança operacional, incluindo:

- não fazer merge/deploy/publicação sem aprovação explícita;
- não expor ou persistir credenciais;
- não escrever em serviços externos fora de escopo autorizado;
- preservar rastreabilidade das fontes;
- não inventar requisito quando o critério de aceite for ambíguo.

Restrições do solicitante são adicionadas aos guardrails padrão.

## Redaction de secrets

Antes da persistência/exportação, o pack aplica redaction determinística em objetivo, critérios, restrições, contexto e referências.

O filtro cobre, entre outros:

- `password` / `passwd`;
- `secret` / `client_secret`;
- `access_token` / `refresh_token`;
- `api_key` / `token` / `authorization`;
- bearer tokens;
- prefixes conhecidos de tokens GitHub/OpenAI;
- parâmetros sensíveis em query strings de URLs.

Valores detectados são substituídos por `[REDACTED]`.

Essa proteção é uma barreira adicional; credenciais reais continuam proibidas no repositório e não devem ser inseridas deliberadamente no contexto.

## Fingerprint

O fingerprint é SHA-256 de uma representação JSON canônica do conteúdo relevante.

Pontuações de ranking (`score`) são excluídas do fingerprint porque podem variar marginalmente com a recência. O conteúdo, referências, critérios, restrições e orçamento permanecem parte da identidade do pack.

Um pack idêntico já persistido gera conflito em vez de duplicar o registro.

## Estados

### `pending`

Criado e persistido, mas ainda não aprovado para handoff.

```text
authorized_for_execution = false
```

### `approved`

Aprovado explicitamente. Repetir a aprovação é idempotente.

```text
authorized_for_execution = true
```

Ainda assim, o Markdown mantém o guardrail de que o pack, sozinho, não autoriza merge/deploy/publicação.

### `cancelled`

Cancelado explicitamente. Repetir cancelamento é idempotente. Um pack cancelado não pode ser aprovado e um pack aprovado não pode ser cancelado pelo mesmo endpoint.

## Endpoints

```text
POST /agent-task-packs/preview
POST /agent-task-packs
GET  /agent-task-packs/{pack_id}
GET  /projects/{project_id}/agent-task-packs
POST /agent-task-packs/{pack_id}/approve
POST /agent-task-packs/{pack_id}/cancel
GET  /agent-task-packs/{pack_id}/markdown
```

## Exportação Markdown

A exportação foi desenhada para ser entregue a Codex/agentes. Inclui:

- fingerprint e status;
- objetivo;
- próxima ação registrada;
- checklist de aceite;
- guardrails;
- áreas sugeridas pelo usuário;
- contexto selecionado com fontes;
- orçamento de tokens;
- aviso de autorização.

Para o mesmo conteúdo e mesmo estado, a exportação é determinística.

## Fora do escopo do M8.0

O M8.0 **não**:

- inicia Codex automaticamente;
- cria branch/commit/PR;
- faz merge;
- faz deploy;
- escreve em Drive/Calendar;
- transforma `approved` em execução autônoma.

Essas capacidades, se adicionadas depois, devem ter políticas de autorização próprias e trilha de auditoria.
