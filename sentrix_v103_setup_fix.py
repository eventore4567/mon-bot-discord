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
    conserve ces sous-commandes et on AJOUTE huit centres interactifs.
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
        ("niveaux", "⭐ XP, niveaux et annonces sur activation.", "levels", False),
    )

    def make_callback(name: str, category: str | None, diagnostic: bool):
        async def config_callback(interaction: discord.Interaction) -> None:
            setup_cog = bot.get_cog("SentriXSetup")
            if setup_cog is None:
                return await interaction.response.send_message(
                    "Le Centre Config de SentriX est indisponible.", ephemeral=True,
                )
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

    # Discord refuse un groupe possédant plus de 25 enfants directs.
    # Le diagnostic reste disponible depuis /setup et son panneau interactif.
    # Éviter une 26e entrée sous /config et préserver les commandes historiques.
    planned = {name for name, *_ in routes}
    old_commands = [command for command in group.commands if command.name not in planned]
    needed = len(old_commands) + len(planned) - 25
    if needed > 0:
        advanced = group.get_command("advanced")
        if advanced is None:
            advanced = app_commands.Group(
                name="advanced",
                description="Réglages complémentaires du serveur.",
            )
            needed += 1  # Le nouveau sous-groupe occupe lui-même un emplacement.
        if not isinstance(advanced, app_commands.Group):
            logger.error("V103 : /config advanced est occupé par une commande.")
            return False
        movable = [command for command in old_commands if command is not advanced]
        if needed > len(movable) or len(advanced.commands) + needed > 25:
            logger.error("V103 : impossible de répartir les sous-commandes /config sans perte.")
            return False
        for command in movable[-needed:]:
            group.remove_command(command.name)
            advanced.add_command(command)
        if group.get_command("advanced") is None:
            group.add_command(advanced)
        logger.info("V103 : %s réglages hérités déplacés dans /config advanced.", needed)

    for name, description, category, diagnostic in routes:
        if group.get_command(name) is not None:
            group.remove_command(name)
        group.add_command(app_commands.Command(
            name=name,
            description=description[:100],
            callback=make_callback(name, category, diagnostic),
        ))

    # Weather est retirée uniquement du menu slash (la commande +weather reste).
    # /afk est importante et doit garder sa racine directe.
    weather = tree.get_command("weather", type=discord.AppCommandType.chat_input)
    if weather is not None:
        tree.remove_command("weather", type=discord.AppCommandType.chat_input)
        logger.info("V103 : /weather retirée du menu slash ; +weather conservée.")

    # Si nécessaire, ranger /translate dans /user pour respecter 100 racines.
    if len(tree.get_commands(guild=None, type=discord.AppCommandType.chat_input)) > 100:
        destination = tree.get_command("user", type=discord.AppCommandType.chat_input)
        translate = tree.get_command("translate", type=discord.AppCommandType.chat_input)
        if (isinstance(destination, app_commands.Group)
                and isinstance(translate, app_commands.Command)
                and destination.get_command("translate") is None
                and len(destination.commands) < 25):
            tree.remove_command("translate", type=discord.AppCommandType.chat_input)
            try:
                destination.add_command(translate)
            except Exception:
                tree.add_command(translate)
                logger.exception("V103 : déplacement de /translate impossible.")
            else:
                logger.info("V103 : /translate regroupée sous /user translate.")

    roots = list(tree.get_commands(guild=None, type=discord.AppCommandType.chat_input))
    if len(roots) > 100:
        logger.error("V103 : /config dépasse le budget global : %s/100 racines.", len(roots))
        return False

    logger.info("V103 : /config publie 7 centres ; Surveillance accessible via la catégorie de l'accueil.")
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
