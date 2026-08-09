"""Correctifs de stabilité transversaux du dashboard SentriX.

Cette couche est volontairement installée en dernier. Elle ne change pas les permissions
ni les réglages métier : elle évite surtout les pages blanches, les sessions corrompues,
les doubles enregistrements et les courses lors d'un changement rapide de serveur.
"""

from __future__ import annotations

import asyncio
import logging
import secrets
from urllib.parse import urlparse

from aiohttp import web

logger = logging.getLogger("bot.dashboard.stability")
_INSTALLED = False


ERROR_HTML = """<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="theme-color" content="#090b12">
  <title>SentriX — Dashboard</title>
  <style>
    :root{color-scheme:dark;--bg:#090b12;--panel:#111522;--line:#29304a;--text:#f2f4ff;--muted:#9ca5bc;--brand:#7c6cff}
    *{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;padding:24px;background:radial-gradient(circle at 20% 0,#392d7255,transparent 36%),var(--bg);color:var(--text);font:16px system-ui,-apple-system,"Segoe UI",sans-serif}
    main{width:min(620px,100%);padding:34px;background:var(--panel);border:1px solid var(--line);border-radius:22px;box-shadow:0 28px 80px #0008}h1{margin:0 0 12px;font-size:30px}p{color:var(--muted);line-height:1.65}.actions{display:flex;gap:10px;flex-wrap:wrap;margin-top:24px}a{padding:11px 16px;border-radius:11px;border:1px solid var(--line);color:var(--text);text-decoration:none;font-weight:800;background:#171c2c}a.primary{background:linear-gradient(135deg,var(--brand),#5d4de1);border-color:transparent}.ref{font:12px ui-monospace,monospace;color:#7f88a2;margin-top:20px}
  </style>
</head>
<body><main><h1>Le dashboard a rencontré une erreur</h1><p>SentriX est toujours en ligne. Rechargez le dashboard ; si votre session a expiré, reconnectez-vous avec Discord.</p><div class="actions"><a class="primary" href="/app">Recharger</a><a href="/login">Se reconnecter</a></div><div class="ref">Référence : __REF__</div></main></body>
</html>"""


STABILITY_JS = r"""
<script id="sentrix-dashboard-stability">
(() => {
  "use strict";
  if (window.__sentrixDashboardStability) return;
  window.__sentrixDashboardStability = true;

  const showClientError = message => {
    try {
      if (typeof toast === "function") {
        toast(message || "Le dashboard a rencontré une erreur. Rechargez la page.", true);
        return;
      }
    } catch {}
    console.error("SentriX dashboard:", message);
  };

  window.addEventListener("error", event => {
    const message = event?.error?.message || event?.message || "Erreur JavaScript du dashboard";
    console.error("SentriX dashboard error", event?.error || event);
    showClientError(message);
  });
  window.addEventListener("unhandledrejection", event => {
    const reason = event?.reason;
    const message = reason?.message || String(reason || "Erreur asynchrone du dashboard");
    console.error("SentriX dashboard promise error", reason);
    showClientError(message);
  });

  // Rend toutes les requêtes privées explicites et renvoie vers Discord si la session
  // a réellement expiré, au lieu de laisser l'interface dans un état semi-chargé.
  if (typeof json === "function") {
    const originalJson = json;
    json = async function sentrixStableJson(url, options = {}) {
      const requestOptions = {...options, credentials:"same-origin"};
      try {
        return await originalJson(url, requestOptions);
      } catch (error) {
        const message = String(error?.message || error || "");
        const privateRequest = String(url).startsWith("/api/") && String(url) !== "/api/public";
        if (privateRequest && /connectez-vous|session.*expir|accès refusé/i.test(message)) {
          try { sessionStorage.setItem("sentrix:return-after-login", location.href); } catch {}
          location.href = "/login";
        }
        throw error;
      }
    };
  }

  // Deux changements de serveur simultanés pouvaient se terminer dans le désordre :
  // l'ancienne réponse réseau écrasait parfois le serveur choisi en dernier.
  if (typeof selectGuild === "function" && typeof state !== "undefined") {
    const originalSelectGuild = selectGuild;
    let switching = false;
    let pendingValue = null;

    selectGuild = async function sentrixStableSelectGuild(value) {
      const requested = value == null ? "" : String(value);
      if (switching) {
        pendingValue = requested;
        return;
      }

      switching = true;
      const select = document.getElementById("serverSelect");
      const previousGuild = state.guildId == null ? "" : String(state.guildId);
      if (select) select.disabled = true;

      try {
        await originalSelectGuild(requested);

        if (requested && !requested.startsWith("invite:")) {
          const loadedId = state.guildData?.guild?.id == null ? "" : String(state.guildData.guild.id);
          if (loadedId && loadedId !== requested) {
            state.guildId = previousGuild || null;
            if (select) select.value = previousGuild;
            showClientError("Le changement de serveur n'a pas pu se terminer. Réessayez.");
          }
        }
      } catch (error) {
        state.guildId = previousGuild || null;
        if (select) select.value = previousGuild;
        showClientError(error?.message || "Impossible de charger ce serveur.");
      } finally {
        switching = false;
        if (select) select.disabled = false;
        const next = pendingValue;
        pendingValue = null;
        if (next !== null && next !== String(state.guildId || "")) {
          await selectGuild(next);
        }
      }
    };
  }

  // Empêche le double clic sur Enregistrer/Ajouter : auparavant deux POST/PUT pouvaient
  // partir à quelques millisecondes d'intervalle et provoquer un faux 429.
  const form = document.getElementById("settingsForm");
  const saveButton = document.getElementById("saveButton");
  if (form && saveButton) {
    let submitLocked = false;
    form.addEventListener("submit", event => {
      if (submitLocked) {
        event.preventDefault();
        event.stopImmediatePropagation();
        return;
      }
      submitLocked = true;
      saveButton.disabled = true;
      const release = () => {
        if (!form.classList.contains("loading")) {
          submitLocked = false;
          saveButton.disabled = false;
          observer.disconnect();
        }
      };
      const observer = new MutationObserver(release);
      observer.observe(form, {attributes:true, attributeFilter:["class"]});
      setTimeout(() => {
        submitLocked = false;
        saveButton.disabled = false;
        observer.disconnect();
      }, 12000);
      setTimeout(release, 0);
    }, true);
  }

  // Si l'utilisateur revient avec le cache arrière du navigateur, force une actualisation
  // des données du serveur au lieu de conserver un état vieux de plusieurs minutes.
  window.addEventListener("pageshow", event => {
    if (!event.persisted) return;
    try {
      if (typeof state !== "undefined" && state.guildId && typeof selectGuild === "function") {
        selectGuild(state.guildId);
      }
    } catch {}
  });
})();
</script>
"""


