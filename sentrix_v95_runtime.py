"""SentriX V95 — journaux d'invitations fiables et surface slash groupée.

Objectifs :
- ne jamais dupliquer le suivi métier des invitations : ``cogs.invites`` garde son cache
  et ce module ne fait que produire les journaux ``invite_create``/``invite_delete`` ;
- corréler le responsable via l'objet Invite puis le journal d'audit, sans afficher un
  faux « utilisateur inconnu » lorsque Discord ne fournit pas l'information ;
- exposer les vraies commandes texte/hybrides derrière des groupes slash compacts sans
  dupliquer leur logique métier, leurs checks, leurs convertisseurs ou leurs accès DB ;
- conserver toutes les commandes ``+`` intactes.

La préparation est idempotente et exécutée juste avant ``CommandTree.sync``. Cela permet
à Railway d'avoir fini de charger ses extensions tardives avant l'inventaire final.
"""
from __future__ import annotations

import hashlib
import inspect
import logging
import re
import shlex
import types
import typing
from dataclasses import dataclass

import discord
from discord import app_commands
from discord.ext import commands
from discord.ext.commands.view import StringView

from utils import embeds, log_service

logger = logging.getLogger("bot.v95")

DIRECT_ROOTS = frozenset({"help", "setup", "ping", "sentrix"})
EXCLUDED_COMMANDS = frozenset({"logsdiag"})
MAX_ROOT_COMMANDS = 100
MAX_CHILDREN = 25
MAX_OPTIONS = 25

CATEGORY_ROOTS = {
    "ai": "ai",
    "information": "info",
    "utility": "utility",
    "economy": "economy",
    "levels": "levels",
    "games": "games",
    "music": "music",
    "events": "events",
    "social": "social",
    "tickets": "ticket",
    "sanctions": "sanctions",
    "moderation": "moderation",
    "security": "security",
    "configuration": "config",
    "server": "server",
    "roles": "roles",
    "embeds": "embeds",
    "stats": "stats",
    "owner": "owner",
    "other": "more",
}

GROUP_DESCRIPTIONS = {
    "ai": "Intelligence artificielle et génération de contenu.",
    "info": "Informations sur les membres, salons, serveur et bot.",
    "utility": "Outils pratiques et commandes quotidiennes.",
    "economy": "Économie, banque, boutique et récompenses.",
    "levels": "Niveaux, XP, réputation et classements.",
    "games": "Mini-jeux et activités communautaires.",
    "music": "Lecture audio, file d'attente et playlists.",
    "events": "Événements et tournois.",
    "giveaway": "Giveaways et tirages au sort.",
    "invites": "Invitations, classements et bonus d'invitations.",
    "notifications": "Notifications sociales et messages d'accueil.",
    "social": "Fonctions sociales de SentriX.",
    "ticket": "Tickets, support et configuration des tickets.",
    "sanctions": "Sanctions, dossiers et quarantaine.",
    "moderation": "Modération des messages, salons, membres et rôles.",
    "security": "AutoMod, anti-raid, anti-nuke et sécurité.",
    "config": "Configuration générale de SentriX.",
    "server": "Structure et administration du serveur.",
    "roles": "Rôles, panels et vérification.",
    "embeds": "Embeds, annonces et design.",
    "stats": "Statistiques et diagnostics.",
    "owner": "Commandes réservées au propriétaire de SentriX.",
    "more": "Autres fonctions actives de SentriX.",
}


@dataclass(frozen=True)
class SlashTarget:
    command: commands.Command
    root_name: str
    leaf_name: str
    original_name: str
    native_options: bool


def _safe_name(value: object, *, fallback: str = "command") -> str:
    text = str(value or "").strip().casefold().replace("_", "-")
    text = re.sub(r"[^a-z0-9-]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-") or fallback
    if len(text) <= 32:
        return text
    digest = hashlib.blake2s(text.encode("utf-8"), digest_size=3).hexdigest()
    return f"{text[:25].rstrip('-')}-{digest}"[:32]


