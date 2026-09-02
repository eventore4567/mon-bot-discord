"""Correctifs transversaux et renderer unifié de SentriX.

Chargé une seule fois depuis utils.__init__ afin de garder les anciens cogs compatibles
sans recopier la même logique dans chaque commande.
"""
from __future__ import annotations

import functools
import re
from datetime import datetime, timezone
from typing import Any, Iterable

import discord

from utils import helpers
from utils import sentrix_panels as panels

import config as _config
from discord.ext import commands

import config
from . import design_system
from . import embeds as sx
from . import log_service

_INSTALLED = False
BAR = "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
CHANGE_BAR = BAR

# Palette semantique : referencee depuis config, source unique. Ces constantes
# ecrasent celles de utils/embeds.py au demarrage — c'est donc CETTE palette que le
# bot affiche reellement, et c'est pour cela qu'elle est devenue la reference.
COLOR_INFO = _config.COLOR_INFO
COLOR_SUCCESS = _config.COLOR_SUCCESS
COLOR_WARNING = _config.COLOR_WARNING
COLOR_MODIFICATION = 0xFACC15
COLOR_DANGER = _config.COLOR_ERROR
# Couleur par defaut quand aucune intention n'est donnee : c'est le role « marque »,
# pas une intention distincte. Elle valait 0x8B5CF6 et ecrasait config.COLOR_BRAND
# (0x7C3AED) au demarrage, ce qui faisait deux violets pour la meme chose.
COLOR_SYSTEM = _config.COLOR_BRAND
COLOR_NEUTRAL = _config.COLOR_NEUTRAL

_IDENTITY_FIELDS = {"membre", "auteur", "utilisateur", "cible"}
_BEFORE_FIELDS = {"avant", "ancienne valeur", "ancien"}
_AFTER_FIELDS = {"apres", "après", "nouvelle valeur", "nouveau"}


def _strip_bars(value: Any) -> str:
    text = str(value or "").strip()
    known = {
        BAR,
        str(getattr(sx, "BAR", "") or ""),
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
    }
    while text:
        first, sep, rest = text.partition("\n")
        if first.strip() not in known:
            break
        text = rest.lstrip() if sep else ""
    return text


def _one_line(value: Any, limit: int = 600) -> str:
    text = str(value or "").replace("\r", " ").replace("\n", " · ")
    text = re.sub(r"[ \t]{2,}", " ", text).strip()
    return sx.clip(text, limit)


def _base_colour(title: str, description: str, colour: int | None, kind: str | None) -> int:
    explicit = str(kind or "").casefold()
    if explicit and explicit != "brand":
        return int(sx._colour(explicit, colour))
    if explicit == "brand":
        return int(colour or COLOR_SYSTEM)
    inferred = sx._kind_from_text(title, description)
    if inferred != "brand":
        return int(sx._colour(inferred, colour))
    return int(colour or COLOR_SYSTEM)


def _base(
    title: str,
    description: str | None = None,
    *,
    banner: bool = False,
    thumbnail: str | None = None,
    timestamp: bool = False,
    footer: str | None = None,
    colour: int | None = None,
    kind: str | None = None,
    clean_description: bool = True,
) -> discord.Embed:
    del banner
    safe_title = sx.clean_ui_text(title, 100, "Information")
    body = (
        sx.clean_multiline_ui_text(description, 3940)
        if clean_description
        else sx.clip(description, 3940)
    )
    body = _strip_bars(body)
    embed = discord.Embed(
        title=safe_title,
        description=f"{BAR}\n{body}" if body else BAR,
        colour=discord.Colour(_base_colour(safe_title, body, colour, kind)),
        timestamp=datetime.now(timezone.utc) if timestamp else None,
    )
    if thumbnail:
        embed.set_thumbnail(url=str(thumbnail))
    return sx._footer(embed, footer)


