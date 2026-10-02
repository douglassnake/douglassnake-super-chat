(() => {
  const SVG_NS = "http://www.w3.org/2000/svg";
  const $ = (selector) => document.querySelector(selector);
  const relationLabels = {
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
    has_document: "HAS_DOCUMENT",
    mentions: "MENTIONS",
    describes: "DESCRIBES",
  };

  function notify(message, isError = false) {
    const toast = $("#toast");
    if (!toast) return;
    toast.textContent = message;
    toast.classList.toggle("error", isError);
    toast.classList.remove("hidden");
    window.clearTimeout(notify.timer);
    notify.timer = window.setTimeout(() => toast.classList.add("hidden"), 4500);
  }

  function activeProjectId() {
    return document.querySelector(".nav-item.active")?.dataset.projectId || null;
  }

  async function api(path, options = {}) {
    const response = await window.fetch(path, {
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
      ...options,
    });
    if (!response.ok) {
      let detail = `HTTP ${response.status}`;
      try {
        const body = await response.json();
        detail = body.detail || detail;
      } catch {}
      throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
    }
    return response.status === 204 ? null : response.json();
  }

  function setBusy(button, busy, label) {
    if (!button) return;
    if (busy) {
      button.dataset.previousText = button.textContent;
      button.textContent = label || "Analisando…";
      button.disabled = true;
    } else {
      button.textContent = button.dataset.previousText || button.textContent;
      delete button.dataset.previousText;
      button.disabled = false;
    }
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function renderBatch(batch) {
    const content = $("#graph-suggestion-content");
    const suggestions = batch.suggestions || [];
    const cards = suggestions.map((item, index) => {
      const confidence = Math.round(Number(item.confidence || 0) * 100);
      const relation = relationLabels[item.relation_type] || item.relation_type.toUpperCase();
      const subject = item.subject_type === "entity" && item.subject_label
        ? `${escapeHtml(item.subject_label)} → `
        : "";
      return `
        <label class="graph-suggestion-card">
          <input type="checkbox" data-suggestion-index="${index}" checked />
          <div class="graph-suggestion-body">
            <div class="graph-suggestion-title">
              <strong>${subject}${escapeHtml(relation)} · ${escapeHtml(item.entity_name)}</strong>
              <span>${confidence}%</span>
            </div>
            <p>${escapeHtml(item.rationale)}</p>
            <small><b>Evidência:</b> ${escapeHtml(item.evidence)}</small>
            ${item.source_ref ? `<small>Fonte: ${escapeHtml(item.source_ref)}</small>` : ""}
          </div>
        </label>
      `;
    }).join("");

    content.innerHTML = `
      <div class="graph-suggestion-callout">
        <strong>Revisão humana obrigatória</strong>
        <p>Nenhuma conexão abaixo entra no grafo até você aplicar explicitamente as sugestões selecionadas.</p>
      </div>
      <div class="graph-suggestion-summary">${escapeHtml(batch.summary)}</div>
      <div class="graph-suggestion-list">
        ${cards || '<div class="graph-suggestion-empty">Nenhuma conexão nova encontrada. Relações existentes e duplicatas foram ignoradas.</div>'}
      </div>
    `;
    const apply = $("#graph-suggestion-apply");
    if (apply) apply.disabled = suggestions.length === 0;
  }

  function openBatch(batch) {
    const dialog = $("#graph-suggestion-dialog");
    dialog.dataset.batchId = batch.id;
    renderBatch(batch);
    if (!dialog.open) dialog.showModal();
  }

  async function pendingBatch(projectId) {
    const batches = await api(`/projects/${encodeURIComponent(projectId)}/graph/suggestions?status=pending`);
    return batches.find((batch) => (batch.suggestions || []).length > 0) || null;
  }

  async function syncButton() {
    const button = $("#graph-discover-relations");
    if (!button) return;
    const projectId = activeProjectId();
    if (!projectId) {
      button.textContent = "Descobrir conexões";
      return;
    }
    try {
      const pending = await pendingBatch(projectId);
      if (pending) {
        const count = (pending.suggestions || []).length;
        button.textContent = count ? `Revisar sugestões (${count})` : "Revisar análise";
        button.dataset.pendingBatchId = pending.id;
      } else {
        button.textContent = "Descobrir conexões";
        delete button.dataset.pendingBatchId;
      }
    } catch {
      button.textContent = "Descobrir conexões";
      delete button.dataset.pendingBatchId;
    }
  }

  let inspectorDirectionBusy = false;

  async function directionalizeInspectorRelations() {
    const inspector = $("#graph-inspector");
    const selected = document.querySelector("#knowledge-graph-svg .graph-node.selected");
    if (!inspector || !selected || inspectorDirectionBusy) return;
    const buttons = [...inspector.querySelectorAll(".graph-relation")]
      .filter((button) => button.dataset.directionApplied !== "true");
    if (!buttons.length) return;

    inspectorDirectionBusy = true;
    try {
      const graph = await api("/graph");
      const nodes = new Map((graph.nodes || []).map((node) => [node.id, node]));
      const selectedId = selected.dataset.nodeId;
      const edges = (graph.edges || []).filter(
        (edge) => edge.semantic && (edge.source === selectedId || edge.target === selectedId),
      );

      buttons.forEach((button) => {
        const raw = String(button.textContent || "").trim();
        const separator = raw.indexOf(" · ");
        if (separator < 0) return;
        const relationText = raw.slice(0, separator).trim();
        const otherLabel = raw.slice(separator + 3).trim();
        const edge = edges.find((candidate) => {
          const label = relationLabels[candidate.type] || String(candidate.label || candidate.type || "").toUpperCase();
          const otherId = candidate.source === selectedId ? candidate.target : candidate.source;
          return label === relationText && nodes.get(otherId)?.label === otherLabel;
        });
        if (!edge) return;

        button.textContent = edge.source === selectedId
          ? `${relationText} → ${otherLabel}`
          : `← ${relationText} · ${otherLabel}`;
        button.dataset.directionApplied = "true";
      });
    } catch {
      // Direction is presentation-only; the inspector remains usable if refresh fails.
    } finally {
      inspectorDirectionBusy = false;
    }
  }

  function svgElement(name, attrs = {}) {
    const element = document.createElementNS(SVG_NS, name);
    Object.entries(attrs).forEach(([key, value]) => element.setAttribute(key, String(value)));
    return element;
  }

  function ensureSemanticArrowMarker(svg) {
    let marker = svg.querySelector("#graph-semantic-arrow");
    if (marker) return marker;

    let defs = svg.querySelector("defs[data-semantic-arrow-defs='true']");
    if (!defs) {
      defs = svgElement("defs", { "data-semantic-arrow-defs": "true" });
      svg.insertBefore(defs, svg.firstChild);
    }

    marker = svgElement("marker", {
      id: "graph-semantic-arrow",
      viewBox: "0 0 8 8",
      refX: 8,
      refY: 4,
      markerWidth: 7,
      markerHeight: 7,
      markerUnits: "userSpaceOnUse",
      orient: "auto",
    });
    marker.appendChild(svgElement("path", {
      d: "M 0 0 L 8 4 L 0 8 z",
      fill: "rgba(101,214,232,.96)",
    }));
    defs.appendChild(marker);
    return marker;
  }

  function translatedPoint(node) {
    const transform = String(node?.getAttribute("transform") || "");
    const match = transform.match(/translate\(\s*([-+]?\d*\.?\d+)\s*[ ,]\s*([-+]?\d*\.?\d+)\s*\)/);
    if (!match) return null;
    const x = Number(match[1]);
    const y = Number(match[2]);
    return Number.isFinite(x) && Number.isFinite(y) ? { x, y } : null;
  }

  function targetNodeForLine(svg, x, y) {
    let closest = null;
    let distance = Number.POSITIVE_INFINITY;
    svg.querySelectorAll(".graph-node").forEach((node) => {
      const point = translatedPoint(node);
      if (!point) return;
      const candidateDistance = Math.hypot(point.x - x, point.y - y);
      if (candidateDistance < distance) {
        closest = node;
        distance = candidateDistance;
      }
    });
    return distance <= 1 ? closest : null;
  }

  function visualNodeRadius(node) {
    const circle = node?.querySelector("circle");
    if (!circle) return 10;
    const computed = Number.parseFloat(window.getComputedStyle(circle).getPropertyValue("r"));
    const declared = Number.parseFloat(circle.getAttribute("r"));
    return Number.isFinite(computed) && computed > 0
      ? computed
      : Number.isFinite(declared) && declared > 0
        ? declared
        : 10;
  }

  function decorateSemanticEdges() {
    const svg = $("#knowledge-graph-svg");
    if (!svg) return;
    const lines = [...svg.querySelectorAll(".graph-edge.semantic")]
      .filter((line) => line.dataset.arrowDecorated !== "true");
    if (!lines.length) return;

    ensureSemanticArrowMarker(svg);
    lines.forEach((line) => {
      const x1 = Number(line.getAttribute("x1"));
      const y1 = Number(line.getAttribute("y1"));
      const x2 = Number(line.getAttribute("x2"));
      const y2 = Number(line.getAttribute("y2"));
      if (![x1, y1, x2, y2].every(Number.isFinite)) return;

      const dx = x2 - x1;
      const dy = y2 - y1;
      const length = Math.hypot(dx, dy);
      const targetNode = targetNodeForLine(svg, x2, y2);
      const targetRadius = visualNodeRadius(targetNode);
      const offset = targetRadius + 4;
      if (length > offset + 8) {
        line.setAttribute("x2", String(x2 - (dx / length) * offset));
        line.setAttribute("y2", String(y2 - (dy / length) * offset));
      }
      line.setAttribute("marker-end", "url(#graph-semantic-arrow)");
      line.classList.add("directed");
      line.dataset.arrowDecorated = "true";
    });
  }

  const graphInspector = $("#graph-inspector");
  if (graphInspector && window.MutationObserver) {
    const inspectorObserver = new MutationObserver(() => {
      window.clearTimeout(directionalizeInspectorRelations.timer);
      directionalizeInspectorRelations.timer = window.setTimeout(directionalizeInspectorRelations, 0);
    });
    inspectorObserver.observe(graphInspector, { childList: true, subtree: true });
  }

  const graphSvg = $("#knowledge-graph-svg");
  if (graphSvg && window.MutationObserver) {
    const semanticEdgeObserver = new MutationObserver(() => {
      window.clearTimeout(decorateSemanticEdges.timer);
      decorateSemanticEdges.timer = window.setTimeout(decorateSemanticEdges, 0);
    });
    semanticEdgeObserver.observe(graphSvg, { childList: true, subtree: true });
    window.setTimeout(decorateSemanticEdges, 0);
  }

  $("#graph-discover-relations")?.addEventListener("click", async (event) => {
    const projectId = activeProjectId();
    if (!projectId) {
      notify("Selecione um projeto antes de descobrir conexões.", true);
      return;
    }
    const button = event.currentTarget;
    setBusy(button, true, "Analisando…");
    try {
      let batch = await pendingBatch(projectId);
      if (!batch) {
        batch = await api(`/projects/${encodeURIComponent(projectId)}/graph/suggestions`, { method: "POST" });
      }
      openBatch(batch);
    } catch (error) {
      notify(`Falha ao descobrir conexões: ${error.message}`, true);
    } finally {
      setBusy(button, false);
      await syncButton();
    }
  });

  $("#graph-suggestion-close")?.addEventListener("click", () => $("#graph-suggestion-dialog")?.close());
  $("#graph-suggestion-later")?.addEventListener("click", () => $("#graph-suggestion-dialog")?.close());

  $("#graph-suggestion-discard")?.addEventListener("click", async () => {
    const dialog = $("#graph-suggestion-dialog");
    const batchId = dialog?.dataset.batchId;
    if (!batchId) return;
    const button = $("#graph-suggestion-discard");
    setBusy(button, true, "Descartando…");
    try {
      await api(`/graph-suggestions/${encodeURIComponent(batchId)}/discard`, { method: "POST" });
      dialog.close();
      notify("Sugestões de conexão descartadas.");
      await syncButton();
    } catch (error) {
      notify(`Falha ao descartar sugestões: ${error.message}`, true);
    } finally {
      setBusy(button, false);
    }
  });

  $("#graph-suggestion-apply")?.addEventListener("click", async () => {
    const dialog = $("#graph-suggestion-dialog");
    const batchId = dialog?.dataset.batchId;
    if (!batchId) return;
    const selected = [...dialog.querySelectorAll("[data-suggestion-index]:checked")]
      .map((input) => Number(input.dataset.suggestionIndex))
      .filter(Number.isInteger);
    if (!selected.length) {
      notify("Selecione pelo menos uma conexão para aplicar.", true);
      return;
    }
    const button = $("#graph-suggestion-apply");
    setBusy(button, true, "Aplicando…");
    try {
      const result = await api(`/graph-suggestions/${encodeURIComponent(batchId)}/apply`, {
        method: "POST",
        body: JSON.stringify({ selected_indexes: selected }),
      });
      dialog.close();
      notify(`${result.applied_count} conexão(ões) aplicada(s); ${result.skipped_count} ignorada(s).`);
      $("#refresh-button")?.click();
      await syncButton();
    } catch (error) {
      notify(`Falha ao aplicar conexões: ${error.message}`, true);
    } finally {
      setBusy(button, false);
    }
  });

  $("#graph-view-button")?.addEventListener("click", () => window.setTimeout(syncButton, 100));
  $("#project-nav")?.addEventListener("click", () => window.setTimeout(syncButton, 120));
  $("#refresh-button")?.addEventListener("click", () => window.setTimeout(syncButton, 180));
  window.setTimeout(syncButton, 300);
})();
