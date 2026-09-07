(() => {
  "use strict";

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

  const nav = $(".side-nav");
  const content = $("main.content");
  if (!nav || !content) return;

  function simplifyProjectModal() {
    const dialog = document.getElementById("project-dialog");
    const form = document.getElementById("project-wizard");
    if (!dialog || !form) return;

    // The X buttons used to submit their form, which meant the app submit
    // handler prevented the native <dialog> close action. Close dialogs
    // explicitly instead.
    $$("dialog .modal-head .icon-btn").forEach((button) => {
      button.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopPropagation();
        button.closest("dialog")?.close();
      });
    });

    // Clicking the dark backdrop also closes the project dialog.
    dialog.addEventListener("click", (event) => {
      if (event.target === dialog) dialog.close();
    });

    const steps = $$(".wizard-step", form);
    const projectStep = steps.find((step) => step.dataset.step === "1");
    const botStep = steps.find((step) => step.dataset.step === "2");
    const envStep = steps.find((step) => step.dataset.step === "3");
    if (!projectStep || !botStep || !envStep) return;

    const stepper = $(".stepper", form);
    if (stepper) stepper.style.display = "none";

    const firstHeading = $("h3", projectStep);
    const firstCopy = $("p", projectStep);
    if (firstHeading) firstHeading.textContent = "Ajouter ton bot";
    if (firstCopy) {
      firstCopy.textContent = "Renseigne juste l'essentiel. SentriX configure le reste automatiquement.";
    }

    const botName = document.getElementById("bot-name");
    const botNameLabel = botName?.closest("label");
    if (botNameLabel) {
      const divider = document.createElement("div");
      divider.className = "simple-project-divider";
      divider.innerHTML = "<small>BOT DISCORD</small>";
      projectStep.append(divider, botNameLabel);
    }

    const advanced = document.createElement("details");
    advanced.className = "simple-project-advanced";
    advanced.innerHTML = "<summary>Options avancées</summary>";

    const libraryLabel = document.getElementById("bot-library")?.closest("label");
    const appIdLabel = document.getElementById("discord-app-id")?.closest("label");
    if (libraryLabel) advanced.append(libraryLabel);
    if (appIdLabel) advanced.append(appIdLabel);
    projectStep.append(advanced);

    // Keep the advanced environment fields in the DOM because the existing
    // creation API reads them, but remove the third setup screen from the UX.
    botStep.style.display = "none";
    envStep.style.display = "none";

    const backButton = document.getElementById("wizard-back");
    const nextButton = document.getElementById("wizard-next");
    const createButton = document.getElementById("wizard-create");
    const projectName = document.getElementById("project-name");

    function applySimpleDefaults() {
      if (backButton) backButton.classList.add("hidden");
      if (nextButton) nextButton.classList.add("hidden");
      if (createButton) {
        createButton.classList.remove("hidden");
        createButton.textContent = "Créer mon bot";
      }

      projectStep.classList.add("active");
      botStep.classList.remove("active");
      envStep.classList.remove("active");

      const kind = document.getElementById("env-kind");
      const runtime = document.getElementById("env-runtime");
      const provider = document.getElementById("secret-provider");
      const library = document.getElementById("bot-library");
      if (kind) kind.value = "prod";
      if (runtime) runtime.value = "managed";
      if (provider) provider.value = "tmpfs_file";
      if (library && !library.value) library.value = "discordpy";

      if (projectName && botName && !botName.value.trim()) {
        botName.value = projectName.value.trim();
      }
    }

    projectName?.addEventListener("input", () => {
      if (botName && (!botName.dataset.edited || !botName.value.trim())) {
        botName.value = projectName.value.trim();
      }
    });
    botName?.addEventListener("input", () => {
      botName.dataset.edited = "1";
    });

    // app.js resets the original 3-step controls every time the dialog opens.
    // Re-apply the simple one-screen layout immediately after showModal().
    const observer = new MutationObserver(() => {
      if (dialog.open) applySimpleDefaults();
    });
    observer.observe(dialog, { attributes: true, attributeFilter: ["open"] });
    applySimpleDefaults();
  }

  simplifyProjectModal();

  const settingsButton = nav.querySelector('[data-view="settings"]');
  const hostingButton = document.createElement("button");
  hostingButton.dataset.view = "hosting";
  hostingButton.innerHTML = "<span>⬡</span>Hébergement";
  nav.insertBefore(hostingButton, settingsButton || null);

  const hostingView = document.createElement("section");
  hostingView.id = "view-hosting";
  hostingView.className = "view";
  hostingView.innerHTML = `
    <div class="view-heading">
      <div><span class="eyebrow">EXECUTION PLANE</span><h1>Hébergement</h1><p>État réel du moteur qui exécute les bots utilisateurs.</p></div>
      <button id="hosting-refresh" class="btn btn-secondary">Vérifier maintenant</button>
    </div>
    <div class="hosting-hero">
      <article class="panel hosting-card">
        <div class="panel-head"><div><small>HÉBERGEUR</small><h3>Worker d'exécution</h3></div><span id="hosting-badge" class="status-badge warn">Vérification…</span></div>
        <div class="hosting-state">
          <span class="hosting-state-icon">⬡</span>
          <div><strong id="hosting-title">Recherche d'un worker…</strong><small id="hosting-detail">Lecture du plan d'exécution SentriX.</small></div>
        </div>
        <div class="hosting-kpis">
          <div><small>WORKERS CONFIGURÉS</small><b id="hosting-configured">—</b></div>
          <div><small>WORKERS EN LIGNE</small><b id="hosting-online">—</b></div>
          <div><small>ISOLATION</small><b>gVisor</b></div>
        </div>
      </article>
      <article class="panel hosting-card">
        <div class="panel-head"><div><small>CONTROL PLANE</small><h3>Santé API</h3></div><span id="cp-badge" class="status-badge warn">Test…</span></div>
        <div id="hosting-orb" class="hosting-node-orb"></div>
        <p id="cp-detail" class="panel-copy" style="text-align:center">Health check en cours…</p>
      </article>
    </div>
    <article id="hosting-notice" class="hosting-notice">
      <span>!</span><div><b id="hosting-notice-title">Vérification de l'hébergement</b><small id="hosting-notice-copy">Un bot n'est réellement hébergé que lorsqu'au moins un node-agent d'exécution répond au control plane.</small></div>
    </article>
    <article class="panel" style="margin-top:16px">
      <div class="panel-head"><div><small>COMMENT ÇA TOURNE</small><h3>Chaîne d'hébergement SentriX</h3></div></div>
      <div class="code-strip"><span>GitHub</span><b>→</b><span>Build</span><b>→</b><span>Release</span><b>→</b><span>Worker gVisor</span><b>→</b><span class="green">Bot en ligne</span></div>
      <p class="panel-copy">Le control plane gère les projets et les déploiements. Le worker est la machine Linux qui exécute réellement les conteneurs des bots.</p>
      <div class="hosting-actions"><button id="hosting-projects" class="btn btn-primary">Configurer un bot</button><button id="hosting-runtime" class="btn btn-secondary">Ouvrir Runtime</button></div>
    </article>
  `;
  const settingsView = $("#view-settings");
  content.insertBefore(hostingView, settingsView || null);

  function setBadge(id, text, kind) {
    const badge = document.getElementById(id);
    if (!badge) return;
    badge.className = `status-badge ${kind || ""}`;
    badge.textContent = text;
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
      const error = new Error(payload?.detail || `HTTP ${response.status}`);
      error.status = response.status;
      throw error;
    }
    return payload;
  }

  async function refreshHostingStatus() {
    const refresh = document.getElementById("hosting-refresh");
    if (refresh) {
      refresh.disabled = true;
      refresh.textContent = "Vérification…";
    }

    const cpStarted = performance.now();
    try {
      const health = await fetchJson(`/healthz?t=${Date.now()}`);
      if (health.status !== "ok") throw new Error("health invalide");
      const latency = Math.max(1, Math.round(performance.now() - cpStarted));
      setBadge("cp-badge", "ONLINE", "good");
      document.getElementById("cp-detail").textContent = `API opérationnelle • ${latency} ms`;
      document.getElementById("hosting-orb").classList.remove("offline");
    } catch {
      setBadge("cp-badge", "OFFLINE", "bad");
      document.getElementById("cp-detail").textContent = "Le control plane ne répond pas correctement.";
      document.getElementById("hosting-orb").classList.add("offline");
    }

    try {
      const status = await fetchJson(`/v1/infra/status?t=${Date.now()}`);
      document.getElementById("hosting-configured").textContent = String(status.configured_nodes ?? 0);
      document.getElementById("hosting-online").textContent = String(status.online_nodes ?? 0);
      const notice = document.getElementById("hosting-notice");
      if (status.hosting_ready) {
        setBadge("hosting-badge", "PRÊT", "good");
        document.getElementById("hosting-title").textContent = "Hébergeur connecté";
        document.getElementById("hosting-detail").textContent = `${status.online_nodes} worker(s) répondent au control plane.`;
        document.getElementById("hosting-notice-title").textContent = "Hébergement disponible";
        document.getElementById("hosting-notice-copy").textContent = "Le plan d'exécution dispose d'au moins un worker actif pour lancer des bots.";
        notice.classList.add("good");
      } else {
        setBadge("hosting-badge", "AUCUN WORKER", "warn");
        document.getElementById("hosting-title").textContent = "Pas encore de machine d'hébergement";
        document.getElementById("hosting-detail").textContent = "Le site et l'API fonctionnent, mais aucun node-agent n'est actuellement en ligne.";
        document.getElementById("hosting-notice-title").textContent = "Le vrai hébergeur manque encore";
        document.getElementById("hosting-notice-copy").textContent = "Les boutons Start/Restart ne peuvent pas faire tourner un bot sans worker Linux connecté. Il faut une machine d'exécution (VPS/serveur) avec Docker + gVisor + node-agent SentriX.";
        notice.classList.remove("good");
      }
    } catch (error) {
      if (error.status === 401) {
        setBadge("hosting-badge", "CONNEXION REQUISE", "warn");
        document.getElementById("hosting-title").textContent = "Connectez-vous avec Discord";
        document.getElementById("hosting-detail").textContent = "Le statut de l'hébergeur est visible après connexion.";
      } else {
        setBadge("hosting-badge", "INDISPONIBLE", "bad");
        document.getElementById("hosting-title").textContent = "Statut worker indisponible";
        document.getElementById("hosting-detail").textContent = error.message;
      }
    } finally {
      if (refresh) {
        refresh.disabled = false;
        refresh.textContent = "Vérifier maintenant";
      }
    }
  }

  function openHostingView() {
    $$(".view").forEach((view) => view.classList.toggle("active", view === hostingView));
    $$(".side-nav button").forEach((button) => button.classList.toggle("active", button === hostingButton));
    const title = document.getElementById("page-title");
    const breadcrumb = document.getElementById("breadcrumb");
    const newProject = document.getElementById("new-project-btn");
    if (title) title.textContent = "Hébergement";
    if (breadcrumb) breadcrumb.textContent = "SENTRIX / HÉBERGEMENT";
    if (newProject) newProject.style.display = "none";
    $(".sidebar")?.classList.remove("open");
    void refreshHostingStatus();
  }

  hostingButton.addEventListener("click", openHostingView);
  document.getElementById("hosting-refresh")?.addEventListener("click", () => void refreshHostingStatus());
  document.getElementById("hosting-projects")?.addEventListener("click", () => {
    nav.querySelector('[data-view="projects"]')?.click();
    window.setTimeout(() => document.querySelector('[data-action="new-project"]')?.click(), 80);
  });
  document.getElementById("hosting-runtime")?.addEventListener("click", () => nav.querySelector('[data-view="runtime"]')?.click());

  $$(".view-heading, .metric-cards, .panel, .resource-card, .runtime-card").forEach((node) => node.classList.add("sentrix-reveal", "is-visible"));
  window.setTimeout(() => void refreshHostingStatus(), 1400);
  window.setInterval(() => {
    if (hostingView.classList.contains("active")) void refreshHostingStatus();
  }, 30000);
})();
