"""SentriX V98 — réparations d'exécution réelles pour la surface slash groupée.

Cette couche reste volontairement petite et tardive. Elle ne remplace pas les cogs métier :
- elle fait passer les slash groupés par ``Bot.invoke`` afin que les gardes/checks/hook finaux
  restent identiques aux commandes préfixées ;
- elle rend le defer du Context idempotent, ce qui évite le double defer des commandes IA ;
- elle conserve les pièces jointes même lorsqu'une ancienne signature exige le fallback
  texte ``arguments`` ;
- elle présente ``/ai ask`` au lieu de ``/ai ai`` et ajoute les contrôles IA réellement
  attendus ;
- elle répare les faux tickets « encore ouverts » lorsque le salon Discord a disparu ;
- elle aligne l'accès ``/setup`` sur la permission Gérer le serveur annoncée par SentriX ;
- elle restaure la signature des callbacks entourés par les gardes V17 avant l'inventaire.

Aucun schéma de base de données n'est modifié et toutes les commandes ``+`` restent intactes.
"""
from __future__ import annotations

import functools
import inspect
import logging
import types
import typing

import discord
from discord import app_commands
from discord.ext import commands
from discord.ext.commands.view import StringView

import sentrix_v95_runtime as v95
import sentrix_v97_reliability as v97
from database.db import now
from utils import ai_service, checks, embeds
from utils import sentrix_panels as panels

logger = logging.getLogger("bot.v98-runtime")


# ---------------------------------------------------------------------------
# Signature / invocation slash -> commande historique
# ---------------------------------------------------------------------------


def _unwrap_optional(annotation):
    origin = typing.get_origin(annotation)
    if origin is typing.Union or origin is types.UnionType:
        args = [item for item in typing.get_args(annotation) if item is not type(None)]
        if len(args) == 1:
            return args[0]
    return annotation


def _is_attachment(annotation) -> bool:
    return _unwrap_optional(annotation) is discord.Attachment


def _build_signature(command: commands.Command):
    """Version V97 corrigée : le fallback texte garde aussi les attachments natifs."""
    try:
        params = list(command.clean_params.items())
    except Exception:
        params = []

    interaction = inspect.Parameter(
        "interaction",
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
        annotation=discord.Interaction,
    )

    if v97._needs_text_fallback(command):
        output = [
            interaction,
            inspect.Parameter(
                "arguments",
                inspect.Parameter.KEYWORD_ONLY,
                annotation=str,
                default="",
            ),
        ]
        names = ["arguments"]
        used = {"arguments"}
        for raw_name, parameter in params:
            if not _is_attachment(parameter.annotation):
                continue
            exposed = v95._safe_name(raw_name, fallback="attachment").replace("-", "_")
            if exposed in used:
                exposed = f"attachment_{len(used)}"
            used.add(exposed)
            names.append(exposed)
            required = bool(getattr(parameter, "required", False))
            output.append(
                inspect.Parameter(
                    exposed,
                    inspect.Parameter.KEYWORD_ONLY,
                    annotation=discord.Attachment,
                    default=inspect.Parameter.empty if required else None,
                )
            )
        return inspect.Signature(output), False, tuple(names)

    return v97._build_signature(command)


_ORIGINAL_ARGUMENT_TEXT = v95._argument_text


def _argument_text(command: commands.Command, option_names: tuple[str, ...], kwargs: dict) -> str:
    # En fallback V98, les options qui suivent ``arguments`` sont exclusivement des
    # attachments. Elles sont injectées dans ctx.message et ne doivent jamais être
    # sérialisées dans le flux texte du parseur préfixé.
    if option_names and option_names[0] == "arguments":
        return str(kwargs.get("arguments") or "").strip()
    return _ORIGINAL_ARGUMENT_TEXT(command, option_names, kwargs)


def _attachment_values(kwargs: dict) -> list[discord.Attachment]:
    return [value for value in kwargs.values() if isinstance(value, discord.Attachment)]


