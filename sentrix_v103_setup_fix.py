"""SentriX V103 — garde de compatibilité de la route /setup.

Historique : V103 réinstallait autrefois /setup en le redirigeant vers
``cogs.setup_control_center.SentriXSetup``. Depuis le Smart Setup V4/V114, cette route est
obsolète : le setup officiel vit dans ``cogs.configuration.SetupView`` et V113/V114
patchent précisément cette vue pour fournir l'accueil compact, Smart Setup, snapshots,
rollback et diagnostic.

Cette couche reste utile pour garantir une signature slash sans argument utilisateur après
les transformations V95+, mais elle ne possède plus d'interface concurrente. Elle ouvre
explicitement le panneau du cog Configuration, donc un redémarrage ou une resynchronisation
des commandes ne peut plus faire réapparaître l'ancien centre de contrôle.
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


async def _is_setup_authorized(bot, interaction: discord.Interaction) -> bool:
    """Même barrière que la commande Configuration.setup_wizard.

    Le callback slash est construit manuellement par V103, donc les decorators de la
    HybridCommand d'origine ne sont pas exécutés automatiquement. On garde ici le contrat
    owner/admin sans élargir silencieusement les droits.
    """
    if interaction.guild is None:
        return False
    user = interaction.user
    if user.id in config.OWNER_IDS:
        return True
    try:
        if await bot.is_owner(user):
            return True
    except Exception:
        # OWNER_IDS reste l'autorité de repli si Discord n'a pas encore résolu le owner.
        pass
    return isinstance(user, discord.Member) and user.guild_permissions.administrator


async def _send_setup_v114(bot, interaction: discord.Interaction) -> None:
    """Ouvre l'unique setup officiel : Configuration.SetupView patché par V113/V114."""
    configuration = bot.get_cog("Configuration")
    opener = getattr(configuration, "_open_setup_panel", None) if configuration is not None else None
    if not callable(opener):
        raise RuntimeError("Le module Configuration / Smart Setup V114 n'est pas chargé.")

    if interaction.guild is None:
        return await interaction.response.send_message(
            "Cette commande doit être utilisée dans un serveur.", ephemeral=True
        )
    if not await _is_setup_authorized(bot, interaction):
        return await interaction.response.send_message(
            "Vous devez être administrateur du serveur pour utiliser `/setup`.",
            ephemeral=True,
        )

    # Préserve le verrou historique : deux administrateurs ne doivent pas modifier la
    # configuration du même serveur en parallèle. Le panneau de reprise reste celui du
    # cog Configuration ; il ne réintroduit pas l'ancien setup_control_center.
    existing = getattr(configuration, "active_by_guild", {}).get(interaction.guild.id)
    if existing and existing[1] != interaction.user.id:
        locked_message_id, locked_author_id, locked_author_name = existing
        from cogs.configuration import SetupLockPromptView

        view = SetupLockPromptView(
            configuration,
            interaction.guild.id,
            locked_message_id,
            locked_author_id,
            locked_author_name,
            interaction.user.id,
        )
        return await panels.envoyer(
            interaction,
            panels.avec_composants(
                panels.depuis_embed(
                    embeds.warning(
                        f"Une configuration est déjà en cours par **{locked_author_name}**.",
                        title="Configuration déjà ouverte",
                    )
                ),
                view,
            ),
            ephemere=True,
        )

    await opener(interaction, author=interaction.user)


def _replace_setup_slash(bot) -> bool:
    """Réinstalle /setup avec une signature native, dirigée vers Smart Setup V114.

    Important : cette fonction ne doit JAMAIS importer ni appeler SentriXSetup. L'ancien
    ``cogs.setup_control_center`` peut rester présent pour compatibilité interne, mais il
    n'est plus propriétaire de la commande publique /setup.
    """
    configuration = bot.get_cog("Configuration")
    if configuration is None or not callable(getattr(configuration, "_open_setup_panel", None)):
        logger.error("V103 : cog Configuration/Smart Setup introuvable ; /setup non remplacé.")
        return False

    tree = bot.tree
    try:
        tree.remove_command("setup", type=discord.AppCommandType.chat_input)
    except TypeError:
        tree.remove_command("setup")

    async def setup_callback(interaction: discord.Interaction) -> None:
        await _send_setup_v114(bot, interaction)

    setup_callback.__name__ = "slash_setup_v114"
    setup_callback.__qualname__ = setup_callback.__name__
    setup_callback.__signature__ = inspect.Signature([
        inspect.Parameter(
            "interaction",
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            annotation=discord.Interaction,
        )
    ])
    setup_callback.__annotations__ = {
        "interaction": discord.Interaction,
        "return": None,
    }
    setup_callback._sentrix_original_command = "setup"
    setup_callback._sentrix_native_options = True
    setup_callback._sentrix_setup_authority = "configuration-v114"

    tree.add_command(
        app_commands.Command(
            name="setup",
            description="Configurer SentriX avec Smart Setup",
            callback=setup_callback,
        ),
        override=True,
    )
    logger.info("V103 : /setup V114 installé — Configuration est l'unique autorité.")
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
        _replace_setup_slash(bot)
        return result

    prepare_bot_v103._sentrix_v103_setup_fix = True
    prepare_bot_v103._sentrix_original = current_prepare
    v95.prepare_bot = prepare_bot_v103
    _INSTALLED = True
    logger.info("V103 setup authority guard armé pour Smart Setup V114.")


__all__ = ["install", "_replace_setup_slash", "_send_setup_v114", "_is_setup_authorized"]
