# Google Context — M6

## Objetivo

Usar Google Drive e Google Calendar como fontes externas do Segundo Cérebro sem transformar o PostgreSQL em uma cópia dos serviços Google.

## Google Drive

A fonte `google_drive` guarda apenas:
- ID do arquivo;
- label/URL;
- nome e MIME type;
- data de modificação;
- web view link;
- estado `trashed`;
- data da última sincronização.

O texto do documento é buscado **sob demanda** durante a construção de contexto. Ele é normalizado, dividido em janelas e ranqueado lexicalmente contra a consulta. Apenas as melhores janelas entram como candidatos `document_excerpt`.

Limites atuais:

| Perfil | Máx. janelas por arquivo | Tamanho aproximado |
|---|---:|---:|
| `minimal` | 1 | 1.200 caracteres |
| `standard` | 2 | 1.800 caracteres |
| `deep` | 4 | 2.600 caracteres |

Esses trechos ainda passam pelo orçamento global do Context Engine, portanto o Google Drive não cria um segundo orçamento paralelo.

### Formatos textuais M6

- Google Docs → exportação `text/plain`;
- `text/*` → conteúdo direto;
- JSON/XML → conteúdo direto.

PDF, Word, Sheets e Slides permanecem como referência/metadados no M6. Extração específica pode ser adicionada depois, sem alterar a regra de não persistir o documento completo.

## Google Calendar

A fonte `google_calendar` usa o ID do calendário (`primary`, por exemplo). O sync lê uma janela temporal de 14 dias para trás e 120 dias para frente.

Cada compromisso vira um evento compacto:

```text
source_type = google_calendar
event_type  = google_calendar.event
```

São preservados título, descrição compacta, local, início/fim, URL e metadados de rastreabilidade.

O sync é um upsert por `project_id + calendar_id + event_id`:
- novo → `created`;
- alterado → `updated`;
- igual → `skipped`.

Datas são normalizadas em UTC antes da comparação para manter idempotência entre PostgreSQL e SQLite/testes.

## OAuth

O conector aceita:
1. `GOOGLE_ACCESS_TOKEN` temporário; ou
2. `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` e `GOOGLE_REFRESH_TOKEN`.

O refresh token é trocado por access token em tempo de execução. Nenhum segredo é persistido em `ProjectSource`, `Event`, `ContextItem` ou `ContextRun`.

## Degradação segura

O Google é uma fonte complementar. Se uma consulta de Drive falhar por ausência de OAuth/API, o Context Engine retorna a memória local existente normalmente. A falha do serviço externo não deve inutilizar `continue`.

O endpoint explícito de sincronização, por outro lado, retorna erro apropriado quando a autenticação/configuração está indisponível, porque o usuário solicitou uma ação de sync.

## Privacidade

- somente leitura;
- nenhum secret no banco;
- nenhum documento completo no repositório;
- nenhum texto completo do Drive persistido por padrão;
- `source_ref`/URL preserva a proveniência;
- testes usam um reader simulado e dados fictícios.
