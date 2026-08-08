"""Expérience et fiabilité des commandes SentriX.

Cette couche garde les réponses normales des commandes, mais ajoute trois filets de sécurité :
- une commande valide qui se termine sans réponse reçoit un accusé de succès ;
- une faute de frappe sur une commande `+` propose automatiquement les commandes proches ;
- les commandes lentes sont signalées dans les logs afin de repérer les régressions de latence.

Les erreurs métier restent gérées par les handlers globaux de main.py.
"""
from __future__ import annotations

import difflib
import logging
import time

import discord
from discord.ext import commands

from utils import embeds

logger = logging.getLogger("bot.command-response-guard")
_INSTALLED = False

# Une commande qui dépasse ce seuil n'est pas interrompue : elle est seulement signalée
# dans les logs pour permettre de cibler les vraies lenteurs sans pénaliser l'utilisateur.
_SLOW_COMMAND_SECONDS = 2.0
_UNKNOWN_REPLY_COOLDOWN = 3.0
_UNKNOWN_REPLY_LAST: dict[int, float] = {}


def _command_suggestions(bot: commands.Bot, typed: str) -> list[str]:
    """Retourne jusqu'à 3 noms canoniques proches, sans exposer les commandes cachées."""
    typed = (typed or "").casefold().strip()
    if not typed:
        return []

    # Les alias participent à la recherche, mais la réponse affiche toujours le nom
    # canonique pour ne pas remplir l'aide de doublons historiques.
    lookup: dict[str, str] = {}
    for command in bot.commands:
        if getattr(command, "hidden", False):
            continue
        canonical = str(command.name)
        lookup[canonical.casefold()] = canonical
        for alias in getattr(command, "aliases", ()):
            lookup[str(alias).casefold()] = canonical

    matches = difflib.get_close_matches(typed, list(lookup), n=6, cutoff=0.52)
    result: list[str] = []
    for match in matches:
        canonical = lookup[match]
        if canonical not in result:
            result.append(canonical)
        if len(result) >= 3:
            break
    return result


def _allow_unknown_reply(user_id: int) -> bool:
    """Évite qu'un spam de fausses commandes transforme SentriX en machine à réponses."""
    now = time.monotonic()
    last = _UNKNOWN_REPLY_LAST.get(int(user_id), 0.0)
    if now - last < _UNKNOWN_REPLY_COOLDOWN:
        return False
    _UNKNOWN_REPLY_LAST[int(user_id)] = now

    # Nettoyage opportuniste : pas de croissance mémoire illimitée sur un gros serveur.
    if len(_UNKNOWN_REPLY_LAST) > 5000:
        cutoff = now - 60.0
        stale = [uid for uid, stamp in _UNKNOWN_REPLY_LAST.items() if stamp < cutoff]
        for uid in stale:
            _UNKNOWN_REPLY_LAST.pop(uid, None)
    return True