def _description(command: commands.Command) -> str:
    raw = re.sub(r"\s+", " ", str(command.description or command.help or "")).strip()
    if not raw:
        raw = f"Exécuter {command.qualified_name}."
    return raw[:100]


def _is_group_with_children(command: commands.Command) -> bool:
    return isinstance(command, commands.Group) and bool(getattr(command, "commands", ()))


def _should_expose(command: commands.Command) -> bool:
    name = str(command.qualified_name).casefold().strip()
    if not name or name in EXCLUDED_COMMANDS:
        return False
    if command.root_parent is None and command.name.casefold() in DIRECT_ROOTS:
        return False
    if _is_group_with_children(command) and not bool(getattr(command, "invoke_without_command", False)):
        return False
    try:
        from cogs.command_catalog_cleanup import PURE_DUPLICATE_COMMANDS
        if name in PURE_DUPLICATE_COMMANDS or command.name.casefold() in PURE_DUPLICATE_COMMANDS:
            return False
    except Exception:
        pass
    return True


def _special_group(command: commands.Command) -> tuple[str, str] | None:
    qualified = str(command.qualified_name).casefold().strip()
    root = qualified.split(" ", 1)[0]
    name = command.name.casefold()

    if root == "ticket" or name.startswith("ticket-") or name.startswith("ticket"):
        leaf = qualified.split(" ", 1)[1] if " " in qualified else name
        leaf = re.sub(r"^ticket-?", "", leaf) or "open"
        return "ticket", leaf
    if root == "giveaway" or name.startswith("giveaway-"):
        leaf = qualified.split(" ", 1)[1] if " " in qualified else name
        leaf = re.sub(r"^giveaway-?", "", leaf) or "panel"
        return "giveaway", leaf
    if name in {
        "invites", "invite-leaderboard", "invited-by", "addbonusinvites",
        "removebonusinvites", "invitebonushistory",
    } or name.startswith("invite-"):
        leaf = name
        replacements = {
            "invites": "me",
            "invite-leaderboard": "leaderboard",
            "invited-by": "invited-by",
            "addbonusinvites": "bonus-add",
            "removebonusinvites": "bonus-remove",
            "invitebonushistory": "bonus-history",
        }
        leaf = replacements.get(leaf, re.sub(r"^invite-?", "", leaf) or "me")
        return "invites", leaf
    if name.startswith("notifs-") or name == "welcome-config":
        leaf = "welcome" if name == "welcome-config" else re.sub(r"^notifs-", "", name)
        return "notifications", leaf
    if name.startswith("event-") or name.startswith("tournament-"):
        return "events", name
    return None


def _group_for(command: commands.Command) -> tuple[str, str]:
    special = _special_group(command)
    if special is not None:
        return special
    try:
        from cogs import help_complete
        category = help_complete._category_for(command).key
    except Exception:
        category = "other"
    root_name = CATEGORY_ROOTS.get(category, "more")
    qualified = str(command.qualified_name).casefold().strip()
    if command.root_parent is not None:
        leaf = qualified.replace(" ", "-")
    else:
        leaf = command.name.casefold()
    return root_name, leaf


def _unwrap_optional(annotation):
    origin = typing.get_origin(annotation)
    if origin in {typing.Union, types.UnionType}:
        args = [item for item in typing.get_args(annotation) if item is not type(None)]
        if len(args) == 1:
            return args[0]
    return annotation


def _native_annotation(annotation):
    annotation = _unwrap_optional(annotation)
    supported = {
        str, int, float, bool,
        discord.Member, discord.User, discord.Role, discord.Attachment,
        discord.TextChannel, discord.VoiceChannel, discord.StageChannel,
        discord.CategoryChannel, discord.ForumChannel,
    }
    if annotation in supported:
        return annotation
    origin = typing.get_origin(annotation)
    if origin is typing.Literal:
        values = typing.get_args(annotation)
        if values and all(isinstance(item, (str, int, float)) for item in values):
            return annotation
    try:
        if inspect.isclass(annotation) and issubclass(annotation, discord.abc.GuildChannel):
            return annotation
    except TypeError:
        pass
    return str


