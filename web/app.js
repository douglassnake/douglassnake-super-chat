const state = {
  dashboard: null,
  selectedProjectId: null,
  overview: null,
  tasks: [],
  decisions: [],
  memories: [],
  currentDeltaId: null,
  editor: null,
};

const $ = (selector) => document.querySelector(selector);

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function safeUrl(value) {
  try {
    const url = new URL(value, window.location.origin);
    return ["http:", "https:"].includes(url.protocol) ? url.href : null;
  } catch {
    return null;
  }
}

function shortDate(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("pt-BR", { dateStyle: "short", timeStyle: "short" }).format(date);
}

function localDateTimeValue(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const offset = date.getTimezoneOffset() * 60000;
  return new Date(date.getTime() - offset).toISOString().slice(0, 16);
}

function healthClass(level) {
  return `health-${level || "healthy"}`;
}

function sourceFreshnessLabel(freshness) {
  const status = freshness?.status || "unknown";
  const labels = {
    fresh: "Atualizada",
    stale: "Atrasada",
    failed: "Falhou",
    never: "Nunca sincronizada",
    inactive: "Inativa",
    unknown: "Desconhecida",
  };
  return labels[status] || status;
}


function slugify(value) {
  return String(value || "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 160);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try {
      const body = await response.json();
      if (body.detail) detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {}
    throw new Error(detail);
  }
  if (response.status === 204) return null;
  return response.json();
}

function showToast(message, isError = false) {
  const toast = $("#toast");
  toast.textContent = message;
  toast.classList.toggle("error", isError);
  toast.classList.remove("hidden");
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => toast.classList.add("hidden"), 3500);
}

function setButtonBusy(button, busy, busyText = "Processando…") {
  if (!button) return;
  if (busy) {
    button.dataset.originalText = button.textContent;
    button.textContent = busyText;
    button.disabled = true;
  } else {
    button.textContent = button.dataset.originalText || button.textContent;
    button.disabled = false;
  }
}

function renderDashboard(data) {
  state.dashboard = data;
  $("#stat-projects").textContent = data.project_count;
  $("#stat-attention").textContent = data.attention_count;
  $("#stat-deltas").textContent = data.pending_delta_count;

  const projects = data.projects || [];
  const nav = $("#project-nav");
  const list = $("#project-list");

  if (!projects.length) {
    nav.innerHTML = '<div class="muted">Nenhum projeto.</div>';
    list.innerHTML = '<div class="empty-state"><h2>Nenhum projeto cadastrado</h2><p>Use “Novo projeto” para começar.</p></div>';
    $("#project-detail").classList.add("hidden");
    $("#empty-detail").classList.remove("hidden");
    return;
  }

  nav.innerHTML = projects.map((project) => `
    <button class="nav-item ${project.id === state.selectedProjectId ? "active" : ""}" data-project-id="${escapeHtml(project.id)}">
      <span>${escapeHtml(project.name)}</span>
      <span class="nav-health">${project.health.score}</span>
    </button>
  `).join("");

  list.innerHTML = projects.map((project) => `
    <button class="project-card ${project.id === state.selectedProjectId ? "active" : ""}" data-project-id="${escapeHtml(project.id)}">
      <div>
        <h3>${escapeHtml(project.name)}</h3>
        <p>${escapeHtml(project.status)} · ${project.health.metrics.open_tasks} tarefa(s) aberta(s)</p>
        <p>${escapeHtml(project.next_action || "Sem próxima ação")}</p>
      </div>
      <div class="project-score ${healthClass(project.health.level)}">${project.health.score}</div>
    </button>
  `).join("");

  document.querySelectorAll("[data-project-id]").forEach((button) => {
    button.addEventListener("click", () => selectProject(button.dataset.projectId));
  });
}

async function loadDashboard({ preserveSelection = true } = {}) {
  const previous = preserveSelection ? state.selectedProjectId : null;
  clearContextPreview();
  try {
    const data = await api("/dashboard");
    state.selectedProjectId = previous;
    renderDashboard(data);
    if (previous && data.projects.some((p) => p.id === previous)) {
      await loadOverview(previous);
    } else if (data.projects.length) {
      await selectProject(data.projects[0].id);
    }
  } catch (error) {
    showToast(`Falha ao carregar dashboard: ${error.message}`, true);
  }
}

