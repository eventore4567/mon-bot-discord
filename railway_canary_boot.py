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
CANARY_TOKEN = os.getenv("CANARY_BOT_TOKEN", "").strip()
PRODUCTION_TOKEN = os.getenv("DISCORD_TOKEN", "").strip()
if not CANARY_TOKEN:
    raise RuntimeError("CANARY_BOT_TOKEN manquant pour le service SentriX Canary.")
if PRODUCTION_TOKEN and CANARY_TOKEN == PRODUCTION_TOKEN:
    raise RuntimeError("CANARY_BOT_TOKEN doit être différent du DISCORD_TOKEN de production.")
os.environ["SENTRIX_CANARY_MODE"] = "1"
os.environ["DATABASE_PATH"] = os.getenv("CANARY_DATABASE_PATH", "database/canary.db")
# config.py exige DISCORD_TOKEN ; le service Canary n'a pas besoin du secret production.
os.environ.setdefault("DISCORD_TOKEN", "canary-token-not-used-by-bootstrap")

import config

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


async def _run_canary_self_test(bot) -> tuple[bool, str]:
    """Valide le minimum vital d'un build avant de déclarer le Canary sain."""
    target = bot.get_guild(config.CANARY_GUILD_ID)
    if target is None:
        return False, "serveur canary introuvable"

    required_cogs = ("Moderation", "Automod", "Tickets", "Utility")
    missing_cogs = [name for name in required_cogs if bot.get_cog(name) is None]
    if missing_cogs:
        return False, "cogs manquants: " + ", ".join(missing_cogs)

    required_commands = ("help", "ping", "security", "ticket", "ban")
    missing_commands = [name for name in required_commands if bot.get_command(name) is None]
    if missing_commands:
        return False, "commandes manquantes: " + ", ".join(missing_commands)

    try:
        row = await asyncio.wait_for(bot.db.fetchone("PRAGMA quick_check"), timeout=5.0)
        db_ok = bool(row and str(row[0]).casefold() == "ok")
    except Exception as exc:
        return False, f"SQLite: {type(exc).__name__}"
    if not db_ok:
        return False, "SQLite quick_check en échec"

    help_command = bot.get_command("help")
    if help_command is None or getattr(help_command, "clean_params", None):
        return False, "+help expose encore des paramètres"

    return True, "cogs, commandes, help et SQLite validés"


async def _start_health(bot):
    async def health(_request):
        target = bot.get_guild(config.CANARY_GUILD_ID)
        self_test_ok = bool(getattr(bot, "_sentrix_canary_self_test_passed", False))
        ready = bool(bot.is_ready() and target is not None and self_test_ok)
        payload = {
            "ok": ready,
            "mode": "canary",
            "discord_ready": bot.is_ready(),
            "canary_guild_ready": target is not None,
            "self_test": self_test_ok,
            "self_test_detail": getattr(bot, "_sentrix_canary_self_test_detail", "en attente"),
            "guild_id": config.CANARY_GUILD_ID,
            "commit_sha": (os.getenv("RAILWAY_GIT_COMMIT_SHA") or "")[:80],
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

    # La base Canary est volontairement séparée de la production et peut être vide au
    # démarrage. Le diagnostic générique de main.py interprète sinon ce cas comme une
    # perte de volume Railway et envoie un MP à chaque redéploiement. On le désactive
    # uniquement sur le bot Beta/Canary ; la protection reste active en production.
    bot._persistence_check_done = True
    bot._sentrix_canary_self_test_passed = False
    bot._sentrix_canary_self_test_detail = "en attente du démarrage Discord"

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

        passed, detail = await _run_canary_self_test(bot)
        bot._sentrix_canary_self_test_passed = passed
        bot._sentrix_canary_self_test_detail = detail
        if passed:
            logger.info("Canary self-test réussi : %s", detail)
        else:
            logger.error("Canary self-test ÉCHEC : %s", detail)

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