def _build_signature(command: commands.Command) -> tuple[inspect.Signature, bool, tuple[str, ...]]:
    try:
        params = list(command.clean_params.items())
    except Exception:
        params = []

    unsupported_shape = (
        len(params) > MAX_OPTIONS
        or any(p.kind in {inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD} for _, p in params)
    )
    interaction_param = inspect.Parameter(
        "interaction",
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
        annotation=discord.Interaction,
    )
    if unsupported_shape:
        arg = inspect.Parameter(
            "arguments",
            inspect.Parameter.KEYWORD_ONLY,
            annotation=str,
            default="",
        )
        return inspect.Signature([interaction_param, arg]), False, ("arguments",)

    output = [interaction_param]
    names: list[str] = []
    native = True
    seen_optional = False
    for raw_name, parameter in params:
        name = _safe_name(raw_name, fallback="option").replace("-", "_")
        if name in names:
            name = f"{name[:25]}_{len(names) + 1}"[:32]
        names.append(name)
        annotation = _native_annotation(parameter.annotation)
        if annotation is str and _unwrap_optional(parameter.annotation) is not str:
            native = False
        required = bool(getattr(parameter, "required", False))
        if not required:
            seen_optional = True
        # Keyword-only évite les signatures Python invalides quand un ancien callback a
        # un paramètre requis après un paramètre optionnel. Discord affiche quand même les
        # options normalement.
        default = inspect.Parameter.empty if required else getattr(parameter, "default", None)
        if default is inspect.Parameter.empty and seen_optional and required:
            # app_commands sait trier required/optional, mais une Signature Python non.
            # En keyword-only, l'ordre est autorisé ; on conserve donc le required.
            pass
        output.append(
            inspect.Parameter(
                name,
                inspect.Parameter.KEYWORD_ONLY,
                annotation=annotation,
                default=default,
            )
        )
    return inspect.Signature(output), native, tuple(names)


def _serialize_value(value) -> str:
    if value is None:
        return ""
    if isinstance(value, discord.Attachment):
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, discord.Role):
        return value.mention
    if isinstance(value, (discord.Member, discord.User)):
        return value.mention
    if isinstance(value, discord.abc.GuildChannel):
        return value.mention
    if hasattr(value, "value") and not isinstance(value, (str, int, float)):
        value = value.value
    return shlex.quote(str(value))


def _argument_text(command: commands.Command, option_names: tuple[str, ...], kwargs: dict) -> str:
    if option_names == ("arguments",):
        return str(kwargs.get("arguments") or "").strip()

    try:
        original_names = list(command.clean_params)
    except Exception:
        original_names = []
    pieces: list[str] = []
    gap = False
    for original, exposed in zip(original_names, option_names):
        value = kwargs.get(exposed)
        parameter = command.clean_params[original]
        required = bool(getattr(parameter, "required", False))
        if value is None and not required:
            gap = True
            continue
        if value is None:
            continue
        if gap:
            # Avec le parseur historique positionnel, sauter une option facultative puis
            # fournir la suivante décalerait les arguments. On refuse plutôt que d'appeler
            # la mauvaise logique métier.
            raise commands.BadArgument(
                f"L'option « {original} » ne peut pas être fournie après une option facultative laissée vide."
            )
        rendered = _serialize_value(value)
        if rendered:
            pieces.append(rendered)
    return " ".join(pieces)


async def _invoke_original(
    bot: commands.Bot,
    command: commands.Command,
    interaction: discord.Interaction,
    option_names: tuple[str, ...],
    kwargs: dict,
) -> None:
    if not interaction.response.is_done():
        await interaction.response.defer(thinking=True)

    ctx = await commands.Context.from_interaction(interaction)
    # Conserver le Context personnalisé de SentriX lorsque Bot.get_context l'utilise.
    try:
        sentrix_context = getattr(__import__("main"), "SentriXContext", None)
        if sentrix_context is not None and not isinstance(ctx, sentrix_context):
            ctx.__class__ = sentrix_context
    except Exception:
        pass

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
    bot.dispatch("command", ctx)
    try:
        await root.invoke(ctx)
    except commands.CommandError as exc:
        ctx.command_failed = True
        current = ctx.command if isinstance(ctx.command, commands.Command) else root
        await current.dispatch_error(ctx, exc)
    else:
        if not ctx.command_failed:
            bot.dispatch("command_completion", ctx)


