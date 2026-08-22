"""Démarrage Railway résilient, durable et shardé pour SentriX.

Le serveur HTTP est ouvert avant le chargement complet des cogs Discord. Quand PostgreSQL
est configuré, le bootstrap tente aussi de restaurer la base SQLite principale depuis son
dernier snapshot durable si le fichier local a disparu ou est invalide.
"""

import asyncio
import logging
import traceback

from discord.ext import commands

import config
from utils.durable_database import DurableDatabaseReplica


class SentriXAutoShardedBot(commands.AutoShardedBot):
    """AutoShardedBot qui respecte SHARD_COUNT quand l'opérateur veut le figer."""

    def __init__(self, *args, **kwargs):
        if config.SHARD_COUNT > 0:
            kwargs.setdefault("shard_count", config.SHARD_COUNT)
        super().__init__(*args, **kwargs)


# IMPORTANT : main.BotAllInOne est défini en héritant de commands.Bot. Sur le bootstrap
# Railway uniquement, on remplace cette classe de base AVANT d'importer main. Avec
# SHARD_COUNT=0, discord.py demande automatiquement à Discord le nombre recommandé.
if not getattr(commands, "_sentrix_auto_sharded_bootstrap", False):
    commands.Bot = SentriXAutoShardedBot
    commands._sentrix_auto_sharded_bootstrap = True

import main as bot_main

# Extensions complémentaires chargées sur les instances Railway. +drop reste une commande
# texte uniquement afin de ne consommer aucun emplacement slash supplémentaire.
if "cogs.drop" not in bot_main.EXTENSIONS:
    bot_main.EXTENSIONS.append("cogs.drop")
if "cogs.log_access_fix" not in bot_main.EXTENSIONS:
    bot_main.EXTENSIONS.append("cogs.log_access_fix")
# Discord ne peut livrer les interactions qu'en Gateway OU via un endpoint HTTP. SentriX
# utilise discord.py/Gateway : cette garde supprime donc tout ancien endpoint HTTP resté
# configuré dans l'application, puis republie le catalogue slash sur le bon transport.
if "cogs.interaction_transport_guard" not in bot_main.EXTENSIONS:
    bot_main.EXTENSIONS.append("cogs.interaction_transport_guard")
# Inventorie les intégrations Discord ressemblant à la marque courante mais appartenant à
# une autre application. Aucun doublon n'est supprimé automatiquement par ce détecteur.
if "cogs.stale_discord_app_detector" not in bot_main.EXTENSIONS:
    bot_main.EXTENSIONS.append("cogs.stale_discord_app_detector")
# Lit le vrai schéma horaire ProductionPhase afin d'identifier les noms de commandes qui
# accumulent des erreurs, sans exposer d'identifiant utilisateur/serveur.
if "cogs.command_error_probe" not in bot_main.EXTENSIONS:
    bot_main.EXTENSIONS.append("cogs.command_error_probe")
# Neutralise uniquement l'ancien observability runtime qui réutilisait un schéma SQL
# incompatible. La gestion des interactions slash n'est plus installée ici en plusieurs
# couches : canonical_interactions sera l'unique politique finale.
if "cogs.legacy_observability_conflict_guard" not in bot_main.EXTENSIONS:
    bot_main.EXTENSIONS.append("cogs.legacy_observability_conflict_guard")
# Commande texte uniquement, ajoutée sous +security sans consommer de slot slash.
if "cogs.automod_enable_all" not in bot_main.EXTENSIONS:
    bot_main.EXTENSIONS.append("cogs.automod_enable_all")
# Doit être chargé après V10 : intercepte +setup auto AVANT le parsing de la commande
# historique /setup, dont les arguments supplémentaires étaient sinon ignorés.
if "cogs.setup_auto_fix" not in bot_main.EXTENSIONS:
    bot_main.EXTENSIONS.append("cogs.setup_auto_fix")
# Rend +addemoji/+addemogi utilisable avec un simple nom (ex: +addemogi ban-1).
# Les anciennes syntaxes avec emoji, pièce jointe ou URL restent compatibles.
if "cogs.emoji_name_lookup" not in bot_main.EXTENSIONS:
    bot_main.EXTENSIONS.append("cogs.emoji_name_lookup")
# TOUJOURS EN DERNIER : une seule politique de réponse Discord. Elle neutralise les
# anciens listeners slash encore installés par le bootstrap historique des cogs et prend
# en charge texte libre, defer, erreurs et confidentialité de façon canonique.
if "cogs.canonical_interactions" not in bot_main.EXTENSIONS:
    bot_main.EXTENSIONS.append("cogs.canonical_interactions")

bot_main.CATEGORY_COMMANDS["economie"] = (
    bot_main.CATEGORY_COMMANDS.get("economie", frozenset()) | frozenset({"drop"})
)
bot_main.KNOWN_PERMISSION_COMMANDS = bot_main.KNOWN_PERMISSION_COMMANDS | frozenset({"drop"})


logger = logging.getLogger("bot.railway")


async def _dashboard_already_started(_bot):
    """Remplace le second démarrage du dashboard dans BotAllInOne.setup_hook."""
    return None


async def _prepare_durable_store(bot) -> DurableDatabaseReplica:
    durable = DurableDatabaseReplica(config.DATABASE_PATH)
    bot.sentrix_durable_store = durable
    if not durable.configured:
        logger.info("PostgreSQL durable non configuré ; démarrage SQLite normal.")
        return durable
    try:
        connected = await asyncio.wait_for(durable.connect(), timeout=8)
        if connected:
            result = await asyncio.wait_for(durable.restore_latest_if_needed(), timeout=20)
            if result.get("restored"):
                logger.warning("Base restaurée depuis PostgreSQL avant connexion SQLite : %s", result)
            else:
                logger.info("Restauration PostgreSQL non nécessaire : %s", result.get("reason"))
    except Exception:
        logger.warning(
            "Préparation PostgreSQL durable impossible ; le démarrage local continue :\n%s",
            traceback.format_exc(),
        )
    return durable


async def run() -> None:
    bot = bot_main.BotAllInOne()
    durable = await _prepare_durable_store(bot)

    await bot.db.connect()
    logger.info("Base prête pour le démarrage anticipé du dashboard Railway.")
    logger.info(
        "Sharding production actif : configuration=%s, runtime=%s.",
        config.SHARD_COUNT or "auto",
        getattr(bot, "shard_count", None) or "auto",
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
        # Dernier snapshot cohérent avant fermeture de la connexion SQLite. Si PostgreSQL
        # est absent, snapshot() retourne immédiatement sans gêner l'arrêt.
        try:
            if durable.configured:
                await asyncio.wait_for(
                    durable.snapshot(reason="graceful_shutdown", clean_shutdown=True),
                    timeout=45,
                )
        except Exception:
            logger.warning("Snapshot durable d'arrêt impossible :\n%s", traceback.format_exc())
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
        try:
            await durable.close()
        except Exception:
            logger.warning("Fermeture du stockage durable impossible :\n%s", traceback.format_exc())


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        logger.info("Arrêt de SentriX.")
