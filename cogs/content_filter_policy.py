"""Politique de modération de contenu SentriX.

Règles globales demandées :
- seul le propriétaire réel du serveur Discord peut ajouter/retirer des whitelists ;
- le propriétaire du serveur est immunisé contre les filtres de contenu ;
- les filtres de contenu (insultes, liens, mots interdits, etc.) suivent l'escalade
  unique de cogs/automod.py (``_maybe_escalate``) : un avertissement, puis le mute.
  Jusqu'au 22/11/2026 cette couche la remplaçait par « suppression seule » ;
  le propriétaire a demandé l'inverse, et le remplacement a été retiré ;
- l'anti-nuke reste indépendant et conserve ses sanctions fortes en cas d'attaque.

Cette couche se branche sur le Cog AutoMod existant sans dupliquer son listener principal.
"""
from __future__ import annotations

import logging
from types import MethodType

import discord
from discord import app_commands
from discord.ext import commands

from utils import checks

logger = logging.getLogger("bot.content-filter-policy")

# Toute opération qui crée ou retire une exemption de sécurité est propriétaire-only.
_OWNER_ONLY_WHITELIST_COMMANDS = {
    "whitelist-domain",
    "unwhitelist-domain",
    "antinuke-whitelist-add",
    "antinuke-whitelist-remove",
    "automod-exempt-role-add",
    "automod-exempt-role-remove",
}



async def _guild_owner_only(ctx: commands.Context) -> bool:
    if ctx.guild is None:
        raise checks.BotPermissionError("Cette commande doit être utilisée dans un serveur.")
    if ctx.author.id == ctx.guild.owner_id:
        return True
    raise checks.BotPermissionError(
        "Seul le **propriétaire du serveur Discord** peut modifier une whitelist ou une exemption de sécurité."
    )


async def _guild_owner_only_interaction(interaction: discord.Interaction) -> bool:
    guild = interaction.guild
    if guild is not None and interaction.user.id == guild.owner_id:
        return True
    raise app_commands.CheckFailure(
        "Seul le propriétaire du serveur Discord peut modifier une whitelist ou une exemption de sécurité."
    )


def _install_owner_only_whitelist_guards(bot: commands.Bot) -> None:
    for name in _OWNER_ONLY_WHITELIST_COMMANDS:
        command = bot.get_command(name)
        if command is None or getattr(command, "_sentrix_owner_only_whitelist", False):
            continue

        command.add_check(_guild_owner_only)
        app_command = getattr(command, "app_command", None)
        if app_command is not None and hasattr(app_command, "add_check"):
            app_command.add_check(_guild_owner_only_interaction)

        command._sentrix_owner_only_whitelist = True
        logger.info("Whitelist verrouillée au propriétaire du serveur : %s", name)


def _patch_automod(bot: commands.Bot) -> None:
    automod = bot.get_cog("Automod")
    if automod is None or getattr(automod, "_sentrix_delete_only_content_policy", False):
        return

    automod._sentrix_delete_only_content_policy = True

    # 1) Le propriétaire du serveur ne doit subir AUCUN filtre de contenu, y compris la
    # blacklist de mots qui est volontairement évaluée avant is_automod_exempt() dans le
    # listener historique.
    original_delete_and_warn = automod._delete_and_warn

    async def _owner_immunity_is_off(_self, message_or_member) -> bool:
        guild = getattr(message_or_member, "guild", None)
        author = getattr(message_or_member, "author", None)
        member = author or message_or_member
        if guild is None or member is None or member.id != guild.owner_id:
            return False
        try:
            override = await _self.get_immunity_override_cached(guild.id, member.id)
        except Exception:
            override = None
        return override is False

    async def owner_safe_delete_and_warn(
        _self,
        message: discord.Message,
        reason: str,
        filter_name: str = "automod",
        *,
        censored_content: str | None = None,
        **options,
    ):
        # 07/11/2026 : `allow_escalation` (insultes probables) faisait planter cet
        # enrobage — TypeError, et l'insulte n'était ni supprimée ni sanctionnée.
        # Toute option est désormais transmise telle quelle.
        if (
            message.guild is not None
            and message.author.id == message.guild.owner_id
            and not await _owner_immunity_is_off(_self, message)
        ):
            return None
        return await original_delete_and_warn(
            message,
            reason,
            filter_name,
            censored_content=censored_content,
            **options,
        )

    automod._delete_and_warn = MethodType(owner_safe_delete_and_warn, automod)

    # 2) Le filtre multilingue d'insultes utilisait historiquement un timeout direct de
    # 10 minutes. Il passe par le même flux que les autres filtres de contenu :
    # suppression, avertissement, puis le mute de l'escalade unique.
    #
    # 22/11/2026 : il tenait son propre compteur de récidive, en mémoire (perdu à
    # chaque redémarrage). Deux compteurs donnaient deux échelles contradictoires
    # — une insulte après un lien pouvait annoncer « avertissement » et muter dans
    # le même message. Il n'y a plus qu'un compteur, celui de _maybe_escalate.
    async def delete_only_toxicity(
        _self,
        message: discord.Message,
        reason: str,
        *,
        detection_kind: str,
    ):
        if (
            message.guild is not None
            and message.author.id == message.guild.owner_id
            and not await _owner_immunity_is_off(_self, message)
        ):
            return None
        detail = reason or "Contenu offensant détecté par le filtre multilingue."
        return await _self._delete_and_warn(message, detail, "multilingual_toxicity")

    automod._delete_and_timeout = MethodType(delete_only_toxicity, automod)

    logger.info(
        "Politique contenu activée : immunité propriétaire pilotable, escalade unique des filtres (avertissement puis mute), anti-nuke inchangé."
    )


def install(bot: commands.Bot) -> None:
    """Idempotent et rappelable après chaque chargement d'extension."""
    _install_owner_only_whitelist_guards(bot)
    _patch_automod(bot)
