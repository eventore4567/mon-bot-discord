"""Démarrage Railway résilient pour SentriX.

Le serveur HTTP est ouvert AVANT le chargement complet des cogs Discord. Railway peut
donc joindre immédiatement le port $PORT au lieu d'afficher un 502 pendant le démarrage
du bot. La base est ouverte une seule fois et le démarrage dashboard historique de
BotAllInOne.setup_hook est neutralisé pour éviter un second bind sur le même port.
"""

import asyncio
import logging
import traceback

import config
import main as bot_main


logger = logging.getLogger("bot.railway")


async def _dashboard_already_started(_bot):
    """Remplace le second démarrage du dashboard dans BotAllInOne.setup_hook."""
    return None


async def run() -> None:
    bot = bot_main.BotAllInOne()

    # Le dashboard possède des hooks qui utilisent SQLite dès son démarrage : on ouvre
    # donc la base avant de binder le port Railway.
    await bot.db.connect()
    logger.info("Base prête pour le démarrage anticipé du dashboard Railway.")

    real_start_dashboard = bot_main.start_dashboard

    # setup_hook appellera db.connect() et start_dashboard() plus tard. La connexion est
    # déjà active et le port déjà bindé : ces deux appels deviennent volontairement no-op.
    async def already_connected():
        return None

    bot.db.connect = already_connected
    bot_main.start_dashboard = _dashboard_already_started

    # Attend réellement site.start() : quand bot.start() commence, Railway a déjà un
    # serveur HTTP à joindre sur $PORT.
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
            await bot.db.close()
        except Exception:
            logger.warning("Fermeture de la base impossible :\n%s", traceback.format_exc())


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        logger.info("Arrêt de SentriX.")