function clearContextPreview() {
  const container = $("#context-result");
  container.innerHTML = "";
  container.classList.add("hidden");
}

async function selectProject(projectId) {
  if (state.selectedProjectId !== projectId) {
    clearContextPreview();
    $("#context-query").value = "";
  }
  state.selectedProjectId = projectId;
  if (state.dashboard) renderDashboard(state.dashboard);
  await loadOverview(projectId);
}

function renderOverview(data, tasks, decisions, memories) {
  state.overview = data;
  state.tasks = tasks;
  state.decisions = decisions;
  state.memories = memories;
  $("#empty-detail").classList.add("hidden");
  $("#project-detail").classList.remove("hidden");

  const project = data.project;
  const health = data.health;
  $("#detail-status").textContent = project.status;
  $("#detail-name").textContent = project.name;
  $("#detail-description").textContent = project.description || `Atualizado em ${shortDate(project.updated_at)}`;
  $("#detail-next-action").textContent = project.next_action || "Não definida";

  const ring = $("#detail-health");
  ring.textContent = health.score;
  ring.title = health.reasons.length ? health.reasons.map((r) => r.label).join(" · ") : "Sem alertas";
  ring.className = `health-ring ${healthClass(health.level)}`;

  const openTasks = tasks.filter((task) => !["done", "cancelled"].includes(task.status));
  $("#task-count").textContent = `${openTasks.length}`;
  $("#task-list").innerHTML = openTasks.length ? openTasks.map((task) => `
    <div class="item-card">
      <div class="item-card-head">
        <div>
          <strong>${escapeHtml(task.title)}</strong>
          <span>${escapeHtml(task.status)} · prioridade ${task.priority}${task.due_at ? ` · ${escapeHtml(shortDate(task.due_at))}` : ""}</span>
        </div>
        <div class="item-card-actions">
          <button class="mini-button" type="button" data-edit-task="${escapeHtml(task.id)}">Editar</button>
          <button class="mini-button success" type="button" data-complete-task="${escapeHtml(task.id)}">Concluir</button>
        </div>
      </div>
      ${task.description ? `<p>${escapeHtml(task.description)}</p>` : ""}
      ${task.blocked_by ? `<p>Bloqueado por: ${escapeHtml(task.blocked_by)}</p>` : ""}
    </div>
  `).join("") : '<div class="item-card"><span>Nenhuma tarefa aberta.</span></div>';

  $("#source-count").textContent = `${data.sources.length}`;
  $("#source-list").innerHTML = data.sources.length ? data.sources.map((source) => {
    const url = safeUrl(source.url);
    const title = url ? `<a href="${escapeHtml(url)}" target="_blank" rel="noreferrer">${escapeHtml(source.label)}</a>` : escapeHtml(source.label);
    const freshness = source.freshness || {};
    const freshnessClass = `source-freshness source-${escapeHtml(freshness.status || "unknown")}`;
    const freshnessDetail = freshness.last_synced_at ? ` · última sincronização ${escapeHtml(shortDate(freshness.last_synced_at))}` : "";
    return `<div class="item-card"><strong>${title}</strong><span>${escapeHtml(source.source_type)} · ${escapeHtml(source.external_id || "sem ID externo")}</span><span class="${freshnessClass}">${escapeHtml(sourceFreshnessLabel(freshness))}${freshnessDetail}</span></div>`;
  }).join("") : '<div class="item-card"><span>Nenhuma fonte vinculada.</span></div>';

  const activeDecisions = decisions.filter((decision) => decision.status === "active");
  $("#decision-count").textContent = `${activeDecisions.length} ativa(s)`;
  $("#decision-list").innerHTML = decisions.length ? decisions.slice(0, 10).map((decision) => `
    <div class="item-card">
      <div class="item-card-head">
        <div>
          <strong>${escapeHtml(decision.title)}</strong>
          <span>${escapeHtml(decision.status)} · ${escapeHtml(shortDate(decision.decided_at))}</span>
        </div>
        <button class="mini-button" type="button" data-edit-decision="${escapeHtml(decision.id)}">Editar</button>
      </div>
      <p>${escapeHtml(decision.body)}</p>
    </div>
  `).join("") : '<div class="item-card"><span>Nenhuma decisão registrada.</span></div>';

  $("#memory-count").textContent = `${memories.length}`;
  $("#memory-list").innerHTML = memories.length ? memories.slice(0, 10).map((item) => `
    <div class="item-card">
      <div class="item-card-head">
        <div>
          <strong>${escapeHtml(item.title || item.kind)}</strong>
          <span>${escapeHtml(item.kind)} · importância ${Number(item.importance).toFixed(2)}</span>
        </div>
        <button class="mini-button" type="button" data-edit-memory="${escapeHtml(item.id)}">Editar</button>
      </div>
      <p>${escapeHtml(item.content.length > 220 ? `${item.content.slice(0, 220)}…` : item.content)}</p>
    </div>
  `).join("") : '<div class="item-card"><span>Nenhuma memória registrada.</span></div>';

  const hasGithub = data.sources.some((source) => source.source_type === "github" && source.is_active);
  $("#github-sync-button").classList.toggle("hidden", !hasGithub);

  const pendingGithubDigest = data.pending_deltas.find((delta) =>
    String(delta.session_key || "").startsWith("github-digest:")
  );
  const digestButton = $("#github-digest-button");
  digestButton.classList.toggle("hidden", !pendingGithubDigest);
  if (pendingGithubDigest) {
    digestButton.dataset.deltaId = pendingGithubDigest.id;
  } else {
    delete digestButton.dataset.deltaId;
  }

  $("#delta-count").textContent = `${data.pending_deltas.length} pendente(s)`;
  $("#delta-list").innerHTML = data.pending_deltas.length ? data.pending_deltas.map((delta) => `
    <div class="item-card clickable" data-delta-id="${escapeHtml(delta.id)}">
      <strong>${escapeHtml(delta.session_key)}</strong>
      <p>${escapeHtml(delta.summary)}</p>
      <span>${escapeHtml(shortDate(delta.created_at))}${delta.status_change ? ` · status → ${escapeHtml(delta.status_change)}` : ""}</span>
    </div>
  `).join("") : '<div class="item-card"><span>Nenhum delta aguardando revisão.</span></div>';

  $("#event-list").innerHTML = data.events.length ? data.events.map((event) => {
    const url = safeUrl(event.url);
    const title = url ? `<a href="${escapeHtml(url)}" target="_blank" rel="noreferrer">${escapeHtml(event.title)}</a>` : escapeHtml(event.title);
    return `<div class="timeline-item"><strong>${title}</strong><span>${escapeHtml(event.event_type)} · ${escapeHtml(shortDate(event.occurred_at))}</span></div>`;
  }).join("") : '<div class="item-card"><span>Nenhum evento técnico registrado.</span></div>';

  document.querySelectorAll("[data-delta-id]").forEach((item) => {
    item.addEventListener("click", () => openDeltaPreview(item.dataset.deltaId));
  });
  document.querySelectorAll("[data-edit-task]").forEach((button) => {
    button.addEventListener("click", () => openTaskEditor(tasks.find((item) => item.id === button.dataset.editTask)));
  });
  document.querySelectorAll("[data-complete-task]").forEach((button) => {
    button.addEventListener("click", () => completeTask(button.dataset.completeTask));
  });
  document.querySelectorAll("[data-edit-decision]").forEach((button) => {
    button.addEventListener("click", () => openDecisionEditor(decisions.find((item) => item.id === button.dataset.editDecision)));
  });
  document.querySelectorAll("[data-edit-memory]").forEach((button) => {
    button.addEventListener("click", () => openMemoryEditor(memories.find((item) => item.id === button.dataset.editMemory)));
  });
}

