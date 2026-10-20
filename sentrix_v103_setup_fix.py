"""SentriX V103 — publication finale des panneaux /config.

Historique : V103 réinstallait autrefois /setup en le redirigeant vers
``cogs.setup_control_center.SentriXSetup``. Depuis le Smart Setup V4/V114, cette route est
obsolète : le setup officiel vit dans ``cogs.configuration.SetupView`` et V113/V114
patchent précisément cette vue pour fournir l'accueil compact, Smart Setup, snapshots,
rollback et diagnostic.

V116 ajoute le centre hiérarchique et redevient l'interface publique de /setup.
La couche V117 reste dans le dépôt pour historique, mais n'est plus installée au runtime.

Cette couche reste utile pour garantir une signature slash sans argument utilisateur après
les transformations V95+, mais elle ne possède plus d'interface concurrente. Elle ouvre
explicitement le panneau du cog Configuration.
"""
from __future__ import annotations

import inspect
import logging

import discord
from discord import app_commands

import config
import sentrix_v95_runtime as v95
from utils import embeds
from utils import sentrix_panels as panels

logger = logging.getLogger("bot.v103-setup-fix")
_INSTALLED = False

# Contrat d'interface publique : le runtime ouvre bien le centre hiérarchique V116.
# Le marqueur d'autorité slash reste volontairement V114 pour compatibilité avec les
# gardes historiques qui vérifient l'unicité de /setup.
PUBLIC_SETUP_UI = "configuration-v116"


async def _is_setup_authorized(bot, interaction: discord.Interaction) -> bool:
    """Même barrière que la commande Configuration.setup_wizard."""
    if interaction.guild is None:
        return False
    user = interaction.user
    if user.id in config.OWNER_IDS:
        return True
    try:
        if await bot.is_owner(user):
            return True
    except Exception:
        pass
    return isinstance(user, discord.Member) and user.guild_permissions.administrator


async def _send_setup_v114(bot, interaction: discord.Interaction) -> None:
    """Ouvre LE centre de configuration : le même que ``+setup``.

    ``/setup`` et ``+setup`` ouvraient deux interfaces différentes (Configuration.SetupView
    d'un côté, setup_control_center.SetupView de l'autre). Il n'y a plus qu'un moteur :
    cogs/setup_control_center.OfficialSetup.send_setup, qui accepte un Context comme une
    Interaction et applique la même autorisation.
    """
    if interaction.guild is None:
        return await interaction.response.send_message(
            "Cette commande doit être utilisée dans un serveur.", ephemeral=True
        )
    setup_cog = bot.get_cog("SentriXSetup")
    if setup_cog is None or not callable(getattr(setup_cog, "send_setup", None)):
        raise RuntimeError("Le centre de configuration (cogs.setup_control_center) n'est pas chargé.")
    await setup_cog.send_setup(interaction)


