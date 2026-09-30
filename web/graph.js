(() => {
  const SVG_NS = "http://www.w3.org/2000/svg";
  const $ = (selector) => document.querySelector(selector);

  const state = {
    payload: null,
    visibleNodes: [],
    visibleEdges: [],
    positions: new Map(),
    selectedId: null,
    transform: { x: 0, y: 0, scale: 1 },
    dragging: null,
    loaded: false,
  };

  const labels = {
    project: "Projeto",
    task: "Tarefa",
    decision: "Decisão",
    memory: "Memória",
    source: "Fonte / arquivo",
    delta: "Revisão pendente",
  };

  const radii = {
    project: 17,
    source: 11,
    decision: 10,
    task: 9,
    memory: 9,
    delta: 9,
  };

  function notify(message, isError = false) {
    const toast = $("#toast");
    if (!toast) return;
    toast.textContent = message;
    toast.classList.toggle("error", isError);
    toast.classList.remove("hidden");
    window.clearTimeout(notify.timer);
    notify.timer = window.setTimeout(() => toast.classList.add("hidden"), 4200);
  }

  async function fetchGraph() {
    const response = await window.fetch("/graph");
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    state.payload = await response.json();
    state.loaded = true;
  }

  function activeProjectId() {
    return document.querySelector(".nav-item.active")?.dataset.projectId || null;
  }

  function enabledTypes() {
    return new Set(
      [...document.querySelectorAll("[data-graph-type]")]
        .filter((input) => input.checked)
        .map((input) => input.dataset.graphType)
    );
  }

  function scopedData() {
    if (!state.payload) return { nodes: [], edges: [] };
    const types = enabledTypes();
    types.add("project");
    const scope = $("#graph-scope")?.value || "all";
    const projectId = activeProjectId();

    let nodes = state.payload.nodes.filter((node) => types.has(node.type));
    if (scope === "selected" && projectId) {
      nodes = nodes.filter((node) => {
        if (node.type === "project") return node.entity_id === projectId;
        if (node.project_id === projectId) return true;
        return Array.isArray(node.project_ids) && node.project_ids.includes(projectId);
      });
    }

    const ids = new Set(nodes.map((node) => node.id));
    const edges = state.payload.edges.filter(
      (edge) => ids.has(edge.source) && ids.has(edge.target)
    );
    return { nodes, edges };
  }

  function projectParents(node, edges) {
    if (node.type === "project") return [];
    const parents = [];
    for (const edge of edges) {
      if (edge.target !== node.id) continue;
      const project = state.visibleNodes.find(
        (candidate) => candidate.id === edge.source && candidate.type === "project"
      );
      if (project) parents.push(project);
    }
    return parents;
  }

  function layoutGraph(width, height) {
    const nodes = state.visibleNodes;
    const edges = state.visibleEdges;
    const positions = new Map();
    const projects = nodes.filter((node) => node.type === "project");
    const cx = width / 2;
    const cy = height / 2;
    const projectOrbit = projects.length <= 1 ? 0 : Math.max(150, Math.min(width, height) * 0.29);

    projects.forEach((project, index) => {
      const angle = projects.length <= 1 ? 0 : -Math.PI / 2 + (index * Math.PI * 2) / projects.length;
      positions.set(project.id, {
        x: projects.length <= 1 ? cx : cx + Math.cos(angle) * projectOrbit,
        y: projects.length <= 1 ? cy : cy + Math.sin(angle) * projectOrbit,
      });
    });

    const typeOffsets = {
      source: -Math.PI / 2,
      task: 0,
      decision: Math.PI / 2,
      memory: Math.PI,
      delta: Math.PI * 0.75,
    };
    const grouped = new Map();

    for (const node of nodes) {
      if (node.type === "project") continue;
      const parents = projectParents(node, edges);
      if (parents.length > 1) {
        const coords = parents.map((parent) => positions.get(parent.id)).filter(Boolean);
        const x = coords.reduce((sum, point) => sum + point.x, 0) / coords.length;
        const y = coords.reduce((sum, point) => sum + point.y, 0) / coords.length;
        positions.set(node.id, { x, y });
        continue;
      }
      const owner = parents[0];
      const ownerId = owner?.id || `orphan:${node.project_id || "global"}`;
      const key = `${ownerId}:${node.type}`;
      const siblings = grouped.get(key) || [];
      siblings.push(node);
      grouped.set(key, siblings);
    }

    for (const [key, siblings] of grouped.entries()) {
      const [ownerId, type] = key.split(":", 2);
      let base = positions.get(ownerId);
      if (!base) {
        const projectId = siblings[0]?.project_id;
        base = positions.get(`project:${projectId}`) || { x: cx, y: cy };
      }
      const baseAngle = typeOffsets[type] ?? 0;
      siblings.forEach((node, index) => {
        const ring = Math.floor(index / 6);
        const slot = index % 6;
        const count = Math.min(6, siblings.length - ring * 6);
        const spread = Math.min(Math.PI * 0.92, 0.52 * Math.max(1, count - 1));
        const local = count <= 1 ? 0 : -spread / 2 + (slot * spread) / Math.max(1, count - 1);
        const radius = 96 + ring * 58 + (node.type === "source" ? 12 : 0);
        const angle = baseAngle + local;
        positions.set(node.id, {
          x: base.x + Math.cos(angle) * radius,
          y: base.y + Math.sin(angle) * radius,
        });
      });
    }

    // Gentle relaxation removes overlaps while keeping each cluster recognizable.
    const movable = nodes.filter((node) => node.type !== "project");
    for (let iteration = 0; iteration < 48; iteration += 1) {
      for (let i = 0; i < movable.length; i += 1) {
        const a = positions.get(movable[i].id);
        if (!a) continue;
        for (let j = i + 1; j < movable.length; j += 1) {
          const b = positions.get(movable[j].id);
          if (!b) continue;
          let dx = b.x - a.x;
          let dy = b.y - a.y;
          let distance = Math.hypot(dx, dy);
          if (distance < 0.01) {
            dx = 1;
            dy = 0;
            distance = 1;
          }
          const minimum = 48;
          if (distance >= minimum) continue;
          const push = (minimum - distance) * 0.18;
          const ux = dx / distance;
          const uy = dy / distance;
          a.x -= ux * push;
          a.y -= uy * push;
          b.x += ux * push;
          b.y += uy * push;
        }
      }
    }

    for (const point of positions.values()) {
      point.x = Math.max(46, Math.min(width - 46, point.x));
      point.y = Math.max(38, Math.min(height - 38, point.y));
    }
    state.positions = positions;
  }

  function svgElement(name, attrs = {}) {
    const element = document.createElementNS(SVG_NS, name);
    for (const [key, value] of Object.entries(attrs)) element.setAttribute(key, String(value));
    return element;
  }

  function shortLabel(value, limit = 34) {
    const text = String(value || "");
    return text.length > limit ? `${text.slice(0, limit - 1)}…` : text;
  }

  function relationNeighborhood(nodeId) {
    const neighbors = new Set([nodeId]);
    const edgeIds = new Set();
    for (const edge of state.visibleEdges) {
      if (edge.source === nodeId || edge.target === nodeId) {
        neighbors.add(edge.source);
        neighbors.add(edge.target);
        edgeIds.add(edge.id);
      }
    }
    return { neighbors, edgeIds };
  }

  function applyFocusClasses() {
    const svg = $("#knowledge-graph-svg");
    if (!svg) return;
    const selected = state.selectedId;
    if (!selected) {
      svg.querySelectorAll(".graph-node, .graph-edge").forEach((element) => {
        element.classList.remove("selected", "neighbor", "dimmed", "highlighted");
      });
      return;
    }

    const { neighbors, edgeIds } = relationNeighborhood(selected);
    svg.querySelectorAll(".graph-node").forEach((element) => {
      const id = element.dataset.nodeId;
      element.classList.toggle("selected", id === selected);
      element.classList.toggle("neighbor", id !== selected && neighbors.has(id));
      element.classList.toggle("dimmed", !neighbors.has(id));
    });
    svg.querySelectorAll(".graph-edge").forEach((element) => {
      const id = element.dataset.edgeId;
      element.classList.toggle("highlighted", edgeIds.has(id));
      element.classList.toggle("dimmed", !edgeIds.has(id));
    });
  }

  function metadataText(node) {
    const metadata = node.metadata || {};
    switch (node.type) {
      case "project":
        return metadata.description || metadata.next_action || `Prioridade ${metadata.priority ?? 0}`;
      case "task":
        return metadata.description || `Prioridade ${metadata.priority ?? 0}`;
      case "decision":
        return metadata.body || metadata.rationale || "Decisão ativa";
      case "memory":
        return metadata.content || `Importância ${metadata.importance ?? node.importance}`;
      case "source":
        return metadata.external_id || metadata.url || node.subtitle || "Fonte vinculada";
      case "delta":
        return metadata.summary || metadata.next_action || "Aguardando revisão";
      default:
        return "";
    }
  }

  function focusNode(nodeId) {
    state.selectedId = nodeId;
    applyFocusClasses();
    const node = state.visibleNodes.find((candidate) => candidate.id === nodeId);
    renderInspector(node || null);
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
    type.textContent = labels[node.type] || node.type;
    const title = document.createElement("h4");
    title.className = "graph-inspector-title";
    title.textContent = node.label;
    const subtitle = document.createElement("div");
    subtitle.className = "graph-inspector-subtitle";
    subtitle.textContent = node.subtitle || "";
    container.append(type, title, subtitle);

    const description = document.createElement("div");
    description.className = "graph-inspector-section";
    const descriptionLabel = document.createElement("span");
    descriptionLabel.textContent = "Contexto";
    const descriptionText = document.createElement("p");
    descriptionText.textContent = metadataText(node);
    description.append(descriptionLabel, descriptionText);
    container.appendChild(description);

    const relations = state.visibleEdges.filter(
      (edge) => edge.source === node.id || edge.target === node.id
    );
    const relationSection = document.createElement("div");
    relationSection.className = "graph-inspector-section";
    const relationLabel = document.createElement("span");
    relationLabel.textContent = `Conexões (${relations.length})`;
    const list = document.createElement("div");
    list.className = "graph-relation-list";
    if (!relations.length) {
      const empty = document.createElement("p");
      empty.textContent = "Nenhuma conexão visível com os filtros atuais.";
      list.appendChild(empty);
    } else {
      for (const edge of relations) {
        const otherId = edge.source === node.id ? edge.target : edge.source;
        const other = state.visibleNodes.find((candidate) => candidate.id === otherId);
        if (!other) continue;
        const item = document.createElement("button");
        item.type = "button";
        item.className = "graph-relation";
        item.textContent = `${edge.label} · ${other.label}`;
        item.addEventListener("click", () => focusNode(other.id));
        list.appendChild(item);
      }
    }
    relationSection.append(relationLabel, list);
    container.appendChild(relationSection);
  }

  function applyTransform() {
    const stage = $("#knowledge-graph-stage");
    if (!stage) return;
    const { x, y, scale } = state.transform;
    stage.setAttribute("transform", `translate(${x} ${y}) scale(${scale})`);
  }

  function resetTransform() {
    state.transform = { x: 0, y: 0, scale: 1 };
    applyTransform();
  }

  function renderGraph() {
    const svg = $("#knowledge-graph-svg");
    if (!svg || !state.payload) return;
    const canvas = $("#graph-canvas-wrap");
    const width = Math.max(640, canvas?.clientWidth || 900);
    const height = Math.max(520, canvas?.clientHeight || 650);
    svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
    svg.replaceChildren();

    const scoped = scopedData();
    state.visibleNodes = scoped.nodes;
    state.visibleEdges = scoped.edges;
    if (state.selectedId && !state.visibleNodes.some((node) => node.id === state.selectedId)) {
      state.selectedId = null;
    }

    $("#graph-node-count").textContent = String(scoped.nodes.length);
    $("#graph-edge-count").textContent = String(scoped.edges.length);
    $("#graph-project-count").textContent = String(scoped.nodes.filter((node) => node.type === "project").length);

    const empty = $("#graph-empty");
    empty?.classList.toggle("hidden", scoped.nodes.length > 0);
    if (!scoped.nodes.length) {
      renderInspector(null);
      return;
    }

    layoutGraph(width, height);
    const stage = svgElement("g", { id: "knowledge-graph-stage" });
    svg.appendChild(stage);

    for (const edge of scoped.edges) {
      const source = state.positions.get(edge.source);
      const target = state.positions.get(edge.target);
      if (!source || !target) continue;
      const line = svgElement("line", {
        x1: source.x,
        y1: source.y,
        x2: target.x,
        y2: target.y,
        class: "graph-edge",
      });
      line.dataset.edgeId = edge.id;
      const title = svgElement("title");
      title.textContent = edge.label || edge.type;
      line.appendChild(title);
      stage.appendChild(line);
    }

    for (const node of scoped.nodes) {
      const point = state.positions.get(node.id);
      if (!point) continue;
      const group = svgElement("g", {
        class: `graph-node ${node.type}`,
        transform: `translate(${point.x} ${point.y})`,
        tabindex: 0,
        role: "button",
        "aria-label": `${labels[node.type] || node.type}: ${node.label}`,
      });
      group.dataset.nodeId = node.id;
      const importance = Number(node.importance || 0.5);
      const radius = (radii[node.type] || 9) * (0.88 + Math.min(1, importance) * 0.22);
      const circle = svgElement("circle", { cx: 0, cy: 0, r: radius });
      const text = svgElement("text", { x: radius + 7, y: 4 });
      text.textContent = shortLabel(node.label, node.type === "project" ? 42 : 31);
      const title = svgElement("title");
      title.textContent = `${labels[node.type] || node.type}: ${node.label}`;
      group.append(circle, text, title);
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
    }

    svg.addEventListener("click", () => focusNode(null));
    resetTransform();
    applyFocusClasses();
    renderInspector(state.selectedId ? scoped.nodes.find((node) => node.id === state.selectedId) : null);
  }

  async function reloadGraph({ quiet = false } = {}) {
    try {
      await fetchGraph();
      renderGraph();
    } catch (error) {
      if (!quiet) notify(`Falha ao carregar grafo: ${error.message}`, true);
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
    if (!state.loaded) await reloadGraph();
    else renderGraph();
  }

  $("#dashboard-view-button")?.addEventListener("click", showDashboard);
  $("#graph-view-button")?.addEventListener("click", showGraph);
  $("#graph-scope")?.addEventListener("change", renderGraph);
  document.querySelectorAll("[data-graph-type]").forEach((input) => {
    input.addEventListener("change", renderGraph);
  });
  $("#graph-reset")?.addEventListener("click", () => {
    state.selectedId = null;
    resetTransform();
    applyFocusClasses();
    renderInspector(null);
  });

  $("#refresh-button")?.addEventListener("click", () => {
    if (!$("#knowledge-graph-panel")?.classList.contains("hidden")) {
      window.setTimeout(() => reloadGraph({ quiet: true }), 100);
    }
  });

  const svg = $("#knowledge-graph-svg");
  if (svg) {
    svg.addEventListener(
      "wheel",
      (event) => {
        event.preventDefault();
        const factor = event.deltaY < 0 ? 1.12 : 0.89;
        state.transform.scale = Math.max(0.55, Math.min(2.8, state.transform.scale * factor));
        applyTransform();
      },
      { passive: false }
    );
    svg.addEventListener("pointerdown", (event) => {
      if (event.target.closest?.(".graph-node")) return;
      state.dragging = {
        pointerId: event.pointerId,
        startX: event.clientX,
        startY: event.clientY,
        originX: state.transform.x,
        originY: state.transform.y,
      };
      svg.setPointerCapture(event.pointerId);
      svg.classList.add("panning");
    });
    svg.addEventListener("pointermove", (event) => {
      if (!state.dragging || state.dragging.pointerId !== event.pointerId) return;
      state.transform.x = state.dragging.originX + event.clientX - state.dragging.startX;
      state.transform.y = state.dragging.originY + event.clientY - state.dragging.startY;
      applyTransform();
    });
    const stopPan = (event) => {
      if (!state.dragging || state.dragging.pointerId !== event.pointerId) return;
      state.dragging = null;
      svg.classList.remove("panning");
      try { svg.releasePointerCapture(event.pointerId); } catch {}
    };
    svg.addEventListener("pointerup", stopPan);
    svg.addEventListener("pointercancel", stopPan);
  }

  if (window.ResizeObserver) {
    const canvas = $("#graph-canvas-wrap");
    if (canvas) {
      let resizeTimer = null;
      new ResizeObserver(() => {
        if ($("#knowledge-graph-panel")?.classList.contains("hidden")) return;
        window.clearTimeout(resizeTimer);
        resizeTimer = window.setTimeout(renderGraph, 120);
      }).observe(canvas);
    }
  }
})();
