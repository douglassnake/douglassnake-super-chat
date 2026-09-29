(() => {
  const $ = (selector) => document.querySelector(selector);

  function notify(message, isError = false) {
    const toast = $("#toast");
    if (!toast) return;
    toast.textContent = message;
    toast.classList.toggle("error", isError);
    toast.classList.remove("hidden");
    window.clearTimeout(notify.timer);
    notify.timer = window.setTimeout(() => toast.classList.add("hidden"), 4500);
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

  function activeProjectId() {
    return document.querySelector(".nav-item.active")?.dataset.projectId || null;
  }

  function normalizeRepository(value) {
    return String(value || "")
      .trim()
      .replace(/^https?:\/\/github\.com\//i, "")
      .replace(/^\/+|\/+$/g, "");
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

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function setBusy(button, busy, label) {
    if (!button) return;
    if (busy) {
      button.dataset.previousText = button.textContent;
      button.textContent = label || "Processando…";
      button.disabled = true;
    } else {
      button.textContent = button.dataset.previousText || button.textContent;
      delete button.dataset.previousText;
      button.disabled = false;
    }
  }

  async function refreshAndSelect(projectId) {
    $("#refresh-button")?.click();
    for (let attempt = 0; attempt < 30; attempt += 1) {
      await new Promise((resolve) => window.setTimeout(resolve, 100));
      const candidate = document.querySelector(`[data-project-id="${CSS.escape(projectId)}"]`);
      if (candidate) {
        candidate.click();
        return;
      }
    }
  }

  function renderReview(preview) {
    const delta = preview.delta;
    const decisions = delta.decisions_json || [];
    const tasks = delta.tasks_json || [];
    const content = $("#onboarding-review-content");
    content.innerHTML = `
      <div class="onboarding-callout">
        <strong>Revisão obrigatória</strong>
        <p>Nada abaixo vira memória permanente até você clicar em “Aplicar sugestões”.</p>
      </div>
      <div class="onboarding-review-section">
        <span>Resumo sugerido</span>
        <p>${escapeHtml(delta.summary)}</p>
      </div>
      <div class="onboarding-review-section">
        <span>Decisões sugeridas (${decisions.length})</span>
        ${decisions.length ? decisions.map((item) => `
          <div class="onboarding-suggestion">
            <strong>${escapeHtml(item.title)}</strong>
            <p>${escapeHtml(item.body)}</p>
            ${item.rationale ? `<small>${escapeHtml(item.rationale)}</small>` : ""}
            ${item.source_ref ? `<small>Fonte: ${escapeHtml(item.source_ref)}</small>` : ""}
          </div>
        `).join("") : "<p>Nenhuma decisão sugerida.</p>"}
      </div>
      <div class="onboarding-review-section">
        <span>Tarefas sugeridas (${tasks.length})</span>
        ${tasks.length ? tasks.map((item) => `
          <div class="onboarding-suggestion">
            <strong>${escapeHtml(item.title)}</strong>
            <p>${escapeHtml(item.description || "")}</p>
            <small>Prioridade ${escapeHtml(item.priority ?? 0)}</small>
            ${item.source_ref ? `<small>Fonte: ${escapeHtml(item.source_ref)}</small>` : ""}
          </div>
        `).join("") : "<p>Nenhuma tarefa sugerida.</p>"}
      </div>
      <div class="onboarding-review-section">
        <span>Próxima ação sugerida</span>
        <p>${escapeHtml(delta.next_action || "Sem alteração")}</p>
      </div>
    `;
  }

  async function openReview(deltaId) {
    const preview = await api(`/session-deltas/${encodeURIComponent(deltaId)}/preview`);
    $("#onboarding-review-dialog").dataset.deltaId = deltaId;
    renderReview(preview);
    $("#onboarding-review-dialog").showModal();
  }

  async function prepareOnboarding(projectId) {
    const result = await api(`/projects/${encodeURIComponent(projectId)}/github/onboarding`, {
      method: "POST",
    });
    await refreshAndSelect(projectId);
    await openReview(result.delta.id);
    return result;
  }

  function syncOnboardingVisibility() {
    const syncButton = $("#github-sync-button");
    const onboardingButton = $("#github-onboarding-button");
    if (!syncButton || !onboardingButton) return;
    onboardingButton.classList.toggle("hidden", syncButton.classList.contains("hidden"));
  }

  const syncButton = $("#github-sync-button");
  if (syncButton) {
    new MutationObserver(syncOnboardingVisibility).observe(syncButton, {
      attributes: true,
      attributeFilter: ["class"],
    });
    syncOnboardingVisibility();
  }

  $("#github-onboarding-button")?.addEventListener("click", async (event) => {
    const projectId = activeProjectId();
    if (!projectId) return;
    const button = event.currentTarget;
    setBusy(button, true, "Preparando…");
    try {
      const result = await prepareOnboarding(projectId);
      notify(`${result.suggested_tasks} tarefa(s) e ${result.suggested_decisions} decisão(ões) aguardando revisão.`);
    } catch (error) {
      notify(`Falha no onboarding GitHub: ${error.message}`, true);
    } finally {
      setBusy(button, false);
    }
  });

  $("#smart-project-button")?.addEventListener("click", () => {
    const form = $("#smart-project-form");
    const slug = $("#smart-project-slug");
    form.reset();
    delete slug.dataset.touched;
    $("#smart-project-status").value = "active";
    $("#smart-project-priority").value = "80";
    $("#smart-project-dialog").showModal();
    $("#smart-project-name").focus();
  });

  $("#smart-project-close")?.addEventListener("click", () => $("#smart-project-dialog").close());
  $("#smart-project-cancel")?.addEventListener("click", () => $("#smart-project-dialog").close());
  $("#onboarding-review-close")?.addEventListener("click", () => $("#onboarding-review-dialog").close());
  $("#onboarding-review-cancel")?.addEventListener("click", () => $("#onboarding-review-dialog").close());

  $("#smart-project-name")?.addEventListener("input", (event) => {
    const slug = $("#smart-project-slug");
    if (!slug.dataset.touched) slug.value = slugify(event.target.value);
  });
  $("#smart-project-slug")?.addEventListener("input", (event) => {
    event.currentTarget.dataset.touched = "1";
  });

  $("#smart-project-form")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = $("#smart-project-save");
    setBusy(button, true, "Criando…");
    let createdProject = null;
    try {
      const name = $("#smart-project-name").value.trim();
      const slug = $("#smart-project-slug").value.trim() || slugify(name);
      const repository = normalizeRepository($("#smart-project-repository").value);
      if (repository && !repository.includes("/")) {
        throw new Error("Repositório GitHub deve usar owner/repository.");
      }

      createdProject = await api("/projects", {
        method: "POST",
        body: JSON.stringify({
          slug,
          name,
          description: $("#smart-project-description").value.trim() || null,
          status: $("#smart-project-status").value,
          priority: Number($("#smart-project-priority").value || 0),
          next_action: $("#smart-project-next-action").value.trim() || null,
        }),
      });

      if (repository) {
        await api(`/projects/${encodeURIComponent(createdProject.id)}/sources`, {
          method: "POST",
          body: JSON.stringify({
            source_type: "github",
            external_id: repository,
            url: `https://github.com/${repository}`,
            label: `Repositório principal · ${repository}`,
            metadata_json: {},
            is_active: true,
          }),
        });
      }

      $("#smart-project-dialog").close();
      await refreshAndSelect(createdProject.id);

      if (repository) {
        const result = await prepareOnboarding(createdProject.id);
        notify(`Projeto criado. ${result.suggested_tasks} sugestão(ões) de tarefa aguardam sua revisão.`);
      } else {
        notify("Projeto criado. Você pode vincular GitHub depois pela seção Fontes.");
      }
    } catch (error) {
      const prefix = createdProject ? "Projeto criado, mas o onboarding não foi concluído" : "Falha ao criar projeto";
      notify(`${prefix}: ${error.message}`, true);
      if (createdProject) await refreshAndSelect(createdProject.id);
    } finally {
      setBusy(button, false);
    }
  });

  $("#onboarding-apply")?.addEventListener("click", async () => {
    const dialog = $("#onboarding-review-dialog");
    const deltaId = dialog.dataset.deltaId;
    if (!deltaId) return;
    const button = $("#onboarding-apply");
    setBusy(button, true, "Aplicando…");
    try {
      await api(`/session-deltas/${encodeURIComponent(deltaId)}/apply`, { method: "POST" });
      dialog.close();
      notify("Sugestões aprovadas e incorporadas à memória do projeto.");
      $("#refresh-button")?.click();
    } catch (error) {
      notify(`Falha ao aplicar onboarding: ${error.message}`, true);
    } finally {
      setBusy(button, false);
    }
  });

  $("#onboarding-discard")?.addEventListener("click", async () => {
    const dialog = $("#onboarding-review-dialog");
    const deltaId = dialog.dataset.deltaId;
    if (!deltaId) return;
    const button = $("#onboarding-discard");
    setBusy(button, true, "Descartando…");
    try {
      await api(`/session-deltas/${encodeURIComponent(deltaId)}/discard`, { method: "POST" });
      dialog.close();
      notify("Sugestões de onboarding descartadas.");
      $("#refresh-button")?.click();
    } catch (error) {
      notify(`Falha ao descartar onboarding: ${error.message}`, true);
    } finally {
      setBusy(button, false);
    }
  });
})();
