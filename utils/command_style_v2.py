"""Thème visuel global des commandes SentriX.

Objectif : toutes les commandes gardent une présentation large, lisible et cohérente,
sans bannière ni emoji décoratif. Les réponses de conversation directe avec SentriX
(/sentrix, /ai, +chat, /ask) sont volontairement exclues afin de rester naturelles.

La logique métier n'est jamais modifiée : ce module agit uniquement sur le rendu final
centralisé par ``cogs.plain_response_policy``.
"""
from __future__ import annotations

import re
import sys
from datetime import datetime, timezone
from typing import Any, Iterable

import discord

from utils import microcopy, premium_style, helpers


_INSTALLED = False

COLORS: dict[str, int] = {
    "brand": 0x7C3AED,
    "info": 0x3B82F6,
    "success": 0x22C55E,
    "warning": 0xF59E0B,
    "danger": 0xEF4444,
    "neutral": 0x64748B,
    "moderation": 0xEF4444,
    "security": 0x7C3AED,
    "tickets": 0x3B82F6,
    "economy": 0xF59E0B,
    "levels": 0x22C55E,
    "games": 0x06B6D4,
    "music": 0xA855F7,
    "events": 0xF97316,
    "invites": 0x14B8A6,
    "ai": 0x7C3AED,
    "configuration": 0x7C3AED,
    "logs": 0x64748B,
    "utility": 0x5865F2,
    "profile": 0x6366F1,
    "shop": 0xF59E0B,
    "leaderboard": 0x6366F1,
    "premium": 0xF59E0B,
}

CHAT_ROOTS = frozenset({"sentrix", "ai", "chat", "ask"})
BAR = "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
_CUSTOM_EMOJI_RE = re.compile(r"<a?:[A-Za-z0-9_~]+:\d+>")
_SENTRIX_PREFIX = re.compile(r"^(?:SENTRIX|ODBOUG)\s*(?:/|•|—|-)\s*", re.I)
_SPACE_RE = re.compile(r"[ \t]{2,}")
_MANY_BLANKS_RE = re.compile(r"\n{3,}")
_GENERIC_TITLES = {
    "information", "action terminée", "action terminee", "action impossible",
    "vérification nécessaire", "verification necessaire", "erreur", "succès",
    "succes", "avertissement", "attention",
}


def _root_name(command: Any) -> str:
    if command is None:
        return ""
    root = getattr(command, "root_parent", None) or command
    return str(getattr(root, "name", "") or "").casefold()


def _is_chat_command(command: Any) -> bool:
    return _root_name(command) in CHAT_ROOTS


def _is_emoji_codepoint(char: str) -> bool:
    cp = ord(char)
    return (
        0x1F000 <= cp <= 0x1FAFF
        or 0x2600 <= cp <= 0x27BF
        or 0x2B00 <= cp <= 0x2BFF
        or 0x1F1E6 <= cp <= 0x1F1FF
        or cp in {0x200D, 0x20E3, 0xFE0E, 0xFE0F}
    )


def _strip_emojis(value: Any) -> str:
    text = _CUSTOM_EMOJI_RE.sub("", str(value or ""))
    text = "".join(char for char in text if not _is_emoji_codepoint(char))
    return _SPACE_RE.sub(" ", text).strip()


