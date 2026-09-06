import fs from "node:fs";
import process from "node:process";
import { JSDOM, VirtualConsole } from "jsdom";

const htmlPath = process.argv[2];
if (!htmlPath) throw new Error("usage: node dashboard_v56_browser_smoke.mjs <dashboard.html>");
const html = fs.readFileSync(htmlPath, "utf8");
const requests = [];
const runtimeErrors = [];
const virtualConsole = new VirtualConsole();
virtualConsole.on("jsdomError", error => runtimeErrors.push(String(error?.stack || error)));
virtualConsole.on("error", (...args) => runtimeErrors.push(args.map(String).join(" ")));

function response(payload, status = 200) {
  return { ok: status >= 200 && status < 300, status, async json() { return payload; } };
}

const diagnosticsPayload = {
  ok: true, score: 82,
  summary: { active: 7, inactive: 1, missing: 2, errors: 0 },
  modules: {
    welcome: { code: "active", status: "ACTIF", detail: "Bienvenue configurée." },
    levels: { code: "missing", status: "NON CONFIGURÉ", detail: "Salon absent." },
    suggestions: { code: "active", status: "ACTIF", detail: "Suggestions configurées." },
    reports: { code: "active", status: "ACTIF", detail: "Signalements configurés." },
    logs: { code: "active", status: "ACTIF", detail: "Logs configurés." },
    roles: { code: "active", status: "ACTIF", detail: "Rôles configurés." },
    tickets: { code: "active", status: "ACTIF", detail: "Tickets configurés." },
    automod: { code: "active", status: "ACTIF", detail: "AutoMod actif." },
    ai: { code: "inactive", status: "INACTIF", detail: "IA désactivée." },
    notifications: { code: "missing", status: "NON CONFIGURÉ", detail: "Aucune source." },
    moderation: { code: "active", status: "ACTIF", detail: "Permissions disponibles." },
  },
  permissions: [
    { key: "administrator", name: "Administrateur", granted: true },
    { key: "manage_roles", name: "Gérer les rôles", granted: true },
    { key: "ban_members", name: "Bannir des membres", granted: true },
  ],
  invalid_resources: [], bot: { id: "999", top_role_position: 10 },
};

const setupPayload = {
  ok: true,
  commands: [
    { name: "help", description: "Aide", protected: true },
    { name: "ban", description: "Bannir un membre", protected: false },
    { name: "ticket", description: "Gérer les tickets", protected: false },
  ],
  disabled_commands: ["ticket"], ignored_channels: [], automod_exempt_roles: [], antinuke_whitelist: [], managers: [],
  manager_categories: { configuration: "Configuration", tickets: "Tickets", moderation: "Modération", securite: "Sécurité", economie: "Économie et jeux", complete: "Accès complet" },
  history: [], verification: { role_id: "", channel_id: "" },
};

const dom = new JSDOM(html, {
  url: "https://sentrix.test/app", runScripts: "dangerously", pretendToBeVisual: true, virtualConsole,
  beforeParse(window) {
    window.fetch = async (input, options = {}) => {
      const url = new URL(typeof input === "string" ? input : input.url, window.location.href);
      const method = String(options.method || "GET").toUpperCase();
      requests.push({ path: url.pathname, method });
      if (url.pathname === "/api/public") return response({ ok: true, online: true, guilds: 20, members: 1000, latency_ms: 42, uptime_seconds: 3600, invite_url: "https://discord.com/oauth2/authorize?client_id=1", avatar_url: null, oauth_ready: true });
      if (url.pathname === "/api/me") return response({ ok: true, user: { id: "42", username: "SentriX Test", avatar_url: null }, csrf: "test-csrf" });
      if (url.pathname === "/api/guilds") return response({ ok: true, guilds: [{ id: "1", name: "Serveur Test", icon_url: null, installed: true }] });
      if (url.pathname === "/api/guilds/1") return response({
        ok: true,
        guild: { id: "1", name: "Serveur Test", members: 12, channels_count: 7, roles_count: 7 },
        metrics: { commands_24h: 3, open_tickets: 1, warnings: 0, economy_accounts: 2 }, settings: {}, automod: {}, ai: {},
        roles: [
          { id: "10", name: "Staff" }, { id: "11", name: "Membre" }, { id: "12", name: "Booster" },
          { id: "13", name: "Modérateur" }, { id: "14", name: "Admin" }, { id: "15", name: "Vérifié" },
        ],
        channels: [
          { id: "20", name: "general", type: "text" }, { id: "21", name: "logs", type: "text" },
          { id: "22", name: "welcome", type: "text" }, { id: "23", name: "tickets", type: "text" },
          { id: "24", name: "reports", type: "text" }, { id: "25", name: "staff", type: "text" },
          { id: "26", name: "Tickets", type: "category" },
        ], social_notifications: [],
      });
      if (url.pathname === "/api/guilds/1/sanctions") return response({ ok: true, sanctions: [], next_offset: null, total: 0 });
      if (url.pathname === "/api/guilds/1/diagnostics") return response(diagnosticsPayload);
      if (url.pathname === "/api/guilds/1/setup-tools") return method === "POST" ? response({ ok: true, message: "Configuration appliquée." }) : response(setupPayload);
      if (url.pathname === "/api/guilds/1/dm/apercu") return response({ guild: { id: "1", name: "Serveur Test" }, destinataires: 11, bots_ignores: 1, duree_estimee_secondes: 8 });
      if (url.pathname === "/api/guilds/1/dm/job") return response({ actif: false, etat: null });
      return response({ error: `Route mock inconnue: ${url.pathname}` }, 404);
    };
    window.confirm = () => true;
    window.scrollTo = () => {};
  },
});