def install(bot: commands.Bot) -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    # reply_reference_fix et le moteur visuel sont déjà installés lorsque cette couche
    # s'exécute. On enveloppe donc la version FINALE de Context.send pour enregistrer toute
    # réponse normale sans modifier son rendu, ses embeds ni ses permissions.
    current_send = commands.Context.send
    if not getattr(current_send, "_sentrix_response_marker", False):
        async def send_with_response_marker(self: commands.Context, *args, **kwargs):
            # Important : marquer seulement APRÈS un envoi réussi. Si Discord refuse
            # l'envoi, la commande ne doit pas être considérée à tort comme ayant répondu.
            result = await current_send(self, *args, **kwargs)
            self._sentrix_response_sent = True
            return result

        send_with_response_marker._sentrix_response_marker = True
        commands.Context.send = send_with_response_marker

    async def mark_prefix_command_start(ctx: commands.Context) -> None:
        ctx._sentrix_command_started_at = time.perf_counter()

    def log_command_duration(ctx: commands.Context, *, failed: bool) -> None:
        started = getattr(ctx, "_sentrix_command_started_at", None)
        if started is None:
            return
        elapsed = max(0.0, time.perf_counter() - started)
        if elapsed < _SLOW_COMMAND_SECONDS:
            return
        logger.warning(
            "Commande lente : +%s a pris %.2fs (user=%s, guild=%s, état=%s).",
            getattr(getattr(ctx, "command", None), "qualified_name", "inconnue"),
            elapsed,
            getattr(getattr(ctx, "author", None), "id", None),
            getattr(getattr(ctx, "guild", None), "id", None),
            "erreur" if failed else "succès",
        )

    async def ensure_prefix_command_response(ctx: commands.Context) -> None:
        log_command_duration(ctx, failed=False)

        # Les slash/hybrid slash utilisent l'événement app_command_completion ci-dessous.
        if getattr(ctx, "interaction", None) is not None:
            return
        if getattr(ctx, "_sentrix_response_sent", False):
            return
        try:
            await ctx.send(
                embed=embeds.success(
                    "La commande s'est terminée correctement.",
                    title="✅ Commande exécutée",
                )
            )
            logger.info(
                "Réponse de secours envoyée pour +%s (user=%s, guild=%s).",
                getattr(getattr(ctx, "command", None), "qualified_name", "inconnue"),
                getattr(getattr(ctx, "author", None), "id", None),
                getattr(getattr(ctx, "guild", None), "id", None),
            )
        except (discord.Forbidden, discord.HTTPException):
            logger.warning(
                "Impossible d'envoyer la réponse de secours pour %s.",
                getattr(getattr(ctx, "command", None), "qualified_name", "commande inconnue"),
                exc_info=True,
            )

    async def improve_prefix_command_error(
        ctx: commands.Context,
        error: commands.CommandError,
    ) -> None:
        original = getattr(error, "original", error)

        if isinstance(original, commands.CommandNotFound):
            author = getattr(ctx, "author", None)
            if author is None or not _allow_unknown_reply(author.id):
                return

            typed = str(getattr(ctx, "invoked_with", "") or "").strip()
            if not typed:
                return
            prefix = str(getattr(ctx, "clean_prefix", None) or "+")
            suggestions = _command_suggestions(bot, typed)

            if suggestions:
                formatted = "\n".join(f"• `{prefix}{name}`" for name in suggestions)
                description = (
                    f"La commande `{prefix}{typed}` n'existe pas.\n\n"
                    f"**Tu voulais peut-être utiliser :**\n{formatted}\n\n"
                    f"Utilise `{prefix}help <commande>` pour voir sa syntaxe."
                )
            else:
                description = (
                    f"La commande `{prefix}{typed}` n'existe pas.\n"
                    f"Utilise `{prefix}help` pour afficher toutes les commandes disponibles."
                )

            try:
                await ctx.send(embed=embeds.warning(description, title="🔎 Commande introuvable"))
            except (discord.Forbidden, discord.HTTPException):
                pass
            return

        log_command_duration(ctx, failed=True)

    async def ensure_slash_command_response(
        interaction: discord.Interaction,
        command: discord.app_commands.Command | discord.app_commands.ContextMenu,
    ) -> None:
        try:
            if interaction.response.is_done():
                return
            await interaction.response.send_message(
                embed=embeds.success(
                    "La commande s'est terminée correctement.",
                    title="✅ Commande exécutée",
                ),
                ephemeral=True,
            )
            logger.info(
                "Réponse slash de secours envoyée pour /%s (user=%s, guild=%s).",
                getattr(command, "qualified_name", getattr(command, "name", "inconnue")),
                getattr(interaction.user, "id", None),
                interaction.guild_id,
            )
        except discord.InteractionResponded:
            return
        except (discord.Forbidden, discord.HTTPException):
            logger.warning(
                "Impossible d'envoyer la réponse slash de secours pour %s.",
                getattr(command, "name", "commande inconnue"),
                exc_info=True,
            )

    bot.add_listener(mark_prefix_command_start, "on_command")
    bot.add_listener(ensure_prefix_command_response, "on_command_completion")
    bot.add_listener(improve_prefix_command_error, "on_command_error")
    bot.add_listener(ensure_slash_command_response, "on_app_command_completion")
    _INSTALLED = True
    logger.info(
        "Expérience commandes activée : réponse garantie, suggestions de fautes et diagnostic de latence."
    )
