const state = {
  dashboard: null,
  selectedProjectId: null,
  overview: null,
  currentDeltaId: null,
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

function healthClass(level) {
  return `health-${level || "healthy"}`;
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
      detail = body.detail || detail;
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
    list.innerHTML = '<div class="empty-state"><h2>Nenhum projeto cadastrado</h2><p>Cadastre um projeto pela API para começar.</p></div>';
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

async function selectProject(projectId) {
  state.selectedProjectId = projectId;
  if (state.dashboard) renderDashboard(state.dashboard);
  await loadOverview(projectId);
}

function renderOverview(data) {
  state.overview = data;
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

  $("#task-count").textContent = `${data.tasks.length}`;
  $("#task-list").innerHTML = data.tasks.length ? data.tasks.map((task) => `
    <div class="item-card">
      <strong>${escapeHtml(task.title)}</strong>
      <span>${escapeHtml(task.status)} · prioridade ${task.priority}${task.due_at ? ` · ${escapeHtml(shortDate(task.due_at))}` : ""}</span>
      ${task.blocked_by ? `<p>Bloqueado por: ${escapeHtml(task.blocked_by)}</p>` : ""}
    </div>
  `).join("") : '<div class="item-card"><span>Nenhuma tarefa aberta.</span></div>';

  $("#source-count").textContent = `${data.sources.length}`;
  $("#source-list").innerHTML = data.sources.length ? data.sources.map((source) => {
    const url = safeUrl(source.url);
    const title = url ? `<a href="${escapeHtml(url)}" target="_blank" rel="noreferrer">${escapeHtml(source.label)}</a>` : escapeHtml(source.label);
    return `<div class="item-card"><strong>${title}</strong><span>${escapeHtml(source.source_type)} · ${escapeHtml(source.external_id || "sem ID externo")}</span></div>`;
  }).join("") : '<div class="item-card"><span>Nenhuma fonte vinculada.</span></div>';

  const hasGithub = data.sources.some((source) => source.source_type === "github" && source.is_active);
  $("#github-sync-button").classList.toggle("hidden", !hasGithub);

  $("#delta-count").textContent = `${data.pending_deltas.length} pendente(s)`;
  $("#delta-list").innerHTML = data.pending_deltas.length ? data.pending_deltas.map((delta) => `
    <div class="item-card clickable" data-delta-id="${escapeHtml(delta.id)}">
      <strong>${escapeHtml(delta.session_key)}</strong>
      <p>${escapeHtml(delta.summary)}</p>
      <span>${escapeHtml(shortDate(delta.created_at))}${delta.status_change ? ` · status → ${escapeHtml(delta.status_change)}` : ""}</span>
    </div>
  `).join("") : '<div class="item-card"><span>Nenhum delta aguardando revisão.</span></div>';

  document.querySelectorAll("[data-delta-id]").forEach((item) => {
    item.addEventListener("click", () => openDeltaPreview(item.dataset.deltaId));
  });

  $("#event-list").innerHTML = data.events.length ? data.events.map((event) => {
    const url = safeUrl(event.url);
    const title = url ? `<a href="${escapeHtml(url)}" target="_blank" rel="noreferrer">${escapeHtml(event.title)}</a>` : escapeHtml(event.title);
    return `<div class="timeline-item"><strong>${title}</strong><span>${escapeHtml(event.event_type)} · ${escapeHtml(shortDate(event.occurred_at))}</span></div>`;
  }).join("") : '<div class="item-card"><span>Nenhum evento técnico registrado.</span></div>';
}

async function loadOverview(projectId) {
  try {
    const data = await api(`/projects/${encodeURIComponent(projectId)}/overview`);
    renderOverview(data);
  } catch (error) {
    showToast(`Falha ao carregar projeto: ${error.message}`, true);
  }
}

async function continueProject() {
  if (!state.selectedProjectId) return;
  const button = $("#continue-button");
  setButtonBusy(button, true, "Montando contexto…");
  try {
    const profile = $("#context-profile").value;
    const query = $("#context-query").value.trim() || "continuar projeto status próxima ação decisões tarefas pendências bloqueios commits PR issues actions";
    const params = new URLSearchParams({ profile, query });
    const packageData = await api(`/projects/${encodeURIComponent(state.selectedProjectId)}/continue?${params}`);
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
  container.innerHTML = `
    <div class="context-budget">
      <strong>${budget.estimated_tokens} / ${budget.max_tokens} tokens</strong>
      <span>${budget.selected_count} de ${budget.candidate_count} itens</span>
      <span>candidatos: ${budget.candidate_tokens} tokens</span>
    </div>
    ${data.items.length ? data.items.map((item) => `
      <div class="context-item">
        <strong>${escapeHtml(item.title || item.kind)} <span class="muted">· ${escapeHtml(item.kind)}</span></strong>
        <p>${escapeHtml(item.content)}</p>
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
    const result = await api(`/projects/${encodeURIComponent(state.selectedProjectId)}/github/sync`, { method: "POST" });
    showToast(`${result.created_events} evento(s) novo(s) do GitHub.`);
    await loadDashboard();
  } catch (error) {
    showToast(`Falha no GitHub: ${error.message}`, true);
  } finally {
    setButtonBusy(button, false);
  }
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
$("#continue-button").addEventListener("click", continueProject);
$("#github-sync-button").addEventListener("click", syncGithub);
$("#apply-delta").addEventListener("click", applyDelta);
$("#discard-delta").addEventListener("click", discardDelta);
$("#context-query").addEventListener("keydown", (event) => {
  if (event.key === "Enter") continueProject();
});

loadDashboard({ preserveSelection: false });
