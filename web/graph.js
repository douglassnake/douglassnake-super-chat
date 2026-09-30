(() => {
  const SVG_NS = "http://www.w3.org/2000/svg";
  const $ = (selector) => document.querySelector(selector);

  const state = {
    payload: null,
    nodes: [],
    edges: [],
    positions: new Map(),
    selectedId: null,
    transform: { x: 0, y: 0, scale: 1 },
    drag: null,
  };

  const typeLabels = {
    project: "Projeto",
    entity: "Entidade",
    task: "Tarefa",
    decision: "Decisão",
    memory: "Memória",
    source: "Fonte / arquivo",
    delta: "Revisão pendente",
  };

  const semanticRelationLabels = {
    uses: "USES",
    runs_on: "RUNS_ON",
    depends_on: "DEPENDS_ON",
    part_of: "PART_OF",
    created_from: "CREATED_FROM",
    supports: "SUPPORTS",
    blocks: "BLOCKS",
    implements: "IMPLEMENTS",
    decided_by: "DECIDED_BY",
    related_to: "RELATED_TO",
  };

  const typeAngles = {
    source: -Math.PI / 2,
    entity: -Math.PI / 4,
    task: 0,
    decision: Math.PI / 2,
    memory: Math.PI,
    delta: Math.PI * 0.75,
  };

  const radii = { project: 17, entity: 11, source: 11, decision: 10, task: 9, memory: 9, delta: 9 };

  function notify(message, isError = false) {
    const toast = $("#toast");
    if (!toast) return;
    toast.textContent = message;
    toast.classList.toggle("error", isError);
    toast.classList.remove("hidden");
    window.clearTimeout(notify.timer);
    notify.timer = window.setTimeout(() => toast.classList.add("hidden"), 4200);
  }

  function activeProjectId() {
    return document.querySelector(".nav-item.active")?.dataset.projectId || null;
  }

  function enabledTypes() {
    const enabled = new Set(["project"]);
    document.querySelectorAll("[data-graph-type]").forEach((input) => {
      if (input.checked) enabled.add(input.dataset.graphType);
    });
    return enabled;
  }

  async function requestJson(path, options = {}) {
    const response = await window.fetch(path, {
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
      ...options,
    });
    if (!response.ok) {
      let detail = `HTTP ${response.status}`;
      try {
        const payload = await response.json();
        if (payload.detail) detail = typeof payload.detail === "string" ? payload.detail : JSON.stringify(payload.detail);
      } catch {}
      throw new Error(detail);
    }
    if (response.status === 204) return null;
    return response.json();
  }

  async function loadGraph() {
    const response = await window.fetch("/graph");
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    state.payload = await response.json();
  }

  function scopedData() {
    if (!state.payload) return { nodes: [], edges: [] };
    const types = enabledTypes();
    const scope = $("#graph-scope")?.value || "all";
    const selectedProject = activeProjectId();

    let nodes = state.payload.nodes.filter((node) => types.has(node.type));
    if (scope === "selected" && selectedProject) {
      nodes = nodes.filter((node) => {
        if (node.type === "project") return node.entity_id === selectedProject;
        if (node.project_id === selectedProject) return true;
        return Array.isArray(node.project_ids) && node.project_ids.includes(selectedProject);
      });
    }

    const ids = new Set(nodes.map((node) => node.id));
    const edges = state.payload.edges.filter((edge) => ids.has(edge.source) && ids.has(edge.target));
    return { nodes, edges };
  }

  function parentsFor(node, edges, nodeById) {
    if (node.type === "project") return [];
    return edges
      .filter((edge) => edge.target === node.id)
      .map((edge) => nodeById.get(edge.source))
      .filter((candidate) => candidate?.type === "project");
  }

  function computeLayout(width, height) {
    const positions = new Map();
    const nodeById = new Map(state.nodes.map((node) => [node.id, node]));
    const projects = state.nodes.filter((node) => node.type === "project");
    const centerX = width / 2;
    const centerY = height / 2;
    const orbit = projects.length <= 1 ? 0 : Math.max(150, Math.min(width, height) * 0.29);

    projects.forEach((project, index) => {
      const angle = projects.length <= 1 ? 0 : -Math.PI / 2 + (index * Math.PI * 2) / projects.length;
      positions.set(project.id, {
        x: projects.length <= 1 ? centerX : centerX + Math.cos(angle) * orbit,
        y: projects.length <= 1 ? centerY : centerY + Math.sin(angle) * orbit,
      });
    });

    const grouped = new Map();
    for (const node of state.nodes) {
      if (node.type === "project") continue;
      const parents = parentsFor(node, state.edges, nodeById);
      if (parents.length > 1) {
        const points = parents.map((parent) => positions.get(parent.id)).filter(Boolean);
        positions.set(node.id, {
          x: points.reduce((sum, point) => sum + point.x, 0) / points.length,
          y: points.reduce((sum, point) => sum + point.y, 0) / points.length,
        });
        continue;
      }

      const ownerId = parents[0]?.id || `project:${node.project_id || "global"}`;
      const key = JSON.stringify([ownerId, node.type]);
      const siblings = grouped.get(key) || [];
      siblings.push(node);
      grouped.set(key, siblings);
    }

    for (const [key, siblings] of grouped.entries()) {
      const [ownerId, type] = JSON.parse(key);
      const base = positions.get(ownerId) || { x: centerX, y: centerY };
      const baseAngle = typeAngles[type] ?? 0;
      siblings.forEach((node, index) => {
        const ring = Math.floor(index / 6);
        const slot = index % 6;
        const count = Math.min(6, siblings.length - ring * 6);
        const spread = Math.min(Math.PI * 0.9, Math.max(0, count - 1) * 0.5);
        const local = count <= 1 ? 0 : -spread / 2 + (slot * spread) / Math.max(1, count - 1);
        const distance = 100 + ring * 58 + (["source", "entity"].includes(type) ? 14 : 0);
        positions.set(node.id, {
          x: base.x + Math.cos(baseAngle + local) * distance,
          y: base.y + Math.sin(baseAngle + local) * distance,
        });
      });
    }

    for (const point of positions.values()) {
      point.x = Math.max(48, Math.min(width - 48, point.x));
      point.y = Math.max(40, Math.min(height - 40, point.y));
    }
    state.positions = positions;
  }

  function svgElement(name, attrs = {}) {
    const element = document.createElementNS(SVG_NS, name);
    Object.entries(attrs).forEach(([key, value]) => element.setAttribute(key, String(value)));
    return element;
  }

  function shortLabel(value, limit) {
    const text = String(value || "");
    return text.length > limit ? `${text.slice(0, limit - 1)}…` : text;
  }

  function neighborhood(nodeId) {
    const nodeIds = new Set([nodeId]);
    const edgeIds = new Set();
    state.edges.forEach((edge) => {
      if (edge.source !== nodeId && edge.target !== nodeId) return;
      nodeIds.add(edge.source);
      nodeIds.add(edge.target);
      edgeIds.add(edge.id);
    });
    return { nodeIds, edgeIds };
  }

  function applyFocus() {
    const svg = $("#knowledge-graph-svg");
    if (!svg) return;
    if (!state.selectedId) {
      svg.querySelectorAll(".graph-node, .graph-edge").forEach((element) => {
        element.classList.remove("selected", "neighbor", "dimmed", "highlighted");
      });
      return;
    }

    const { nodeIds, edgeIds } = neighborhood(state.selectedId);
    svg.querySelectorAll(".graph-node").forEach((element) => {
      const id = element.dataset.nodeId;
      element.classList.toggle("selected", id === state.selectedId);
      element.classList.toggle("neighbor", id !== state.selectedId && nodeIds.has(id));
      element.classList.toggle("dimmed", !nodeIds.has(id));
    });
    svg.querySelectorAll(".graph-edge").forEach((element) => {
      const id = element.dataset.edgeId;
      element.classList.toggle("highlighted", edgeIds.has(id));
      element.classList.toggle("dimmed", !edgeIds.has(id));
    });
  }

  function contextText(node) {
    const metadata = node.metadata || {};
    if (node.type === "project") return metadata.description || metadata.next_action || `Prioridade ${metadata.priority ?? 0}`;
    if (node.type === "entity") return metadata.description || `Entidade ${metadata.kind || node.subtitle || "sem tipo"}`;
    if (node.type === "task") return metadata.description || `Prioridade ${metadata.priority ?? 0}`;
    if (node.type === "decision") return metadata.body || metadata.rationale || "Decisão ativa";
    if (node.type === "memory") return metadata.content || `Importância ${metadata.importance ?? node.importance}`;
    if (node.type === "source") return metadata.external_id || metadata.url || node.subtitle || "Fonte vinculada";
    if (node.type === "delta") return metadata.summary || metadata.next_action || "Aguardando revisão";
    return "";
  }

  async function removeSemanticRelation(relationId) {
    if (!relationId) return;
    if (!window.confirm("Remover esta relação semântica do grafo?")) return;
    try {
      await requestJson(`/relations/${encodeURIComponent(relationId)}`, { method: "DELETE" });
      state.selectedId = null;
      await reloadGraph();
      notify("Relação removida.");
    } catch (error) {
      notify(`Falha ao remover relação: ${error.message}`, true);
    }
  }

  function renderInspector(node) {
    const container = $("#graph-inspector");
    if (!container) return;
    container.replaceChildren();
    if (!node) {
      const empty = document.createElement("p");
      empty.className = "graph-inspector-empty";
      empty.textContent = "Clique em um nó para destacar suas conexões e inspecionar o contexto relacionado.";
      container.appendChild(empty);
      return;
    }

    const type = document.createElement("span");
    type.className = "graph-inspector-type";
    type.textContent = typeLabels[node.type] || node.type;
    const title = document.createElement("h4");
    title.className = "graph-inspector-title";
    title.textContent = node.label;
    const subtitle = document.createElement("div");
    subtitle.className = "graph-inspector-subtitle";
    subtitle.textContent = node.subtitle || "";
    container.append(type, title, subtitle);

    const contextSection = document.createElement("div");
    contextSection.className = "graph-inspector-section";
    const contextLabel = document.createElement("span");
    contextLabel.textContent = "Contexto";
    const context = document.createElement("p");
    context.textContent = contextText(node);
    contextSection.append(contextLabel, context);
    container.appendChild(contextSection);

    const relations = state.edges.filter((edge) => edge.source === node.id || edge.target === node.id);
    const relationsSection = document.createElement("div");
    relationsSection.className = "graph-inspector-section";
    const relationsLabel = document.createElement("span");
    relationsLabel.textContent = `Conexões (${relations.length})`;
    const list = document.createElement("div");
    list.className = "graph-relation-list";
    relations.forEach((edge) => {
      const otherId = edge.source === node.id ? edge.target : edge.source;
      const other = state.nodes.find((candidate) => candidate.id === otherId);
      if (!other) return;
      const row = document.createElement("div");
      row.className = "graph-relation-row";
      const button = document.createElement("button");
      button.type = "button";
      button.className = "graph-relation";
      const relationLabel = semanticRelationLabels[edge.type] || edge.label || edge.type;
      button.textContent = `${relationLabel} · ${other.label}`;
      if (edge.metadata?.rationale) button.title = edge.metadata.rationale;
      button.addEventListener("click", () => focusNode(other.id));
      row.appendChild(button);
      if (edge.semantic && edge.metadata?.relation_id) {
        const remove = document.createElement("button");
        remove.type = "button";
        remove.className = "graph-relation-remove";
        remove.textContent = "×";
        remove.title = "Remover relação";
        remove.setAttribute("aria-label", "Remover relação");
        remove.addEventListener("click", () => removeSemanticRelation(edge.metadata.relation_id));
        row.appendChild(remove);
      }
      list.appendChild(row);
    });
    if (!relations.length) {
      const empty = document.createElement("p");
      empty.textContent = "Nenhuma conexão visível com os filtros atuais.";
      list.appendChild(empty);
    }
    relationsSection.append(relationsLabel, list);
    container.appendChild(relationsSection);
  }

  function focusNode(nodeId) {
    state.selectedId = nodeId;
    applyFocus();
    renderInspector(state.nodes.find((node) => node.id === nodeId) || null);
  }

  function applyTransform() {
    const stage = $("#knowledge-graph-stage");
    if (!stage) return;
    const { x, y, scale } = state.transform;
    stage.setAttribute("transform", `translate(${x} ${y}) scale(${scale})`);
  }

  function resetView() {
    state.selectedId = null;
    state.transform = { x: 0, y: 0, scale: 1 };
    applyTransform();
    applyFocus();
    renderInspector(null);
  }

  function renderGraph() {
    const svg = $("#knowledge-graph-svg");
    const canvas = $("#graph-canvas-wrap");
    if (!svg || !canvas || !state.payload) return;

    const scoped = scopedData();
    state.nodes = scoped.nodes;
    state.edges = scoped.edges;
    if (state.selectedId && !state.nodes.some((node) => node.id === state.selectedId)) state.selectedId = null;

    $("#graph-project-count").textContent = String(state.nodes.filter((node) => node.type === "project").length);
    $("#graph-node-count").textContent = String(state.nodes.length);
    $("#graph-edge-count").textContent = String(state.edges.length);
    $("#graph-empty")?.classList.toggle("hidden", state.nodes.length > 0);

    const width = Math.max(640, canvas.clientWidth || 900);
    const height = Math.max(520, canvas.clientHeight || 650);
    svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
    svg.replaceChildren();
    if (!state.nodes.length) {
      renderInspector(null);
      return;
    }

    computeLayout(width, height);
    const stage = svgElement("g", { id: "knowledge-graph-stage" });
    svg.appendChild(stage);

    state.edges.forEach((edge) => {
      const source = state.positions.get(edge.source);
      const target = state.positions.get(edge.target);
      if (!source || !target) return;
      const line = svgElement("line", {
        x1: source.x,
        y1: source.y,
        x2: target.x,
        y2: target.y,
        class: `graph-edge${edge.semantic ? " semantic" : ""}`,
      });
      line.dataset.edgeId = edge.id;
      const title = svgElement("title");
      title.textContent = semanticRelationLabels[edge.type] || edge.label || edge.type;
      line.appendChild(title);
      stage.appendChild(line);
    });

    state.nodes.forEach((node) => {
      const point = state.positions.get(node.id);
      if (!point) return;
      const importance = Math.max(0, Math.min(1, Number(node.importance || 0.5)));
      const radius = (radii[node.type] || 9) * (0.9 + importance * 0.18);
      const group = svgElement("g", {
        class: `graph-node ${node.type}`,
        transform: `translate(${point.x} ${point.y})`,
        tabindex: 0,
        role: "button",
        "aria-label": `${typeLabels[node.type] || node.type}: ${node.label}`,
      });
      group.dataset.nodeId = node.id;
      group.appendChild(svgElement("circle", { cx: 0, cy: 0, r: radius }));
      const text = svgElement("text", { x: radius + 7, y: 4 });
      text.textContent = shortLabel(node.label, node.type === "project" ? 42 : 31);
      group.appendChild(text);
      const title = svgElement("title");
      title.textContent = `${typeLabels[node.type] || node.type}: ${node.label}`;
      group.appendChild(title);
      group.addEventListener("click", (event) => {
        event.stopPropagation();
        focusNode(node.id);
      });
      group.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          focusNode(node.id);
        }
      });
      stage.appendChild(group);
    });

    state.transform = { x: 0, y: 0, scale: 1 };
    applyTransform();
    applyFocus();
    renderInspector(state.selectedId ? state.nodes.find((node) => node.id === state.selectedId) : null);
  }

  async function reloadGraph({ quiet = false } = {}) {
    try {
      await loadGraph();
      renderGraph();
    } catch (error) {
      if (!quiet) notify(`Falha ao carregar grafo: ${error.message}`, true);
    }
  }

  function openRelationDialog() {
    const projectId = activeProjectId();
    if (!projectId) {
      notify("Selecione um projeto antes de criar uma relação.", true);
      return;
    }
    const dialog = $("#graph-relation-dialog");
    $("#graph-relation-form")?.reset();
    if (dialog && !dialog.open) dialog.showModal();
  }

  function closeRelationDialog() {
    const dialog = $("#graph-relation-dialog");
    if (dialog?.open) dialog.close();
  }

  async function submitRelation(event) {
    event.preventDefault();
    const projectId = activeProjectId();
    if (!projectId) return;
    const save = $("#graph-relation-save");
    const original = save?.textContent;
    if (save) {
      save.disabled = true;
      save.textContent = "Salvando…";
    }
    try {
      const payload = {
        entity_name: $("#graph-entity-name").value.trim(),
        entity_kind: $("#graph-entity-kind").value,
        relation_type: $("#graph-relation-type").value,
        entity_description: $("#graph-entity-description").value.trim() || null,
        rationale: $("#graph-relation-rationale").value.trim() || null,
      };
      await requestJson(`/projects/${encodeURIComponent(projectId)}/relations`, {
        method: "POST",
        body: JSON.stringify(payload),
      });
      closeRelationDialog();
      await reloadGraph();
      notify(`${semanticRelationLabels[payload.relation_type] || payload.relation_type} registrada.`);
    } catch (error) {
      notify(`Falha ao criar relação: ${error.message}`, true);
    } finally {
      if (save) {
        save.disabled = false;
        save.textContent = original || "Salvar relação";
      }
    }
  }

  function showDashboard() {
    $("#stats")?.classList.remove("hidden");
    $(".workspace-grid")?.classList.remove("hidden");
    $("#knowledge-graph-panel")?.classList.add("hidden");
    $("#dashboard-view-button")?.classList.add("active-view");
    $("#graph-view-button")?.classList.remove("active-view");
  }

  async function showGraph() {
    $("#stats")?.classList.add("hidden");
    $(".workspace-grid")?.classList.add("hidden");
    $("#knowledge-graph-panel")?.classList.remove("hidden");
    $("#dashboard-view-button")?.classList.remove("active-view");
    $("#graph-view-button")?.classList.add("active-view");
    if (!state.payload) await reloadGraph();
    else renderGraph();
  }

  $("#dashboard-view-button")?.addEventListener("click", showDashboard);
  $("#graph-view-button")?.addEventListener("click", showGraph);
  $("#graph-scope")?.addEventListener("change", renderGraph);
  $("#graph-reset")?.addEventListener("click", resetView);
  $("#graph-new-relation")?.addEventListener("click", openRelationDialog);
  $("#graph-relation-form")?.addEventListener("submit", submitRelation);
  $("#graph-relation-close")?.addEventListener("click", closeRelationDialog);
  $("#graph-relation-cancel")?.addEventListener("click", closeRelationDialog);
  document.querySelectorAll("[data-graph-type]").forEach((input) => input.addEventListener("change", renderGraph));
  $("#project-nav")?.addEventListener("click", () => {
    if ($("#graph-scope")?.value !== "selected") return;
    window.setTimeout(renderGraph, 80);
  });
  $("#refresh-button")?.addEventListener("click", () => {
    if ($("#knowledge-graph-panel")?.classList.contains("hidden")) return;
    window.setTimeout(() => reloadGraph({ quiet: true }), 100);
  });

  const svg = $("#knowledge-graph-svg");
  if (svg) {
    svg.addEventListener("click", () => focusNode(null));
    svg.addEventListener("wheel", (event) => {
      event.preventDefault();
      const factor = event.deltaY < 0 ? 1.12 : 0.89;
      state.transform.scale = Math.max(0.55, Math.min(2.8, state.transform.scale * factor));
      applyTransform();
    }, { passive: false });
    svg.addEventListener("pointerdown", (event) => {
      if (event.target.closest?.(".graph-node")) return;
      state.drag = {
        id: event.pointerId,
        startX: event.clientX,
        startY: event.clientY,
        x: state.transform.x,
        y: state.transform.y,
      };
      svg.setPointerCapture(event.pointerId);
      svg.classList.add("panning");
    });
    svg.addEventListener("pointermove", (event) => {
      if (!state.drag || state.drag.id !== event.pointerId) return;
      state.transform.x = state.drag.x + event.clientX - state.drag.startX;
      state.transform.y = state.drag.y + event.clientY - state.drag.startY;
      applyTransform();
    });
    const stop = (event) => {
      if (!state.drag || state.drag.id !== event.pointerId) return;
      state.drag = null;
      svg.classList.remove("panning");
      try { svg.releasePointerCapture(event.pointerId); } catch {}
    };
    svg.addEventListener("pointerup", stop);
    svg.addEventListener("pointercancel", stop);
  }

  if (window.ResizeObserver) {
    const canvas = $("#graph-canvas-wrap");
    if (canvas) {
      let timer = null;
      new ResizeObserver(() => {
        if ($("#knowledge-graph-panel")?.classList.contains("hidden")) return;
        window.clearTimeout(timer);
        timer = window.setTimeout(renderGraph, 120);
      }).observe(canvas);
    }
  }
})();