await new Promise(resolve => setTimeout(resolve, 1300));

const bootstrapPaths = requests.map(item => item.path);
for (const required of ["/api/public", "/api/me", "/api/guilds", "/api/guilds/1"]) {
  if (!bootstrapPaths.includes(required)) {
    console.error("Requetes observees:", JSON.stringify(requests, null, 2));
    console.error("Erreurs runtime:", runtimeErrors.join("\n"));
    throw new Error(`Le bootstrap dashboard n'a jamais appelé ${required}`);
  }
}

const dashboard = dom.window.document.getElementById("dashboard");
if (!dashboard || dashboard.classList.contains("hidden")) throw new Error("La session est chargée mais le dashboard reste masqué.");
const serverContent = dom.window.document.getElementById("serverContent");
if (!serverContent || serverContent.classList.contains("hidden")) throw new Error("Le serveur est chargé mais sa zone centrale reste masquée.");

const expectedTabs = [
  "overview", "general", "access", "features", "security", "sanctions", "logs", "welcome", "levels", "tickets",
  "ai", "notifications", "embeds", "roles", "dm",
];
const buttons = [...dom.window.document.querySelectorAll("#navigation button[data-tab]")];
const actualTabs = buttons.map(button => button.dataset.tab);
for (const tab of expectedTabs) if (!actualTabs.includes(tab)) throw new Error(`Page dashboard absente: ${tab}`);

for (const tab of expectedTabs) {
  const button = dom.window.document.querySelector(`#navigation button[data-tab="${tab}"]`);
  button.click();
  await new Promise(resolve => setTimeout(resolve, ["overview","access","features","dm"].includes(tab) ? 120 : 50));
  if (!button.classList.contains("active")) throw new Error(`Le clic sidebar n'active pas la page ${tab}`);
  const title = dom.window.document.getElementById("tabTitle")?.textContent?.trim();
  if (!title) throw new Error(`La page ${tab} n'a plus de titre central`);
  if (tab === "embeds" && !dom.window.document.querySelector(".sx-embed-layout,.embed-builder")) throw new Error("La page Embeds s'ouvre mais son créateur avancé n'est pas rendu.");
  if (tab === "overview" && !dom.window.document.querySelector(".sx-config-hero")) throw new Error("La vue d'ensemble n'affiche pas le score de configuration réel.");
  if (tab === "access" && !dom.window.document.querySelector(".sx-permission-grid,.sx-command-list")) throw new Error("La page Accès & commandes ne rend pas les permissions/commandes.");
  if (tab === "features") {
    const frame = dom.window.document.querySelector("#sxFeaturesFrame");
    if (!frame) throw new Error("Les fonctions avancées quittent encore le shell V60 au lieu de rendre leur panneau intégré.");
    if (!String(frame.getAttribute("src") || "").includes("/feature-suite?embed=1&guild=1")) throw new Error("Le panneau avancé ne conserve pas le serveur sélectionné.");
    if (!dom.window.document.querySelector(".sx-features-shell")) throw new Error("Le shell V60 des fonctions avancées est absent.");
  }
  if (tab === "dm" && !dom.window.document.querySelector("#dmAllMessage,#dmOneMessage")) throw new Error("La page Messages privés ne rend pas le formulaire autorisé.");
}

const interactivePaths = requests.map(item => item.path);
for (const required of ["/api/guilds/1/diagnostics", "/api/guilds/1/setup-tools", "/api/guilds/1/dm/apercu", "/api/guilds/1/dm/job"]) {
  if (!interactivePaths.includes(required)) throw new Error(`Route interactive jamais chargée: ${required}`);
}

if (runtimeErrors.some(message => /SyntaxError|ReferenceError|TypeError/.test(message))) {
  console.error("Requetes observees:", JSON.stringify(requests, null, 2));
  throw new Error(`Erreur JavaScript dashboard: ${runtimeErrors.join("\n")}`);
}

console.log("Dashboard V60 final browser smoke OK:", interactivePaths.join(" -> "));
console.log("Pages sidebar OK:", expectedTabs.join(", "));
dom.window.close();
