# Douglas Snake — Super Chat

O **Super Chat** é a interface operacional do **Segundo Cérebro**: memória persistente, recuperação seletiva de contexto, grafo semântico revisável, conectores somente leitura e execução técnica auditável com autorização humana por efeito.

## Arquitetura atual

```text
Usuário autenticado
  ↓
Super Chat Web / API
  ├── Painel operacional
  ├── CRUD de projetos, tarefas, decisões e memórias
  ├── Onboarding GitHub
  └── Grafo do conhecimento
       ├── entidades
       ├── relações tipadas e direcionadas
       ├── documentos/arquivos
       └── sugestões com revisão humana
  ↓
Context Engine + memória operacional
  ↓
Task Pack → Handoff → Agent Execution
  ↓
Controlled Executor
  ├── isolated-local
  ├── github-publish
  └── github-pr

Operação self-hosted
  ├── PostgreSQL persistente
  ├── secrets file-backed
  ├── Caddy/HTTPS
  ├── backup automático
  ├── restore periódico em banco descartável
  └── rotação de logs + monitoramento de storage
```

Cada efeito externo tem autorização própria. Relações descobertas pelo grafo também não são persistidas automaticamente: sugestões exigem revisão humana explícita.

## Marcos

- **M0–M6** — fundação, memória operacional, Context Engine, interface e conectores somente leitura;
- **M7.0** — benchmark determinístico de recuperação de contexto;
- **M8.0–M8.15** — Task Packs, handoffs, tracking e executor controlado;
- **M9.0–M9.3** — autenticação, observabilidade, secret files e readiness self-hosted;
- **M10.2–M10.3.1** — CRUD operacional na Web e onboarding GitHub;
- **M11.1–M11.6** — grafo do conhecimento, relações semânticas tipadas, documentos, descoberta com revisão humana e direção visual;
- **M12.1–M12.5** — operação contínua no ZimaOS/NAS, checkpoint real do host e documentação consolidada;
- **M12.6** — onboarding controlado dos projetos reais no Segundo Cérebro;
- **M13** — atualização contínua das fontes, frescor do contexto, digest revisável e benchmark real de recuperação.

O checkpoint operacional real do ZimaOS/NAS foi concluído em **06/10/2026** no commit `dd9eab884deed3865e51ffa68ac3cc9ddb37986f`. A Issue #57 foi fechada com critério GO para operação interna.

## Interface operacional — M10

A interface Web em `/app/` é o ponto principal de operação do Segundo Cérebro.

Ela permite:
- criar e editar projetos;
- criar e concluir tarefas;
- registrar decisões e memórias;
- vincular fontes GitHub;
- revisar contexto e estado operacional;
- abrir o onboarding GitHub de um projeto;
- alternar entre **Painel** e **Grafo**.

O onboarding GitHub permanece controlado: ele ajuda a registrar e estruturar a fonte, sem transformar o navegador em um executor genérico de ações externas.

## Grafo do conhecimento — M11

O grafo representa contexto persistente além das tabelas operacionais tradicionais.

Entidades de conhecimento podem representar, entre outros:
- plataformas e serviços;
- infraestrutura;
- documentos/arquivos;
- conceitos e outros nós compartilháveis entre projetos.

Relações semânticas incluem:
`USES`, `RUNS_ON`, `DEPENDS_ON`, `PART_OF`, `CREATED_FROM`, `SUPPORTS`, `BLOCKS`, `IMPLEMENTS`, `DECIDED_BY`, `RELATED_TO`, `HAS_DOCUMENT`, `MENTIONS` e `DESCRIBES`.

O grafo:
- mantém projetos visualmente dominantes;
- distingue tipos de nó;
- suporta zoom, pan, filtro e foco por vizinhança;
- mostra direção das relações;
- expõe relações de entrada e saída no inspector;
- permite documentos como nós;
- gera sugestões com evidência e confiança;
- exige aplicar, descartar ou adiar cada sugestão.

Veja `docs/KNOWLEDGE_GRAPH.md`.

## Segurança e execução controlada — M8/M9

O Controlled Executor segue a sequência:

