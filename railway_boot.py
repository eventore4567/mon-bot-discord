"""Démarrage Railway résilient et shardé pour SentriX.

Le serveur HTTP est ouvert AVANT le chargement complet des cogs Discord. Railway peut
donc joindre immédiatement le port $PORT au lieu d'afficher un 502 pendant le démarrage.
En production, BotAllInOne hérite d'AutoShardedBot : Discord répartit automatiquement les
serveurs entre plusieurs shards quand l'application grandit, sans changer les commandes.
"""

import asyncio
import logging
import traceback

from discord.ext import commands

# IMPORTANT : main.BotAllInOne est défini en héritant de commands.Bot. Sur le bootstrap
# Railway uniquement, on remplace cette classe de base AVANT d'importer main afin d'obtenir
# AutoShardedBot sans dupliquer les centaines de lignes du point d'entrée historique.
if not getattr(commands, "_sentrix_auto_sharded_bootstrap", False):
    commands.Bot = commands.AutoShardedBot
    commands._sentrix_auto_sharded_bootstrap = True

import config
import main as bot_main


logger = logging.getLogger("bot.railway")


async def _dashboard_already_started(_bot):
    """Remplace le second démarrage du dashboard dans BotAllInOne.setup_hook."""
    return None


async def run() -> None:
    bot = bot_main.BotAllInOne()

    await bot.db.connect()
    logger.info("Base prête pour le démarrage anticipé du dashboard Railway.")
    logger.info(
        "Sharding production actif : %s (0/None signifie détermination automatique par Discord).",
        getattr(bot, "shard_count", None),
    )

    real_start_dashboard = bot_main.start_dashboard

    async def already_connected():
        return None

    bot.db.connect = already_connected
    bot_main.start_dashboard = _dashboard_already_started

    await real_start_dashboard(bot)
    logger.info("Dashboard Railway démarré avant la connexion Discord.")

    try:
        async with bot:
            await bot.start(config.DISCORD_TOKEN)
    except Exception:
        logger.critical("Le processus Discord s'est arrêté :\n%s", traceback.format_exc())
        raise
    finally:
        try:
            infra = getattr(bot, "sentrix_infra", None)
            if infra is not None:
                await infra.close()
        except Exception:
            logger.warning("Fermeture de l'infrastructure Enterprise impossible :\n%s", traceback.format_exc())
        try:
            await bot.db.close()
        except Exception:
            logger.warning("Fermeture de la base impossible :\n%s", traceback.format_exc())


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        logger.info("Arrêt de SentriX.")