def _normal_text(value: Any, *, limit: int, strip_emojis: bool = True) -> str:
    text = str(value or "")
    if strip_emojis:
        text = _strip_emojis(text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    text = _MANY_BLANKS_RE.sub("\n\n", text).strip()
    text = microcopy.polish_text(text)
    return premium_style.clip(text, limit)


def _display_title(original: Any, category: str) -> str:
    raw = _strip_emojis(original)
    raw = _SENTRIX_PREFIX.sub("", raw).strip(" -—•|")
    cleaned = premium_style.clean_title(raw, fallback="") if raw else ""
    if not cleaned or cleaned.casefold() in _GENERIC_TITLES:
        cleaned = str(premium_style.CATEGORY_NAMES.get(category, "Information"))
    cleaned = _strip_emojis(premium_style.display_label(cleaned, fallback="Information"))
    return premium_style.clip(cleaned or "Information", premium_style.VISUAL_LIMITS["title"])


def _field_name(value: Any) -> str:
    text = _normal_text(value, limit=256) or "Information"
    text = re.sub(r"^[^A-Za-zÀ-ÿ0-9@#<]+", "", text).strip() or "Information"
    return text


def _useful_footer(embed: discord.Embed) -> str | None:
    current = _normal_text(getattr(getattr(embed, "footer", None), "text", ""), limit=1500)
    if not current:
        return None
    if current.casefold().startswith(("sentrix", "odboug")):
        return None
    return current


def _latency_quality(latency_ms: int) -> tuple[str, str]:
    if latency_ms <= 80:
        return "Excellente", "██████████"
    if latency_ms <= 140:
        return "Très bonne", "█████████░"
    if latency_ms <= 220:
        return "Correcte", "███████░░░"
    return "Dégradée", "████░░░░░░"


def _enrich_ping(embed: discord.Embed, command: Any) -> None:
    if _root_name(command) != "ping":
        return
    bot = getattr(getattr(command, "cog", None), "bot", None)
    if bot is None:
        return

    latency_ms = helpers.latence_ms(bot)
    quality, quality_bar = _latency_quality(latency_ms)
    server_count = len(getattr(bot, "guilds", ()) or ())
    member_count = sum((guild.member_count or 0) for guild in getattr(bot, "guilds", ()) or ())
    shard_count = int(getattr(bot, "shard_count", None) or 1)
    active = not bool(getattr(bot, "is_closed", lambda: False)())

    embed.title = "Ping"
    embed.description = (
        f"{BAR}\n"
        f"**Latence**  {latency_ms} ms   •   **Qualité**  {quality}   `{quality_bar}`"
    )
    embed.clear_fields()
    embed.add_field(name="Connexion", value="Active" if active else "Hors ligne", inline=True)
    embed.add_field(name="État", value="Opérationnel" if active else "Indisponible", inline=True)
    embed.add_field(name="Serveurs", value=f"{server_count:,}", inline=True)
    embed.add_field(name="Membres", value=f"{member_count:,}", inline=True)
    embed.add_field(name="Shards", value=str(shard_count), inline=True)


def style_embed(
    embed: discord.Embed,
    *,
    command: Any = None,
    guild: discord.Guild | None = None,
    requester: Any = None,
    category: str | None = None,
    kind: str | None = None,
    bot_user: discord.ClientUser | discord.User | None = None,
    log_type: str | None = None,
) -> discord.Embed:
    """Applique le panneau SentriX aux réponses de commande sans toucher au métier."""
    del guild, requester, log_type
    if not isinstance(embed, discord.Embed) or _is_chat_command(command):
        return embed

    resolved_category = premium_style.infer_category(command=command, embed=embed, hint=category)
    resolved_kind = kind or premium_style.infer_kind(embed)

    embed.title = _display_title(getattr(embed, "title", None), resolved_category)
    body = _normal_text(embed.description, limit=3970) if embed.description is not None else ""
    if body.startswith(BAR):
        embed.description = body
    else:
        embed.description = f"{BAR}\n{body}" if body else BAR

    state_colour = COLORS.get(resolved_kind)
    category_colour = premium_style.COLORS.get(
        resolved_category,
        COLORS.get(resolved_category, COLORS["brand"]),
    )
    if resolved_kind in {"success", "warning", "danger"} and state_colour:
        embed.colour = discord.Colour(state_colour)
    else:
        embed.colour = discord.Colour(category_colour or COLORS["brand"])

    if embed.timestamp is None:
        embed.timestamp = datetime.now(timezone.utc)

    # Les auteurs métier (profil, citation, sanction) sont conservés. L'ancien auteur
    # purement décoratif SentriX est retiré pour garder le cadre plus large et plus calme.
    author_name = str(getattr(getattr(embed, "author", None), "name", "") or "")
    if author_name and author_name.casefold().startswith(("sentrix", "odboug")):
        embed.remove_author()

    for index, field in enumerate(list(embed.fields)[:25]):
        embed.set_field_at(
            index,
            name=_field_name(field.name),
            value=_normal_text(field.value, limit=1024) or "—",
            inline=bool(field.inline),
        )

    _enrich_ping(embed, command)

    useful_footer = _useful_footer(embed)
    category_name = _strip_emojis(premium_style.CATEGORY_NAMES.get(resolved_category, "SentriX"))
    footer = f"SentriX • {category_name or 'Système'}"
    if useful_footer:
        footer = premium_style.clip(f"{useful_footer} • SentriX", 2048)
    embed.set_footer(text=footer)
    return embed


def _iter_items(root: Any) -> Iterable[Any]:
    seen: set[int] = set()
    stack = list(getattr(root, "children", ()) or ())
    while stack:
        item = stack.pop(0)
        if id(item) in seen:
            continue
        seen.add(id(item))
        yield item
        stack.extend(list(getattr(item, "children", ()) or ()))


def style_view(view: Any) -> Any:
    """Nettoie aussi les vues classiques et Components V2, sans casser leurs callbacks."""
    if view is None:
        return None

    for item in _iter_items(view):
        if isinstance(item, discord.ui.Button):
            if item.label:
                item.label = _normal_text(item.label, limit=80) or "Action"
            try:
                item.emoji = None
            except Exception:
                pass
            if item.style is discord.ButtonStyle.link:
                continue
            haystack = f"{item.label or ''} {item.custom_id or ''}".casefold()
            if any(word in haystack for word in (
                "supprimer", "delete", "fermer", "close", "annuler", "cancel",
                "ban", "wipe", "reset", "retirer", "remove", "stop",
            )):
                item.style = discord.ButtonStyle.danger
            elif any(word in haystack for word in (
                "enregistrer", "save", "confirmer", "confirm", "valider", "verify",
                "claim", "rouvrir", "reopen", "ajouter", "add",
            )):
                item.style = discord.ButtonStyle.success
            elif any(word in haystack for word in (
                "ouvrir", "open", "continuer", "next", "suivant", "actualiser",
                "refresh", "configurer", "setup", "créer", "create", "envoyer", "send",
                "activer", "enable",
            )):
                item.style = discord.ButtonStyle.primary
            elif item.style not in {discord.ButtonStyle.success, discord.ButtonStyle.danger}:
                item.style = discord.ButtonStyle.secondary
            continue

        if isinstance(item, discord.ui.Select):
            if item.placeholder:
                item.placeholder = _normal_text(item.placeholder, limit=150) or "Choisir une option…"
            for option in list(getattr(item, "options", ()) or ()):
                option.label = _normal_text(option.label, limit=100) or "Option"
                if option.description:
                    option.description = _normal_text(option.description, limit=100) or None
                try:
                    option.emoji = None
                except Exception:
                    pass
            continue

        # Les Components V2 déjà utilisés par quelques panneaux gardent leur structure ;
        # seuls les emojis décoratifs de leurs blocs texte sont retirés.
        content = getattr(item, "content", None)
        if isinstance(content, str):
            try:
                item.content = "".join(ch for ch in _CUSTOM_EMOJI_RE.sub("", content) if not _is_emoji_codepoint(ch))
            except Exception:
                pass

    return view


def _patch_help_raw_edits(bot) -> None:
    module = sys.modules.get("cogs.help_clean_style")
    if module is None or getattr(module, "_sentrix_command_style_v2_patched", False):
        return
    original_edit = getattr(module, "_edit_help_message", None)
    if original_edit is None:
        return

    async def styled_edit(interaction, *, embed, view):
        style_embed(
            embed,
            guild=getattr(interaction, "guild", None),
            requester=getattr(interaction, "user", None),
            bot_user=getattr(getattr(interaction, "client", None), "user", None),
        )
        style_view(view)
        return await original_edit(interaction, embed=embed, view=view)

    module._edit_help_message = styled_edit
    module._sentrix_command_style_v2_patched = True
    if bot is not None:
        setattr(bot, "_sentrix_help_style_v2", True)


def _patch_chat_bypass() -> None:
    """Laisse les conversations IA dans leur présentation naturelle."""
    module = sys.modules.get("cogs.plain_response_policy")
    if module is None or getattr(module, "_sentrix_chat_bypass_v4", False):
        return

    original_force = getattr(module, "_force_rich_args", None)
    if original_force is not None:
        def force_with_chat_bypass(args, kwargs, *, command=None, **options):
            if _is_chat_command(command):
                return args, kwargs
            return original_force(args, kwargs, command=command, **options)
        force_with_chat_bypass._sentrix_original = original_force
        module._force_rich_args = force_with_chat_bypass

    original_interaction = getattr(module, "_style_interaction_args", None)
    if original_interaction is not None:
        def interaction_with_chat_bypass(interaction, args, kwargs, *, include_brand_asset=False):
            if _is_chat_command(getattr(interaction, "command", None)):
                return args, kwargs
            return original_interaction(
                interaction,
                args,
                kwargs,
                include_brand_asset=include_brand_asset,
            )
        interaction_with_chat_bypass._sentrix_original = original_interaction
        module._style_interaction_args = interaction_with_chat_bypass

    module._sentrix_chat_bypass_v4 = True


def install(bot=None) -> None:
    """Branche le thème global, de façon idempotente et sans nouveau transport."""
    global _INSTALLED

    premium_style.COLORS.update(COLORS)
    premium_style.style_embed = style_embed
    premium_style.style_view = style_view

    _patch_chat_bypass()
    if bot is not None:
        _patch_help_raw_edits(bot)
        setattr(bot, "_sentrix_command_style_v2", True)
        setattr(bot, "_sentrix_command_style_v4_wide", True)
    _INSTALLED = True