async function loadOverview(projectId) {
  try {
    const encoded = encodeURIComponent(projectId);
    const [overview, tasks, decisions, memories] = await Promise.all([
      api(`/projects/${encoded}/overview`),
      api(`/projects/${encoded}/tasks`),
      api(`/projects/${encoded}/decisions`),
      api(`/projects/${encoded}/context-items`),
    ]);
    // A slow response from a previously selected project must not
    // overwrite the details of the newly selected project.
    if (state.selectedProjectId !== projectId) return;
    renderOverview(overview, tasks, decisions, memories);
  } catch (error) {
    if (state.selectedProjectId !== projectId) return;
    showToast(`Falha ao carregar projeto: ${error.message}`, true);
  }
}

async function continueProject() {
  if (!state.selectedProjectId) return;
  const projectId = state.selectedProjectId;
  const button = $("#continue-button");
  setButtonBusy(button, true, "Montando contexto…");
  try {
    const profile = $("#context-profile").value;
    const query = $("#context-query").value.trim() || "continuar projeto status próxima ação decisões tarefas pendências bloqueios commits PR issues actions";
    const params = new URLSearchParams({ profile, query });
    const packageData = await api(`/projects/${encodeURIComponent(projectId)}/continue?${params}`);
    if (state.selectedProjectId !== projectId || packageData.project.id !== projectId) return;
    renderContext(packageData);
  } catch (error) {
    showToast(`Falha ao montar contexto: ${error.message}`, true);
  } finally {
    setButtonBusy(button, false);
  }
}

