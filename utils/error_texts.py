"""Textes d'erreur utilisateur — source unique pour les deux transports (+ et /).

Règle : chaque refus dit sa VRAIE cause. Une erreur n'est jamais reformulée en
« pas la permission » quand la cause est un module désactivé, un système d'argent
coupé, un message privé, un cooldown ou un argument invalide.

- ``MissingPermissions``      → la permission Discord exacte qui manque au membre ;
- ``BotMissingPermissions``   → la permission Discord exacte qui manque à SentriX ;
- ``BotPermissionError``      → son message d'origine, toujours conservé tel quel ;
- ``CheckFailure`` nu         → la raison si un check ou la matrice la connaît
                                (:func:`explain_check_failure`), sinon un dernier
                                recours qui ne parle pas de permission ;
- arguments                   → quel argument pose problème.

Ce module ne dépend d'aucune couche runtime : ``cogs/final_error_embed_v5.py``
(préfixe + slash natif) et ``sentrix_grouped_slash_fix.py`` (slash groupé) l'appellent.
"""
from __future__ import annotations

from typing import Any

import discord
from discord.ext import commands

from utils.command_permissions import permission_label

# Message par défaut de discord.py pour un check qui renvoie False sans explication.
_DEFAULT_CHECK_MESSAGE = "The check functions for command"
# Dernier recours : n'affirme PAS un problème de permission (on ne le sait pas).
CHECK_FALLBACK = (
    "SentriX n'a pas pu autoriser cette commande ici : une vérification a refusé "
    "sans préciser laquelle. Réessayez sur un serveur où le module est activé, "
    "ou demandez `/permissions explain`."
)
GUILD_ONLY_TEXT = "Cette commande s'utilise dans un salon de serveur, pas en message privé."
DM_ONLY_TEXT = "Cette commande s'utilise en message privé avec SentriX."


def permission_labels(permissions) -> str:
    """« Gérer les messages » / « Gérer les rôles et Bannir des membres »."""
    names = [permission_label(str(p)) for p in (permissions or ())]
    if not names:
        return "une permission supplémentaire"
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + f" et {names[-1]}"


def missing_permissions_text(permissions) -> str:
    labels = permission_labels(permissions)
    mot = "la permission" if len(list(permissions or ())) <= 1 else "les permissions"
    return f"Il te faut {mot} **{labels}** pour utiliser cette commande."


def bot_missing_permissions_text(permissions) -> str:
    labels = permission_labels(permissions)
    mot = "la permission" if len(list(permissions or ())) <= 1 else "les permissions"
    return f"Il manque à SentriX {mot} **{labels}** pour effectuer cette action."


def cooldown_text(retry_after: float) -> str:
    return f"Commande en attente : réessayez dans {max(1, round(float(retry_after or 1.0)))} s."


def check_failure_message(error: BaseException) -> str | None:
    """Le message porté par le check lui-même, ou None s'il n'en a pas."""
    message = getattr(error, "message", None)
    if message:
        return str(message)
    reason = getattr(error, "reason", None)
    if reason and type(error).__name__ == "BotBlacklistedError":
        return f"Vous n'êtes pas autorisé à utiliser SentriX ({reason})."
    text = str(error or "").strip()
    if text and not text.startswith(_DEFAULT_CHECK_MESSAGE):
        return text
    return None


def argument_error_text(error: BaseException, *, usage: str | None, param_name: str | None = None) -> str | None:
    """Explique QUEL argument pose problème. None si ce n'est pas une erreur d'argument."""
    aide = f" Usage : `{usage}`" if usage else ""
    if isinstance(error, commands.MissingRequiredArgument):
        name = getattr(getattr(error, "param", None), "displayed_name", None) or getattr(getattr(error, "param", None), "name", "argument")
        return f"Il manque l'argument obligatoire « {name} ».{aide}"
    if isinstance(error, commands.MissingRequiredAttachment):
        return f"Cette commande attend un fichier joint au message.{aide}"
    if isinstance(error, commands.TooManyArguments):
        return f"Trop d'arguments.{aide}"
    introuvables = {
        commands.MemberNotFound: "Membre introuvable",
        commands.UserNotFound: "Utilisateur introuvable",
        commands.RoleNotFound: "Rôle introuvable",
        commands.ChannelNotFound: "Salon introuvable",
        commands.MessageNotFound: "Message introuvable",
        commands.EmojiNotFound: "Emoji introuvable",
        commands.ThreadNotFound: "Fil introuvable",
        commands.GuildNotFound: "Serveur introuvable",
    }
    for kind, label in introuvables.items():
        if isinstance(error, kind):
            argument = getattr(error, "argument", None)
            precision = f" : « {str(argument)[:60]} »" if argument else ""
            return f"{label}{precision}. Indiquez une mention, un nom ou un identifiant."
    if isinstance(error, commands.RangeError):
        minimum, maximum = getattr(error, "minimum", None), getattr(error, "maximum", None)
        nom = f" « {param_name} »" if param_name else ""
        if minimum is not None and maximum is not None:
            return f"La valeur{nom} doit être comprise entre {minimum} et {maximum}.{aide}"
        if maximum is not None:
            return f"La valeur{nom} ne doit pas dépasser {maximum}.{aide}"
        if minimum is not None:
            return f"La valeur{nom} doit être au moins {minimum}.{aide}"
        return f"Valeur{nom} hors limites.{aide}"
    if isinstance(error, commands.BadLiteralArgument):
        valeurs = ", ".join(f"`{v}`" for v in getattr(error, "literals", ()) or ())
        name = getattr(getattr(error, "param", None), "name", param_name or "argument")
        return f"L'argument « {name} » doit être l'une de ces valeurs : {valeurs}.{aide}"
    if isinstance(error, commands.BadBoolArgument):
        return f"Indiquez `oui` ou `non` pour « {param_name or 'cet argument'} ».{aide}"
    if isinstance(error, commands.BadColourArgument):
        return f"Couleur invalide : utilisez un code comme `#5865F2`.{aide}"
    if isinstance(error, commands.BadInviteArgument):
        return f"Invitation invalide ou expirée.{aide}"
    if isinstance(error, commands.BadUnionArgument):
        name = getattr(getattr(error, "param", None), "name", param_name or "argument")
        return f"L'argument « {name} » n'est pas reconnu (membre, rôle ou salon attendu).{aide}"
    if isinstance(error, (commands.BadArgument, commands.ConversionError, commands.ArgumentParsingError, commands.UserInputError)):
        nom = f" « {param_name} »" if param_name else ""
        return f"L'argument{nom} est invalide.{aide}"
    return None