def _design_create_embed(
    *,
    title: str,
    description: str | None = None,
    colour: int = design_system.COLORS.primary,
    user: discord.abc.User | None = None,
    thumbnail: str | None = None,
    footer: str | None = None,
) -> discord.Embed:
    """Même renderer pour les cogs migrés, sans ancienne bannière spéciale de +ping."""
    footer_text = footer or (f"SentriX • demandé par {user}" if user else "SentriX")
    embed = _base(
        title,
        description,
        thumbnail=thumbnail,
        timestamp=True,
        footer=footer_text,
        colour=colour,
        kind="brand",
    )
    if user is not None:
        icon = str(getattr(getattr(user, "display_avatar", None), "url", "") or "")
        if icon:
            embed.set_footer(text=footer_text, icon_url=icon)
    return embed


def _coerce_fields(
    fields: Iterable[tuple[str, Any, bool | None] | tuple[str, Any]],
) -> list[tuple[str, str, bool | None]]:
    result: list[tuple[str, str, bool | None]] = []
    for item in fields:
        if len(item) == 2:
            name, value = item
            requested = None
        else:
            name, value, requested = item
        if value is None or not str(value).strip():
            continue
        safe_name = sx.clean_ui_text(name, 256, "Information")
        if safe_name.casefold() in getattr(sx, "_LEGACY_FILLER_FIELDS", set()):
            continue
        if getattr(sx, "_empty_log_value", lambda _value: False)(value):
            continue
        result.append((safe_name, sx.clip(value, 1024), requested))
    return result


def _clean_log_description(description: Any, fields: list[tuple[str, str, bool | None]]) -> str:
    text = _strip_bars(description)
    if not text:
        return ""
    names = {name.casefold() for name, _value, _inline in fields}
    if not names.intersection(_IDENTITY_FIELDS):
        return text

    # Retire uniquement l'ancien doublon « **Nom** / ID » placé au-dessus d'un champ
    # Membre/Auteur. Le vrai contenu métier situé après reste intact.
    lines = text.splitlines()
    if (
        len(lines) >= 2
        and lines[0].strip().startswith("**")
        and lines[0].strip().endswith("**")
        and re.fullmatch(r"ID\s*:\s*`\d{5,22}`", lines[1].strip(), flags=re.IGNORECASE)
    ):
        lines = lines[2:]
        while lines and not lines[0].strip():
            lines.pop(0)
        return "\n".join(lines).strip()
    return text


def _log_colour(title: str) -> int:
    text = sx.clean_ui_text(title, 150, "").casefold()
    # Les états positifs qui contiennent « banni » sont testés avant le rouge.
    if any(token in text for token in (
        "débanni", "debanni", "timeout retiré", "timeout retire",
        "arrivé", "arrive", "créé", "cree", "ajouté", "ajoute",
        "restauré", "restaure", "déverrouillé", "deverrouille",
    )):
        return COLOR_SUCCESS
    if any(token in text for token in (
        "supprim", "banni", "bannissement", "expuls", "erreur", "échec",
        "echec", "refus", "bloqué", "bloque",
    )):
        return COLOR_DANGER
    if any(token in text for token in (
        "modifi", "renomm", "mise à jour", "mise a jour", "changé", "change",
    )):
        return COLOR_MODIFICATION
    if any(token in text for token in (
        "avert", "timeout appliqué", "timeout applique", "retiré", "retire",
        "parti", "départ", "depart", "désactiv", "desactiv",
    )):
        return COLOR_WARNING
    if any(token in text for token in (
        "message", "vocal", "connexion", "déconnexion", "deconnexion", "test",
        "information", "statut",
    )):
        return COLOR_INFO
    return COLOR_SYSTEM