function renderContext(data) {
  const container = $("#context-result");
  const budget = data.budget;
  const project = data.project;
  container.innerHTML = `
    <div class="context-current">
      <strong>Cadastro atual · ${escapeHtml(project.name)}</strong>
      <p>Próxima ação registrada: ${escapeHtml(project.next_action || "Não definida")}</p>
      <small>Contexto gerado em ${shortDate(data.generated_at)}. Registros históricos abaixo não substituem o cadastro atual.</small>
    </div>
    <div class="context-budget">
      <strong>${budget.estimated_tokens} / ${budget.max_tokens} tokens</strong>
      <span>${budget.selected_count} de ${budget.candidate_count} itens</span>
      <span>candidatos: ${budget.candidate_tokens} tokens</span>
    </div>
    ${data.items.length ? data.items.map((item) => `
      <div class="context-item">
        <strong>${escapeHtml(item.title || item.kind)} <span class="muted">· ${escapeHtml(item.kind)}${["summary", "status"].includes(item.kind) ? " · histórico" : ""}</span></strong>
        <p>${escapeHtml(item.content)}</p>
        <small class="muted">Fonte: ${escapeHtml(item.source_type)} · ${item.timestamp ? shortDate(item.timestamp) : "sem data informada"}</small>
      </div>
    `).join("") : '<div class="context-item"><p>Nenhum item adicional selecionado.</p></div>'}
  `;
  container.classList.remove("hidden");
}

async function syncGithub() {
  if (!state.selectedProjectId) return;
  const button = $("#github-sync-button");
  setButtonBusy(button, true, "Sincronizando…");
  try {
    const projectId = state.selectedProjectId;
    const result = await api(`/projects/${encodeURIComponent(projectId)}/github/sync`, { method: "POST" });
    if (state.selectedProjectId === projectId) clearContextPreview();
    showToast(`${result.created_events} evento(s) novo(s) do GitHub. Clique em Continuar projeto para atualizar o contexto.`);
    await loadDashboard();
  } catch (error) {
    showToast(`Falha no GitHub: ${error.message}`, true);
  } finally {
    setButtonBusy(button, false);
  }
}

function fieldHtml(field) {
  const full = field.full ? " full" : "";
  const required = field.required ? " required" : "";
  const value = field.value ?? "";
  const help = field.help ? `<span class="form-help">${escapeHtml(field.help)}</span>` : "";
  let control;
  if (field.type === "textarea") {
    control = `<textarea id="editor-${escapeHtml(field.name)}" name="${escapeHtml(field.name)}"${required}>${escapeHtml(value)}</textarea>`;
  } else if (field.type === "select") {
    control = `<select id="editor-${escapeHtml(field.name)}" name="${escapeHtml(field.name)}"${required}>${field.options.map((option) => {
      const optionValue = typeof option === "string" ? option : option.value;
      const optionLabel = typeof option === "string" ? option : option.label;
      return `<option value="${escapeHtml(optionValue)}"${String(optionValue) === String(value) ? " selected" : ""}>${escapeHtml(optionLabel)}</option>`;
    }).join("")}</select>`;
  } else {
    const min = field.min !== undefined ? ` min="${escapeHtml(field.min)}"` : "";
    const max = field.max !== undefined ? ` max="${escapeHtml(field.max)}"` : "";
    const step = field.step !== undefined ? ` step="${escapeHtml(field.step)}"` : "";
    control = `<input id="editor-${escapeHtml(field.name)}" name="${escapeHtml(field.name)}" type="${escapeHtml(field.type || "text")}" value="${escapeHtml(value)}"${min}${max}${step}${required} />`;
  }
  return `<div class="form-field${full}"><label for="editor-${escapeHtml(field.name)}">${escapeHtml(field.label)}</label>${control}${help}</div>`;
}

