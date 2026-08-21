"""SentriX V2.3 — accessibilité et simplicité, sans nouvelle commande.

Objectifs :
- une faute de commande reçoit une seule suggestion claire via le garde de réponses ;
- les erreurs d'arguments expliquent quoi corriger avec la syntaxe réelle ;
- la navigation naturelle tolère les petites fautes ;
- les paginations utilisent des libellés textuels, pas uniquement des flèches ;
- les actions sensibles ne sont jamais auto-corrigées/exécutées à partir d'une faute.
"""
from __future__ import annotations

import logging
import sys
import types

import discord
from discord.ext import commands

from utils import embeds
from utils.accessibility import closest_commands, human_parameter, match_quick_intent, usage_line

from . import bot_experience_v6

logger = logging.getLogger("bot.accessibility-v23")


def _runtime_main():
    return sys.modules.get("main") or sys.modules.get("__main__")


def _prefix(ctx: commands.Context) -> str:
    return str(getattr(ctx, "clean_prefix", None) or "+")


def _typed_root(ctx: commands.Context) -> str:
    message = getattr(ctx, "message", None)
    content = str(getattr(message, "content", "") or "").strip()
    prefix = _prefix(ctx)
    if content.startswith(prefix):
        content = content[len(prefix):]
    return content.split(maxsplit=1)[0].strip()


def _friendly_permissions(names) -> str:
    main = _runtime_main()
    labels = getattr(main, "PERMISSION_LABELS", {}) if main else {}
    values = [labels.get(name, str(name).replace("_", " ").capitalize()) for name in names]
    return ", ".join(values)


def _visible_candidates(bot: commands.Bot, ctx: commands.Context) -> list[str]:
    """Ne suggère pas aveuglément des commandes staff à un membre normal."""
    main = _runtime_main()
    public = set(getattr(main, "PUBLIC_COMMANDS", set()) or set()) if main else set()
    permission_commands = dict(getattr(main, "DISCORD_PERMISSION_COMMANDS", {}) or {}) if main else {}

    member = ctx.author if isinstance(ctx.author, discord.Member) else None
    perms = getattr(member, "guild_permissions", None)
    is_admin = bool(perms and (perms.administrator or perms.manage_guild))

    result: list[str] = []
    for command in bot.commands:
        if command.hidden or not command.enabled:
            continue
        name = str(command.name)
        if name in public or is_admin:
            result.append(name)
            continue
        required = permission_commands.get(name)
        if required and perms and getattr(perms, required, False):
            result.append(name)
    # +help doit toujours pouvoir être proposé même pendant une phase de bootstrap.
    if bot.get_command("help") is not None and "help" not in result:
        result.append("help")
    return result


async def _safe_send(ctx: commands.Context, *, title: str, description: str):
    """Embed textuel + fallback texte brut si Discord refuse l'embed."""
    embed = embeds.warning(description, title=title)
    try:
        return await ctx.send(embed=embed)
    except discord.HTTPException:
        try:
            return await ctx.send(f"**{title}**\n{description}")
        except discord.HTTPException:
            return None


