"""Expérience et fiabilité des commandes SentriX.

Cette couche garde les réponses normales des commandes, mais ajoute des filets de sécurité
transversaux qui s'appliquent automatiquement à TOUT le registre actif :
- une commande valide qui se termine sans réponse reçoit un accusé de succès ;
- une faute de frappe sur une commande `+`, y compris une sous-commande, propose les noms proches ;
- les suggestions respectent la surface réellement accessible au membre et n'exposent pas
  les commandes staff/owner à quelqu'un qui n'a pas les permissions nécessaires ;
- les commandes préfixées et slash lentes sont signalées dans les logs ;
- le catalogue de suggestions est construit depuis walk_commands(), donc une future commande
  bénéficie du système sans ajout manuel.

Les erreurs métier restent gérées par les handlers globaux de main.py.
"""
from __future__ import annotations

import difflib
import logging
import sys
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
_SLASH_STARTS: dict[int, float] = {}


def _runtime_main():
    """Retourne le module main réellement utilisé, y compris quand le bot est lancé en script."""
    return sys.modules.get("main") or sys.modules.get("__main__")


def _command_policy_name(command: commands.Command) -> str:
    root = getattr(command, "root_parent", None) or command
    return str(getattr(root, "name", "") or getattr(command, "name", "") or "").casefold()


def _can_suggest_command(ctx: commands.Context, command: commands.Command) -> bool:
    """Applique une version synchrone et fail-closed de la politique de commandes.

    Une suggestion n'exécute rien, mais elle ne doit pas révéler inutilement les outils
    staff/owner. Les checks métier restent évidemment la vraie autorité à l'exécution.
    """
    if getattr(command, "hidden", False) or not getattr(command, "enabled", True):
        return False

    main = _runtime_main()
    if main is None:
        # Pendant un bootstrap inhabituel, mieux vaut ne proposer que +help plutôt que
        # d'exposer une commande dont la politique n'est pas encore disponible.
        return _command_policy_name(command) == "help"

    name = _command_policy_name(command)
    public = set(getattr(main, "PUBLIC_COMMANDS", set()) or set())
    owner_only = set(getattr(main, "OWNER_ONLY_COMMANDS", set()) or set())
    permission_commands = dict(getattr(main, "DISCORD_PERMISSION_COMMANDS", {}) or {})
    categories = dict(getattr(main, "CATEGORY_COMMANDS", {}) or {})

    if name in owner_only:
        # Les commandes propriétaire restent hors des suggestions publiques. Le propriétaire
        # peut toujours les utiliser normalement ou les retrouver dans son aide dédiée.
        return False
    if name in public or name == "help":
        return True

    author = getattr(ctx, "author", None)
    perms = getattr(author, "guild_permissions", None)
    is_admin = bool(perms and (getattr(perms, "administrator", False) or getattr(perms, "manage_guild", False)))

    required = permission_commands.get(name)
    if required:
        return bool(perms and (is_admin or getattr(perms, required, False)))

    for names in categories.values():
        if name in set(names or ()):
            return is_admin

    # La politique centrale de main.py est fail-closed : une commande inconnue de la
    # matrice n'est suggérée qu'à un administrateur.
    return is_admin


def _command_suggestions(bot: commands.Bot, ctx: commands.Context, typed: str) -> list[str]:
    """Retourne jusqu'à 3 commandes/sous-commandes proches réellement accessibles."""
    typed = (typed or "").casefold().strip()
    if not typed:
        return []

    # walk_commands() couvre aussi les sous-commandes de groupes. Les alias participent à
    # la recherche, mais l'utilisateur reçoit toujours le nom canonique complet.
    lookup: dict[str, str] = {}
    for command in bot.walk_commands():
        if not _can_suggest_command(ctx, command):
            continue
        canonical = str(command.qualified_name).strip()
        if not canonical:
            continue
        lookup[canonical.casefold()] = canonical

        parent = getattr(command, "parent", None)
        parent_name = str(getattr(parent, "qualified_name", "") or "").strip()
        for alias in getattr(command, "aliases", ()):
            alias_name = str(alias).strip()
            if not alias_name:
                continue
            qualified_alias = f"{parent_name} {alias_name}".strip() if parent_name else alias_name
            lookup[qualified_alias.casefold()] = canonical

    matches = difflib.get_close_matches(typed, list(lookup), n=8, cutoff=0.52)
    result: list[str] = []
    for match in matches:
        canonical = lookup[match]
        if canonical not in result:
            result.append(canonical)
        if len(result) >= 3:
            break
    return result