def _log_embed(
    title: str,
    *,
    fields: Iterable[tuple[str, Any, bool | None] | tuple[str, Any]] = (),
    description: str = "",
    event_time: datetime | None = None,
    banner: bool = True,
) -> discord.Embed:
    del banner
    prepared = _coerce_fields(fields)
    body = _clean_log_description(description, prepared)
    metadata: list[str] = []
    details: list[tuple[str, str]] = []
    saw_before = False

    for name, value, requested in prepared:
        key = name.casefold()
        if key in _BEFORE_FIELDS:
            details.append((name, _strip_bars(value)))
            saw_before = True
            continue
        if key in _AFTER_FIELDS:
            clean_value = _strip_bars(value)
            details.append((name, f"{CHANGE_BAR}\n{clean_value}" if saw_before else clean_value))
            continue
        if requested is True:
            metadata.append(f"**{name} :** {_one_line(value)}")
        else:
            details.append((name, value))

    parts = [BAR]
    if body:
        parts.append(body)
    parts.extend(metadata)

    event_dt = event_time or datetime.now(timezone.utc)
    embed = discord.Embed(
        title=sx.clean_ui_text(title, 120, "Journal SentriX"),
        description="\n".join(parts),
        colour=discord.Colour(_log_colour(title)),
    )
    embed.set_footer(text=f"SentriX • {sx.format_datetime_fr(event_dt)}")
    for name, value in details[:25]:
        embed.add_field(name=name, value=sx.clip(value, 1024), inline=False)
    return embed


def _normalize_log(source: discord.Embed, *, event_time: datetime | None = None) -> discord.Embed:
    fields = [(field.name, field.value, bool(field.inline)) for field in source.fields]
    panel = _log_embed(
        str(source.title or "Journal SentriX"),
        fields=fields,
        description=str(source.description or ""),
        event_time=event_time or getattr(source, "timestamp", None),
    )
    thumbnail = str(getattr(getattr(source, "thumbnail", None), "url", "") or "")
    if thumbnail:
        panel.set_thumbnail(url=thumbnail)

    # Les vraies images métier sont conservées ; seules les anciennes bannières SentriX
    # responsables du grand bloc/placeholder sont retirées.
    image_url = str(getattr(getattr(source, "image", None), "url", "") or "")
    if image_url and not any(token in image_url.casefold() for token in (
        "sentrix-log-header", "sentrix-ping-header", "sentrix-information",
    )):
        panel.set_image(url=image_url)

    author_name = str(getattr(getattr(source, "author", None), "name", "") or "")
    author_icon = str(getattr(getattr(source, "author", None), "icon_url", "") or "")
    if author_name and not author_name.casefold().startswith(("sentrix", "odboug")):
        panel.set_author(name=sx.clean_ui_text(author_name, 256, "Utilisateur"), icon_url=author_icon or None)
    return panel


def _command_key(payload: Any) -> str:
    command = getattr(payload, "command", None)
    if command is not None:
        name = str(getattr(command, "qualified_name", "") or getattr(command, "name", "") or "")
        if name:
            return name.casefold()
    content = str(getattr(payload, "content", "") or "").strip()
    if content:
        return content.split(maxsplit=1)[0].casefold()
    return "__unknown_command__"


def _install_per_command_cooldown() -> None:
    current = commands.CooldownMapping._bucket_key
    if getattr(current, "_sentrix_per_command", False):
        return
    original = current

    def bucket_key(mapping, payload):
        key = original(mapping, payload)
        cooldown = getattr(mapping, "_cooldown", None)
        bucket_type = getattr(mapping, "_type", None)
        is_global = (
            cooldown is not None
            and getattr(cooldown, "rate", None) == config.GLOBAL_COOLDOWN_RATE
            and abs(float(getattr(cooldown, "per", 0.0)) - float(config.GLOBAL_COOLDOWN_PER)) < 1e-9
            and bucket_type == commands.BucketType.user
        )
        return (key, _command_key(payload)) if is_global else key

    bucket_key._sentrix_per_command = True
    bucket_key._sentrix_original = original
    commands.CooldownMapping._bucket_key = bucket_key


