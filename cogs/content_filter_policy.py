"""Politique de modération de contenu SentriX.

Règles globales demandées :
- seul le propriétaire réel du serveur Discord peut ajouter/retirer des whitelists ;
- le propriétaire du serveur est immunisé contre les filtres de contenu ;
- les filtres de contenu (insultes, liens, spam, mentions, pièces jointes, etc.)
  suppriment le message mais n'appliquent jamais de mute/kick/ban ;
- l'anti-nuke reste indépendant et conserve ses sanctions fortes en cas d'attaque.

Cette couche se branche sur le Cog AutoMod existant sans dupliquer son listener principal.
"""
from __future__ import annotations

import logging
import time
from types import MethodType

import discord
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

# Même fenêtre que le moteur historique : on conserve un compteur informatif, mais aucune
# sanction n'est déclenchée par les filtres de contenu.
_CONTENT_INFRACTION_WINDOW = 3600


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
    raise discord.app_commands.CheckFailure(
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

    async def owner_safe_delete_and_warn(
        _self,
        message: discord.Message,
        reason: str,
        filter_name: str = "automod",
    ):
        if message.guild is not None and message.author.id == message.guild.owner_id:
            return None
        return await original_delete_and_warn(message, reason, filter_name)

    automod._delete_and_warn = MethodType(owner_safe_delete_and_warn, automod)

    # 2) Une infraction de contenu reste comptée pour les logs/diagnostics, mais elle ne
    # déclenche plus jamais mute, kick ou ban. L'anti-nuke n'utilise pas cette méthode et
    # garde donc sa réponse forte contre les comptes staff compromis.
    async def delete_only_escalation(
        _self,
        guild: discord.Guild,
        member: discord.Member,
        reason: str,
    ) -> tuple[str | None, int]:
        key = (guild.id, member.id)
        now_ts = time.time()
        hits = _self.infraction_tracker.setdefault(key, [])
        hits.append(now_ts)
        hits = [stamp for stamp in hits if now_ts - stamp < _CONTENT_INFRACTION_WINDOW]
        _self.infraction_tracker[key] = hits
        return None, len(hits)

    automod._maybe_escalate = MethodType(delete_only_escalation, automod)

    # 3) Le filtre multilingue d'insultes utilisait historiquement un timeout direct de
    # 10 minutes. Il passe maintenant par le même flux "suppression + avertissement bref"
    # que les liens/spams, sans aucune sanction sur le membre.
    async def delete_only_toxicity(
        _self,
        message: discord.Message,
        reason: str,
        *,
        detection_kind: str,
    ):
        if message.guild is not None and message.author.id == message.guild.owner_id:
            return None
        detail = reason or "Contenu offensant détecté par le filtre multilingue."
        return await _self._delete_and_warn(message, detail, "multilingual_toxicity")

    automod._delete_and_timeout = MethodType(delete_only_toxicity, automod)

    logger.info(
        "Politique contenu activée : propriétaire immunisé, filtres en suppression seule, anti-nuke inchangé."
    )


def install(bot: commands.Bot) -> None:
    """Idempotent et rappelable après chaque chargement d'extension."""
    _install_owner_only_whitelist_guards(bot)
    _patch_automod(bot)