def _replace_setup_slash(bot) -> bool:
    """Publie /config après V95/V98/V110 et retire l'ancien slash /setup.

    V98 construit déjà une racine /config pour les commandes historiques : on
    conserve ces sous-commandes et on AJOUTE les huit centres interactifs.
    Ajouter un second /config ferait disparaître la surface V98 et dépasserait
    le budget mondial des 100 commandes slash.
    """
    if bot.get_cog("SentriXSetup") is None:
        logger.error("V103 : centre officiel SentriXSetup introuvable ; /config indisponible.")
        return False

    tree = bot.tree
    try:
        tree.remove_command("setup", type=discord.AppCommandType.chat_input)
    except TypeError:
        tree.remove_command("setup")

    try:
        group = tree.get_command("config", type=discord.AppCommandType.chat_input)
    except TypeError:
        group = tree.get_command("config")
    if group is None:
        group = app_commands.Group(
            name="config",
            description="Panneaux de configuration du serveur SentriX.",
        )
        tree.add_command(group)
    elif not isinstance(group, app_commands.Group):
        logger.error("V103 : la racine /config existe mais n'est pas un groupe.")
        return False

    routes = (
        ("accueil", "🏠 Centre principal de configuration.", None, False),
        ("automod", "🛡️ Protection AutoMod, anti-spam et anti-raid.", "security", False),
        ("logs", "📋 Configurer tous les journaux du serveur.", "logs", False),
        ("tickets", "🎫 Gérer les tickets et leurs catégories.", "tickets", False),
        ("bienvenue", "👋 Messages de bienvenue et autorôles.", "welcome", False),
        ("moderation", "⚖️ Sanctions et autorisations staff.", "moderation", False),
        ("avertissements", "⚠️ Gérer avertissements, MP, seuils, rôles et logs.", None, False),
        ("signalements", "🚨 Salon privé, notifications et suivi des signalements.", None, False),
        ("niveaux", "⭐ XP, niveaux et annonces sur activation.", "levels", False),
        ("diagnostic", "🔧 Analyser les problèmes de configuration.", None, True),
    )

    def make_callback(name: str, category: str | None, diagnostic: bool):
        async def config_callback(interaction: discord.Interaction) -> None:
            setup_cog = bot.get_cog("SentriXSetup")
            if setup_cog is None:
                return await interaction.response.send_message(
                    "Le Centre Config de SentriX est indisponible.", ephemeral=True,
                )
            if name == "avertissements":
                from cogs.warnings_config import open_warning_config
                return await open_warning_config(bot, interaction)
            if name == "signalements":
                report_cog = bot.get_cog("ReportCenter")
                if report_cog is None:
                    return await interaction.response.send_message(
                        "Centre des signalements indisponible.", ephemeral=True,
                    )
                return await report_cog.open_config(interaction)
            await setup_cog.send_setup(
                interaction, category=category, diagnostic=diagnostic, private=True,
            )

        config_callback.__name__ = f"config_{name}"
        config_callback.__qualname__ = config_callback.__name__
        config_callback.__signature__ = inspect.Signature([
            inspect.Parameter(
                "interaction",
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                annotation=discord.Interaction,
            )
        ])
        config_callback.__annotations__ = {
            "interaction": discord.Interaction,
            "return": None,
        }
        config_callback._sentrix_original_command = f"config {name}"
        config_callback._sentrix_native_options = True
        # Conservé pour les couches de compatibilité du setup historique.
        config_callback._sentrix_setup_authority = "configuration-v114"
        return config_callback

    for name, description, category, diagnostic in routes:
        if group.get_command(name) is not None:
            group.remove_command(name)
        group.add_command(app_commands.Command(
            name=name,
            description=description[:100],
            callback=make_callback(name, category, diagnostic),
        ))

    roots = list(tree.get_commands(guild=None, type=discord.AppCommandType.chat_input))
    if len(roots) > 100:
        logger.error("V103 : /config dépasse le budget global : %s/100 racines.", len(roots))
        return False

    logger.info("V103 : /config publie 10 centres ; /setup slash retiré, +setup conservé.")
    return True


def install() -> None:
    """Place la garde après toutes les transformations de ``prepare_bot``."""
    global _INSTALLED
    if _INSTALLED:
        return

    current_prepare = v95.prepare_bot
    if getattr(current_prepare, "_sentrix_v103_setup_fix", False):
        _INSTALLED = True
        return

    async def prepare_bot_v103(bot):
        result = await current_prepare(bot)
        try:
            from sentrix_setup_v116 import install_for_bot as install_setup_v116
            install_setup_v116(bot)
        except Exception:
            logger.exception("Installation du centre Setup V116 impossible.")
        _replace_setup_slash(bot)
        return result

    prepare_bot_v103._sentrix_v103_setup_fix = True
    prepare_bot_v103._sentrix_original = current_prepare
    v95.prepare_bot = prepare_bot_v103
    _INSTALLED = True
    logger.info("V103 setup authority guard armé pour Smart Setup V114/V116.")


__all__ = ["install", "_replace_setup_slash", "_send_setup_v114", "_is_setup_authorized"]
