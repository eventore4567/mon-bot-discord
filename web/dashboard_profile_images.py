"""Photos de profil fiables pour le dashboard SentriX.

Le navigateur ne charge plus directement les avatars Discord. Le serveur web lit les
assets via discord.py puis les sert en same-origin, ce qui évite les icônes d'image cassée
liées au CDN, au cache, au CSP ou à un avatar Discord modifié entre deux sessions.

Cette couche n'enveloppe aucune fonction JavaScript critique du dashboard.
"""

from __future__ import annotations

import html
import logging

import discord
from aiohttp import web

logger = logging.getLogger("bot.dashboard.profile-images")
_INSTALLED = False


def _content_type(data: bytes) -> str:
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    return "application/octet-stream"


def _fallback_svg(letter: str, *, bot: bool = False) -> web.Response:
    safe = html.escape((letter or "S")[:1].upper())
    start = "#8b72ff" if bot else "#59627d"
    end = "#5944d2" if bot else "#2c3347"
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128">
<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop stop-color="{start}"/><stop offset="1" stop-color="{end}"/></linearGradient></defs>
<rect width="128" height="128" rx="30" fill="url(#g)"/>
<circle cx="64" cy="64" r="47" fill="#ffffff10" stroke="#ffffff26" stroke-width="2"/>
<text x="64" y="80" text-anchor="middle" font-family="Arial,Helvetica,sans-serif" font-size="58" font-weight="800" fill="white">{safe}</text>
</svg>"""
    return web.Response(
        text=svg,
        content_type="image/svg+xml",
        headers={"Cache-Control": "no-store"},
    )


async def _asset_response(asset: discord.Asset | None, fallback_letter: str, *, bot: bool = False) -> web.Response:
    if asset is None:
        return _fallback_svg(fallback_letter, bot=bot)
    try:
        data = await asset.read()
    except Exception:
        logger.debug("Lecture d'un avatar Discord impossible.", exc_info=True)
        return _fallback_svg(fallback_letter, bot=bot)
    return web.Response(
        body=data,
        content_type=_content_type(data),
        headers={"Cache-Control": "private, max-age=120"},
    )


PROFILE_CSS = r"""
<style id="sentrix-profile-images-css">
  #publicLogo,#appLogo,#userAvatar{overflow:hidden;position:relative;flex:0 0 auto}
  #publicLogo img,#appLogo img,#userAvatar img{display:block;width:100%;height:100%;object-fit:cover}
  #userAvatar{border-radius:50%!important;background:#20263a!important;box-shadow:0 0 0 2px #ffffff0b,0 8px 22px #0005}
  #userAvatar img{border-radius:50%!important}
  #publicLogo img,#appLogo img{border-radius:inherit}
</style>
"""


PROFILE_JS = r"""
<script id="sentrix-profile-images-js">
(() => {
  "use strict";
  if (window.__sentrixProfileImages) return;
  window.__sentrixProfileImages = true;

  function putImage(id, src, fallback, alt) {
    const box = document.getElementById(id);
    if (!box) return;
    const current = box.querySelector("img[data-sentrix-profile]");
    if (current && current.dataset.source === src) return;

    const image = document.createElement("img");
    image.dataset.sentrixProfile = "1";
    image.dataset.source = src;
    image.alt = alt || "Photo de profil";
    image.decoding = "async";
    image.loading = "eager";
    image.src = src;
    image.addEventListener("error", () => {
      image.remove();
      box.textContent = fallback;
    }, {once:true});
    box.replaceChildren(image);
  }

  function refreshBotAvatar() {
    putImage("publicLogo", "/assets/sentrix-avatar", "S", "Photo de profil de SentriX");
    putImage("appLogo", "/assets/sentrix-avatar", "S", "Photo de profil de SentriX");
  }

  function refreshUserAvatar() {
    let username = "Utilisateur";
    try {
      if (typeof state !== "undefined" && state.user?.username) username = state.user.username;
    } catch (_) {}
    putImage("userAvatar", "/assets/user-avatar", String(username).slice(0,1).toUpperCase() || "U", `Photo de profil de ${username}`);
  }

  refreshBotAvatar();
  refreshUserAvatar();

  // La session OAuth peut terminer après le chargement du script. On rafraîchit seulement
  // les images, sans toucher aux clics, formulaires ou fonctions du dashboard.
  let attempts = 0;
  const timer = setInterval(() => {
    attempts += 1;
    refreshBotAvatar();
    refreshUserAvatar();
    let ready = false;
    try { ready = typeof state !== "undefined" && Boolean(state.user); } catch (_) {}
    if ((ready && attempts >= 4) || attempts >= 30) clearInterval(timer);
  }, 500);

  window.addEventListener("pageshow", () => {
    refreshBotAvatar();
    refreshUserAvatar();
  });
})();
</script>
"""


def install(dashboard) -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    original_build_app = dashboard.build_app

    async def sentrix_avatar(request: web.Request):
        bot = request.app["bot"]
        user = bot.user
        return await _asset_response(
            getattr(user, "display_avatar", None) if user else None,
            "S",
            bot=True,
        )

    async def user_avatar(request: web.Request):
        session = dashboard._session(request)
        if not session:
            return _fallback_svg("U")

        user_data = session.get("user") or {}
        user_id_raw = user_data.get("id")
        username = str(user_data.get("username") or "U")
        try:
            user_id = int(user_id_raw)
        except (TypeError, ValueError):
            return _fallback_svg(username[:1])

        bot = request.app["bot"]
        user = bot.get_user(user_id)
        if user is None:
            try:
                user = await bot.fetch_user(user_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                user = None
        return await _asset_response(
            getattr(user, "display_avatar", None) if user else None,
            username[:1],
        )

    def build_app(bot) -> web.Application:
        app = original_build_app(bot)
        app.router.add_get("/assets/sentrix-avatar", sentrix_avatar)
        app.router.add_get("/assets/user-avatar", user_avatar)
        return app

    dashboard.build_app = build_app

    html_text = dashboard.INDEX_HTML
    if 'id="sentrix-profile-images-css"' not in html_text:
        html_text = html_text.replace("</head>", PROFILE_CSS + "\n</head>", 1)
    if 'id="sentrix-profile-images-js"' not in html_text:
        html_text = html_text.replace("</body>", PROFILE_JS + "\n</body>", 1)
    dashboard.INDEX_HTML = html_text
    logger.info("Photos de profil dashboard servies en local avec fallback fiable.")