def _make_callback(bot: commands.Bot, command: commands.Command):
    signature, native, option_names = _build_signature(command)

    async def callback(interaction: discord.Interaction, **kwargs) -> None:
        await _invoke_original(bot, command, interaction, option_names, kwargs)

    callback.__name__ = f"slash_{_safe_name(command.qualified_name).replace('-', '_')}"
    callback.__qualname__ = callback.__name__
    callback.__signature__ = signature
    callback.__annotations__ = {"interaction": discord.Interaction}
    callback._sentrix_original_command = str(command.qualified_name)
    callback._sentrix_native_options = native
    return callback, native


def _unique_leaf(base: str, used: set[str], original: str) -> str:
    candidate = _safe_name(base)
    if candidate not in used:
        used.add(candidate)
        return candidate
    digest = hashlib.blake2s(original.encode("utf-8"), digest_size=3).hexdigest()
    candidate = _safe_name(f"{candidate[:24]}-{digest}")
    serial = 2
    while candidate in used:
        candidate = _safe_name(f"{base[:20]}-{digest}-{serial}")
        serial += 1
    used.add(candidate)
    return candidate


def _build_targets(bot: commands.Bot) -> list[SlashTarget]:
    raw: list[tuple[commands.Command, str, str]] = []
    for command in bot.walk_commands():
        if not _should_expose(command):
            continue
        root_name, leaf = _group_for(command)
        raw.append((command, _safe_name(root_name), leaf))

    used_by_root: dict[str, set[str]] = {}
    targets: list[SlashTarget] = []
    for command, root_name, leaf in sorted(raw, key=lambda item: item[0].qualified_name.casefold()):
        used = used_by_root.setdefault(root_name, set())
        unique = _unique_leaf(leaf, used, command.qualified_name)
        _signature, native, _names = _build_signature(command)
        targets.append(
            SlashTarget(
                command=command,
                root_name=root_name,
                leaf_name=unique,
                original_name=str(command.qualified_name),
                native_options=native,
            )
        )
    return targets


def _remove_old_roots(tree: app_commands.CommandTree) -> None:
    for item in list(tree.get_commands(guild=None, type=discord.AppCommandType.chat_input)):
        name = str(getattr(item, "name", "") or "").casefold()
        if name in DIRECT_ROOTS:
            continue
        try:
            tree.remove_command(name, type=discord.AppCommandType.chat_input)
        except TypeError:
            tree.remove_command(name)


def _install_permission_bridge(bot: commands.Bot) -> None:
    try:
        from cogs import permission_guard
    except Exception:
        return
    current = permission_guard.interaction_root_name
    if getattr(current, "_sentrix_v95", False):
        return

    def interaction_root_name_v95(interaction: discord.Interaction) -> str:
        app_command = getattr(interaction, "command", None)
        callback = getattr(app_command, "callback", None)
        original = getattr(callback, "_sentrix_original_command", None)
        if original:
            text_command = bot.get_command(str(original))
            if text_command is not None:
                return permission_guard.command_root_name(text_command)
            return str(original).split(" ", 1)[0]
        return current(interaction)

    interaction_root_name_v95._sentrix_v95 = True
    interaction_root_name_v95._sentrix_original = current
    permission_guard.interaction_root_name = interaction_root_name_v95


def _install_invite_semantic_dedup() -> None:
    current = log_service.semantic_event_key
    if getattr(current, "_sentrix_v95", False):
        return

    def semantic_event_key_v95(guild_id: int, log_type: str, embed: discord.Embed):
        event_type = str(log_type or "").strip().casefold().replace("-", "_")
        if event_type in {"invite_create", "invite_delete"}:
            sample = "\n".join(
                [str(embed.title or ""), str(embed.description or "")]
                + [f"{field.name}\n{field.value}" for field in embed.fields]
            )
            match = re.search(r"(?:discord\.gg/|code\s*[:：]?\s*`?)([A-Za-z0-9_-]{2,})", sample, re.I)
            code = match.group(1).casefold() if match else "unknown"
            return f"semantic:{int(guild_id)}:{event_type}:{code}"
        return current(guild_id, log_type, embed)

    semantic_event_key_v95._sentrix_v95 = True
    semantic_event_key_v95._sentrix_original = current
    log_service.semantic_event_key = semantic_event_key_v95