class SentriXAccessibility(commands.Cog):
    """Couche runtime V2.3. Elle ne déclare aucune commande publique."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        self._install_error_explanations()
        self._install_typo_tolerant_navigation()
        self._install_accessible_pagination()
        self.bot._sentrix_accessibility_ready = True
        self.bot._sentrix_accessibility_state = {
            "ready": True,
            "new_commands": 0,
            "unknown_command_suggestions": True,
            "friendly_argument_errors": True,
            "typo_tolerant_navigation": True,
            "text_pagination_labels": True,
        }
        logger.info("SentriX V2.3 accessibilité installée, 0 nouvelle commande.")

    def _install_error_explanations(self):
        if getattr(self.bot, "_sentrix_accessible_error_handler", False):
            return
        original = self.bot.on_command_error

        async def accessible_error_handler(_bot, ctx: commands.Context, error: commands.CommandError):
            raw_error = error
            error = getattr(error, "original", error)

            # Les commandes inconnues sont volontairement laissées au garde de réponses
            # global (command_response_guard). Il est l'unique source de suggestion pour
            # les fautes comme +hyelp -> +help. Les traiter aussi ici produisait deux embeds
            # pour le même message Discord.
            if isinstance(error, commands.CommandNotFound):
                return await original(ctx, raw_error)

            command = getattr(ctx, "command", None)
            command_name = str(getattr(command, "qualified_name", "") or getattr(command, "name", "") or "commande")
            signature = str(getattr(command, "signature", "") or "")
            usage = usage_line(_prefix(ctx), command_name, signature)

            if isinstance(error, commands.MissingRequiredArgument):
                parameter = human_parameter(getattr(error.param, "name", None))
                return await _safe_send(
                    ctx,
                    title="Information manquante",
                    description=(
                        f"Il manque **{parameter}**.\n"
                        f"Utilise : `{usage}`\n\n"
                        "Les éléments entre `< >` sont obligatoires ; ceux entre `[ ]` sont optionnels."
                    ),
                )

            if isinstance(error, commands.TooManyArguments):
                return await _safe_send(
                    ctx,
                    title="Trop d'informations",
                    description=f"Cette commande a reçu trop d'arguments.\nUtilise : `{usage}`",
                )

            member_not_found = getattr(commands, "MemberNotFound", ())
            user_not_found = getattr(commands, "UserNotFound", ())
            role_not_found = getattr(commands, "RoleNotFound", ())
            channel_not_found = getattr(commands, "ChannelNotFound", ())

            if member_not_found and isinstance(error, member_not_found):
                return await _safe_send(
                    ctx,
                    title="Membre introuvable",
                    description=f"Mentionne le membre ou utilise son identifiant Discord.\nExemple : `{_prefix(ctx)}{command_name} @membre ...`",
                )
            if user_not_found and isinstance(error, user_not_found):
                return await _safe_send(ctx, title="Utilisateur introuvable", description=f"Vérifie la mention ou l'identifiant.\nUtilise : `{usage}`")
            if role_not_found and isinstance(error, role_not_found):
                return await _safe_send(ctx, title="Rôle introuvable", description=f"Mentionne un rôle existant ou vérifie son nom.\nUtilise : `{usage}`")
            if channel_not_found and isinstance(error, channel_not_found):
                return await _safe_send(ctx, title="Salon introuvable", description=f"Mentionne un salon existant.\nUtilise : `{usage}`")

            if isinstance(error, commands.BadArgument):
                return await _safe_send(
                    ctx,
                    title="Argument non compris",
                    description=(
                        "Je n'ai pas compris une des informations données.\n"
                        f"Syntaxe attendue : `{usage}`\n"
                        "Tu peux utiliser des mentions Discord quand une commande demande un membre, un rôle ou un salon."
                    ),
                )

            if isinstance(error, commands.CommandOnCooldown):
                seconds = max(1, round(float(error.retry_after)))
                if seconds >= 3600:
                    wait = f"{seconds // 3600} h {(seconds % 3600) // 60} min"
                elif seconds >= 60:
                    wait = f"{seconds // 60} min {seconds % 60} s"
                else:
                    wait = f"{seconds} s"
                return await _safe_send(ctx, title="Commande en pause", description=f"Tu pourras la réutiliser dans **{wait}**.")

            if isinstance(error, commands.MissingPermissions):
                return await _safe_send(
                    ctx,
                    title="Permission nécessaire",
                    description=f"Il te manque : **{_friendly_permissions(error.missing_permissions)}**.",
                )

            if isinstance(error, commands.BotMissingPermissions):
                return await _safe_send(
                    ctx,
                    title="Permission du bot manquante",
                    description=(
                        f"SentriX a besoin de : **{_friendly_permissions(error.missing_permissions)}**.\n"
                        "Un administrateur doit corriger les permissions du rôle du bot."
                    ),
                )

            if isinstance(error, commands.NoPrivateMessage):
                return await _safe_send(ctx, title="Serveur requis", description="Cette action doit être utilisée dans un serveur Discord, pas en message privé.")

            # Les erreurs de sécurité/permissions personnalisées et les exceptions métier
            # continuent vers le gestionnaire historique, qui connaît mieux leur contexte.
            return await original(ctx, raw_error)

        self.bot.on_command_error = types.MethodType(accessible_error_handler, self.bot)
        self.bot._sentrix_accessible_error_handler = True

    def _install_typo_tolerant_navigation(self):
        original = bot_experience_v6._quick_intent
        if getattr(original, "_sentrix_accessibility", False):
            return

        def tolerant_intent(question: str):
            direct = original(question)
            if direct is not None:
                return direct
            return match_quick_intent(question)

        tolerant_intent._sentrix_accessibility = True
        bot_experience_v6._quick_intent = tolerant_intent

    def _install_accessible_pagination(self):
        from utils import helpers

        cls = helpers.PaginatorView
        if getattr(cls, "_sentrix_accessibility", False):
            return
        original_init = cls.__init__
        original_update = cls._update_buttons

        def accessible_init(view, *args, **kwargs):
            original_init(view, *args, **kwargs)
            view.previous_page.label = "Précédent"
            view.previous_page.emoji = "◀️"
            view.next_page.label = "Suivant"
            view.next_page.emoji = "▶️"
            original_update(view)

        def accessible_update(view):
            original_update(view)
            # Le texte reste compréhensible même sans distinguer la couleur/forme du bouton.
            view.previous_page.label = "Précédent"
            view.next_page.label = "Suivant"

        cls.__init__ = accessible_init
        cls._update_buttons = accessible_update
        cls._sentrix_accessibility = True