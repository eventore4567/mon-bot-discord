"""Couche UX/performance isolée pour le dashboard SentriX."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time

from aiohttp import web

logger = logging.getLogger("bot.dashboard.polish")
_INSTALLED = False

POLISH_CSS = r"""
<style id="sentrix-polish-css">
  #sentrix-progress{position:fixed;inset:0 auto auto 0;width:0;height:3px;z-index:10000;background:linear-gradient(90deg,#7c6cff,#a897ff,#44d39a);box-shadow:0 0 18px #7c6cffaa;opacity:0;transition:width .2s ease,opacity .25s ease;pointer-events:none}
  #sentrix-progress.active{opacity:1}
  #sentrix-offline{position:fixed;top:14px;left:50%;transform:translateX(-50%) translateY(-140%);z-index:10001;padding:10px 14px;border-radius:12px;background:#341720;border:1px solid #743348;color:#ffb8c4;font-weight:800;box-shadow:0 14px 38px #0008;transition:transform .25s ease;max-width:min(92vw,620px);text-align:center}
  #sentrix-offline.show{transform:translateX(-50%) translateY(0)}
  #sentrix-health{position:fixed;right:18px;bottom:18px;z-index:9500;display:flex;align-items:center;gap:8px;padding:9px 12px;border:1px solid var(--line,#29304a);border-radius:999px;background:#101522e8;backdrop-filter:blur(12px);box-shadow:0 12px 36px #0007;color:var(--muted,#9ca5bc);font-size:12px;font-weight:800;transition:.2s}
  #sentrix-health i{width:8px;height:8px;border-radius:50%;background:#44d39a;box-shadow:0 0 12px #44d39a}
  #sentrix-health.bad i{background:#ff667d;box-shadow:0 0 12px #ff667d}
  #sentrix-health.busy i{background:#f2bd5a;box-shadow:0 0 12px #f2bd5a}
  #sentrix-mobile-toggle{display:none;position:fixed;left:12px;bottom:14px;z-index:9801;width:46px;height:46px;border:1px solid var(--line,#29304a);border-radius:14px;background:#171c2cf2;color:#fff;font-size:20px;box-shadow:0 14px 35px #0008;cursor:pointer}
  #sentrix-mobile-overlay{display:none;position:fixed;inset:0;z-index:9790;background:#0009;backdrop-filter:blur(2px)}
  .sentrix-busy{opacity:.72!important;pointer-events:none!important}
  .sentrix-dirty-dot{display:inline-flex;align-items:center;gap:7px;color:#f2bd5a!important;font-weight:800}
  .sentrix-dirty-dot::before{content:"";width:8px;height:8px;border-radius:50%;background:#f2bd5a;box-shadow:0 0 12px #f2bd5a}
  .sentrix-saved-dot{display:inline-flex;align-items:center;gap:7px;color:#7fe0bb!important;font-weight:800}
  .sentrix-saved-dot::before{content:"✓";font-weight:950}
  .sentrix-quick-link{display:flex!important;width:100%;align-items:center;justify-content:flex-start!important;gap:9px;text-decoration:none!important}
  .savebar{position:sticky!important;bottom:12px!important;z-index:30!important;padding:12px!important;border:1px solid var(--line,#29304a)!important;border-radius:14px!important;background:#111522e8!important;backdrop-filter:blur(16px)!important;box-shadow:0 16px 42px #0008!important}
  .card,.metric,.sanction-card,.notification-item,.feature,.field{content-visibility:auto;contain-intrinsic-size:1px 90px}
  button:focus-visible,a:focus-visible,input:focus-visible,select:focus-visible,textarea:focus-visible{outline:3px solid #a897ff!important;outline-offset:2px!important}
  .loading .card,.loading .metric,.loading .field,.loading .sanction-card{animation:sentrix-pulse 1.15s ease-in-out infinite alternate}
  @keyframes sentrix-pulse{from{opacity:.52}to{opacity:.9}}
  @media(max-width:880px){
    #sentrix-mobile-toggle{display:grid;place-items:center}
    .shell{display:block!important}.side{position:fixed!important;left:0!important;top:0!important;bottom:0!important;width:min(86vw,310px)!important;z-index:9800!important;transform:translateX(-105%);transition:transform .24s ease;box-shadow:18px 0 55px #000a}.side.sentrix-open{transform:translateX(0)}
    #sentrix-mobile-overlay.show{display:block}.workspace{padding:24px 16px 80px!important}.workspace-head{align-items:stretch!important;flex-direction:column!important}.server-select{min-width:0!important;width:100%!important}.overview{grid-template-columns:repeat(2,minmax(0,1fr))!important}.grid{grid-template-columns:1fr!important}.full{grid-column:auto!important}
    #sentrix-health{right:12px;bottom:72px}
  }
  @media(max-width:540px){.overview{grid-template-columns:1fr!important}.panel-head,.panel-body,.content{padding-left:15px!important;padding-right:15px!important}.btn{min-height:42px}.savebar{bottom:70px!important}}
  @media(prefers-reduced-motion:reduce){*,*::before,*::after{animation-duration:.001ms!important;animation-iteration-count:1!important;scroll-behavior:auto!important;transition-duration:.001ms!important}}
</style>
"""

POLISH_JS = r"""
<script id="sentrix-polish-js">
(() => {
  "use strict";
  if (window.__sentrixPolishLoaded) return;
  window.__sentrixPolishLoaded = true;

  const originalFetch = window.fetch.bind(window);
  const inflight = new Map();
  let pendingRequests = 0;
  let activeButton = null;
  let dirty = false;
  let savedTimer = null;

  const create = (tag, attrs = {}, text = "") => {
    const element = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs)) {
      if (key === "class") element.className = value;
      else if (key === "html") element.innerHTML = value;
      else element.setAttribute(key, value);
    }
    if (text) element.textContent = text;
    return element;
  };

  const progress = create("div", {id:"sentrix-progress", "aria-hidden":"true"});
  const offline = create("div", {id:"sentrix-offline", role:"status", "aria-live":"polite"}, "Connexion perdue — les modifications ne peuvent pas être enregistrées.");
  const health = create("div", {id:"sentrix-health", role:"status", "aria-live":"polite", class:"busy"});
  health.innerHTML = "<i></i><span>Connexion…</span>";
  document.documentElement.append(progress, offline);
  document.body.appendChild(health);

  function setProgress(active) {
    if (active) {
      pendingRequests += 1;
      progress.classList.add("active");
      progress.style.width = pendingRequests === 1 ? "34%" : "68%";
    } else {
      pendingRequests = Math.max(0, pendingRequests - 1);
      if (!pendingRequests) {
        progress.style.width = "100%";
        setTimeout(() => {
          progress.classList.remove("active");
          progress.style.width = "0";
        }, 180);
      } else {
        progress.style.width = "78%";
      }
    }
  }

  function setOffline(isOffline, message = "") {
    offline.textContent = message || "Connexion perdue — les modifications ne peuvent pas être enregistrées.";
    offline.classList.toggle("show", Boolean(isOffline));
    health.classList.toggle("bad", Boolean(isOffline));
    health.classList.toggle("busy", false);
    health.querySelector("span").textContent = isOffline ? "Hors ligne" : "Connecté";
  }

  function setButtonBusy(button, busy) {
    if (!(button instanceof HTMLElement)) return;
    button.classList.toggle("sentrix-busy", busy);
    button.setAttribute("aria-busy", busy ? "true" : "false");
  }

  function cloneResponse(response) {
    try { return response.clone(); } catch { return response; }
  }

  async function performFetch(input, init, retry = true) {
    const method = String(init?.method || (input instanceof Request ? input.method : "GET")).toUpperCase();
    const target = typeof input === "string" ? input : input.url;
    const url = new URL(target, location.href);
    const sameOrigin = url.origin === location.origin;
    const controller = new AbortController();
    const externalSignal = init?.signal;
    if (externalSignal) {
      if (externalSignal.aborted) controller.abort(externalSignal.reason);
      else externalSignal.addEventListener("abort", () => controller.abort(externalSignal.reason), {once:true});
    }
    const timeout = setTimeout(() => controller.abort(new DOMException("Délai dépassé", "TimeoutError")), 16000);
    try {
      const response = await originalFetch(input, {...(init || {}), signal:controller.signal});
      if (retry && method === "GET" && [502,503,504].includes(response.status)) {
        await new Promise(resolve => setTimeout(resolve, 350));
        return performFetch(input, init, false);
      }
      if (sameOrigin && response.status === 401 && url.pathname.startsWith("/api/")) {
        setOffline(true, "Votre session a expiré — reconnectez-vous avec Discord.");
      } else if (response.ok) {
        setOffline(false);
      }
      return response;
    } catch (error) {
      if (retry && method === "GET" && error?.name !== "AbortError") {
        await new Promise(resolve => setTimeout(resolve, 350));
        return performFetch(input, init, false);
      }
      const message = error?.name === "TimeoutError" || error?.name === "AbortError"
        ? "Le serveur met trop de temps à répondre. Réessayez."
        : "Connexion au dashboard impossible. Vérifiez Internet.";
      setOffline(true, message);
      throw error;
    } finally {
      clearTimeout(timeout);
    }
  }

  window.fetch = async function sentrixFetch(input, init = {}) {
    const method = String(init?.method || (input instanceof Request ? input.method : "GET")).toUpperCase();
    const target = typeof input === "string" ? input : input.url;
    const url = new URL(target, location.href);
    const dedupe = method === "GET" && url.origin === location.origin;
    const key = `${method} ${url.href}`;
    const button = activeButton;
    setProgress(true);
    setButtonBusy(button, true);
    try {
      if (dedupe && inflight.has(key)) return cloneResponse(await inflight.get(key));
      const promise = performFetch(input, init);
      if (dedupe) inflight.set(key, promise);
      const response = await promise;
      if (method !== "GET" && response.ok) {
        markSaved();
      }
      return cloneResponse(response);
    } finally {
      if (dedupe) inflight.delete(key);
      setProgress(false);
      setButtonBusy(button, false);
      if (activeButton === button) activeButton = null;
    }
  };

  window.addEventListener("offline", () => setOffline(true));
  window.addEventListener("online", () => {
    setOffline(false);
    checkHealth();
  });

  function storageKey(name) {
    const page = location.pathname.includes("setup-center") ? "setup" : location.pathname.includes("embed-builder") ? "embed" : "main";
    return `sentrix:${page}:${name}`;
  }

  function markDirty() {
    if (dirty) return;
    dirty = true;
    document.body.dataset.sentrixDirty = "1";
    const status = document.getElementById("saveStatus");
    if (status) {
      status.textContent = "Modifications non enregistrées";
      status.classList.remove("sentrix-saved-dot");
      status.classList.add("sentrix-dirty-dot");
    }
  }

  function markSaved() {
    dirty = false;
    delete document.body.dataset.sentrixDirty;
    const status = document.getElementById("saveStatus");
    if (status) {
      status.classList.remove("sentrix-dirty-dot");
      status.classList.add("sentrix-saved-dot");
      clearTimeout(savedTimer);
      savedTimer = setTimeout(() => status.classList.remove("sentrix-saved-dot"), 3200);
    }
  }

  function shouldTrack(element) {
    if (!(element instanceof HTMLInputElement || element instanceof HTMLSelectElement || element instanceof HTMLTextAreaElement)) return false;
    if (element.type === "search" || element.dataset.noDirty === "1") return false;
    if (element.closest(".setup-channel-search,.channel-search,.sanction-toolbar")) return false;
    return Boolean(element.closest("#settingsForm,#content,.panel,.embed-form"));
  }

  document.addEventListener("input", event => {
    if (shouldTrack(event.target)) markDirty();
  }, true);
  document.addEventListener("change", event => {
    if (shouldTrack(event.target)) markDirty();
  }, true);
  document.addEventListener("click", event => {
    const button = event.target.closest("button,.btn");
    if (button) {
      activeButton = button;
      setTimeout(() => { if (activeButton === button) activeButton = null; }, 900);
    }
  }, true);

  window.addEventListener("beforeunload", event => {
    if (!dirty) return;
    event.preventDefault();
    event.returnValue = "";
  });

  document.addEventListener("click", event => {
    const destination = event.target.closest("[data-tab]");
    if (!destination) return;
    if (dirty && !confirm("Vous avez des modifications non enregistrées. Changer d’onglet quand même ?")) {
      event.preventDefault();
      event.stopImmediatePropagation();
      return;
    }
    const tab = destination.getAttribute("data-tab");
    if (tab) localStorage.setItem(storageKey("tab"), tab);
    markSaved();
    if (window.matchMedia("(max-width:880px)").matches) closeMobileMenu();
    setTimeout(() => document.querySelector(".workspace,.content")?.scrollTo?.({top:0,behavior:"smooth"}), 0);
  }, true);

  function confirmServerChange(event) {
    if (!dirty) return true;
    if (confirm("Des modifications ne sont pas enregistrées. Changer de serveur quand même ?")) {
      markSaved();
      return true;
    }
    event.preventDefault();
    event.stopImmediatePropagation();
    return false;
  }

  for (const id of ["serverSelect", "guild"]) {
    document.addEventListener("change", event => {
      if (event.target?.id !== id) return;
      if (!confirmServerChange(event)) return;
      if (event.target.value && !String(event.target.value).startsWith("invite:")) {
        localStorage.setItem(storageKey("guild"), event.target.value);
      }
    }, true);
  }

  function restoreSelect(id) {
    const saved = localStorage.getItem(storageKey("guild"));
    if (!saved) return;
    let attempts = 0;
    const timer = setInterval(() => {
      attempts += 1;
      const select = document.getElementById(id);
      if (select instanceof HTMLSelectElement && [...select.options].some(option => option.value === saved)) {
        clearInterval(timer);
        if (select.value !== saved) {
          select.value = saved;
          select.dispatchEvent(new Event("change", {bubbles:true}));
        }
      } else if (attempts > 40) clearInterval(timer);
    }, 150);
  }

  function restoreTab() {
    const saved = localStorage.getItem(storageKey("tab"));
    if (!saved) return;
    let attempts = 0;
    const timer = setInterval(() => {
      attempts += 1;
      const button = document.querySelector(`[data-tab="${CSS.escape(saved)}"]`);
      if (button instanceof HTMLElement) {
        clearInterval(timer);
        button.click();
      } else if (attempts > 40) clearInterval(timer);
    }, 180);
  }

  function installMobileMenu() {
    const side = document.querySelector(".side");
    if (!side || document.getElementById("sentrix-mobile-toggle")) return;
    const toggle = create("button", {id:"sentrix-mobile-toggle", type:"button", "aria-label":"Ouvrir le menu", "aria-expanded":"false"}, "☰");
    const overlay = create("div", {id:"sentrix-mobile-overlay"});
    document.body.append(overlay, toggle);
    toggle.addEventListener("click", () => side.classList.contains("sentrix-open") ? closeMobileMenu() : openMobileMenu());
    overlay.addEventListener("click", closeMobileMenu);
  }

  function openMobileMenu() {
    const side = document.querySelector(".side");
    const toggle = document.getElementById("sentrix-mobile-toggle");
    side?.classList.add("sentrix-open");
    document.getElementById("sentrix-mobile-overlay")?.classList.add("show");
    toggle?.setAttribute("aria-expanded", "true");
    if (toggle) toggle.textContent = "✕";
  }

  function closeMobileMenu() {
    const side = document.querySelector(".side");
    const toggle = document.getElementById("sentrix-mobile-toggle");
    side?.classList.remove("sentrix-open");
    document.getElementById("sentrix-mobile-overlay")?.classList.remove("show");
    toggle?.setAttribute("aria-expanded", "false");
    if (toggle) toggle.textContent = "☰";
  }

  function addQuickLinks() {
    const sideBottom = document.querySelector(".side-bottom");
    if (sideBottom && !sideBottom.querySelector('[href="/embed-builder"]')) {
      const embed = create("a", {href:"/embed-builder", class:"btn sentrix-quick-link"}, "📨 Créateur d’embeds");
      sideBottom.prepend(embed);
    }
    const actions = document.querySelector("header .actions,.top .actions");
    if (actions && !actions.querySelector('[href="/embed-builder"]')) {
      actions.appendChild(create("a", {href:"/embed-builder", class:"btn"}, "📨 Embeds"));
    }
  }

  function improveAccessibility() {
    for (const id of ["toast", "status", "saveStatus"]) {
      const element = document.getElementById(id);
      if (element) {
        element.setAttribute("aria-live", "polite");
        element.setAttribute("role", "status");
      }
    }
    document.querySelectorAll("button:not([type])").forEach(button => button.setAttribute("type", "button"));
  }

  async function checkHealth() {
    try {
      health.classList.add("busy");
      const response = await originalFetch("/health", {cache:"no-store"});
      const data = await response.json();
      const ok = Boolean(response.ok && data.ok && data.discord_ready);
      health.classList.toggle("bad", !ok);
      health.classList.remove("busy");
      health.querySelector("span").textContent = ok ? `${data.latency_ms ?? "—"} ms` : "Bot en reconnexion";
    } catch {
      health.classList.add("bad");
      health.classList.remove("busy");
      health.querySelector("span").textContent = "Indisponible";
    }
  }

  document.addEventListener("keydown", event => {
    const modifier = event.ctrlKey || event.metaKey;
    if (modifier && event.key.toLowerCase() === "s") {
      event.preventDefault();
      const button = document.querySelector("#saveButton:not(.hidden),#saveGames,#saveDesign,#sendEmbed");
      if (button instanceof HTMLButtonElement && !button.disabled) button.click();
    }
    if (modifier && event.key.toLowerCase() === "k") {
      event.preventDefault();
      const search = [...document.querySelectorAll('input[type="search"]')].find(element => element.offsetParent !== null);
      const target = search || document.getElementById("serverSelect") || document.getElementById("guild");
      target?.focus();
    }
    if (event.key === "Escape") closeMobileMenu();
  });

  const observer = new MutationObserver(() => {
    installMobileMenu();
    addQuickLinks();
    improveAccessibility();
  });
  observer.observe(document.body, {childList:true, subtree:true});

  installMobileMenu();
  addQuickLinks();
  improveAccessibility();
  restoreSelect("serverSelect");
  restoreSelect("guild");
  restoreTab();
  checkHealth();
  setInterval(checkHealth, 45000);
  if (!navigator.onLine) setOffline(true);
})();
</script>
"""


def _inject(html: str) -> str:
    if "sentrix-polish-js" in html:
        return html
    if "</head>" not in html or "</body>" not in html:
        logger.warning("Fluidité dashboard : balises d'insertion introuvables.")
        return html
    html = html.replace("</head>", POLISH_CSS + "\n</head>", 1)
    return html.replace("</body>", POLISH_JS + "\n</body>", 1)


async def _cleanup_runtime_state(app: web.Application) -> None:
    """Évite que les sessions expirées et limites d’écriture restent en mémoire."""
    while True:
        await asyncio.sleep(600)
        current = time.time()
        sessions = app.get("sessions", {})
        for key, session in list(sessions.items()):
            if float(session.get("expires_at", 0)) <= current:
                sessions.pop(key, None)
        oauth_states = app.get("oauth_states", {})
        for key, expires_at in list(oauth_states.items()):
            if float(expires_at or 0) <= current:
                oauth_states.pop(key, None)
        write_limits = app.get("write_limits", {})
        for key, timestamp in list(write_limits.items()):
            if current - float(timestamp or 0) > 3600:
                write_limits.pop(key, None)


def install(dashboard, setup_center, embed_center=None) -> None:
    """Ajoute la couche UX et les optimisations serveur sans réécrire le dashboard."""
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    dashboard.INDEX_HTML = _inject(dashboard.INDEX_HTML)
    setup_center.SETUP_CENTER_HTML = _inject(setup_center.SETUP_CENTER_HTML)
    if embed_center is not None:
        embed_center.EMBED_CENTER_HTML = _inject(embed_center.EMBED_CENTER_HTML)

    original_build_app = dashboard.build_app

    @web.middleware
    async def performance_middleware(request: web.Request, handler):
        started = time.perf_counter()
        response = await handler(request)
        elapsed_ms = (time.perf_counter() - started) * 1000
        response.headers["Server-Timing"] = f"sentrix;dur={elapsed_ms:.1f}"
        response.headers["X-Response-Time"] = f"{elapsed_ms:.1f}ms"
        try:
            content_type = (response.content_type or "").lower()
            body_length = response.content_length or 0
            if body_length >= 1024 and (content_type.startswith("text/") or content_type == "application/json"):
                response.enable_compression()
        except (AttributeError, RuntimeError):
            pass
        return response

    async def start_cleanup(app: web.Application):
        app["sentrix_runtime_cleanup"] = asyncio.create_task(_cleanup_runtime_state(app))

    async def stop_cleanup(app: web.Application):
        task = app.get("sentrix_runtime_cleanup")
        if task is None:
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    def build_app(bot) -> web.Application:
        app = original_build_app(bot)
        # Après les en-têtes de sécurité, avant le verrou Administrateur installé en dernier.
        app.middlewares.append(performance_middleware)
        app.on_startup.append(start_cleanup)
        app.on_cleanup.append(stop_cleanup)
        return app

    dashboard.build_app = build_app
    logger.info("Couche Fluidité Pro du dashboard chargée.")