async def _context_from_interaction(bot: commands.Bot, interaction: discord.Interaction) -> commands.Context:
    ctx = await commands.Context.from_interaction(interaction)
    try:
        sentrix_context = getattr(__import__("main"), "SentriXContext", None)
        if sentrix_context is not None and not isinstance(ctx, sentrix_context):
            ctx.__class__ = sentrix_context
    except Exception:
        logger.debug("Impossible d'appliquer SentriXContext au contexte slash V98.", exc_info=True)

    # Certaines commandes historiques (notamment l'IA) appellent ctx.defer() elles-mêmes.
    # Le bridge a déjà defer pour sécuriser le délai Discord : rendre ce second appel no-op
    # évite InteractionResponded sans demander une réécriture de chaque commande métier.
    original_defer = getattr(ctx, "defer", None)
    if callable(original_defer) and not getattr(original_defer, "_sentrix_v98", False):
        async def safe_defer(*args, **kwargs):
            if interaction.response.is_done():
                return None
            try:
                return await original_defer(*args, **kwargs)
            except discord.InteractionResponded:
                return None
        safe_defer._sentrix_v98 = True
        try:
            ctx.defer = safe_defer
        except Exception:
            logger.debug("Context.defer non remplaçable sur cette version discord.py.", exc_info=True)
    return ctx


async def _invoke_original(
    bot: commands.Bot,
    command: commands.Command,
    interaction: discord.Interaction,
    option_names: tuple[str, ...],
    kwargs: dict,
) -> None:
    """Exécute la vraie commande + via le pipeline Bot.invoke complet.

    V95/V97 appelaient directement ``root.invoke(ctx)``. Cela contournait les enveloppes
    finales posées sur ``Bot.invoke`` et produisait des comportements différents entre + et /
    (permissions, gardes runtime, journalisation et certains correctifs tardifs).
    """
    if not interaction.response.is_done():
        try:
            await interaction.response.defer(thinking=True)
        except discord.InteractionResponded:
            pass

    ctx = await _context_from_interaction(bot, interaction)

    attachments = _attachment_values(kwargs)
    if attachments:
        try:
            ctx.message.attachments = list(attachments)
        except Exception:
            logger.debug("Impossible d'injecter les pièces jointes slash dans ctx.message.", exc_info=True)

    root = command.root_parent or command
    path = str(command.qualified_name).split()[1:] if command.root_parent is not None else []
    arguments = _argument_text(command, option_names, kwargs)
    source = " ".join([*path, arguments]).strip()

    ctx.view = StringView(source)
    ctx.command = root
    ctx.invoked_with = root.name
    ctx.invoked_parents = []
    ctx.invoked_subcommand = None
    ctx.subcommand_passed = None

    try:
        await bot.invoke(ctx)
    except Exception as exc:
        logger.exception("V98 : exception hors pipeline sur /%s.", command.qualified_name)
        try:
            await v97._dispatch_legacy_error(ctx, root, exc)
        except Exception:
            logger.exception("V98 : impossible de dispatcher l'erreur de /%s.", command.qualified_name)


# ---------------------------------------------------------------------------
# Réparations avant construction de la surface V95
# ---------------------------------------------------------------------------


def _restore_wrapped_signatures(bot: commands.Bot) -> None:
    """Rend inspectables les wrappers V17 sans retirer leurs protections métier."""
    repaired = 0
    for command in bot.walk_commands():
        callback = getattr(command, "callback", None)
        original = getattr(callback, "_sentrix_original", None)
        if not callable(callback) or not callable(original):
            continue
        try:
            if getattr(callback, "__wrapped__", None) is not original:
                callback.__wrapped__ = original
            callback.__signature__ = inspect.signature(original)
            # update_wrapper garde les attributs de sécurité déjà présents dans __dict__.
            functools.update_wrapper(callback, original, updated=())
            repaired += 1
        except (TypeError, ValueError, AttributeError):
            logger.debug("Signature legacy non restaurable pour %s.", command.qualified_name, exc_info=True)
    if repaired:
        logger.info("V98 : %s wrapper(s) legacy rendus inspectables pour les slash.", repaired)


def _patch_setup_permissions() -> None:
    try:
        from cogs import setup_control_center as setup_center
    except Exception:
        return
    current = setup_center._can_setup
    if getattr(current, "_sentrix_v98", False):
        return

    async def can_setup_v98(bot, member, guild):
        if guild is None or not isinstance(member, discord.Member):
            return False
        if member.id == guild.owner_id:
            return True
        if member.guild_permissions.administrator or member.guild_permissions.manage_guild:
            return True

        class Ctx:
            pass

        ctx = Ctx()
        ctx.author, ctx.bot, ctx.guild = member, bot, guild
        return bool(await checks.is_verified_bot_owner(ctx))

    async def permission_error_v98(target):
        panel = embeds.error(
            "Vous ne pouvez pas ouvrir la configuration de ce serveur.\n\n"
            "**Permission requise :** Gérer le serveur"
        )
        if isinstance(target, commands.Context):
            return await panels.envoyer(target, panels.depuis_embed(panel))
        if target.response.is_done():
            return await panels.envoyer(target.followup, panels.depuis_embed(panel), ephemere=True)
        return await panels.envoyer(target.response, panels.depuis_embed(panel), ephemere=True)

    can_setup_v98._sentrix_v98 = True
    can_setup_v98._sentrix_original = current
    setup_center._can_setup = can_setup_v98
    setup_center._permission_error = permission_error_v98
    logger.info("V98 : /setup aligné sur Gérer le serveur / Administrateur / owner.")


