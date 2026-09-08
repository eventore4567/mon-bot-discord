(() => {
  "use strict";

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  const cache = {
    orgId: null,
    projects: [],
    bots: [],
    envs: [],
    builds: [],
    releases: [],
    deployments: [],
    infra: null,
    updatedAt: 0,
  };

  const esc = (value) => String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");

  function currentOrgId() {
    return document.getElementById("org-select")?.value || null;
  }

  async function fetchJson(path) {
    const response = await fetch(path, {
      credentials: "same-origin",
      cache: "no-store",
      headers: { Accept: "application/json" },
    });
    let payload = null;
    try { payload = await response.json(); } catch { payload = null; }
    if (!response.ok) {
      const detail = typeof payload?.detail === "string" ? payload.detail : `HTTP ${response.status}`;
      const error = new Error(detail);
      error.status = response.status;
      throw error;
    }
    return payload;
  }

  async function refreshCache(force = false) {
    const orgId = currentOrgId();
    if (!orgId) return null;
    if (!force && cache.orgId === orgId && Date.now() - cache.updatedAt < 9000) return cache;

    const org = `/v1/orgs/${orgId}`;
    const results = await Promise.allSettled([
      fetchJson(`${org}/projects`),
      fetchJson(`${org}/bots`),
      fetchJson(`${org}/environments`),
      fetchJson(`${org}/hosting/builds?limit=80`),
      fetchJson(`${org}/hosting/releases?limit=80`),
      fetchJson(`${org}/hosting/deployments?limit=80`),
      fetchJson(`/v1/infra/status`),
    ]);
    const value = (index, fallback) => results[index].status === "fulfilled" ? results[index].value : fallback;
    Object.assign(cache, {
      orgId,
      projects: value(0, []),
      bots: value(1, []),
      envs: value(2, []),
      builds: value(3, []),
      releases: value(4, []),
      deployments: value(5, []),
      infra: value(6, null),
      updatedAt: Date.now(),
    });
    return cache;
  }

  function statusKind(status) {
    const s = String(status || "").toLowerCase();
    if (["success", "succeeded", "running", "active", "healthy", "ready"].includes(s)) return "good";
    if (["failed", "error", "crashed", "rejected", "unhealthy"].includes(s)) return "bad";
    return "warn";
  }

  function short(value, n = 10) {
    const text = String(value || "");
    return text.length > n ? `${text.slice(0, n)}…` : text || "—";
  }

  function dateLabel(value) {
    if (!value) return "—";
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) return "—";
    return new Intl.DateTimeFormat("fr-FR", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }).format(d);
  }

  function bytes(value) {
    let amount = Number(value || 0);
    if (!Number.isFinite(amount) || amount <= 0) return "0 B";
    const units = ["B", "KB", "MB", "GB", "TB"];
    let unit = 0;
    while (amount >= 1024 && unit < units.length - 1) { amount /= 1024; unit += 1; }
    return `${amount >= 10 || unit === 0 ? amount.toFixed(0) : amount.toFixed(1)} ${units[unit]}`;
  }

  function clickView(view) {
    document.querySelector(`.side-nav [data-view="${view}"]`)?.click();
  }

  function toast(message, kind = "good") {
    const root = document.getElementById("toast-root");
    if (!root) return;
    const node = document.createElement("div");
    node.className = `toast ${kind}`;
    node.textContent = message;
    root.appendChild(node);
    window.setTimeout(() => node.remove(), 4200);
  }

  /* ---------- Top command bar ---------- */
  function installToolbar() {
    const actions = $(".top-actions");
    if (!actions || $(".sx-premium-toolbar", actions)) return;

    const toolbar = document.createElement("div");
    toolbar.className = "sx-premium-toolbar";
    toolbar.innerHTML = `
      <button class="sx-premium-search" type="button" aria-label="Recherche et commandes">
        <span>⌕</span><span>Rechercher projets, services, actions…</span><kbd>⌘ K</kbd>
      </button>
      <div class="sx-live-health"><span class="dot"></span><span>Control plane</span></div>
      <div class="sx-notify-wrap">
        <button class="sx-notify-btn" type="button" aria-label="Activité récente">◉<span class="count" hidden>0</span></button>
        <div class="sx-notify-panel" aria-label="Activité récente"></div>
      </div>`;
    actions.insertBefore(toolbar, actions.firstChild);
    $(".sx-premium-search", toolbar)?.addEventListener("click", openPalette);
    $(".sx-notify-btn", toolbar)?.addEventListener("click", (event) => {
      event.stopPropagation();
      $(".sx-notify-panel", toolbar)?.classList.toggle("open");
    });
    document.addEventListener("click", (event) => {
      if (!event.target.closest(".sx-notify-wrap")) $(".sx-notify-panel", toolbar)?.classList.remove("open");
    });
    void refreshHealthBadge();
  }

  async function refreshHealthBadge() {
    const node = $(".sx-live-health");
    if (!node) return;
    const start = performance.now();
    try {
      const health = await fetchJson(`/healthz?t=${Date.now()}`);
      if (health.status !== "ok") throw new Error("health");
      const latency = Math.max(1, Math.round(performance.now() - start));
      node.classList.remove("offline");
      node.querySelector("span:last-child").textContent = `Control plane · ${latency} ms`;
    } catch {
      node.classList.add("offline");
      node.querySelector("span:last-child").textContent = "Control plane indisponible";
    }
  }

  /* ---------- Command palette ---------- */
  const actions = [
    { group: "Navigation", icon: "⌂", label: "Vue d'ensemble", hint: "Dashboard", run: () => clickView("overview") },
    { group: "Navigation", icon: "◇", label: "Projets & services", hint: "Ressources", run: () => clickView("projects") },
    { group: "Navigation", icon: "↗", label: "Builds & déploiements", hint: "CI/CD", run: () => clickView("deployments") },
    { group: "Navigation", icon: "◫", label: "Runtime", hint: "Start / Stop / Restart", run: () => clickView("runtime") },
    { group: "Navigation", icon: "◌", label: "Observabilité", hint: "Métriques réelles", run: () => clickView("observability") },
    { group: "Navigation", icon: "⌾", label: "Secrets", hint: "Métadonnées write-only", run: () => clickView("secrets") },
    { group: "Navigation", icon: "⬡", label: "Infrastructure", hint: "Workers gVisor", run: () => document.querySelector('.side-nav [data-view="hosting"]')?.click() },
    { group: "Actions", icon: "+", label: "Créer un service", hint: "Projet + service + environnement", run: () => document.querySelector('[data-action="new-project"]')?.click() },
    { group: "Actions", icon: "↗", label: "Lancer un build", hint: "Commit GitHub", run: () => { clickView("deployments"); window.setTimeout(() => document.getElementById("open-build-btn")?.click(), 100); } },
    { group: "Actions", icon: "↻", label: "Actualiser les données", hint: "Refresh", run: () => document.getElementById("refresh-btn")?.click() },
    { group: "Actions", icon: "⌁", label: "Synchroniser GitHub", hint: "Targets", run: () => document.querySelector('[data-action="github-refresh"]')?.click() },
    { group: "Technique", icon: "{}", label: "Documentation API", hint: "/docs", run: () => window.open("/docs", "_blank", "noopener,noreferrer") },
  ];

  function installPalette() {
    if ($(".sx-palette-backdrop")) return;
    const backdrop = document.createElement("div");
    backdrop.className = "sx-palette-backdrop";
    backdrop.innerHTML = `
      <div class="sx-palette" role="dialog" aria-modal="true" aria-label="Palette de commandes">
        <div class="sx-palette-head"><span>⌕</span><input aria-label="Rechercher" placeholder="Tape une action, un projet, un service…" autocomplete="off"><small>ESC</small></div>
        <div class="sx-palette-results"></div>
      </div>`;
    document.body.appendChild(backdrop);
    backdrop.addEventListener("mousedown", (event) => { if (event.target === backdrop) closePalette(); });
    const input = $("input", backdrop);
    input?.addEventListener("input", renderPalette);
    input?.addEventListener("keydown", onPaletteKeydown);
  }

  async function openPalette() {
    installPalette();
    await refreshCache().catch(() => null);
    const backdrop = $(".sx-palette-backdrop");
    backdrop?.classList.add("open");
    const input = $(".sx-palette-head input", backdrop);
    if (input) { input.value = ""; input.focus(); }
    renderPalette();
  }

  function closePalette() { $(".sx-palette-backdrop")?.classList.remove("open"); }

  function paletteItems(query) {
    const q = query.trim().toLowerCase();
    const result = actions.map((item) => ({ ...item, searchable: `${item.label} ${item.hint} ${item.group}`.toLowerCase() }));
    for (const project of cache.projects) {
      const bots = cache.bots.filter((bot) => bot.project_id === project.id);
      result.push({
        group: "Projets", icon: "◇", label: project.name, hint: project.repo_full_name || `${bots.length} service(s)`,
        searchable: `${project.name} ${project.repo_full_name || ""}`.toLowerCase(),
        run: () => { clickView("projects"); window.setTimeout(() => openProjectInspector(project.id), 120); },
      });
    }
    for (const bot of cache.bots) {
      const project = cache.projects.find((item) => item.id === bot.project_id);
      result.push({
        group: "Services", icon: "◫", label: bot.name, hint: `${bot.library || "runtime"}${project ? ` · ${project.name}` : ""}`,
        searchable: `${bot.name} ${bot.library || ""} ${project?.name || ""}`.toLowerCase(),
        run: () => { clickView("projects"); if (project) window.setTimeout(() => openProjectInspector(project.id), 120); },
      });
    }
    return q ? result.filter((item) => item.searchable.includes(q)).slice(0, 30) : result.slice(0, 22);
  }

  function renderPalette() {
    const backdrop = $(".sx-palette-backdrop");
    const input = $(".sx-palette-head input", backdrop);
    const root = $(".sx-palette-results", backdrop);
    if (!root) return;
    const items = paletteItems(input?.value || "");
    if (!items.length) { root.innerHTML = `<div class="sx-palette-empty">Aucun résultat.</div>`; return; }
    let lastGroup = "";
    root.innerHTML = items.map((item, index) => {
      const group = item.group !== lastGroup ? `<div class="sx-palette-group">${esc(item.group)}</div>` : "";
      lastGroup = item.group;
      return `${group}<button class="sx-palette-item${index === 0 ? " active" : ""}" data-palette-index="${index}" type="button"><span class="ic">${esc(item.icon)}</span><b>${esc(item.label)}</b><small>${esc(item.hint)}</small></button>`;
    }).join("");
    $$('[data-palette-index]', root).forEach((button) => {
      button.addEventListener("click", () => { const item = items[Number(button.dataset.paletteIndex)]; closePalette(); item?.run(); });
    });
    root.dataset.count = String(items.length);
    root._items = items;
  }

  function onPaletteKeydown(event) {
    const root = $(".sx-palette-results");
    if (!root) return;
    const buttons = $$('[data-palette-index]', root);
    const current = buttons.findIndex((node) => node.classList.contains("active"));
    if (event.key === "Escape") { closePalette(); return; }
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      if (!buttons.length) return;
      const delta = event.key === "ArrowDown" ? 1 : -1;
      const next = (Math.max(0, current) + delta + buttons.length) % buttons.length;
      buttons.forEach((node, index) => node.classList.toggle("active", index === next));
      buttons[next]?.scrollIntoView({ block: "nearest" });
    }
    if (event.key === "Enter") {
      event.preventDefault();
      const active = buttons[current >= 0 ? current : 0];
      active?.click();
    }
  }

  document.addEventListener("keydown", (event) => {
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") { event.preventDefault(); void openPalette(); }
    if (event.key === "Escape") { closePalette(); closeProjectInspector(); }
  });

  /* ---------- Activity center ---------- */
  async function refreshNotifications() {
    await refreshCache().catch(() => null);
    const panel = $(".sx-notify-panel");
    const count = $(".sx-notify-btn .count");
    if (!panel) return;
    const events = [
      ...cache.deployments.map((d) => ({ type: "deploy", status: d.status, title: `Déploiement ${d.status}`, detail: `${short(d.release_id, 12)} · ${dateLabel(d.created_at)}`, date: d.created_at })),
      ...cache.builds.map((b) => ({ type: "build", status: b.status, title: `Build ${b.status}`, detail: `${short(b.commit_sha, 12)} · ${dateLabel(b.created_at)}`, date: b.created_at })),
    ].sort((a, b) => new Date(b.date) - new Date(a.date)).slice(0, 12);
    panel.innerHTML = `<div class="sx-notify-head"><b>Activité réelle</b><small>${events.length} événement(s)</small></div>${events.length ? events.map((event) => `<div class="sx-notify-item ${statusKind(event.status)}"><span class="event-dot"></span><div><b>${esc(event.title)}</b><small>${esc(event.detail)}</small></div></div>`).join("") : `<div class="sx-palette-empty">Aucun build ou déploiement.</div>`}`;
    const attention = events.filter((e) => statusKind(e.status) === "bad").length;
    if (count) { count.hidden = attention === 0; count.textContent = String(attention); }
  }

  /* ---------- Overview operations intelligence ---------- */
  async function installOverviewIntelligence() {
    const view = document.getElementById("view-overview");
    if (!view || $(".sx-ops-grid", view)) return;
    await refreshCache().catch(() => null);
    const metrics = $(".metric-cards", view);
    if (!metrics) return;
    const runningBuilds = cache.builds.filter((b) => ["queued", "building", "scanning"].includes(String(b.status).toLowerCase())).length;
    const activeDeploys = cache.deployments.filter((d) => ["pending", "running", "deploying"].includes(String(d.status).toLowerCase())).length;
    const readyReleases = cache.releases.length;
    const infra = cache.infra;
    const block = document.createElement("div");
    block.className = "sx-ops-grid";
    block.innerHTML = `
      <article class="sx-ops-card">
        <small>PIPELINE LIVE</small><h3>Du commit au runtime</h3>
        <div class="sx-pipeline">
          <div><small>GITHUB</small><b>${cache.projects.filter((p) => p.repo_full_name).length} dépôt(s)</b></div>
          <div><small>BUILDS</small><b>${runningBuilds ? `${runningBuilds} actif(s)` : `${cache.builds.length} total`}</b></div>
          <div><small>RELEASES</small><b>${readyReleases} immuable(s)</b></div>
          <div><small>DÉPLOIEMENTS</small><b>${activeDeploys ? `${activeDeploys} actif(s)` : `${cache.deployments.length} total`}</b></div>
        </div>
      </article>
      <article class="sx-ops-card">
        <small>EXECUTION PLANE</small><h3>Capacité réelle</h3>
        <div class="sx-infra-mini">
          <div><small>WORKERS</small><strong>${infra?.online_nodes ?? 0}/${infra?.configured_nodes ?? 0}</strong></div>
          <div><small>ISOLATION</small><strong>gVisor</strong></div>
          <div><small>COMPUTE</small><strong>${infra?.hosting_ready ? "Prêt" : "En attente"}</strong></div>
          <div><small>CONTROL</small><strong>${infra?.control_plane === "ok" ? "Online" : "—"}</strong></div>
        </div>
      </article>`;
    metrics.insertAdjacentElement("afterend", block);
  }

  /* ---------- Project drawer ---------- */
  function installProjectInspector() {
    if ($(".sx-project-inspector")) return;
    const root = document.createElement("div");
    root.className = "sx-project-inspector";
    root.innerHTML = `<aside class="sx-project-drawer" aria-label="Détails du projet"></aside>`;
    root.addEventListener("mousedown", (event) => { if (event.target === root) closeProjectInspector(); });
    document.body.appendChild(root);
  }

  async function openProjectInspector(projectId) {
    installProjectInspector();
    await refreshCache().catch(() => null);
    const project = cache.projects.find((p) => p.id === projectId);
    if (!project) return;
    const bots = cache.bots.filter((b) => b.project_id === project.id);
    const botIds = new Set(bots.map((b) => b.id));
    const envs = cache.envs.filter((e) => botIds.has(e.bot_id));
    const envIds = new Set(envs.map((e) => e.id));
    const builds = cache.builds.filter((b) => envIds.has(b.environment_id)).slice(0, 6);
    const deployments = cache.deployments.filter((d) => envIds.has(d.environment_id)).slice(0, 6);
    const drawer = $(".sx-project-drawer");
    drawer.innerHTML = `
      <div class="sx-drawer-head"><div><small>PROJET</small><h2>${esc(project.name)}</h2><p>${esc(project.repo_full_name || "Aucun dépôt GitHub associé")}</p></div><button class="icon-btn sx-close-drawer" type="button">×</button></div>
      <div class="sx-project-kpis"><div><small>SERVICES</small><b>${bots.length}</b></div><div><small>ENVIRONNEMENTS</small><b>${envs.length}</b></div><div><small>BRANCHE</small><b>${esc(project.default_branch || "main")}</b></div></div>
      <div class="sx-drawer-section"><h4>Services</h4>${bots.length ? bots.map((bot) => { const count = envs.filter((e) => e.bot_id === bot.id).length; return `<div class="sx-resource-line"><div><b>${esc(bot.name)}</b><small>${esc(bot.library || "runtime")}</small></div><span>${count} env.</span></div>`; }).join("") : `<p class="muted">Aucun service.</p>`}</div>
      <div class="sx-drawer-section"><h4>Environnements</h4>${envs.length ? envs.map((env) => `<div class="sx-resource-line"><div><b>${esc(env.kind || "env")}</b><small>${esc(env.runtime_mode || "runtime")} · ${esc(env.secret_provider || "secrets")}</small></div><span class="status-badge ${statusKind(env.status)}">${esc(env.status)}</span></div>`).join("") : `<p class="muted">Aucun environnement.</p>`}</div>
      <div class="sx-drawer-section"><h4>Derniers builds</h4>${builds.length ? builds.map((build) => `<div class="sx-resource-line"><div><b class="mono">${esc(short(build.commit_sha, 12))}</b><small>${dateLabel(build.created_at)}</small></div><span class="status-badge ${statusKind(build.status)}">${esc(build.status)}</span></div>`).join("") : `<p class="muted">Aucun build.</p>`}</div>
      <div class="sx-drawer-section"><h4>Derniers déploiements</h4>${deployments.length ? deployments.map((dep) => `<div class="sx-resource-line"><div><b>${esc(dep.step || "deployment")}</b><small>${dateLabel(dep.created_at)} · ${esc(short(dep.release_id, 12))}</small></div><span class="status-badge ${statusKind(dep.status)}">${esc(dep.status)}</span></div>`).join("") : `<p class="muted">Aucun déploiement.</p>`}</div>`;
    $(".sx-close-drawer", drawer)?.addEventListener("click", closeProjectInspector);
    $(".sx-project-inspector")?.classList.add("open");
  }

  function closeProjectInspector() { $(".sx-project-inspector")?.classList.remove("open"); }

  async function bindProjectCards() {
    const root = document.getElementById("projects-grid");
    if (!root) return;
    await refreshCache().catch(() => null);
    const cards = $$(".resource-card", root);
    cards.forEach((card, index) => {
      if (card.dataset.sxInspector) return;
      const project = cache.projects[index];
      if (!project) return;
      card.dataset.sxInspector = project.id;
      card.style.cursor = "pointer";
      card.setAttribute("tabindex", "0");
      card.setAttribute("role", "button");
      card.setAttribute("aria-label", `Ouvrir les détails de ${project.name}`);
      const open = () => void openProjectInspector(project.id);
      card.addEventListener("click", (event) => { if (!event.target.closest("button,a,input,select")) open(); });
      card.addEventListener("keydown", (event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); open(); } });
    });
  }

  /* ---------- Real usage chart ---------- */
  let chartMetric = "memory_bytes";
  async function renderPremiumChart() {
    const view = document.getElementById("view-observability");
    const select = document.getElementById("usage-env-select");
    if (!view || !select?.value) return;
    let card = $(".sx-chart-card", view);
    if (!card) {
      card = document.createElement("article");
      card.className = "sx-chart-card";
      card.innerHTML = `<div class="sx-chart-head"><div><small>TÉLÉMÉTRIE</small><h3>Courbe réelle</h3></div><div class="sx-chart-tabs"><button data-metric="memory_bytes" class="active">RAM</button><button data-metric="cpu_millis">CPU</button><button data-metric="egress_bytes">Egress</button><button data-metric="log_bytes">Logs</button></div></div><div class="sx-chart-body"><div class="empty-mini">Chargement…</div></div>`;
      view.appendChild(card);
      $$('[data-metric]', card).forEach((button) => button.addEventListener("click", () => {
        chartMetric = button.dataset.metric;
        $$('[data-metric]', card).forEach((item) => item.classList.toggle("active", item === button));
        void renderPremiumChart();
      }));
    }
    const orgId = currentOrgId();
    if (!orgId) return;
    const root = $(".sx-chart-body", card);
    try {
      const samples = (await fetchJson(`/v1/orgs/${orgId}/hosting/environments/${select.value}/usage?limit=80`)).reverse();
      if (!samples.length) { root.innerHTML = `<div class="empty-mini">Aucun échantillon. Le worker publiera les métriques ici lorsqu'il sera connecté.</div>`; return; }
      const values = samples.map((s) => Number(s[chartMetric] || 0));
      const max = Math.max(...values, 1);
      const w = 1000, h = 190, pad = 14;
      const points = values.map((v, i) => {
        const x = values.length === 1 ? w / 2 : pad + i * ((w - pad * 2) / (values.length - 1));
        const y = h - pad - (v / max) * (h - pad * 2);
        return [x, y];
      });
      const line = points.map((p) => p.join(",")).join(" ");
      const area = `${pad},${h-pad} ${line} ${w-pad},${h-pad}`;
      const last = values[values.length - 1];
      const label = chartMetric === "memory_bytes" ? bytes(last) : chartMetric === "cpu_millis" ? `${last} mCPU` : bytes(last);
      root.innerHTML = `<div class="sx-chart-head"><small>${samples.length} échantillon(s)</small><b>${esc(label)}</b></div><svg class="sx-svg-chart" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" role="img" aria-label="Historique ${esc(chartMetric)}"><defs><linearGradient id="sxFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="#4f8cff" stop-opacity=".28"/><stop offset="100%" stop-color="#4f8cff" stop-opacity="0"/></linearGradient></defs>${[.25,.5,.75].map((r) => `<line class="grid" x1="${pad}" x2="${w-pad}" y1="${h*r}" y2="${h*r}"/>`).join("")}<polygon class="fill" points="${area}"/><polyline class="line" points="${line}"/>${points.slice(-1).map((p) => `<circle class="dot" cx="${p[0]}" cy="${p[1]}" r="4"/>`).join("")}</svg>`;
    } catch (error) {
      root.innerHTML = `<div class="empty-mini">Métriques indisponibles : ${esc(error.message)}</div>`;
    }
  }

  /* ---------- Mutation / lifecycle ---------- */
  let refreshTimer = null;
  async function enhance() {
    installToolbar();
    installPalette();
    installProjectInspector();
    await installOverviewIntelligence();
    await bindProjectCards();
    await refreshNotifications();
    await renderPremiumChart();
  }

  function scheduleEnhance() {
    window.clearTimeout(refreshTimer);
    refreshTimer = window.setTimeout(() => void enhance(), 180);
  }

  const observer = new MutationObserver((records) => {
    if (records.some((record) => record.target.closest?.(".sx-palette-backdrop, .sx-project-inspector, .sx-notify-panel"))) return;
    scheduleEnhance();
  });

  function bootEnhancements() {
    const dashboard = document.getElementById("dashboard");
    if (!dashboard) return;
    observer.observe(dashboard, { childList: true, subtree: true });
    document.getElementById("org-select")?.addEventListener("change", () => { cache.updatedAt = 0; scheduleEnhance(); });
    document.getElementById("usage-env-select")?.addEventListener("change", () => void renderPremiumChart());
    document.getElementById("refresh-btn")?.addEventListener("click", () => { cache.updatedAt = 0; window.setTimeout(scheduleEnhance, 500); });
    window.setInterval(() => { void refreshHealthBadge(); if (!document.hidden) { cache.updatedAt = 0; void refreshNotifications(); } }, 30000);
    void enhance();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", bootEnhancements);
  else bootEnhancements();
})();
