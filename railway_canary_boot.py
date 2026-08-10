"""Bootstrap d'un service Railway SentriX Beta/Canary complètement séparé.

Ce processus exige un second bot Discord (CANARY_BOT_TOKEN) et refuse volontairement
le token de production. Il utilise une base séparée et quitte tout serveur autre que
CANARY_GUILD_ID. Le service principal continue d'utiliser railway_boot.py.
"""
from __future__ import annotations

import asyncio
import logging
import os
import traceback

from aiohttp import web
from discord.ext import commands

# Le mode doit être défini AVANT l'import de config/main.
os.environ["SENTRIX_CANARY_MODE"] = "1"
os.environ["DATABASE_PATH"] = os.getenv("CANARY_DATABASE_PATH", "database/canary.db")

import config

CANARY_TOKEN = os.getenv("CANARY_BOT_TOKEN", "").strip()
if not CANARY_TOKEN:
    raise RuntimeError("CANARY_BOT_TOKEN manquant pour le service SentriX Canary.")
if CANARY_TOKEN == (config.DISCORD_TOKEN or ""):
    raise RuntimeError("CANARY_BOT_TOKEN doit être différent du DISCORD_TOKEN de production.")
if not config.CANARY_GUILD_ID:
    raise RuntimeError("CANARY_GUILD_ID manquant pour le service SentriX Canary.")


class CanaryBotBase(commands.AutoShardedBot):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("shard_count", 1)
        super().__init__(*args, **kwargs)


if not getattr(commands, "_sentrix_canary_bootstrap", False):
    commands.Bot = CanaryBotBase
    commands._sentrix_canary_bootstrap = True

import main as bot_main

logger = logging.getLogger("bot.canary")


async def _no_dashboard(_bot):
    return None


async def _start_health(bot):
    async def health(_request):
        target = bot.get_guild(config.CANARY_GUILD_ID)
        ready = bool(bot.is_ready() and target is not None)
        payload = {
            "ok": ready,
            "mode": "canary",
            "discord_ready": bot.is_ready(),
            "canary_guild_ready": target is not None,
            "guild_id": config.CANARY_GUILD_ID,
            "latency_ms": round(bot.latency * 1000) if bot.is_ready() else None,
        }
        return web.json_response(payload, status=200 if ready else 503)

    app = web.Application()
    app.router.add_get("/health", health)
    app.router.add_get("/", health)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", "8080"))
    await web.TCPSite(runner, "0.0.0.0", port).start()
    return runner


async def run() -> None:
    bot = bot_main.BotAllInOne()
    bot_main.start_dashboard = _no_dashboard
    await bot.db.connect()

    original_connect = bot.db.connect

    async def already_connected():
        return None

    bot.db.connect = already_connected
    runner = await _start_health(bot)

    @bot.listen("on_ready")
    async def canary_isolation():
        # Ce token appartient obligatoirement au bot Beta. Toute invitation accidentelle
        # hors du serveur de test est immédiatement quittée.
        for guild in list(bot.guilds):
            if guild.id != config.CANARY_GUILD_ID:
                try:
                    await guild.leave()
                except Exception:
                    logger.exception("Impossible de quitter un serveur non-canary %s.", guild.id)

    try:
        async with bot:
            await bot.start(CANARY_TOKEN)
    except Exception:
        logger.critical("Le service Canary s'est arrêté :\n%s", traceback.format_exc())
        raise
    finally:
        bot.db.connect = original_connect
        try:
            infra = getattr(bot, "sentrix_infra", None)
            if infra is not None:
                await infra.close()
        except Exception:
            pass
        try:
            await bot.db.close()
        except Exception:
            pass
        await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(run())