```text
modify_worktree
   ↓
diff + patch_digest
   ↓ aprovação humana
create_branch
   ↓
apply_git_change
   ↓
create_commit
   ↓
publish_branch          # bare local
   ↓
publish_github_branch   # release separado
   ↓
create_pull_request     # release separado
```

Continuam fora da política de execução genérica:

```text
atualizar branch GitHub existente sem fluxo controlado
force push final
merge automático por agente
deploy arbitrário
shell/comando/binário/argv arbitrário
escrita externa genérica
```

Em produção:
- autenticação single-admin é obrigatória;
- senha é configurada por hash PBKDF2-SHA256;
- sessões são server-side;
- CSRF e cookies seguros são exigidos;
- `SECRET_BACKEND=files` é obrigatório;
- secrets ficam fora do Git e são montados read-only.

Veja `docs/AUTHENTICATION.md`, `docs/OBSERVABILITY.md` e `docs/ZIMAOS_SELF_HOSTED.md`.

## Operação contínua — M12

No host real ZimaOS/NAS:

- backup automático PostgreSQL roda diariamente;
- retenção automática atua apenas sobre backups criados pela própria rotina;
- cada dump recebe SHA-256 e validação por `pg_restore -l`;
- restore-check periódico cria banco descartável, restaura, executa `integration_readiness.py --database` e remove o banco temporário;
- o PostgreSQL principal não é reiniciado pelo processo;
- logs Docker usam `json-file` com `max-size=10m` e `max-file=5`;
- storage de aplicação e backup são monitorados;
- dados e backup ficam em filesystems/dispositivos distintos;
- API direta fica em loopback e o acesso normal ocorre por HTTPS via proxy compartilhado.

Runbook: `docs/M12_OPERATIONS.md`.

## Integration readiness

```bash
python scripts/integration_readiness.py
```

O check valida, entre outros:
- grafo Alembic com base/head únicos;
- migrations críticas presentes;
- executores externos indisponíveis por padrão;
- produção sem autenticação bloqueada;
- produção sem secret backend dedicado bloqueada;
- `merge`, `deploy` e publicação arbitrária proibidos;
- versão da API coerente;
- credenciais e `DATABASE_URL` fora de serializações de `Settings`.

No M12, o mesmo readiness é executado também contra um banco restaurado descartável no host real.

## Desenvolvimento local

```bash
git clone https://github.com/douglassnake/douglassnake-super-chat.git
cd douglassnake-super-chat
cp .env.example .env
docker compose up --build
```

Interface: `http://127.0.0.1:8000/app/`

OpenAPI: `http://127.0.0.1:8000/docs`

Em `development`, autenticação permanece desabilitada por padrão para DX/testes.

## Segurança de dados

O repositório é público. Nunca versione:
- `.env` real;
- tokens ou hashes reais;
- dumps/bancos;
- conversas ou memória privada;
- worktrees/staging privados;
- diretórios de secrets;
- evidências operacionais com dados sensíveis.

As fontes externas continuam sendo fonte de verdade para seus próprios domínios; o PostgreSQL mantém estado operacional e relações necessárias à continuidade.

## Onboarding de projetos reais — M12.6

O M12.6 adiciona um importador idempotente para manifesto privado:

```text
scripts/onboard_projects.py
```

Ele suporta dry-run por padrão e só grava com `--apply`. O manifesto pode definir projeto, fonte, decisão, tarefa, memória e relação semântica inicial sem incluir secrets.

Manifestos reais não devem entrar no Git. Um exemplo fictício está em:

```text
docs/M12_6_ONBOARDING_EXAMPLE.json
```

O fluxo foi validado no host real em 07/10/2026 com três projetos reais, retomada de contexto, relações semânticas úteis e segunda aplicação idempotente sem criações ou atualizações.


## Próximo marco — M13

Com o M12 concluído e três projetos reais já cadastrados, o próximo passo é manter esse contexto atualizado automaticamente sem abrir mão da revisão humana.

O M13 será executado em cinco etapas: sincronização GitHub read-only agendada, estado de frescor, digest revisável, benchmark com projetos reais e validação operacional no ZimaOS/NAS.

Plano: `docs/M13_CONTINUOUS_CONTEXT.md`.
