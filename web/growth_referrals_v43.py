"""Suivi marketing minimal SentriX V43.

Mesure uniquement la source d'un clic vers l'installation du bot. Aucune IP, aucun user-agent,
aucun identifiant Discord et aucun cookie marketing n'est collecté. Les liens /go/<source>
peuvent être utilisés sur Top.gg, TikTok, YouTube, DiscordBotList, bots.gg et partenariats.
"""
from __future__ import annotations

import html
import time

from aiohttp import web

_INSTALLED = False
_ALLOWED = {
    "topgg": "Top.gg",
    "discordbotlist": "DiscordBotList",
    "botsgg": "Bots.gg",
    "discordlist": "DiscordList",
    "tiktok": "TikTok",
    "youtube": "YouTube",
    "partner": "Partenariat",
    "discord": "Discord",
    "other": "Autre",
}


async def _ensure_table(bot) -> None:
    await bot.db.execute(
        """
        CREATE TABLE IF NOT EXISTS marketing_referral_clicks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            created_at INTEGER NOT NULL
        )
        """
    )
    await bot.db.execute(
        "CREATE INDEX IF NOT EXISTS idx_marketing_referral_source_time "
        "ON marketing_referral_clicks(source, created_at)"
    )


def _invite(request: web.Request) -> str:
    dashboard = request.app["dashboard_module"]
    return str(dashboard._invite_url(request.app["bot"]) or f"{dashboard._public_url(request).rstrip('/')}/start")


async def referral_redirect(request: web.Request) -> web.StreamResponse:
    source = str(request.match_info.get("source") or "").strip().casefold()
    if source not in _ALLOWED:
        source = "other"
    bot = request.app["bot"]
    try:
        await _ensure_table(bot)
        await bot.db.execute(
            "INSERT INTO marketing_referral_clicks(source, created_at) VALUES(?, ?)",
            (source, int(time.time())),
        )
    except Exception:
        # Le suivi ne doit jamais empêcher une installation.
        pass
    raise web.HTTPFound(_invite(request), headers={"Cache-Control": "no-store", "X-Robots-Tag": "noindex, nofollow"})


async def referral_stats(request: web.Request) -> web.Response:
    bot = request.app["bot"]
    rows = []
    try:
        await _ensure_table(bot)
        rows = await bot.db.fetchall(
            "SELECT source, COUNT(*) AS clicks FROM marketing_referral_clicks GROUP BY source ORDER BY clicks DESC"
        )
    except Exception:
        rows = []
    counts = {str(row["source"]): int(row["clicks"] or 0) for row in rows}
    total = sum(counts.values())
    cards = "".join(
        f'<div class="card"><strong>{html.escape(label)}</strong><span>{counts.get(key, 0)}</span></div>'
        for key, label in _ALLOWED.items()
    )
    body = f'''<!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex,nofollow"><title>SentriX — Sources marketing</title><style>body{{margin:0;background:#080a11;color:#f4f6ff;font:15px system-ui;padding:40px}}main{{max-width:900px;margin:auto}}h1{{font-size:38px}}p{{color:#a3acc2}}.total{{font-size:28px;font-weight:900;margin:20px 0}}.grid{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}}.card{{border:1px solid #283047;background:#111522;border-radius:14px;padding:18px}}.card strong{{display:block;margin-bottom:8px}}.card span{{font-size:30px;font-weight:900}}code{{background:#151a29;padding:3px 6px;border-radius:6px}}@media(max-width:700px){{.grid{{grid-template-columns:1fr}}}}</style></head><body><main><h1>Sources d'installation SentriX</h1><p>Compteur anonyme de clics sur les liens de campagne. Aucune IP, aucun cookie marketing et aucun identifiant Discord n'est enregistré.</p><div class="total">{total} clic(s) suivis</div><div class="grid">{cards}</div><p>Exemple : <code>/go/topgg</code>, <code>/go/tiktok</code>, <code>/go/youtube</code>, <code>/go/partner</code>.</p></main></body></html>'''
    return web.Response(text=body, content_type="text/html", headers={"Cache-Control": "no-store", "X-Robots-Tag": "noindex, nofollow"})


def install(dashboard) -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    original_build_app = dashboard.build_app

    def build_app(bot):
        app = original_build_app(bot)
        # Listener opérationnel : n'altère jamais l'arrivée du bot dans un serveur.
        guild_join_notify_v46.install(bot)
        app.router.add_get("/go/{source}", referral_redirect)
        app.router.add_get("/marketing-stats", referral_stats)

        async def prepare_referrals(_app):
            try:
                await _ensure_table(bot)
            except Exception:
                pass

        app.on_startup.append(prepare_referrals)
        return app

    dashboard.build_app = build_app

    # Les couches V44/V45/V46 sont installées ici car V43 est déjà appelée en dernier par
    # l'identité publique V39. Cela garantit qu'elles sont branchées avant build_app().
    from . import bot_directory_stats_v44, guild_join_notify_v46, health_runtime_v45

    bot_directory_stats_v44.install(dashboard)
    health_runtime_v45.install(dashboard)