def _typed_command_path(bot: commands.Bot, ctx: commands.Context) -> str:
    """Reconstruit le chemin saisi pour pouvoir corriger aussi `+groupe sous-commnde`."""
    invoked = str(getattr(ctx, "invoked_with", "") or "").strip()
    message = getattr(ctx, "message", None)
    content = str(getattr(message, "content", "") or "")
    prefix = str(getattr(ctx, "clean_prefix", None) or "+")

    if content.startswith(prefix):
        content = content[len(prefix):].strip()
    parts = content.split()
    if not parts:
        return invoked

    root = bot.get_command(parts[0])
    if not isinstance(root, commands.Group):
        return parts[0]

    # Une erreur CommandNotFound à l'intérieur d'un groupe signifie que les premiers mots
    # décrivent encore un chemin de commande, pas des arguments. On conserve uniquement la
    # profondeur maximale réellement possible sous ce groupe pour éviter d'inclure le texte
    # libre placé après une commande.
    max_depth = 1
    for child in root.walk_commands():
        max_depth = max(max_depth, len(str(child.qualified_name).split()))
    return " ".join(parts[:max_depth])


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


def _record_slash_start(interaction: discord.Interaction) -> None:
    """Mémorise le début d'une interaction slash sans modifier l'objet discord.py."""
    _SLASH_STARTS[int(interaction.id)] = time.perf_counter()
    if len(_SLASH_STARTS) > 5000:
        # Une interaction normale vit quelques secondes. Les entrées plus vieilles ne
        # peuvent être que des interactions interrompues avant completion.
        now = time.perf_counter()
        stale = [key for key, stamp in _SLASH_STARTS.items() if now - stamp > 300.0]
        for key in stale:
            _SLASH_STARTS.pop(key, None)


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

    async def mark_slash_command_start(interaction: discord.Interaction) -> None:
        if interaction.type is discord.InteractionType.application_command:
            _record_slash_start(interaction)

    def log_prefix_duration(ctx: commands.Context, *, failed: bool) -> None:
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

    def log_slash_duration(
        interaction: discord.Interaction,
        command: discord.app_commands.Command | discord.app_commands.ContextMenu,
    ) -> None:
        started = _SLASH_STARTS.pop(int(interaction.id), None)
        if started is None:
            return
        elapsed = max(0.0, time.perf_counter() - started)
        if elapsed < _SLOW_COMMAND_SECONDS:
            return
        logger.warning(
            "Commande lente : /%s a pris %.2fs (user=%s, guild=%s, état=succès).",
            getattr(command, "qualified_name", getattr(command, "name", "inconnue")),
            elapsed,
            getattr(interaction.user, "id", None),
            interaction.guild_id,
        )

    async def ensure_prefix_command_response(ctx: commands.Context) -> None:
        log_prefix_duration(ctx, failed=False)

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

            typed = _typed_command_path(bot, ctx)
            if not typed:
                return
            prefix = str(getattr(ctx, "clean_prefix", None) or "+")
            suggestions = _command_suggestions(bot, ctx, typed)

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

        log_prefix_duration(ctx, failed=True)

    async def ensure_slash_command_response(
        interaction: discord.Interaction,
        command: discord.app_commands.Command | discord.app_commands.ContextMenu,
    ) -> None:
        log_slash_duration(interaction, command)
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
    bot.add_listener(mark_slash_command_start, "on_interaction")
    # Aucun accusé de succès automatique : certaines commandes répondent via un message
    # direct, un menu ou une édition que ce garde ne peut pas toujours détecter. L'ancien
    # filet de sécurité ajoutait alors à tort « Commande exécutée » et pouvait donner
    # l'impression que la vraie interface avait disparu.
    bot.add_listener(improve_prefix_command_error, "on_command_error")
    _INSTALLED = True
    logger.info(
        "Expérience commandes activée : aucun succès automatique, suggestions filtrées et diagnostic préfixe/slash."
    )
