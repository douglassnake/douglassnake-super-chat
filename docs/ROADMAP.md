# Roadmap

## M0 — Fundação documental
Status: **concluído**.

## M1 — Memória operacional
Status: **concluído**.

FastAPI, PostgreSQL, Alembic, projetos, decisões, tarefas, resumos, snapshot, Docker e testes.

## M2 — Context Engine v1
Status: **concluído**.

Perfis `minimal`, `standard` e `deep`, ranking determinístico, deduplicação, compactação, orçamento de tokens, auditoria e `continue`.

## M3 — GitHub Connector
Status: **concluído**.

GitHub somente leitura, commits, PRs, Issues, Actions, eventos normalizados e sync idempotente.

## M4 — Session Memory
Status: **concluído**.

`SessionDelta`, preview, confirmação humana, aplicação transacional, decisões/tarefas propostas, alteração de status/próxima ação e descarte.

## M5 — Interface web
Status: **concluído**.

Dashboard responsivo, Health Score explicável, projetos, tarefas, fontes, eventos, painel de tokens, `continuar`, SessionDelta visual e sync GitHub.

## M6 — Google Drive e Calendar
Status: **concluído**.

- fontes `google_drive` e `google_calendar`;
- OAuth somente por ambiente;
- Drive somente leitura;
- metadados persistidos sem copiar documentos completos;
- Google Docs/textos recuperados sob demanda;
- seleção lexical de janelas relevantes;
- trechos Drive disputando o orçamento normal do Context Engine;
- Calendar normalizado para `events`;
- sync idempotente com create/update/skip;
- degradação segura quando OAuth Drive não está disponível;
- testes sem credenciais reais.

## M7 — Qualidade de recuperação

### M7.0 — benchmark de contexto
Status: **concluído na branch `codex/m7-retrieval-benchmark`**.

Entregas:
- `precision@k` e `recall@k`;
- cobertura de fontes esperadas;
- eficiência e compressão de tokens;
- latência;
- endpoint `POST /evaluation/context`;
- dataset sintético versionável;
- runner CLI;
- execução automática no CI;
- cenário de pressão de tokens;
- documentação de interpretação.

Baseline sintético v1:
- 4 casos;
- recall e coverage de 1,0 nos fixtures;
- cenário `Token pressure minimal`: 13.926 tokens candidatos → 1.794 selecionados, compressão de 0,871176, preservando recall@2 de 1,0.

Esses números validam o mecanismo e o orçamento, mas não são evidência de desempenho em dados reais.

### M7.1 — busca híbrida/semântica
Status: **condicional — não iniciado**.

Possíveis entregas, somente se benchmark real justificar:
- pgvector;
- embeddings;
- lexical + vetorial;
- re-ranking;
- comparação A/B contra o baseline M7.0.

Critério: manter embeddings somente se houver melhoria mensurável de recuperação que compense custo, latência e complexidade operacional.

### Próxima validação

Criar um conjunto **privado** de consultas reais dos projetos, com gabaritos de `source_ref`. Dados e documentos privados não entram no repositório público; somente métricas agregadas podem ser registradas.

## M8 — Automação e agentes

### M8.0 — Agent Task Packs
Status: **concluído na branch `codex/m8-agent-task-packs`**.

Entregas:
- estrutura persistente `AgentTaskPack`;
- snapshot do projeto, objetivo, contexto, fontes e budget;
- critérios de aceite explícitos e obrigatórios;
- guardrails padrão + restrições do solicitante;
- áreas/arquivos sugeridos sem inventar paths;
- redaction determinística de padrões de secrets;
- fingerprint SHA-256 canônico;
- prevenção de duplicação de pack idêntico;
- estados `pending`, `approved` e `cancelled`;
- aprovação e cancelamento protegidos por estado;
- preview sem persistência;
- exportação Markdown determinística;
- endpoints de criação, consulta, aprovação, cancelamento e exportação;
- migration Alembic;
- testes automatizados;
- documentação `docs/AGENT_TASK_PACKS.md`.

Regra de autorização: `approved` significa **pronto para handoff**, não autorização automática para merge, deploy, publicação ou escrita externa.

### M8.1 — handoff assistido e auditável
Status: **planejado**.

Objetivo: entregar um `AgentTaskPack` aprovado a um executor sem ampliar silenciosamente permissões.

Possíveis entregas:
- registro de handoff com executor/alvo;
- trilha de auditoria do pack entregue;
- retorno estruturado de execução/status;
- associação entre pack, branch, commit e PR quando esses artefatos existirem;
- diferenças entre plano aprovado e resultado executado;
- revisão humana antes de qualquer ação de escrita externa;
- nenhum merge/deploy automático por padrão.

### M8.2 — acompanhamento de execução
Status: **futuro**.

Somente após M8.1 e métricas operacionais:
- acompanhamento de PRs e CI;
- atualização de progresso;
- geração de follow-ups;
- encerramento de tarefa mediante evidência;
- políticas explícitas por tipo de ação.

## Regra de evolução

Não adicionar complexidade de IA ou autonomia antes de existir:
1. fonte de verdade;
2. modelo de dados;
3. rastreabilidade;
4. teste de recuperação;
5. métrica de contexto;
6. autorização humana explícita para ações com efeito externo.