function openEditor(config) {
  state.editor = config;
  $("#editor-eyebrow").textContent = config.eyebrow || "CADASTRO";
  $("#editor-title").textContent = config.title;
  $("#editor-fields").innerHTML = config.fields.map(fieldHtml).join("");
  $("#editor-dialog").showModal();
}

function closeEditor() {
  state.editor = null;
  $("#editor-dialog").close();
}

function editorPayload() {
  const config = state.editor;
  const form = $("#editor-form");
  const payload = {};
  for (const field of config.fields) {
    const input = form.elements[field.name];
    let value = input.value;
    if (field.type === "number") {
      value = value === "" ? null : Number(value);
    } else if (field.type === "datetime-local") {
      value = value ? new Date(value).toISOString() : null;
    } else {
      value = value.trim();
      if (!field.required && value === "") value = null;
    }
    payload[field.name] = value;
  }
  return payload;
}

async function submitEditor(event) {
  event.preventDefault();
  if (!state.editor) return;
  const button = $("#editor-save");
  setButtonBusy(button, true, "Salvando…");
  try {
    await state.editor.submit(editorPayload());
    closeEditor();
    showToast(state.editor?.success || "Alteração salva.");
  } catch (error) {
    showToast(`Falha ao salvar: ${error.message}`, true);
  } finally {
    setButtonBusy(button, false);
  }
}

function projectFields(project = null) {
  const fields = [];
  if (!project) {
    fields.push({ name: "slug", label: "Slug", required: true, value: "", help: "Identificador estável, por exemplo: camara360." });
  }
  fields.push(
    { name: "name", label: "Nome", required: true, value: project?.name || "" },
    { name: "status", label: "Status", type: "select", required: true, value: project?.status || "active", options: ["active", "planning", "implementation", "paused", "done"] },
    { name: "priority", label: "Prioridade", type: "number", value: project?.priority ?? 0, min: -1000, max: 1000 },
    { name: "description", label: "Descrição", type: "textarea", full: true, value: project?.description || "" },
    { name: "next_action", label: "Próxima ação", type: "textarea", full: true, value: project?.next_action || "" },
  );
  return fields;
}

function openProjectEditor(project = null) {
  openEditor({
    eyebrow: "PROJETO",
    title: project ? "Editar projeto" : "Novo projeto",
    fields: projectFields(project),
    success: project ? "Projeto atualizado." : "Projeto criado.",
    submit: async (payload) => {
      if (!project && !payload.slug) payload.slug = slugify(payload.name);
      const saved = project
        ? await api(`/projects/${encodeURIComponent(project.id)}`, { method: "PATCH", body: JSON.stringify(payload) })
        : await api("/projects", { method: "POST", body: JSON.stringify(payload) });
      state.selectedProjectId = saved.id;
      await loadDashboard();
    },
  });
}

function openTaskEditor(task = null) {
  if (!state.selectedProjectId) return;
  openEditor({
    eyebrow: "TAREFA",
    title: task ? "Editar tarefa" : "Nova tarefa",
    fields: [
      { name: "title", label: "Título", required: true, full: true, value: task?.title || "" },
      { name: "status", label: "Status", type: "select", required: true, value: task?.status || "todo", options: ["todo", "in_progress", "blocked", "done", "cancelled"] },
      { name: "priority", label: "Prioridade", type: "number", value: task?.priority ?? 0, min: -1000, max: 1000 },
      { name: "due_at", label: "Prazo", type: "datetime-local", value: localDateTimeValue(task?.due_at) },
      { name: "blocked_by", label: "Bloqueado por", value: task?.blocked_by || "" },
      { name: "description", label: "Descrição", type: "textarea", full: true, value: task?.description || "" },
    ],
    success: task ? "Tarefa atualizada." : "Tarefa criada.",
    submit: async (payload) => {
      if (task) {
        await api(`/tasks/${encodeURIComponent(task.id)}`, { method: "PATCH", body: JSON.stringify(payload) });
      } else {
        await api(`/projects/${encodeURIComponent(state.selectedProjectId)}/tasks`, { method: "POST", body: JSON.stringify(payload) });
      }
      await loadDashboard();
    },
  });
}