def user_error_text(error: BaseException, *, usage: str | None = None, param_name: str | None = None) -> str | None:
    """Une phrase pour une erreur SIMPLE ; None pour une vraie erreur technique.

    Traite l'erreur telle quelle (``CommandInvokeError`` déjà déballé par l'appelant).
    """
    if isinstance(error, commands.CommandOnCooldown):
        return cooldown_text(error.retry_after)
    if isinstance(error, commands.MaxConcurrencyReached):
        return "Cette commande est déjà en cours. Terminez-la avant de recommencer."
    if isinstance(error, commands.MissingPermissions):
        return missing_permissions_text(error.missing_permissions)
    if isinstance(error, commands.BotMissingPermissions):
        return bot_missing_permissions_text(error.missing_permissions)
    if isinstance(error, (commands.MissingRole, commands.MissingAnyRole)):
        roles = getattr(error, "missing_roles", None) or [getattr(error, "missing_role", "")]
        return "Il te faut le rôle **" + "** ou **".join(str(r) for r in roles) + "** pour utiliser cette commande."
    if isinstance(error, (commands.BotMissingRole, commands.BotMissingAnyRole)):
        return "Il manque à SentriX un rôle requis pour effectuer cette action."
    if isinstance(error, commands.NoPrivateMessage):
        return GUILD_ONLY_TEXT
    if isinstance(error, commands.PrivateMessageOnly):
        return DM_ONLY_TEXT
    if isinstance(error, commands.NotOwner):
        return "Cette commande est réservée au **propriétaire de SentriX**."
    if isinstance(error, commands.NSFWChannelRequired):
        return "Cette commande n'est disponible que dans un salon NSFW."
    if isinstance(error, commands.DisabledCommand):
        return "Cette commande est désactivée pour le moment."
    if type(error).__name__ == "RuntimeRateLimitError":
        return f"Fonction temporairement limitée : réessayez dans {max(1, round(float(getattr(error, 'retry_after', 1.0) or 1.0)))} s."
    argument = argument_error_text(error, usage=usage, param_name=param_name)
    if argument is not None:
        return argument
    if isinstance(error, commands.CheckFailure):
        # BotPermissionError, BotBlacklistedError, ou un check qui a expliqué son refus.
        return check_failure_message(error)  # None => l'appelant tente explain_check_failure
    if isinstance(error, discord.Forbidden):
        return ("Discord a refusé l'action : vérifiez que le rôle SentriX est placé au-dessus "
                "du membre ou du rôle visé et qu'il possède la permission nécessaire.")
    if isinstance(error, discord.HTTPException):
        texte = str(getattr(error, "text", "") or "").strip()
        return f"Discord a refusé la requête{f' : {texte}' if texte else ''}."
    return None


async def explain_check_failure(bot, *, command: Any, author: Any, guild: Any) -> str:
    """Pourquoi un check nu a refusé : matrice d'accès, systèmes coupés, MP… sinon dernier recours."""
    try:
        from cogs import permission_guard
        from utils import access_matrix

        name = permission_guard.command_root_name(command)
        if name:
            decision = await access_matrix.evaluate(bot, command_name=name, author=author, guild=guild)
            if not decision.allowed and decision.message:
                return decision.message
    except Exception:
        pass
    guild_id = getattr(guild, "id", None)
    if guild_id is not None:
        try:
            from utils.system_features import is_system_enabled

            cog_name = str(getattr(command, "cog_name", "") or "")
            if cog_name == "Economy" and not await is_system_enabled(bot.db, int(guild_id), "economy"):
                return "Le **système d'argent est désactivé** sur ce serveur."
            if cog_name in {"Levels", "Stats"} and not await is_system_enabled(bot.db, int(guild_id), "levels"):
                return "Le **système de niveaux est désactivé** sur ce serveur."
        except Exception:
            pass
    else:
        return GUILD_ONLY_TEXT
    return CHECK_FALLBACK


__all__ = [
    "CHECK_FALLBACK", "GUILD_ONLY_TEXT", "DM_ONLY_TEXT", "permission_labels",
    "missing_permissions_text", "bot_missing_permissions_text", "cooldown_text",
    "check_failure_message", "argument_error_text", "user_error_text", "explain_check_failure",
]
