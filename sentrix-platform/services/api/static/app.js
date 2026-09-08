(() => {
  "use strict";

  const state = {
    user: null,
    orgs: [],
    org: null,
    overview: null,
    projects: [],
    bots: [],
    envs: [],
    builds: [],
    releases: [],
    deployments: [],
    wizardStep: 1,
  };

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  const byId = (id) => document.getElementById(id);

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function shortId(value, n = 8) {
    if (!value) return "—";
    const text = String(value);
    return text.length <= n ? text : `${text.slice(0, n)}…`;
  }

  function formatDate(value) {
    if (!value) return "—";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "—";
    return new Intl.DateTimeFormat("fr-FR", {
      day: "2-digit",
      month: "short",
      hour: "2-digit",
      minute: "2-digit",
    }).format(date);
  }

  function formatBytes(bytes) {
    const value = Number(bytes || 0);
    if (value < 1024) return `${value} B`;
    const units = ["KB", "MB", "GB", "TB"];
    let amount = value / 1024;
    let unit = units[0];
    for (let index = 1; index < units.length && amount >= 1024; index += 1) {
      amount /= 1024;
      unit = units[index];
    }
    return `${amount >= 10 ? amount.toFixed(0) : amount.toFixed(1)} ${unit}`;
  }

  function statusClass(status) {
    const text = String(status || "").toLowerCase();
    if (["success", "succeeded", "healthy", "running", "live", "active"].includes(text)) {
      return "good";
    }
    if (["failed", "error", "rejected", "crashed", "unhealthy"].includes(text)) {
      return "bad";
    }
    if (["queued", "pending", "building", "scanning", "deploying", "stopping"].includes(text)) {
      return "warn";
    }
    return "";
  }

  function badge(status) {
    return `<span class="status-badge ${statusClass(status)}">${escapeHtml(status || "unknown")}</span>`;
  }

  function toast(message, kind = "good") {
    const item = document.createElement("div");
    item.className = `toast ${kind}`;
    item.textContent = message;
    byId("toast-root").appendChild(item);
    window.setTimeout(() => item.remove(), 4200);
  }

  async function api(path, options = {}) {
    const headers = { Accept: "application/json", ...(options.headers || {}) };
    if (options.body && !headers["Content-Type"]) headers["Content-Type"] = "application/json";
    const response = await fetch(path, {
      credentials: "same-origin",
      ...options,
      headers,
    });
    if (response.status === 204) return null;
    let payload = null;
    try {
      payload = await response.json();
    } catch {
      payload = null;
    }
    if (!response.ok) {
      const detail = payload?.detail;
      const message = typeof detail === "string"
        ? detail
        : detail?.[0]?.msg || `Erreur HTTP ${response.status}`;
      const error = new Error(message);
      error.status = response.status;
      throw error;
    }
    return payload;
  }

  function orgPath(suffix = "") {
    if (!state.org) throw new Error("Aucune organisation active");
    return `/v1/orgs/${state.org.id}${suffix}`;
  }

  function showScreen(name) {
    for (const id of ["boot-screen", "auth-screen", "onboarding-screen", "dashboard"]) {
      byId(id).classList.add("hidden");
    }
    byId(name).classList.remove("hidden");
  }

  function userInitial() {
    return String(state.user?.display_name || "S").trim().slice(0, 1).toUpperCase() || "S";
  }

  async function boot() {
    try {
      state.user = await api("/v1/auth/me");
    } catch (error) {
      if (error.status === 401) {
        showScreen("auth-screen");
        return;
      }
      showScreen("auth-screen");
      toast(`Control plane indisponible : ${error.message}`, "bad");
      return;
    }

    try {
      state.orgs = await api("/v1/auth/organizations");
    } catch (error) {
      toast(`Impossible de charger les organisations : ${error.message}`, "bad");
      showScreen("auth-screen");
      return;
    }

    if (!state.orgs.length) {
      showScreen("onboarding-screen");
      bindUserIdentity();
      return;
    }

    const saved = localStorage.getItem("sentrix_hosting_org");
    state.org = state.orgs.find((org) => org.id === saved) || state.orgs[0];
    bindUserIdentity();
    populateOrgSwitcher();
    showScreen("dashboard");
    await refreshAll();
  }

  function bindUserIdentity() {
    const name = state.user?.display_name || "Utilisateur";
    const email = state.user?.email || `Discord ${state.user?.discord_user_id || ""}`;
    if (byId("user-name")) byId("user-name").textContent = name;
    if (byId("user-email")) byId("user-email").textContent = email;
    if (byId("welcome-name")) byId("welcome-name").textContent = name.split(/\s+/)[0];
    if (byId("user-avatar")) byId("user-avatar").textContent = userInitial();
  }

  function populateOrgSwitcher() {
    const select = byId("org-select");
    select.innerHTML = state.orgs
      .map((org) => `<option value="${org.id}">${escapeHtml(org.name)}</option>`)
      .join("");
    select.value = state.org.id;
    renderSettings();
  }

  async function refreshAll() {
    byId("refresh-btn").disabled = true;
    try {
      const [overview, projects, bots, envs, builds, releases, deployments] = await Promise.all([
        api(orgPath("/hosting/overview")),
        api(orgPath("/projects")),
        api(orgPath("/bots")),
        api(orgPath("/environments")),
        api(orgPath("/hosting/builds?limit=50")),
        api(orgPath("/hosting/releases?limit=50")),
        api(orgPath("/hosting/deployments?limit=50")),
      ]);
      Object.assign(state, { overview, projects, bots, envs, builds, releases, deployments });
      renderAll();
    } catch (error) {
      if (error.status === 401) {
        showScreen("auth-screen");
        return;
      }
      toast(`Actualisation impossible : ${error.message}`, "bad");
    } finally {
      byId("refresh-btn").disabled = false;
    }
  }

  function renderAll() {
    renderOverview();
    renderProjects();
    renderDeploymentView();
    renderRuntime();
    populateEnvironmentSelects();
    renderSettings();
    void renderUsage();
    void renderSecrets();
  }

  function renderOverview() {
    const o = state.overview || {};
    byId("m-projects").textContent = o.projects ?? 0;
    byId("m-bots").textContent = o.bots ?? 0;
    byId("m-envs").textContent = o.environments ?? 0;
    byId("m-running").textContent = o.running_instances ?? 0;

    const recent = state.deployments.slice(0, 5);
    byId("overview-deployments").innerHTML = recent.length
      ? recent.map((deployment) => {
          const env = state.envs.find((item) => item.id === deployment.environment_id);
          return `<div class="list-row"><div class="primary"><span class="item-icon">↗</span><div><b>${escapeHtml(envLabel(env))}</b><small>${formatDate(deployment.created_at)} • ${shortId(deployment.release_id, 12)}</small></div></div>${badge(deployment.status)}</div>`;
        }).join("")
      : `<div class="empty-mini">Aucun déploiement pour le moment.</div>`;

    byId("overview-envs").innerHTML = state.envs.length
      ? state.envs.slice(0, 5).map((env) => `<div class="list-row"><div class="primary"><span class="item-icon">◫</span><div><b>${escapeHtml(envLabel(env))}</b><small>${escapeHtml(env.runtime_mode)} • ${escapeHtml(env.secret_provider)}</small></div></div>${badge(env.status)}</div>`).join("")
      : `<div class="empty-mini">Créez votre premier environnement.</div>`;
  }

  function envLabel(env) {
    if (!env) return "Environnement";
    const bot = state.bots.find((item) => item.id === env.bot_id);
    return `${bot?.name || "Bot"} / ${env.kind}`;
  }

  function renderProjects() {
    const root = byId("projects-grid");
    if (!state.projects.length) {
      root.innerHTML = `<div class="empty-state"><span>◇</span><h3>Aucun projet</h3><p>Créez un projet pour commencer à héberger un bot.</p></div>`;
      return;
    }
    root.innerHTML = state.projects.map((project) => {
      const bots = state.bots.filter((bot) => bot.project_id === project.id);
      const botRows = bots.length
        ? bots.map((bot) => {
            const count = state.envs.filter((env) => env.bot_id === bot.id).length;
            return `<div class="mini-resource"><span>${escapeHtml(bot.name)} · ${escapeHtml(bot.library)}</span><code>${count} env.</code></div>`;
          }).join("")
        : `<div class="mini-resource"><span>Aucun bot</span><code>—</code></div>`;
      return `<article class="resource-card"><div class="resource-card-head"><span class="item-icon">◇</span>${badge(project.status)}</div><h3>${escapeHtml(project.name)}</h3><p>${escapeHtml(project.repo_full_name || "Aucun dépôt GitHub associé")}</p><div class="resource-meta"><div><small>BRANCHE</small><b>${escapeHtml(project.default_branch)}</b></div><div><small>CRÉÉ</small><b>${formatDate(project.created_at)}</b></div></div><div class="resource-bots">${botRows}</div></article>`;
    }).join("");
  }

  function renderDeploymentView() {
    const o = state.overview || {};
    byId("stat-queued").textContent = o.queued_builds ?? 0;
    byId("stat-deploying").textContent = o.active_deployments ?? 0;
    byId("stat-release").textContent = state.releases.length
      ? shortId(state.releases[0].id, 10)
      : "—";

    const buildRoot = byId("builds-table");
    if (!state.builds.length) {
      buildRoot.innerHTML = `<div class="empty-mini">Aucun build.</div>`;
    } else {
      buildRoot.innerHTML = `<table class="data-table"><thead><tr><th>ENVIRONNEMENT</th><th>COMMIT</th><th>ÉTAT</th><th>IMAGE</th><th>DATE</th></tr></thead><tbody>${state.builds.map((build) => {
        const env = state.envs.find((item) => item.id === build.environment_id);
        return `<tr><td>${escapeHtml(envLabel(env))}</td><td class="mono">${escapeHtml(shortId(build.commit_sha, 12))}</td><td>${badge(build.status)}</td><td class="mono">${escapeHtml(build.image_digest ? shortId(build.image_digest, 18) : build.error ? shortId(build.error, 24) : "—")}</td><td>${formatDate(build.created_at)}</td></tr>`;
      }).join("")}</tbody></table>`;
    }

    const deploymentRoot = byId("deployments-table");
    const releaseMap = new Map(state.releases.map((release) => [release.id, release]));
    if (!state.deployments.length && !state.releases.length) {
      deploymentRoot.innerHTML = `<div class="empty-mini">Aucun déploiement ou release.</div>`;
    } else {
      const deployedReleaseIds = new Set(state.deployments.map((d) => d.release_id));
      const deployRows = state.deployments.map((deployment) => {
        const env = state.envs.find((item) => item.id === deployment.environment_id);
        return `<tr><td>${escapeHtml(envLabel(env))}</td><td class="mono">${escapeHtml(shortId(deployment.release_id, 12))}</td><td>${badge(deployment.status)}</td><td>${escapeHtml(deployment.step || "—")}</td><td>${formatDate(deployment.created_at)}</td><td>—</td></tr>`;
      });
      const readyRows = state.releases
        .filter((release) => !deployedReleaseIds.has(release.id))
        .slice(0, 20)
        .map((release) => {
          const env = state.envs.find((item) => item.id === release.environment_id);
          const older = state.releases.some((candidate) => candidate.environment_id === release.environment_id && new Date(candidate.created_at) > new Date(release.created_at));
          return `<tr><td>${escapeHtml(envLabel(env))}</td><td class="mono">${escapeHtml(shortId(release.id, 12))}</td><td>${badge("ready")}</td><td>${older ? "rollback possible" : "release prête"}</td><td>${formatDate(release.created_at)}</td><td><button class="table-action" data-deploy-release="${release.id}">${older ? "Rollback" : "Déployer"}</button></td></tr>`;
        });
      const rows = [...deployRows, ...readyRows];
      deploymentRoot.innerHTML = `<table class="data-table"><thead><tr><th>ENVIRONNEMENT</th><th>RELEASE</th><th>ÉTAT</th><th>ÉTAPE</th><th>DATE</th><th>ACTION</th></tr></thead><tbody>${rows.join("")}</tbody></table>`;
      $$('[data-deploy-release]', deploymentRoot).forEach((button) => {
        button.addEventListener("click", () => void deployRelease(button.dataset.deployRelease));
      });
      void releaseMap;
    }
  }

  function renderRuntime() {
    const root = byId("runtime-grid");
    if (!state.envs.length) {
      root.innerHTML = `<div class="empty-state"><span>◫</span><h3>Aucun runtime</h3><p>Créez un projet et un environnement.</p></div>`;
      return;
    }
    root.innerHTML = state.envs.map((env) => {
      const bot = state.bots.find((item) => item.id === env.bot_id);
      return `<article class="runtime-card"><div class="runtime-top"><span class="env-symbol">◫</span>${badge(env.status)}</div><h3>${escapeHtml(envLabel(env))}</h3><p>${escapeHtml(bot?.library || "runtime")} • ${escapeHtml(env.runtime_mode)}</p><div class="runtime-details"><div><span>Application Discord</span><b class="mono">${escapeHtml(env.discord_application_id || "non définie")}</b></div><div><span>Secrets</span><b>${escapeHtml(env.secret_provider)}</b></div><div><span>Vérification</span><b>${env.discord_application_verified_at ? "vérifiée" : "en attente"}</b></div></div><div class="runtime-actions"><button class="btn btn-secondary" data-runtime="start" data-env="${env.id}">Start</button><button class="btn btn-secondary" data-runtime="restart" data-env="${env.id}">Restart</button><button class="btn btn-danger" data-runtime="stop" data-env="${env.id}">Stop</button></div></article>`;
    }).join("");
    $$('[data-runtime]', root).forEach((button) => {
      button.addEventListener("click", () => void runtimeAction(button.dataset.env, button.dataset.runtime));
    });
  }

  function populateEnvironmentSelects() {
    const markup = state.envs.map((env) => `<option value="${env.id}">${escapeHtml(envLabel(env))}</option>`).join("");
    for (const id of ["build-env", "usage-env-select", "secret-env-select"]) {
      const select = byId(id);
      const old = select.value;
      select.innerHTML = markup || `<option value="">Aucun environnement</option>`;
      if (old && state.envs.some((env) => env.id === old)) select.value = old;
    }
    const filter = byId("deploy-env-filter");
    const oldFilter = filter.value;
    filter.innerHTML = `<option value="">Tous les environnements</option>${markup}`;
    filter.value = state.envs.some((env) => env.id === oldFilter) ? oldFilter : "";
  }

  async function renderUsage() {
    const select = byId("usage-env-select");
    const envId = select.value || state.envs[0]?.id;
    if (!envId) {
      setUsageEmpty();
      return;
    }
    try {
      const samples = await api(orgPath(`/hosting/environments/${envId}/usage?limit=80`));
      const latest = samples[0];
      byId("u-cpu").textContent = latest ? latest.cpu_millis : "—";
      byId("u-memory").textContent = latest ? formatBytes(latest.memory_bytes) : "—";
      byId("u-egress").textContent = latest ? formatBytes(latest.egress_bytes) : "—";
      byId("u-logs").textContent = latest ? formatBytes(latest.log_bytes) : "—";
      byId("usage-samples-count").textContent = `${samples.length} échantillon${samples.length > 1 ? "s" : ""}`;
      renderUsageChart(samples);
    } catch (error) {
      setUsageEmpty();
      toast(`Métriques : ${error.message}`, "bad");
    }
  }

  function setUsageEmpty() {
    for (const id of ["u-cpu", "u-memory", "u-egress", "u-logs"]) byId(id).textContent = "—";
    byId("usage-samples-count").textContent = "0 échantillon";
    renderUsageChart([]);
  }

  function renderUsageChart(samples) {
    const root = byId("usage-chart");
    if (!samples.length) {
      root.innerHTML = `<div class="empty-state"><span>◌</span><h3>Aucune donnée</h3><p>Les métriques apparaîtront lorsque le worker enverra des échantillons.</p></div>`;
      return;
    }
    const chronological = [...samples].reverse();
    const max = Math.max(...chronological.map((sample) => Number(sample.memory_bytes || 0)), 1);
    root.innerHTML = chronological.map((sample) => {
      const height = Math.max(4, (Number(sample.memory_bytes || 0) / max) * 100);
      return `<i class="chart-bar" style="height:${height}%" title="${escapeHtml(formatDate(sample.sampled_at))} — ${escapeHtml(formatBytes(sample.memory_bytes))}"></i>`;
    }).join("");
  }

  async function renderSecrets() {
    const select = byId("secret-env-select");
    const envId = select.value || state.envs[0]?.id;
    const root = byId("secrets-table");
    if (!envId) {
      root.innerHTML = `<div class="empty-mini">Aucun environnement.</div>`;
      return;
    }
    try {
      const secrets = await api(orgPath(`/hosting/environments/${envId}/secrets`));
      if (!secrets.length) {
        root.innerHTML = `<div class="empty-mini">Aucun secret enregistré. L'injection sécurisée sera disponible lorsque le worker KMS sera connecté.</div>`;
        return;
      }
      root.innerHTML = `<table class="data-table"><thead><tr><th>NOM</th><th>PROVIDER</th><th>VERSION</th><th>EMPREINTE</th><th>ROTATION</th></tr></thead><tbody>${secrets.map((secret) => `<tr><td class="mono">${escapeHtml(secret.name)}</td><td>${escapeHtml(secret.provider)}</td><td>v${escapeHtml(secret.version)}</td><td class="mono">${escapeHtml(secret.fingerprint)}</td><td>${formatDate(secret.rotated_at || secret.created_at)}</td></tr>`).join("")}</tbody></table>`;
    } catch (error) {
      root.innerHTML = `<div class="empty-mini">Métadonnées indisponibles.</div>`;
      if (error.status !== 403) toast(`Secrets : ${error.message}`, "bad");
    }
  }

  function renderSettings() {
    if (!state.org) return;
    byId("settings-org-name").textContent = state.org.name;
    byId("settings-org-slug").textContent = state.org.slug;
    byId("settings-org-role").textContent = state.org.role;
    byId("settings-org-id").textContent = state.org.id;
  }

  async function createOrganization(event) {
    event.preventDefault();
    const name = byId("org-name").value.trim();
    const slug = byId("org-slug").value.trim().toLowerCase();
    try {
      const org = await api("/v1/auth/organizations", {
        method: "POST",
        body: JSON.stringify({ name, slug }),
      });
      state.orgs = [org];
      state.org = org;
      localStorage.setItem("sentrix_hosting_org", org.id);
      populateOrgSwitcher();
      showScreen("dashboard");
      toast("Organisation créée.");
      await refreshAll();
    } catch (error) {
      toast(error.message, "bad");
    }
  }

  function autoSlug() {
    const value = byId("org-name").value
      .normalize("NFD").replace(/[\u0300-\u036f]/g, "")
      .toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 48);
    if (!byId("org-slug").dataset.edited) byId("org-slug").value = value;
  }

  function switchView(name) {
    $$(".view").forEach((view) => view.classList.toggle("active", view.id === `view-${name}`));
    $$(".side-nav button").forEach((button) => button.classList.toggle("active", button.dataset.view === name));
    const labels = {
      overview: "Vue d'ensemble", projects: "Projets & bots", deployments: "Déploiements",
      runtime: "Runtime", observability: "Observabilité", secrets: "Secrets", settings: "Configuration",
    };
    byId("page-title").textContent = labels[name] || "SentriX Hosting";
    byId("breadcrumb").textContent = `SENTRIX / ${name.toUpperCase()}`;
    byId("new-project-btn").style.display = ["overview", "projects"].includes(name) ? "inline-flex" : "none";
    $(".sidebar").classList.remove("open");
    if (name === "observability") void renderUsage();
    if (name === "secrets") void renderSecrets();
  }

  function openProjectDialog() {
    state.wizardStep = 1;
    updateWizard();
    byId("project-dialog").showModal();
  }

  function updateWizard() {
    $$(".wizard-step").forEach((step) => step.classList.toggle("active", Number(step.dataset.step) === state.wizardStep));
    $$('[data-step-dot]').forEach((dot) => dot.classList.toggle("active", Number(dot.dataset.stepDot) <= state.wizardStep));
    byId("wizard-back").classList.toggle("hidden", state.wizardStep === 1);
    byId("wizard-next").classList.toggle("hidden", state.wizardStep === 3);
    byId("wizard-create").classList.toggle("hidden", state.wizardStep !== 3);
  }

  function wizardNext() {
    const current = $(`.wizard-step[data-step="${state.wizardStep}"]`);
    const required = $$('[required]', current);
    if (!required.every((input) => input.reportValidity())) return;
    state.wizardStep = Math.min(3, state.wizardStep + 1);
    updateWizard();
  }

  async function createProjectWizard(event) {
    event.preventDefault();
    const button = byId("wizard-create");
    button.disabled = true;
    button.textContent = "Création…";
    try {
      const project = await api(orgPath("/projects"), {
        method: "POST",
        body: JSON.stringify({
          name: byId("project-name").value.trim(),
          repo_full_name: byId("project-repo").value.trim() || null,
          default_branch: byId("project-branch").value.trim() || "main",
        }),
      });
      const bot = await api(orgPath("/bots"), {
        method: "POST",
        body: JSON.stringify({
          project_id: project.id,
          name: byId("bot-name").value.trim(),
          library: byId("bot-library").value,
        }),
      });
      await api(orgPath("/environments"), {
        method: "POST",
        body: JSON.stringify({
          bot_id: bot.id,
          kind: byId("env-kind").value,
          discord_application_id: byId("discord-app-id").value.trim() || null,
          runtime_mode: byId("env-runtime").value,
          secret_provider: byId("secret-provider").value,
        }),
      });
      byId("project-dialog").close();
      byId("project-wizard").reset();
      byId("project-branch").value = "main";
      toast("Projet, bot et environnement créés.");
      await refreshAll();
      switchView("projects");
    } catch (error) {
      toast(`Création interrompue : ${error.message}`, "bad");
    } finally {
      button.disabled = false;
      button.textContent = "Créer le projet";
    }
  }

  function openBuildDialog() {
    if (!state.envs.length) {
      toast("Créez d'abord un environnement.", "bad");
      return;
    }
    byId("build-dialog").showModal();
  }

  async function queueBuild(event) {
    event.preventDefault();
    const commit = byId("build-sha").value.trim().toLowerCase();
    try {
      await api(orgPath("/hosting/builds"), {
        method: "POST",
        body: JSON.stringify({ environment_id: byId("build-env").value, commit_sha: commit }),
      });
      byId("build-dialog").close();
      byId("build-sha").value = "";
      toast("Build mis en file d'attente.");
      await refreshAll();
      switchView("deployments");
    } catch (error) {
      toast(`Build impossible : ${error.message}`, "bad");
    }
  }

  async function deployRelease(releaseId) {
    const release = state.releases.find((item) => item.id === releaseId);
    const env = state.envs.find((item) => item.id === release?.environment_id);
    if (!window.confirm(`Déployer la release ${shortId(releaseId, 12)} sur ${envLabel(env)} ?`)) return;
    try {
      await api(orgPath("/hosting/deployments"), {
        method: "POST",
        body: JSON.stringify({ release_id: releaseId }),
      });
      toast("Déploiement mis en file.");
      await refreshAll();
    } catch (error) {
      toast(`Déploiement impossible : ${error.message}`, "bad");
    }
  }

  async function runtimeAction(envId, action) {
    try {
      const result = await api(orgPath(`/hosting/environments/${envId}/runtime`), {
        method: "POST",
        body: JSON.stringify({ action }),
      });
      toast(`${action} envoyé • ${result.affected_instances} instance(s) affectée(s).`);
      await refreshAll();
    } catch (error) {
      toast(`Action runtime impossible : ${error.message}`, "bad");
    }
  }

  async function githubRefresh() {
    try {
      const result = await api(orgPath("/hosting/github/refresh"), { method: "POST" });
      toast(`GitHub synchronisé : ${result.environments} environnement(s).`);
    } catch (error) {
      toast(`Synchronisation GitHub impossible : ${error.message}`, "bad");
    }
  }

  async function logout() {
    try {
      await api("/v1/auth/logout", { method: "POST" });
    } catch {
      // A local navigation still clears the current dashboard state.
    }
    localStorage.removeItem("sentrix_hosting_org");
    window.location.assign("/");
  }

  function filterDeployments() {
    const envId = byId("deploy-env-filter").value;
    if (!envId) {
      renderDeploymentView();
      return;
    }
    const originalBuilds = state.builds;
    const originalDeployments = state.deployments;
    const originalReleases = state.releases;
    state.builds = originalBuilds.filter((item) => item.environment_id === envId);
    state.deployments = originalDeployments.filter((item) => item.environment_id === envId);
    state.releases = originalReleases.filter((item) => item.environment_id === envId);
    renderDeploymentView();
    state.builds = originalBuilds;
    state.deployments = originalDeployments;
    state.releases = originalReleases;
  }

  function bindEvents() {
    byId("org-form").addEventListener("submit", createOrganization);
    byId("org-name").addEventListener("input", autoSlug);
    byId("org-slug").addEventListener("input", () => { byId("org-slug").dataset.edited = "1"; });

    byId("org-select").addEventListener("change", async (event) => {
      state.org = state.orgs.find((org) => org.id === event.target.value) || state.orgs[0];
      localStorage.setItem("sentrix_hosting_org", state.org.id);
      renderSettings();
      await refreshAll();
    });

    $$(".side-nav button").forEach((button) => button.addEventListener("click", () => switchView(button.dataset.view)));
    $$('[data-jump]').forEach((button) => button.addEventListener("click", () => switchView(button.dataset.jump)));
    $$('[data-action="new-project"]').forEach((button) => button.addEventListener("click", openProjectDialog));
    $$('[data-action="github-refresh"]').forEach((button) => button.addEventListener("click", () => void githubRefresh()));

    byId("new-project-btn").addEventListener("click", openProjectDialog);
    byId("refresh-btn").addEventListener("click", () => void refreshAll());
    byId("open-build-btn").addEventListener("click", openBuildDialog);
    byId("github-refresh-btn").addEventListener("click", () => void githubRefresh());
    byId("logout-btn").addEventListener("click", () => void logout());
    byId("settings-logout-btn").addEventListener("click", () => void logout());
    byId("menu-toggle").addEventListener("click", () => $(".sidebar").classList.toggle("open"));

    byId("wizard-next").addEventListener("click", wizardNext);
    byId("wizard-back").addEventListener("click", () => {
      state.wizardStep = Math.max(1, state.wizardStep - 1);
      updateWizard();
    });
    byId("project-wizard").addEventListener("submit", createProjectWizard);
    byId("build-form").addEventListener("submit", queueBuild);
    byId("usage-env-select").addEventListener("change", () => void renderUsage());
    byId("secret-env-select").addEventListener("change", () => void renderSecrets());
    byId("deploy-env-filter").addEventListener("change", filterDeployments);

    document.addEventListener("click", (event) => {
      const sidebar = $(".sidebar");
      if (window.innerWidth <= 820 && sidebar.classList.contains("open") && !sidebar.contains(event.target) && event.target !== byId("menu-toggle")) {
        sidebar.classList.remove("open");
      }
    });
  }

  bindEvents();
  void boot();
})();