async function completeTask(taskId) {
  const task = state.tasks.find((item) => item.id === taskId);
  if (!task) return;
  if (!window.confirm(`Concluir a tarefa “${task.title}”?`)) return;
  try {
    await api(`/tasks/${encodeURIComponent(taskId)}`, { method: "PATCH", body: JSON.stringify({ status: "done" }) });
    showToast("Tarefa concluída.");
    await loadDashboard();
  } catch (error) {
    showToast(`Falha ao concluir tarefa: ${error.message}`, true);
  }
}

function openDecisionEditor(decision = null) {
  if (!state.selectedProjectId) return;
  openEditor({
    eyebrow: "DECISÃO",
    title: decision ? "Editar decisão" : "Nova decisão",
    fields: [
      { name: "title", label: "Título", required: true, full: true, value: decision?.title || "" },
      { name: "status", label: "Status", type: "select", required: true, value: decision?.status || "active", options: ["active", "superseded", "archived"] },
      { name: "body", label: "Decisão", type: "textarea", required: true, full: true, value: decision?.body || "" },
      { name: "rationale", label: "Justificativa", type: "textarea", full: true, value: decision?.rationale || "" },
    ],
    success: decision ? "Decisão atualizada." : "Decisão registrada.",
    submit: async (payload) => {
      if (decision) {
        await api(`/decisions/${encodeURIComponent(decision.id)}`, { method: "PATCH", body: JSON.stringify(payload) });
      } else {
        await api(`/projects/${encodeURIComponent(state.selectedProjectId)}/decisions`, { method: "POST", body: JSON.stringify(payload) });
      }
      await loadDashboard();
    },
  });
}

function openMemoryEditor(item = null) {
  if (!state.selectedProjectId) return;
  openEditor({
    eyebrow: "MEMÓRIA",
    title: item ? "Editar memória" : "Nova memória operacional",
    fields: [
      { name: "kind", label: "Tipo", type: "select", required: true, value: item?.kind || "operational", options: ["fact", "note", "deployment", "architecture", "operational", "runbook", "document_excerpt"] },
      { name: "importance", label: "Importância", type: "number", value: item?.importance ?? 0.8, min: 0, max: 1, step: 0.05 },
      { name: "title", label: "Título", full: true, value: item?.title || "" },
      { name: "content", label: "Conteúdo", type: "textarea", required: true, full: true, value: item?.content || "" },
    ],
    success: item ? "Memória atualizada." : "Memória registrada.",
    submit: async (payload) => {
      payload.source_type = item?.source_type || "manual";
      if (!item) payload.generated = false;
      if (item) {
        await api(`/context-items/${encodeURIComponent(item.id)}`, { method: "PATCH", body: JSON.stringify(payload) });
      } else {
        await api(`/projects/${encodeURIComponent(state.selectedProjectId)}/context-items`, { method: "POST", body: JSON.stringify(payload) });
      }
      await loadDashboard();
    },
  });
}