async def _audit_invite_actor(
    guild: discord.Guild,
    action: discord.AuditLogAction,
    invite: discord.Invite,
    *,
    attempts: int = 3,
) -> tuple[discord.abc.User | None, discord.AuditLogEntry | None]:
    me = guild.me
    if me is None or not me.guild_permissions.view_audit_log:
        return None, None
    for attempt in range(attempts):
        if attempt:
            import asyncio
            await asyncio.sleep(0.35 * attempt)
        now = discord.utils.utcnow()
        try:
            async for entry in guild.audit_logs(limit=12, action=action):
                if abs((now - entry.created_at).total_seconds()) > 12:
                    continue
                target = getattr(entry, "target", None)
                code = getattr(target, "code", None)
                if code and invite.code and str(code) != str(invite.code):
                    continue
                channel_id = getattr(getattr(target, "channel", None), "id", None)
                if channel_id and invite.channel and int(channel_id) != int(invite.channel.id):
                    continue
                return entry.user, entry
        except (discord.Forbidden, discord.HTTPException):
            return None, None
    return None, None


class InviteResourceLogsV95(commands.Cog, name="InviteResourceLogsV95"):
    """Producteur unique V95 pour les événements de création/suppression d'invitation."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _send(
        self,
        invite: discord.Invite,
        *,
        event_type: str,
        title: str,
        actor: discord.abc.User | None,
        audit: discord.AuditLogEntry | None,
    ) -> None:
        guild = invite.guild
        channel = invite.channel
        actor_text = (
            f"<@{actor.id}>\n`ID : {actor.id}`"
            if actor is not None
            else "Responsable indisponible — Discord ne l'a pas fourni ou SentriX n'a pas accès au journal d'audit."
        )
        fields = [
            ("Invitation", f"`{invite.code}`", True),
            ("Salon", channel.mention if channel is not None else "Salon indisponible", True),
            ("Responsable", actor_text, False),
        ]
        max_uses = int(getattr(invite, "max_uses", 0) or 0)
        max_age = int(getattr(invite, "max_age", 0) or 0)
        if event_type == "invite_create":
            fields.extend(
                [
                    ("Utilisations max", "Illimitées" if max_uses == 0 else str(max_uses), True),
                    ("Expiration", "Jamais" if max_age == 0 else f"{max_age} s", True),
                ]
            )
        panel = embeds.canonical_log_embed(title, fields=fields)
        ids = []
        if actor is not None:
            ids.append(("Copier l'ID du responsable", actor.id))
        if channel is not None:
            ids.append(("Copier l'ID du salon", channel.id))
        key = log_service.make_event_key(
            guild.id,
            event_type,
            executor_id=getattr(actor, "id", None),
            audit_log_id=getattr(audit, "id", None),
            discriminator=str(invite.code),
        )
        await log_service.send_log(
            self.bot,
            guild,
            event_type,
            panel,
            view=log_service.log_actions(ids=ids),
            event_key=key,
        )

    @commands.Cog.listener()
    async def on_invite_create(self, invite: discord.Invite) -> None:
        actor = getattr(invite, "inviter", None)
        audit = None
        if actor is None:
            actor, audit = await _audit_invite_actor(
                invite.guild, discord.AuditLogAction.invite_create, invite
            )
        await self._send(
            invite,
            event_type="invite_create",
            title="Invitation créée",
            actor=actor,
            audit=audit,
        )

    @commands.Cog.listener()
    async def on_invite_delete(self, invite: discord.Invite) -> None:
        actor, audit = await _audit_invite_actor(
            invite.guild, discord.AuditLogAction.invite_delete, invite
        )
        await self._send(
            invite,
            event_type="invite_delete",
            title="Invitation supprimée",
            actor=actor,
            audit=audit,
        )


async def _install_invite_cog(bot: commands.Bot) -> None:
    if bot.get_cog("InviteResourceLogsV95") is None:
        await bot.add_cog(InviteResourceLogsV95(bot))


def _add_grouped_surface(bot: commands.Bot) -> dict[str, dict]:
    tree = bot.tree
    targets = _build_targets(bot)
    _remove_old_roots(tree)
    report: dict[str, dict] = {}

    by_root: dict[str, list[SlashTarget]] = {}
    for target in targets:
        by_root.setdefault(target.root_name, []).append(target)

    for root_name, members in sorted(by_root.items()):
        root = app_commands.Group(
            name=_safe_name(root_name),
            description=GROUP_DESCRIPTIONS.get(root_name, f"Commandes {root_name} de SentriX.")[:100],
        )
        if len(members) <= MAX_CHILDREN:
            pages = [(None, members)]
        else:
            pages = []
            for index in range(0, len(members), MAX_CHILDREN):
                pages.append((f"page-{index // MAX_CHILDREN + 1}", members[index:index + MAX_CHILDREN]))

        for page_name, page_members in pages:
            parent = root
            if page_name is not None:
                subgroup = app_commands.Group(
                    name=page_name,
                    description=f"Commandes {index + 1 if False else page_name} de {root_name}."[:100],
                    parent=root,
                )
                root.add_command(subgroup)
                parent = subgroup
            for target in page_members:
                callback, native = _make_callback(bot, target.command)
                slash = app_commands.Command(
                    name=target.leaf_name,
                    description=_description(target.command),
                    callback=callback,
                )
                parent.add_command(slash)
                path = f"/{root.name}"
                if page_name is not None:
                    path += f" {page_name}"
                path += f" {slash.name}"
                report[path] = {
                    "original": target.original_name,
                    "category": root.name,
                    "native_options": bool(native),
                }
        tree.add_command(root, override=True)

    roots = list(tree.get_commands(guild=None, type=discord.AppCommandType.chat_input))
    if len(roots) > MAX_ROOT_COMMANDS:
        raise RuntimeError(f"V95 slash root budget exceeded: {len(roots)}/{MAX_ROOT_COMMANDS}")
    bot._sentrix_v95_slash_mapping = report
    bot._sentrix_v95_slash_root_count = len(roots)
    return report


async def prepare_bot(bot: commands.Bot) -> dict[str, dict]:
    """Prépare les deux fonctions V95. Idempotent pour un registre inchangé."""
    _install_invite_semantic_dedup()
    await _install_invite_cog(bot)
    _install_permission_bridge(bot)
    report = _add_grouped_surface(bot)
    bot._sentrix_v95_prepared = True
    logger.info(
        "V95 prête : %s commandes historiques exposées en slash groupé, %s racines globales.",
        len(report),
        getattr(bot, "_sentrix_v95_slash_root_count", 0),
    )
    return report


_ORIGINAL_SYNC = None


def install_global() -> None:
    """Installe une seule interception de sync, sans lancer ni synchroniser Discord."""
    global _ORIGINAL_SYNC
    if getattr(app_commands.CommandTree.sync, "_sentrix_v95", False):
        return
    _ORIGINAL_SYNC = app_commands.CommandTree.sync

    async def sync_v95(self, *args, **kwargs):
        client = getattr(self, "client", None) or getattr(self, "_client", None)
        if isinstance(client, commands.Bot):
            await prepare_bot(client)
        return await _ORIGINAL_SYNC(self, *args, **kwargs)

    sync_v95._sentrix_v95 = True
    sync_v95._sentrix_original = _ORIGINAL_SYNC
    app_commands.CommandTree.sync = sync_v95
    logger.info("V95 : préparation slash/invitations branchée avant CommandTree.sync().")


__all__ = [
    "DIRECT_ROOTS", "InviteResourceLogsV95", "SlashTarget", "install_global",
    "prepare_bot", "_build_targets", "_group_for", "_install_invite_semantic_dedup",
]
