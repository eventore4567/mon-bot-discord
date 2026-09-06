"""Bootstrap correctif V95.

Séparé du module métier afin de garder le branchement Python minuscule dans sitecustomize.
Cette couche corrige aussi les incompatibilités introduites par les anciens runtimes qui
sont chargés après le catalogue principal sur Railway.
"""
from __future__ import annotations

import inspect
import logging
import re
import types
import typing

import discord
from discord import app_commands

import sentrix_v95_runtime as v95
from utils import log_categories, log_service

logger = logging.getLogger("bot.v95-bootstrap")


def _unwrap_optional_safe(annotation):
    """Version sûre : certains objets Greedy de discord.py ne sont pas hashables."""
    origin = typing.get_origin(annotation)
    if origin is typing.Union or origin is types.UnionType:
        args = [item for item in typing.get_args(annotation) if item is not type(None)]
        if len(args) == 1:
            return args[0]
    return annotation


def _native_annotation_safe(annotation):
    """Convertit une annotation legacy vers un type App Command sans hash() fragile."""
    annotation = _unwrap_optional_safe(annotation)
    supported = (
        str,
        int,
        float,
        bool,
        discord.Member,
        discord.User,
        discord.Role,
        discord.Attachment,
        discord.TextChannel,
        discord.VoiceChannel,
        discord.StageChannel,
        discord.CategoryChannel,
        discord.ForumChannel,
    )
    if any(annotation is item for item in supported):
        return annotation
    origin = typing.get_origin(annotation)
    if origin is typing.Literal:
        values = typing.get_args(annotation)
        if values and all(isinstance(item, (str, int, float)) for item in values):
            return annotation
    try:
        if isinstance(annotation, type) and issubclass(annotation, discord.abc.GuildChannel):
            return annotation
    except (TypeError, AttributeError):
        pass
    return str


