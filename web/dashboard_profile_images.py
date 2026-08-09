"""Photos de profil fiables pour le dashboard SentriX.

Le navigateur ne charge plus directement les avatars Discord. Le serveur web lit les
assets via discord.py puis les sert en same-origin. La photo de profil du tableau de bord
utilise maintenant le T personnalisé demandé, sans dépendre du CDN Discord.

Cette couche n'enveloppe aucune fonction JavaScript critique du dashboard.
"""

from __future__ import annotations

import base64
import html
import logging

import discord
from aiohttp import web

logger = logging.getLogger("bot.dashboard.profile-images")
_INSTALLED = False

# Avatar T personnalisé compressé en WebP 256x256.
_CUSTOM_USER_AVATAR = base64.b64decode(
    "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"
)


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
  #userAvatar{
    border-radius:50%!important;
    background:#090b12!important;
    box-shadow:0 0 0 2px #8b72ff55,0 0 18px #8b72ff40,0 8px 22px #0007;
  }
  #userAvatar img{border-radius:50%!important;transform:scale(1.06)}
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
    putImage("userAvatar", "/assets/user-avatar?v=t3d", "T", "Photo de profil T");
  }

  refreshBotAvatar();
  refreshUserAvatar();

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
        # L'avatar T est volontairement local au dashboard et ne dépend d'aucun CDN.
        return web.Response(
            body=_CUSTOM_USER_AVATAR,
            content_type="image/webp",
            headers={
                "Cache-Control": "public, max-age=86400",
                "X-Content-Type-Options": "nosniff",
            },
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
    logger.info("Avatar T personnalisé chargé dans le dashboard.")
