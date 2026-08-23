"""Correctifs V17 visibles par les utilisateurs.

Garanties :
- une mention seule de SentriX n'affiche plus l'ancienne carte Utilitaires en plus de
  l'accueil compact ;
- toute réponse déclenchée par ``on_command_error`` est privée : ephemeral en slash et
  DM pour une commande préfixée ; si les DM sont fermés, aucun détail d'erreur n'est
  publié dans le salon et SentriX ajoute seulement une réaction d'échec ;
- ``+create sentrix`` est réellement enregistré une fois les dépendances nécessaires
  chargées, sans ajouter une seconde extension à la liste historique de main.py.
"""
from __future__ import annotations

import logging
from typing import Any

import discord
from discord.ext import commands

logger = logging.getLogger("bot.v17-user-facing-hotfix")

_DISPATCH_PATCHED = False
_MENTION_PATCHED = False
_PLAIN_INSTALL_PATCHED = False


def _patch_error_dispatch() -> None:
    """Marque le Context AVANT que tous les handlers/listeners d'erreur soient planifiés."""
    global _DISPATCH_PATCHED
    if _DISPATCH_PATCHED:
        return

    current_dispatch = commands.Bot.dispatch
    if getattr(current_dispatch, "_sentrix_private_command_errors", False):
        _DISPATCH_PATCHED = True
        return

    def private_error_dispatch(self: commands.Bot, event_name: str, /, *args: Any, **kwargs: Any):
        if event_name == "command_error" and args:
            ctx = args[0]
            if isinstance(ctx, commands.Context):
                ctx._sentrix_private_error = True
        return current_dispatch(self, event_name, *args, **kwargs)

    private_error_dispatch._sentrix_private_command_errors = True
    private_error_dispatch._sentrix_original = current_dispatch
    commands.Bot.dispatch = private_error_dispatch
    _DISPATCH_PATCHED = True


def _apply_private_context_transport() -> None:
    """Pose le transport privé AU-DESSUS de la politique riche finale."""
    from . import plain_response_policy

    current_send = commands.Context.send
    if getattr(current_send, "_sentrix_private_error_transport", False):
        return

    async def private_error_send(self: commands.Context, *args, **kwargs):
        if not getattr(self, "_sentrix_private_error", False):
            return await current_send(self, *args, **kwargs)

        interaction = getattr(self, "interaction", None)
        if interaction is not None:
            # Discord permet une vraie réponse privée pour les interactions slash.
            kwargs["ephemeral"] = True
            return await current_send(self, *args, **kwargs)

        # Une commande préfixée ne peut pas être ephemeral côté Discord. On envoie donc
        # le même rendu uniquement en DM à l'auteur, jamais dans le salon public.
        try:
            dm_args, dm_kwargs = plain_response_policy._rich_send_args(self, args, dict(kwargs))
            dm_args, dm_kwargs = plain_response_policy._clean_send_args(dm_args, dm_kwargs)
            for key in ("ephemeral", "reference", "mention_author", "silent"):
                dm_kwargs.pop(key, None)
            dm_kwargs["allowed_mentions"] = discord.AllowedMentions.none()
            result = await self.author.send(*dm_args, **dm_kwargs)
            self._sentrix_response_sent = True
            return result
        except (discord.Forbidden, discord.NotFound, discord.HTTPException):
            # DM fermés : ne jamais divulguer le détail de l'erreur publiquement.
            try:
                message = getattr(self, "message", None)
                if message is not None:
                    await message.add_reaction("❌")
            except (discord.Forbidden, discord.NotFound, discord.HTTPException):
                pass
            self._sentrix_response_sent = True
            return None

    private_error_send._sentrix_private_error_transport = True
    private_error_send._sentrix_original = current_send
    commands.Context.send = private_error_send


def _patch_plain_response_install() -> None:
    """Réapplique le transport privé après CHAQUE réinstallation du transport final.

    plain_response_policy se réaffirme aussi après on_ready. En enveloppant son install(),
    la confidentialité ne peut pas être perdue par un ancien runtime chargé plus tard.
    """
    global _PLAIN_INSTALL_PATCHED
    if _PLAIN_INSTALL_PATCHED:
        return

    from . import plain_response_policy

    current_install = plain_response_policy.install
    if getattr(current_install, "_sentrix_private_error_install", False):
        _PLAIN_INSTALL_PATCHED = True
        return

    def install_with_private_errors(bot: commands.Bot | None = None) -> None:
        current_install(bot)
        _apply_private_context_transport()

    install_with_private_errors._sentrix_private_error_install = True
    install_with_private_errors._sentrix_original = current_install
    plain_response_policy.install = install_with_private_errors
    _PLAIN_INSTALL_PATCHED = True


def _patch_duplicate_mention() -> None:
    """Désactive uniquement l'ancienne carte de mention quand le nouvel accueil existe."""
    global _MENTION_PATCHED
    if _MENTION_PATCHED:
        return

    from . import common_command_names

    current = common_command_names._mention_help
    if getattr(current, "_sentrix_compact_home_guard", False):
        _MENTION_PATCHED = True
        return

    async def mention_help_without_duplicate(bot: commands.Bot, message: discord.Message):
        # Avec le Cog Ai chargé, mention_home_runtime fournit la carte Accueil + boutons.
        # On ne doit donc plus envoyer l'ancien « SentriX • Utilitaires ».
        if bot.get_cog("Ai") is not None:
            return None
        return await current(bot, message)

    mention_help_without_duplicate._sentrix_compact_home_guard = True
    mention_help_without_duplicate._sentrix_original = current
    common_command_names._mention_help = mention_help_without_duplicate
    _MENTION_PATCHED = True


async def _ensure_create_sentrix(bot: commands.Bot) -> None:
    """Enregistre +create sentrix quand Tickets/Configuration/IA sont disponibles."""
    if bot.get_command("create") is not None:
        return
    if bot.get_cog("CreateSentrix") is not None:
        return
    if bot.get_cog("Tickets") is None or bot.get_cog("Ai") is None:
        return

    from .create_sentrix import CreateSentrix

    try:
        await bot.add_cog(CreateSentrix(bot))
    except commands.CommandRegistrationError:
        logger.exception("Impossible d'enregistrer +create sentrix : le nom +create est déjà occupé.")
        return

    command = bot.get_command("create sentrix")
    if command is None:
        logger.error("Le Cog CreateSentrix a été ajouté mais +create sentrix reste introuvable.")
        return
    logger.info("Commande +create sentrix enregistrée et disponible.")


async def install(bot: commands.Bot, extension_name: str = "") -> None:
    del extension_name
    _patch_error_dispatch()
    _patch_plain_response_install()
    _patch_duplicate_mention()
    await _ensure_create_sentrix(bot)


__all__ = ["install"]