def _clear_panneau(nombre: int) -> "panels.Panneau":
    """Confirmation de purge, composee comme le reste du bot.

    Ce message s'auto-detruit : il doit se lire d'un coup d'oeil, d'ou une seule
    ligne utile plutot qu'un tableau.
    """
    return panels.Panneau(
        titre="Salon nettoyé",
        sous_titre=f"{nombre} message(s) supprimé(s).",
        kind="moderation",
        pied="Ce message disparaît tout seul.",
    )


def _patch_clear(bot: commands.Bot) -> None:
    command = bot.get_command("clear")
    if command is None or getattr(command, "_sentrix_clear_fixed", False):
        return
    params = command.params.copy()
    old_callback = command.callback

    async def callback(_cog, ctx: commands.Context, nombre: int):
        amount = max(1, min(100, int(nombre)))
        if ctx.interaction is not None:
            if not ctx.interaction.response.is_done():
                await ctx.interaction.response.defer(ephemeral=True)
            deleted = await ctx.channel.purge(limit=amount)
            return await panels.envoyer(ctx, _clear_panneau(len(deleted)), ephemere=True)

        # +clear 10 retire d'abord le message « +clear 10 », puis exactement 10 anciens
        # messages. La confirmation n'essaie donc jamais de répondre à un message supprimé.
        try:
            await ctx.message.delete()
        except (discord.Forbidden, discord.NotFound, discord.HTTPException):
            pass
        try:
            deleted = await ctx.channel.purge(limit=amount)
        except discord.Forbidden:
            return await panels.envoyer(
                ctx.channel,
                panels.Panneau(
                    titre="Suppression impossible",
                    sous_titre="Il manque une permission à SentriX dans ce salon.",
                    kind="danger",
                    sections=[
                        panels.Section(
                            "À VÉRIFIER",
                            lignes=[
                                panels.Ligne("Gérer les messages", "requise pour supprimer"),
                                panels.Ligne("Voir l'historique des messages", "requise pour lire ce qui précède"),
                            ],
                        )
                    ],
                    pied="Aucun message n'a été supprimé.",
                ),
                allowed_mentions=discord.AllowedMentions.none(),
                delete_after=6,
            )
        return await panels.envoyer(
            ctx.channel,
            _clear_panneau(len(deleted)),
            allowed_mentions=discord.AllowedMentions.none(),
            delete_after=4,
        )

    command.callback = functools.wraps(old_callback)(callback)
    command.params = params
    command._sentrix_clear_fixed = True


def _install_cog_patches() -> None:
    current = commands.Bot.add_cog
    if getattr(current, "_sentrix_runtime_patch", False):
        return
    original = current

    async def add_cog(bot, cog, *args, **kwargs):
        result = await original(bot, cog, *args, **kwargs)
        _patch_clear(bot)
        return result

    add_cog._sentrix_runtime_patch = True
    add_cog._sentrix_original = original
    commands.Bot.add_cog = add_cog


def _install_log_transport() -> None:
    """Ne remplace plus log_service.send_log.

    Cette couche n'ajoutait qu'un appel a normalize_log avant de retransmettre. Le
    pipeline canonique (utils.log_service.send_log) normalise deja l'embed lui-meme, avec
    la meme fonction : le wrapper etait une double normalisation pour rien, au prix d'un
    maillon de plus dans une chaine dont l'ordre dependait du chargeur de cogs.
    """
    return None


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    sx.COLOR_INFO = COLOR_INFO
    sx.COLOR_SUCCESS = COLOR_SUCCESS
    sx.COLOR_WARNING = COLOR_WARNING
    sx.COLOR_DANGER = COLOR_DANGER
    sx.COLOR_NEUTRAL = COLOR_NEUTRAL
    sx.COLOR_BRAND_UI = COLOR_SYSTEM
    sx.BAR = BAR

    # Une seule base visuelle pour l'ancien système embeds.py et design_system.py.
    sx._base = _base
    sx.log_embed = _log_embed
    sx.normalize_log = _normalize_log
    design_system.create_embed = _design_create_embed

    _install_per_command_cooldown()
    _install_log_transport()
    _install_cog_patches()
    _INSTALLED = True


install()
