(() => {
  "use strict";

  const auth = document.getElementById("auth-screen");
  if (auth) {
    auth.innerHTML = `
      <a class="brand" href="/"><span class="brand-mark">S</span><span>SentriX <b>Hosting</b></span></a>
      <form id="local-login-form" class="auth-card">
        <span class="eyebrow">DASHBOARD</span>
        <h1>Connecte-toi à SentriX Hosting.</h1>
        <p>Accès privé au control plane. Aucun compte Discord ni OAuth requis.</p>
        <label>Utilisateur<input id="local-username" autocomplete="username" value="admin" required maxlength="80"></label>
        <label>Mot de passe<input id="local-password" type="password" autocomplete="current-password" required maxlength="512"></label>
        <button id="local-login-button" class="btn btn-primary btn-lg full" type="submit">Se connecter</button>
        <small id="local-login-error" class="muted" style="display:block;margin-top:12px"></small>
        <a class="text-link centered" href="/">← Retour au site</a>
      </form>`;

    document.getElementById("local-login-form")?.addEventListener("submit", async (event) => {
      event.preventDefault();
      const button = document.getElementById("local-login-button");
      const errorNode = document.getElementById("local-login-error");
      if (button) {
        button.disabled = true;
        button.textContent = "Connexion…";
      }
      if (errorNode) errorNode.textContent = "";
      try {
        const response = await fetch("/v1/auth/login", {
          method: "POST",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json", Accept: "application/json" },
          body: JSON.stringify({
            username: document.getElementById("local-username")?.value || "admin",
            password: document.getElementById("local-password")?.value || "",
          }),
        });
        if (!response.ok) {
          let message = `Erreur HTTP ${response.status}`;
          try {
            const payload = await response.json();
            if (typeof payload?.detail === "string") message = payload.detail;
          } catch {
            // Keep the HTTP fallback.
          }
          throw new Error(message);
        }
        window.location.reload();
      } catch (error) {
        if (errorNode) errorNode.textContent = error.message || "Connexion impossible";
      } finally {
        if (button) {
          button.disabled = false;
          button.textContent = "Se connecter";
        }
      }
    });
  }

  const exact = new Map([
    ["Projets & bots", "Projets & services"],
    ["Projets & Bots", "Projets & services"],
    ["BOTS", "SERVICES"],
    ["configurés", "configurés"],
    ["Projet + bot + environnement", "Projet + service + environnement"],
    ["Organisez vos dépôts et les bots associés.", "Organisez vos dépôts et les services associés."],
    ["Créez un projet pour commencer à héberger un bot.", "Créez un projet pour commencer à héberger une application."],
    ["Aucun bot", "Aucun service"],
    ["Application Discord", "Identifiant applicatif"],
    ["Compte Discord", "Session locale"],
    ["Déconnecte uniquement votre session SentriX Hosting de ce navigateur.", "Déconnecte uniquement la session SentriX Hosting de ce navigateur."],
    ["Elle contiendra vos projets, bots et environnements. Vous en serez propriétaire.", "Ce workspace contiendra vos projets, services et environnements."],
    ["Créez votre organisation.", "Créez votre workspace."],
    ["Nom de l'organisation", "Nom du workspace"],
    ["ORGANISATION", "WORKSPACE"],
    ["Organisation active", "Workspace actif"],
    ["Organisation", "Workspace"],
    ["Connectez votre compte Discord pour accéder aux projets, déploiements et environnements autorisés.", "Connecte-toi avec ton compte administrateur local."],
  ]);

  function rewriteText(root = document.body) {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    const nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    for (const node of nodes) {
      const value = node.nodeValue;
      if (!value || !value.trim()) continue;
      let next = value;
      for (const [from, to] of exact) next = next.replaceAll(from, to);
      next = next.replace(/\bbots\b/gi, (match) => match[0] === "B" ? "Services" : "services");
      next = next.replace(/\bbot\b/gi, (match) => match[0] === "B" ? "Service" : "service");
      if (next !== value) node.nodeValue = next;
    }
  }

  function neutralizeLegacyControls() {
    const library = document.getElementById("bot-library");
    if (library && ![...library.options].some((option) => option.value === "python")) {
      library.innerHTML = `
        <option value="python">Python</option>
        <option value="node">Node.js</option>
        <option value="docker">Dockerfile</option>`;
      library.value = "python";
    }
    const appId = document.getElementById("discord-app-id");
    const appIdLabel = appId?.closest("label");
    if (appId) appId.value = "";
    if (appIdLabel) appIdLabel.style.display = "none";
  }

  rewriteText();
  neutralizeLegacyControls();

  const observer = new MutationObserver(() => {
    rewriteText();
    neutralizeLegacyControls();
  });
  observer.observe(document.body, { subtree: true, childList: true, characterData: true });
})();