def _patch_ticket_runtime(bot: commands.Bot) -> None:
    cog = bot.get_cog("Tickets")
    if cog is None:
        return
    cls = type(cog)
    current = cls.start_ticket_flow
    if not getattr(current, "_sentrix_v98", False):
        async def start_ticket_flow_v98(self, interaction: discord.Interaction, type_id: int):
            guild = interaction.guild
            user = interaction.user
            if guild is not None and user is not None:
                rows = await self.bot.db.fetchall(
                    "SELECT id, channel_id FROM tickets WHERE guild_id=? AND user_id=? AND type_id=? AND status='ouvert'",
                    (guild.id, user.id, type_id),
                )
                repaired = 0
                for row in rows:
                    channel_id = int(row["channel_id"] or 0)
                    if channel_id <= 0:
                        missing = True
                    else:
                        missing = guild.get_channel(channel_id) is None
                        if missing:
                            try:
                                await guild.fetch_channel(channel_id)
                                missing = False
                            except discord.NotFound:
                                missing = True
                            except (discord.Forbidden, discord.HTTPException):
                                # En cas d'incertitude réseau/permission, ne jamais fermer
                                # automatiquement un vrai ticket encore existant.
                                missing = False
                    if missing:
                        await self.bot.db.execute(
                            "UPDATE tickets SET status='ferme', closed_at=COALESCE(closed_at, ?), locked=1 "
                            "WHERE id=? AND status='ouvert'",
                            (now(), row["id"]),
                        )
                        repaired += 1
                if repaired:
                    logger.warning(
                        "V98 : %s ticket(s) fantôme(s) réparés avant ouverture (guild=%s user=%s type=%s).",
                        repaired, guild.id, user.id, type_id,
                    )
            return await current(self, interaction, type_id)

        start_ticket_flow_v98._sentrix_v98 = True
        start_ticket_flow_v98._sentrix_original = current
        cls.start_ticket_flow = start_ticket_flow_v98

    if not getattr(bot, "_sentrix_v98_ticket_delete_listener", False):
        async def deleted_channel(channel: discord.abc.GuildChannel):
            try:
                await bot.db.execute(
                    "UPDATE tickets SET status='ferme', closed_at=COALESCE(closed_at, ?), locked=1 "
                    "WHERE guild_id=? AND channel_id=? AND status='ouvert'",
                    (now(), channel.guild.id, channel.id),
                )
            except Exception:
                logger.exception("V98 : nettoyage du ticket supprimé impossible (channel=%s).", channel.id)

        bot.add_listener(deleted_channel, "on_guild_channel_delete")
        bot._sentrix_v98_ticket_delete_listener = True
    logger.info("V98 : auto-réparation des tickets fantômes active.")


# ---------------------------------------------------------------------------
# Surface IA explicite
# ---------------------------------------------------------------------------


_ORIGINAL_GROUP_FOR = v95._group_for


def _group_for(command: commands.Command) -> tuple[str, str]:
    name = str(command.name or "").casefold()
    if name == "ai":
        return "ai", "ask"
    if name == "ai-translate":
        return "ai", "translate"
    return _ORIGINAL_GROUP_FOR(command)


async def _ai_context(bot: commands.Bot, interaction: discord.Interaction) -> commands.Context:
    return await _context_from_interaction(bot, interaction)


async def _ai_admin_allowed(bot: commands.Bot, interaction: discord.Interaction) -> bool:
    guild = interaction.guild
    member = interaction.user
    if guild is None or not isinstance(member, discord.Member):
        return False
    if member.id == guild.owner_id or member.guild_permissions.administrator or member.guild_permissions.manage_guild:
        return True
    ctx = await _ai_context(bot, interaction)
    return bool(await checks.is_verified_bot_owner(ctx))


async def _ai_reply(interaction: discord.Interaction, embed: discord.Embed, *, ephemeral: bool = True):
    if interaction.response.is_done():
        return await panels.envoyer(interaction.followup, panels.depuis_embed(embed), ephemere=ephemeral)
    return await panels.envoyer(interaction.response, panels.depuis_embed(embed), ephemere=ephemeral)