def _build_signature_safe(command):
    """Construit des options Discord sans copier les defaults typés du parser +.

    Les defaults des anciennes commandes appartiennent au callback historique. Un slash
    omis ne doit donc jamais injecter artificiellement ``0``, ``False`` ou un sentinel
    dans la signature App Command. On expose ``None`` et on laisse ``Command.invoke``
    appliquer le default d'origine lorsque l'argument n'est pas sérialisé.
    """
    try:
        params = list(command.clean_params.items())
    except Exception:
        params = []

    unsupported_shape = (
        len(params) > v95.MAX_OPTIONS
        or any(
            p.kind in {inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD}
            for _, p in params
        )
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
    for raw_name, parameter in params:
        name = v95._safe_name(raw_name, fallback="option").replace("-", "_")
        if name in names:
            name = f"{name[:25]}_{len(names) + 1}"[:32]
        names.append(name)

        original_annotation = _unwrap_optional_safe(parameter.annotation)
        annotation = _native_annotation_safe(parameter.annotation)
        if annotation is str and original_annotation is not str:
            native = False

        required = bool(getattr(parameter, "required", False))
        output.append(
            inspect.Parameter(
                name,
                inspect.Parameter.KEYWORD_ONLY,
                annotation=annotation,
                default=inspect.Parameter.empty if required else None,
            )
        )
    return inspect.Signature(output), native, tuple(names)


def _repair_invite_registry() -> None:
    """Réaffirme le routage final après les anciens runtimes logs V5/V6."""
    log_categories.CATEGORIES["resources"] = "Ressources"
    log_categories.LOG_REGISTRY["invite_create"] = ("resources", "🔗", "success")
    log_categories.LOG_REGISTRY["invite_delete"] = ("resources", "🔗", "error")
    log_categories.EVENT_EMOJI["invite_create"] = "🔗"
    log_categories.EVENT_EMOJI["invite_delete"] = "🔗"
    log_categories.LEGACY_CATEGORY_KEYS["resources"] = "resources"
    log_categories.LEGACY_CATEGORY_KEYS["dossiers"] = "resources"
    log_categories.LEGACY_CATEGORY_KEYS["log_resources"] = "resources"
    log_categories.LEGACY_CATEGORY_KEYS["log_dossiers"] = "resources"


def _install_invite_semantic_dedup_fixed() -> None:
    current = log_service.semantic_event_key
    if getattr(current, "_sentrix_v95_fixed", False):
        return

    def semantic_event_key_v95(guild_id: int, log_type: str, embed: discord.Embed):
        event_type = str(log_type or "").strip().casefold().replace("-", "_")
        if event_type in {"invite_create", "invite_delete"}:
            code = ""
            for field in embed.fields:
                if "invitation" not in str(field.name or "").casefold():
                    continue
                value = str(field.value or "")
                match = re.search(r"discord\.gg/([A-Za-z0-9_-]{2,})", value, re.I)
                if match:
                    code = match.group(1)
                    break
                stripped = value.strip().strip("`").strip()
                if re.fullmatch(r"[A-Za-z0-9_-]{2,}", stripped):
                    code = stripped
                    break
            if not code:
                sample = "\n".join(
                    [str(embed.title or ""), str(embed.description or "")]
                    + [f"{field.name}\n{field.value}" for field in embed.fields]
                )
                match = re.search(
                    r"(?:discord\.gg/|code\s*[:：]?\s*`?)([A-Za-z0-9_-]{2,})",
                    sample,
                    re.I,
                )
                if match:
                    code = match.group(1)
            return f"semantic:{int(guild_id)}:{event_type}:{(code or 'unknown').casefold()}"
        return current(guild_id, log_type, embed)

    semantic_event_key_v95._sentrix_v95_fixed = True
    semantic_event_key_v95._sentrix_original = current
    log_service.semantic_event_key = semantic_event_key_v95


def _add_grouped_surface_fixed(bot):
    tree = bot.tree
    targets = v95._build_targets(bot)
    v95._remove_old_roots(tree)
    report: dict[str, dict] = {}

    by_root: dict[str, list[v95.SlashTarget]] = {}
    for target in targets:
        by_root.setdefault(target.root_name, []).append(target)

    for root_name, members in sorted(by_root.items()):
        root = app_commands.Group(
            name=v95._safe_name(root_name),
            description=v95.GROUP_DESCRIPTIONS.get(
                root_name, f"Commandes {root_name} de SentriX."
            )[:100],
        )
        chunks = [members[i:i + v95.MAX_CHILDREN] for i in range(0, len(members), v95.MAX_CHILDREN)]
        paged = len(chunks) > 1
        if len(chunks) > v95.MAX_CHILDREN:
            raise RuntimeError(
                f"V95 group too large: {root_name} requires {len(chunks)} subgroups"
            )

        for page_index, page_members in enumerate(chunks, start=1):
            if paged:
                parent = app_commands.Group(
                    name=f"page-{page_index}",
                    description=f"Page {page_index} des commandes {root_name}."[:100],
                    parent=root,
                )
                page_name = parent.name
            else:
                parent = root
                page_name = None

            for target in page_members:
                callback, native = v95._make_callback(bot, target.command)
                slash = app_commands.Command(
                    name=target.leaf_name,
                    description=v95._description(target.command),
                    callback=callback,
                )
                parent.add_command(slash)
                path = f"/{root.name}"
                if page_name:
                    path += f" {page_name}"
                path += f" {slash.name}"
                report[path] = {
                    "original": target.original_name,
                    "category": root.name,
                    "native_options": bool(native),
                }

        tree.add_command(root, override=True)

    roots = list(tree.get_commands(guild=None, type=discord.AppCommandType.chat_input))
    if len(roots) > v95.MAX_ROOT_COMMANDS:
        raise RuntimeError(
            f"V95 slash root budget exceeded: {len(roots)}/{v95.MAX_ROOT_COMMANDS}"
        )
    bot._sentrix_v95_slash_mapping = report
    bot._sentrix_v95_slash_root_count = len(roots)
    return report


def _wrap_prepare_bot() -> None:
    current = v95.prepare_bot
    if getattr(current, "_sentrix_v95_bootstrap", False):
        return

    async def prepare_bot_fixed(bot):
        _repair_invite_registry()
        result = await current(bot)
        _repair_invite_registry()
        return result

    prepare_bot_fixed._sentrix_v95_bootstrap = True
    prepare_bot_fixed._sentrix_original = current
    v95.prepare_bot = prepare_bot_fixed


def install() -> None:
    v95._unwrap_optional = _unwrap_optional_safe
    v95._native_annotation = _native_annotation_safe
    v95._build_signature = _build_signature_safe
    v95._install_invite_semantic_dedup = _install_invite_semantic_dedup_fixed
    v95._add_grouped_surface = _add_grouped_surface_fixed
    _wrap_prepare_bot()
    _repair_invite_registry()
    v95.install_global()
    logger.info("V95 bootstrap actif.")


__all__ = ["install"]