function openSourceEditor() {
  if (!state.selectedProjectId) return;
  openEditor({
    eyebrow: "FONTE GITHUB",
    title: "Vincular repositório GitHub",
    fields: [
      { name: "repository", label: "Repositório", required: true, full: true, value: "", help: "Formato owner/repository. Não informe token aqui." },
      { name: "label", label: "Rótulo", full: true, value: "" },
    ],
    success: "Fonte GitHub vinculada.",
    submit: async (payload) => {
      const repository = payload.repository.replace(/^https?:\/\/github\.com\//, "").replace(/^\/+|\/+$/g, "");
      if (!repository.includes("/")) throw new Error("Use o formato owner/repository.");
      await api(`/projects/${encodeURIComponent(state.selectedProjectId)}/sources`, {
        method: "POST",
        body: JSON.stringify({
          source_type: "github",
          external_id: repository,
          url: `https://github.com/${repository}`,
          label: payload.label || repository,
          metadata_json: {},
          is_active: true,
        }),
      });
      await loadDashboard();
    },
  });
}

async function openDeltaPreview(deltaId) {
  try {
    const data = await api(`/session-deltas/${encodeURIComponent(deltaId)}/preview`);
    state.currentDeltaId = deltaId;
    const effects = data.effects;
    const delta = data.delta;
    $("#delta-preview").innerHTML = `
      <div class="preview-row"><span>Resumo</span><p>${escapeHtml(delta.summary)}</p></div>
      <div class="preview-row"><span>Decisões novas</span><strong>${effects.decisions_to_create}</strong></div>
      <div class="preview-row"><span>Tarefas novas</span><strong>${effects.tasks_to_create}</strong></div>
      <div class="preview-row"><span>Tarefas a concluir</span><strong>${effects.tasks_to_close.length}</strong>${effects.tasks_to_close.map((task) => `<p>${escapeHtml(task.title)}</p>`).join("")}</div>
      <div class="preview-row"><span>Mudança de status</span><strong>${escapeHtml(effects.status_change || "sem alteração")}</strong></div>
      <div class="preview-row"><span>Próxima ação</span><strong>${escapeHtml(effects.next_action || "sem alteração")}</strong></div>
      ${effects.missing_or_foreign_task_ids.length ? `<div class="preview-row"><span>Atenção</span><p>${effects.missing_or_foreign_task_ids.length} referência(s) de tarefa inválida(s).</p></div>` : ""}
    `;
    $("#apply-delta").disabled = effects.missing_or_foreign_task_ids.length > 0 || delta.status !== "pending";
    $("#discard-delta").disabled = delta.status !== "pending";
    $("#delta-dialog").showModal();
  } catch (error) {
    showToast(`Falha ao revisar delta: ${error.message}`, true);
  }
}

async function applyDelta() {
  if (!state.currentDeltaId) return;
  if (!window.confirm("Aplicar este SessionDelta à memória operacional?")) return;
  const button = $("#apply-delta");
  setButtonBusy(button, true, "Aplicando…");
  try {
    await api(`/session-deltas/${encodeURIComponent(state.currentDeltaId)}/apply`, { method: "POST" });
    $("#delta-dialog").close();
    showToast("SessionDelta aplicado à memória.");
    await loadDashboard();
  } catch (error) {
    showToast(`Falha ao aplicar delta: ${error.message}`, true);
  } finally {
    setButtonBusy(button, false);
  }
}

async function discardDelta() {
  if (!state.currentDeltaId) return;
  if (!window.confirm("Descartar este SessionDelta? Essa ação impede aplicação posterior.")) return;
  const button = $("#discard-delta");
  setButtonBusy(button, true, "Descartando…");
  try {
    await api(`/session-deltas/${encodeURIComponent(state.currentDeltaId)}/discard`, { method: "POST" });
    $("#delta-dialog").close();
    showToast("SessionDelta descartado.");
    await loadDashboard();
  } catch (error) {
    showToast(`Falha ao descartar delta: ${error.message}`, true);
  } finally {
    setButtonBusy(button, false);
  }
}

$("#refresh-button").addEventListener("click", () => loadDashboard());
$("#new-project-button").addEventListener("click", () => openProjectEditor());
$("#edit-project-button").addEventListener("click", () => state.overview && openProjectEditor(state.overview.project));
$("#new-task-button").addEventListener("click", () => openTaskEditor());
$("#new-decision-button").addEventListener("click", () => openDecisionEditor());
$("#new-memory-button").addEventListener("click", () => openMemoryEditor());
$("#new-source-button").addEventListener("click", openSourceEditor);
$("#continue-button").addEventListener("click", continueProject);
$("#github-sync-button").addEventListener("click", syncGithub);
$("#github-digest-button").addEventListener("click", (event) => {
  const deltaId = event.currentTarget.dataset.deltaId;
  if (deltaId) openDeltaPreview(deltaId);
});
$("#apply-delta").addEventListener("click", applyDelta);
$("#discard-delta").addEventListener("click", discardDelta);
$("#editor-form").addEventListener("submit", submitEditor);
$("#editor-close").addEventListener("click", closeEditor);
$("#editor-cancel").addEventListener("click", closeEditor);
$("#context-query").addEventListener("keydown", (event) => {
  if (event.key === "Enter") continueProject();
});

loadDashboard({ preserveSelection: false });