def _safe_public_url(original, request: web.Request) -> str:
    """Nettoie l'URL externe utilisée par OAuth derrière le proxy Railway."""
    try:
        value = str(original(request) or "").strip().rstrip("/")
    except Exception:
        value = ""
    if value:
        try:
            parsed = urlparse(value)
            if parsed.scheme in {"http", "https"} and parsed.netloc:
                return value
        except ValueError:
            pass

    proto = request.headers.get("X-Forwarded-Proto", request.scheme).split(",", 1)[0].strip().lower()
    if proto not in {"http", "https"}:
        proto = "https"
    host = request.headers.get("X-Forwarded-Host", request.host).split(",", 1)[0].strip()
    return f"{proto}://{host}".rstrip("/")


def install(dashboard) -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    original_build_app = dashboard.build_app
    original_session = dashboard._session
    original_public_url = dashboard._public_url

    def safe_session(request: web.Request):
        try:
            session = original_session(request)
        except Exception:
            session = None
        if session is None:
            return None

        user = session.get("user") if isinstance(session, dict) else None
        valid = (
            isinstance(user, dict)
            and str(user.get("id", "")).isdigit()
            and bool(session.get("csrf"))
            and bool(session.get("expires_at"))
        )
        if valid:
            return session

        session_id = request.cookies.get(dashboard.SESSION_COOKIE, "")
        if session_id:
            request.app.get("sessions", {}).pop(session_id, None)

            async def delete_invalid_session() -> None:
                try:
                    await request.app["bot"].db.execute(
                        "DELETE FROM dashboard_sessions WHERE session_id = ?",
                        (session_id,),
                    )
                except Exception:
                    pass

            try:
                asyncio.create_task(delete_invalid_session())
            except RuntimeError:
                pass
        return None

    def public_url(request: web.Request) -> str:
        return _safe_public_url(original_public_url, request)

    @web.middleware
    async def dashboard_errors(request: web.Request, handler):
        try:
            return await handler(request)
        except web.HTTPException:
            raise
        except Exception:
            reference = secrets.token_hex(5)
            logger.exception(
                "Erreur dashboard non gérée [%s] sur %s %s",
                reference,
                request.method,
                request.path,
            )
            if request.path.startswith("/api/"):
                response = dashboard._json_error(
                    f"Le dashboard a rencontré une erreur temporaire. Référence : {reference}",
                    500,
                )
            else:
                response = web.Response(
                    text=ERROR_HTML.replace("__REF__", reference),
                    content_type="text/html",
                    status=500,
                )
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            return response

    def build_app(bot) -> web.Application:
        app = original_build_app(bot)
        # security_headers reste en première position et ajoute donc aussi les protections
        # aux erreurs récupérées par ce middleware.
        insert_at = 1 if len(app.middlewares) >= 1 else 0
        app.middlewares.insert(insert_at, dashboard_errors)
        return app

    dashboard._session = safe_session
    dashboard._public_url = public_url
    dashboard.build_app = build_app

    html = dashboard.INDEX_HTML
    bootstrap = 'Promise.all([loadPublic(),loadSession()]).catch(e=>toast(e.message,true));'
    stable_bootstrap = (
        'setTimeout(()=>Promise.allSettled([loadPublic(),loadSession()]).then(results=>{'
        'for(const result of results){if(result.status==="rejected"&&typeof toast==="function")'
        'toast(result.reason?.message||"Le dashboard n’a pas pu tout charger.",true);}}),0);'
    )
    if bootstrap in html:
        html = html.replace(bootstrap, stable_bootstrap, 1)
    if 'id="sentrix-dashboard-stability"' not in html:
        html = html.replace("</body>", f"{STABILITY_JS}\n</body>", 1)
    dashboard.INDEX_HTML = html

    _INSTALLED = True
    logger.info(
        "Stabilité dashboard activée : erreurs récupérées, sessions validées, requêtes et changements de serveur sécurisés."
    )
