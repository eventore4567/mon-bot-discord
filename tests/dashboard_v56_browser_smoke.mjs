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
  return {
    ok: status >= 200 && status < 300,
    status,
    async json() { return payload; },
  };
}

const dom = new JSDOM(html, {
  url: "https://sentrix.test/app",
  runScripts: "dangerously",
  pretendToBeVisual: true,
  virtualConsole,
  beforeParse(window) {
    window.fetch = async (input, options = {}) => {
      const url = new URL(typeof input === "string" ? input : input.url, window.location.href);
      requests.push({ path: url.pathname, method: String(options.method || "GET").toUpperCase() });
      if (url.pathname === "/api/public") {
        return response({
          ok: true,
          online: true,
          guilds: 20,
          members: 1000,
          latency_ms: 42,
          uptime_seconds: 3600,
          invite_url: "https://discord.com/oauth2/authorize?client_id=1",
          avatar_url: null,
          oauth_ready: true,
        });
      }
      if (url.pathname === "/api/me") {
        return response({
          ok: true,
          user: { id: "42", username: "SentriX Test", avatar_url: null },
          csrf: "test-csrf",
        });
      }
      if (url.pathname === "/api/guilds") {
        return response({
          ok: true,
          guilds: [{ id: "1", name: "Serveur Test", icon_url: null, installed: true }],
        });
      }
      if (url.pathname === "/api/guilds/1") {
        return response({
          ok: true,
          guild: {
            id: "1",
            name: "Serveur Test",
            member_count: 12,
            settings: {},
            automod: {},
            ai: {},
            roles: [],
            channels: [],
            stats: { commands_24h: 0, tickets_open: 0, warnings: 0 },
            notifications: [],
          },
        });
      }
      if (url.pathname === "/api/guilds/1/sanctions") {
        return response({ ok: true, sanctions: [], next_cursor: null });
      }
      return response({ error: `Route mock inconnue: ${url.pathname}` }, 404);
    };
    window.scrollTo = () => {};
  },
});

await new Promise(resolve => setTimeout(resolve, 1200));

const paths = requests.map(item => item.path);
for (const required of ["/api/public", "/api/me", "/api/guilds"]) {
  if (!paths.includes(required)) {
    console.error("Requetes observees:", JSON.stringify(requests, null, 2));
    console.error("Erreurs runtime:", runtimeErrors.join("\n"));
    throw new Error(`Le bootstrap dashboard n'a jamais appelé ${required}`);
  }
}

const dashboard = dom.window.document.getElementById("dashboard");
if (!dashboard || dashboard.classList.contains("hidden")) {
  throw new Error("La session est chargée mais le dashboard reste masqué.");
}

const expectedTabs = [
  "general", "security", "sanctions", "logs", "welcome", "levels", "tickets",
  "ai", "notifications", "embeds", "roles",
];
const buttons = [...dom.window.document.querySelectorAll("#navigation button[data-tab]")];
const actualTabs = buttons.map(button => button.dataset.tab);
for (const tab of expectedTabs) {
  if (!actualTabs.includes(tab)) throw new Error(`Page dashboard absente: ${tab}`);
}

for (const tab of expectedTabs) {
  const button = dom.window.document.querySelector(`#navigation button[data-tab="${tab}"]`);
  button.click();
  await new Promise(resolve => setTimeout(resolve, 30));
  if (!button.classList.contains("active")) {
    throw new Error(`Le clic sidebar n'active pas la page ${tab}`);
  }
  const title = dom.window.document.getElementById("tabTitle")?.textContent?.trim();
  if (!title) throw new Error(`La page ${tab} n'a plus de titre central`);
  if (tab === "embeds" && !dom.window.document.querySelector(".embed-builder")) {
    throw new Error("La page Embeds s'ouvre mais son créateur n'est pas rendu.");
  }
}

if (runtimeErrors.some(message => /SyntaxError|ReferenceError|TypeError/.test(message))) {
  console.error("Requetes observees:", JSON.stringify(requests, null, 2));
  throw new Error(`Erreur JavaScript dashboard: ${runtimeErrors.join("\n")}`);
}

console.log("Dashboard V56 browser smoke OK:", paths.join(" -> "));
console.log("Pages sidebar OK:", expectedTabs.join(", "));
dom.window.close();