def _install_ai_controls(bot: commands.Bot) -> None:
    cog = bot.get_cog("Ai")
    if cog is None:
        logger.warning("V98 : Cog Ai introuvable, contrôles /ai non ajoutés.")
        return
    group = bot.tree.get_command("ai", type=discord.AppCommandType.chat_input)
    if not isinstance(group, app_commands.Group):
        logger.warning("V98 : racine /ai non groupée, contrôles non ajoutés.")
        return

    existing = {item.name for item in group.commands}

    def add(name: str, description: str, callback):
        if name in existing:
            return
        group.add_command(app_commands.Command(name=name, description=description[:100], callback=callback))
        existing.add(name)

    async def enable(interaction: discord.Interaction):
        if not await _ai_admin_allowed(bot, interaction):
            return await _ai_reply(interaction, embeds.error("Permission **Gérer le serveur** requise."))
        await ai_service.update_setting(bot, interaction.guild.id, "enabled", 1)
        await _ai_reply(interaction, embeds.success("L'IA SentriX est maintenant activée sur ce serveur."))

    async def disable(interaction: discord.Interaction):
        if not await _ai_admin_allowed(bot, interaction):
            return await _ai_reply(interaction, embeds.error("Permission **Gérer le serveur** requise."))
        await ai_service.update_setting(bot, interaction.guild.id, "enabled", 0)
        await _ai_reply(interaction, embeds.success("L'IA SentriX est maintenant désactivée sur ce serveur."))

    async def reset(interaction: discord.Interaction):
        ctx = await _ai_context(bot, interaction)
        await cog._ai_reset(ctx)

    async def memory(interaction: discord.Interaction):
        ctx = await _ai_context(bot, interaction)
        await cog._ai_memory(ctx)

    async def model(interaction: discord.Interaction):
        ctx = await _ai_context(bot, interaction)
        await cog._ai_model(ctx)

    async def help_cmd(interaction: discord.Interaction):
        ctx = await _ai_context(bot, interaction)
        await cog._ai_help(ctx)

    async def search(interaction: discord.Interaction, query: str):
        ctx = await _ai_context(bot, interaction)
        await cog._handle_ai_command(
            ctx,
            f"Recherche sur le web des informations actuelles et réponds précisément à ceci : {query}",
        )

    search.__annotations__ = {"interaction": discord.Interaction, "query": str}
    search.__signature__ = inspect.Signature([
        inspect.Parameter("interaction", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=discord.Interaction),
        inspect.Parameter("query", inspect.Parameter.KEYWORD_ONLY, annotation=str),
    ])

    add("enable", "Activer l'IA SentriX sur ce serveur.", enable)
    add("disable", "Désactiver l'IA SentriX sur ce serveur.", disable)
    add("reset", "Réinitialiser votre conversation IA dans ce salon.", reset)
    add("memory", "Afficher l'état de votre mémoire de conversation IA.", memory)
    add("model", "Afficher le modèle IA actuellement utilisé.", model)
    add("help", "Afficher l'aide des fonctions IA SentriX.", help_cmd)
    add("search", "Rechercher des informations actuelles avec l'IA.", search)

    logger.info("V98 : contrôles /ai ajoutés (%s).", ", ".join(sorted(existing)))


# ---------------------------------------------------------------------------
# Installation
# ---------------------------------------------------------------------------


def install() -> None:
    if getattr(v95, "_sentrix_v98_runtime", False):
        return

    # V97 reste utile pour le fallback texte et le dashboard ; V98 corrige son chemin
    # d'exécution et sa gestion des attachments en fallback.
    v97.install_slash()
    v95._build_signature = _build_signature
    v95._argument_text = _argument_text
    v95._invoke_original = _invoke_original
    v95._group_for = _group_for

    current_prepare = v95.prepare_bot

    async def prepare_bot_v98(bot):
        _restore_wrapped_signatures(bot)
        _patch_setup_permissions()
        _patch_ticket_runtime(bot)
        mapping = await current_prepare(bot)
        _install_ai_controls(bot)
        bot._sentrix_v98_ready = True
        return mapping

    prepare_bot_v98._sentrix_v98 = True
    prepare_bot_v98._sentrix_original = current_prepare
    v95.prepare_bot = prepare_bot_v98
    v95._sentrix_v98_runtime = True
    logger.warning("V98 installé : Bot.invoke, IA groupée, tickets fantômes et permissions setup réparés.")


__all__ = [
    "install",
    "_build_signature",
    "_argument_text",
    "_invoke_original",
    "_group_for",
]
