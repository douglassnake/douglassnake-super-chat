# Knowledge Graph — M11

## Objetivo

O grafo do conhecimento adiciona uma camada relacional explícita ao Segundo Cérebro sem substituir projetos, memória operacional ou fontes oficiais.

Ele serve para:
- retomar projetos com dependências visíveis;
- conectar infraestrutura, plataformas, documentos e conceitos;
- reutilizar entidades canônicas em vários projetos;
- representar direção semântica;
- sugerir novas relações sem persistência automática.

## Princípios

1. **Projetos continuam centrais.**
   O grafo complementa o Painel; não vira a única forma de navegar o sistema.

2. **Entidades são canônicas.**
   Uma mesma entidade, como `GitHub` ou `ZimaOS`, pode ser ligada a mais de um projeto.

3. **Relações possuem semântica.**
   Sempre que possível, use um tipo específico em vez de `RELATED_TO`.

4. **Direção importa.**
   `RUNS_ON`, `USES`, `CREATED_FROM` e demais relações não devem ser interpretadas como simétricas.

5. **Descoberta não é persistência.**
   Sugestões precisam de revisão humana.

## Estruturas persistentes

### knowledge_entities

Armazena nós canônicos do conhecimento.

Pode representar:
- plataforma/serviço;
- infraestrutura;
- documento/arquivo;
- outros conceitos úteis.

### project_relations

Relaciona:

```text
project → knowledge_entity
```

Tipos suportados:
- `USES`
- `RUNS_ON`
- `DEPENDS_ON`
- `PART_OF`
- `CREATED_FROM`
- `SUPPORTS`
- `BLOCKS`
- `IMPLEMENTS`
- `DECIDED_BY`
- `RELATED_TO`
- `HAS_DOCUMENT`

### knowledge_relations

Relaciona:

```text
knowledge_entity → knowledge_entity
```

Tipos atuais usados nesta camada:
- `MENTIONS`
- `DESCRIBES`
- `CREATED_FROM`

### graph_suggestion_batches

Agrupa sugestões descobertas antes da revisão.

Cada sugestão deve carregar informação suficiente para mostrar:
- origem;
- alvo;
- tipo;
- evidência;
- confiança;
- estado da revisão.

## Fluxo de revisão

```text
descoberta
  ↓
sugestão
  ↓
review-later / discard / apply
                     ↓
              relação persistente
```

Regras:
- relações já existentes não devem ser sugeridas de novo;
- duplicatas devem ser suprimidas;
- `apply` é o único estado que cria relação persistente;
- `review-later` preserva a pendência;
- `discard` encerra a sugestão sem criar relação.

## Documentos

M11.3 introduziu documentos como entidades de conhecimento.

Metadados úteis:
- título;
- tipo;
- fonte;
- external ID;
- path;
- URL;
- descrição;
- rationale.

Projeto → documento usa `HAS_DOCUMENT`.

Documento → entidade pode usar:
- `MENTIONS`;
- `DESCRIBES`;
- `CREATED_FROM`.

## Visualização

A UI do grafo suporta:
- Painel/Grafo;
- tipos de nó distintos;
- projetos com maior destaque;
- labels periféricos reduzidos em repouso;
- zoom;
- pan;
- filtros;
- foco por vizinhança;
- inspector lateral;
- direção visual em arestas semânticas.

## Inspector direcionado

Relações de saída aparecem como:

```text
USES → GitHub
```

Relações de entrada aparecem como:

```text
← USES · Super Chat / Segundo Cérebro
```

Essa distinção é necessária para preservar a semântica da direção.

## Exemplo validado

```text
Super Chat / Segundo Cérebro
  ├── USES → GitHub
  └── HAS_DOCUMENT → README — Super Chat

README — Super Chat
  └── CREATED_FROM → GitHub

Camara360
  └── RUNS_ON → ZimaOS
```

Entidades compartilhadas convergem para o mesmo nó canônico quando representam o mesmo objeto do mundo.

## Migrations

- `0010_semantic_graph_relations`
- `0011_graph_suggestion_batches`
- `0012_cross_knowledge_relations`

## Segurança e qualidade

O grafo não deve:
- inferir relação persistente silenciosamente;
- criar duplicatas semânticas óbvias;
- guardar secrets;
- substituir a fonte oficial de um dado externo;
- transformar `RELATED_TO` no tipo padrão para tudo.

Quando houver ambiguidade, prefira sugestão revisável a persistência automática.
