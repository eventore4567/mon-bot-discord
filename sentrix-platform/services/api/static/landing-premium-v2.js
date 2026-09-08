(() => {
  "use strict";
  const $ = (selector, root = document) => root.querySelector(selector);

  async function fetchJson(path) {
    const response = await fetch(path, { credentials: "same-origin", cache: "no-store", headers: { Accept: "application/json" } });
    let payload = null;
    try { payload = await response.json(); } catch { payload = null; }
    if (!response.ok) { const error = new Error(`HTTP ${response.status}`); error.status = response.status; throw error; }
    return payload;
  }

  function installProofSection() {
    const status = document.getElementById("status");
    if (!status || $(".sx-landing-proof")) return;
    const section = document.createElement("section");
    section.className = "section wrap";
    section.innerHTML = `
      <div class="section-heading"><span>Expérience complète</span><h2>Un control plane pensé comme un vrai produit.</h2><p>Chaque bouton actif du dashboard est branché sur une route réelle : ressources, builds, releases, déploiements, runtime, métriques, secrets et infrastructure.</p></div>
      <div class="sx-landing-proof">
        <article>
          <small>RUNTIMES</small><h3>Déploie plusieurs types de services</h3>
          <p>SentriX sépare le control plane de l'execution plane. Les workloads sont conçus pour tourner sur des workers Linux dédiés sous gVisor.</p>
          <div class="sx-compat-grid"><span>Python</span><span>Node.js</span><span>Dockerfile</span><span>API</span><span>Worker</span><span>Bot</span></div>
        </article>
        <article class="sx-live-status-card">
          <div><small>STATUT LIVE</small><h3>Infrastructure</h3></div>
          <div class="sx-status-line"><b>Control plane</b><span id="sx-landing-cp">Vérification…</span></div>
          <div class="sx-status-line"><b>Workers gVisor</b><span id="sx-landing-workers">Connexion requise</span></div>
          <div class="sx-status-line"><b>Secrets</b><span class="ok">write-only</span></div>
          <div class="sx-status-line"><b>Isolation DB</b><span class="ok">PostgreSQL RLS</span></div>
          <a class="btn btn-secondary" href="/app">Voir le dashboard</a>
        </article>
      </div>`;
    status.insertAdjacentElement("beforebegin", section);
  }

  async function refreshLiveStatus() {
    const cp = document.getElementById("sx-landing-cp");
    const workers = document.getElementById("sx-landing-workers");
    const statusPanel = document.getElementById("status");
    const started = performance.now();
    try {
      const health = await fetchJson(`/healthz?t=${Date.now()}`);
      const latency = Math.max(1, Math.round(performance.now() - started));
      if (cp) { cp.textContent = health.status === "ok" ? `Online · ${latency} ms` : "État inattendu"; cp.className = health.status === "ok" ? "ok" : "warn"; }
      const strong = statusPanel?.querySelector("strong");
      const small = statusPanel?.querySelector("small");
      if (strong) strong.textContent = "Control plane opérationnel";
      if (small) small.textContent = `Health check réel · ${latency} ms`;
    } catch {
      if (cp) { cp.textContent = "Indisponible"; cp.className = "warn"; }
    }

    try {
      const infra = await fetchJson(`/v1/infra/status?t=${Date.now()}`);
      if (workers) {
        workers.textContent = infra.hosting_ready
          ? `${infra.online_nodes}/${infra.configured_nodes} en ligne`
          : `${infra.online_nodes}/${infra.configured_nodes} en ligne`;
        workers.className = infra.hosting_ready ? "ok" : "warn";
      }
    } catch (error) {
      if (workers) {
        workers.textContent = error.status === 401 ? "Visible après connexion" : "Statut indisponible";
        workers.className = "";
      }
    }
  }

  function installHeroDetails() {
    const trust = $(".trust-row");
    if (!trust || trust.dataset.sxPremium) return;
    trust.dataset.sxPremium = "1";
    trust.innerHTML = `<span>GitHub CI/CD</span><i></i><span>PostgreSQL RLS</span><i></i><span>Secrets write-only</span><i></i><span>Workers gVisor</span><i></i><span>Rollback</span>`;

    const eyebrow = $(".hero .eyebrow");
    if (eyebrow) eyebrow.innerHTML = `<span class="status-dot"></span> Control plane en production · execution plane isolé`;
  }

  function boot() {
    installHeroDetails();
    installProofSection();
    void refreshLiveStatus();
    window.setInterval(() => { if (!document.hidden) void refreshLiveStatus(); }, 30000);
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();
