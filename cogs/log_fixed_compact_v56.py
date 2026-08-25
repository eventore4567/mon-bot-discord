"""SentriX V56 — renderer final compact et de taille stable pour tous les logs.

Tous les événements utilisent exactement la même structure Components V2 :
identité, un titre, trois lignes de détails, une rangée de boutons. Les textes sont
tronqués sur une ligne afin qu'un message modifié, un timeout ou un événement vocal ne
change plus brutalement la hauteur de la carte.
"""
from __future__ import annotations

import re

import discord
from discord.ext import commands

from . import premium_logs_v2
from . import log_premium_v28 as v28
from . import log_preferred_style_v30 as v30
from .log_rectangle_v25 import _field_value, _target_id


ZWSP = "\u200b"


def _one_line(value: object, limit: int = 72, fallback: str = "Non disponible") -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text:
        return fallback
    if len(text) <= limit:
        return text
    return text[: max(1, limit - 1)].rstrip() + "…"


def _first_target(embed: discord.Embed) -> int | None:
    raw = _field_value(embed, "auteur", "membre", "utilisateur", "cible")
    target = v28._first_id(raw)
    if target:
        return target
    return _target_id(embed)


def _identity(bot: commands.Bot, guild: discord.Guild, embed: discord.Embed) -> tuple[str, str, str | None]:
    target_id = _first_target(embed)
    user = None
    if target_id:
        user = guild.get_member(target_id) or bot.get_user(target_id)
    if user is not None:
        name = _one_line(getattr(user, "display_name", None) or getattr(user, "name", None), 40, "Membre")
        avatar = str(user.display_avatar.url) if getattr(user, "display_avatar", None) else None
        return name, str(target_id), avatar

    name = _one_line(guild.name, 40, "Serveur")
    avatar = str(guild.icon.url) if guild.icon else (str(bot.user.display_avatar.url) if bot.user else None)
    return name, str(target_id or guild.id), avatar


def _channel_line(guild: discord.Guild, embed: discord.Embed) -> str:
    try:
        channel = v28._resolved_channel(guild, embed)
    except Exception:
        channel = None
    if channel is not None:
        return f"Salon : {channel.mention}"
    raw = _field_value(embed, "salon", "channel")
    return f"Salon : {_one_line(raw, 54)}"


def _detail_lines(guild: discord.Guild, embed: discord.Embed) -> list[str]:
    lines: list[str] = []

    before = _field_value(embed, "avant")
    after = _field_value(embed, "apres")
    reason = _field_value(embed, "raison")
    duration = _field_value(embed, "duree", "fin du timeout", "nouvel etat")
    actor = _field_value(embed, "effectue par", "effectué par", "moderateur", "modérateur", "acteur")
    content = _field_value(embed, "contenu", "message")

    # La première ligne est toujours le contexte du salon : même hauteur partout.
    lines.append(_channel_line(guild, embed))

    if before or after:
        lines.append(f"Avant : {_one_line(before, 58)}")
        lines.append(f"Après : {_one_line(after, 58)}")
    else:
        if content:
            lines.append(f"Détail : {_one_line(content, 58)}")
        elif duration:
            lines.append(f"Durée : {_one_line(duration, 58)}")
        elif actor:
            lines.append(f"Par : {_one_line(actor, 58)}")
        else:
            # Prend le premier champ métier utile sans faire grossir la carte.
            selected = None
            for field in embed.fields:
                name = v30._norm(str(field.name or ""))
                if v30._is_id_field(str(field.name or "")):
                    continue
                if any(token in name for token in ("salon", "channel", "auteur", "membre", "utilisateur", "cible")):
                    continue
                selected = f"{_one_line(field.name, 20)} : {_one_line(field.value, 48)}"
                break
            lines.append(selected or ZWSP)

        if reason:
            lines.append(f"Raison : {_one_line(reason, 58)}")
        elif actor and not any(line.startswith("Par :") for line in lines):
            lines.append(f"Par : {_one_line(actor, 58)}")
        else:
            lines.append(ZWSP)

    while len(lines) < 3:
        lines.append(ZWSP)
    return lines[:3]


class CopyButton(discord.ui.Button):
    def __init__(self, label: str, value: int, index: int):
        clean = str(label or "ID").replace("Copier ", "").strip()
        if not clean.casefold().startswith("id"):
            clean = "ID " + clean
        super().__init__(
            label=_one_line(clean, 28, "ID"),
            style=discord.ButtonStyle.secondary,
            custom_id=f"sentrix_log_v56_copy:{index}:{int(value)}",
        )
        self.value = int(value)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_message(str(self.value), ephemeral=True)


def _buttons(guild: discord.Guild, log_type: str, embed: discord.Embed, inherited: list[tuple[str, int]]) -> list[tuple[str, int]]:
    result: list[tuple[str, int]] = []
    seen: set[int] = set()

    def add(label: str, value: int | None) -> None:
        if not value:
            return
        ivalue = int(value)
        if ivalue in seen:
            return
        seen.add(ivalue)
        result.append((label, ivalue))

    try:
        for label, value in v30._button_items(guild, log_type, embed):
            add(str(label), int(value))
    except Exception:
        pass
    for label, value in inherited:
        try:
            add(str(label), int(value))
        except (TypeError, ValueError):
            pass
    add("ID serveur", guild.id)
    return result[:3]


class FixedCompactLogV56(discord.ui.LayoutView):
    _sentrix_log_layout = True
    _sentrix_rectangle_v25 = True
    _sentrix_reference_v26 = True
    _sentrix_unified_v27 = True
    _sentrix_premium_v28 = True
    _sentrix_fixed_height_v50 = True
    _sentrix_fixed_compact_v56 = True

    def __init__(
        self,
        bot: commands.Bot,
        guild: discord.Guild,
        log_type: str,
        embed: discord.Embed,
        buttons: list[tuple[str, int]],
    ):
        super().__init__(timeout=6 * 60 * 60)
        clean = embed.copy()
        try:
            clean = v28._silent_mention_embed(clean)
        except Exception:
            pass

        name, identity_id, avatar = _identity(bot, guild, clean)
        try:
            title = _one_line(v30._title(log_type, clean), 54, "Journal SentriX")
        except Exception:
            title = _one_line(clean.title, 54, "Journal SentriX")

        accent = v30._accent(log_type, clean)
        container = discord.ui.Container(accent_colour=accent)

        identity = discord.ui.TextDisplay(
            f"**{name}**\n-# ID : {identity_id}"
        )
        if avatar:
            try:
                container.add_item(
                    discord.ui.Section(
                        identity,
                        accessory=discord.ui.Thumbnail(avatar, description="Identité"),
                    )
                )
            except Exception:
                container.add_item(identity)
        else:
            container.add_item(identity)

        container.add_item(discord.ui.Separator())
        details = _detail_lines(guild, clean)
        body = "\n".join([f"## {title}", *details])
        container.add_item(discord.ui.TextDisplay(body))
        container.add_item(discord.ui.Separator())

        final_buttons = _buttons(guild, str(log_type), clean, buttons)
        row = discord.ui.ActionRow()
        for index, (label, value) in enumerate(final_buttons):
            row.add_item(CopyButton(label, int(value), index))
        if not row.children:
            row.add_item(
                discord.ui.Button(
                    label="Aucune action",
                    style=discord.ButtonStyle.secondary,
                    disabled=True,
                    custom_id="sentrix_log_v56_none",
                )
            )
        container.add_item(row)

        try:
            self._sentrix_log_fingerprint = v30._canonical_fingerprint(guild, str(log_type), clean)
        except Exception:
            self._sentrix_log_fingerprint = f"{guild.id}:{log_type}:{identity_id}:{title}"
        self._sentrix_is_log_layout = True
        self.add_item(container)


def _is_transcript_file(file: discord.File | None) -> bool:
    filename = str(getattr(file, "filename", "") or "").casefold()
    return "transcript" in filename


def install(bot: commands.Bot, extension_name: str = "") -> None:
    del extension_name
    required = ("LayoutView", "Container", "TextDisplay", "Section", "Thumbnail", "Separator")
    if not all(hasattr(discord.ui, name) for name in required):
        return

    # Source de vérité pour tous les senders qui résolvent le renderer au moment de l'envoi.
    premium_logs_v2.PremiumLogLayout = FixedCompactLogV56

    # Les wrappers historiques V30/V53 résolvent ces symboles globalement à l'exécution.
    try:
        from . import log_preferred_style_v30 as preferred
        preferred.PreferredLogV30 = FixedCompactLogV56
    except Exception:
        pass
    try:
        from . import log_output_polish_v53 as output
        output.UnifiedWideLogV53 = FixedCompactLogV56
    except Exception:
        output = None

    # Dernier filet : un ancien sender qui envoie encore directement un embed de log est
    # converti vers la même carte compacte, sans toucher aux transcripts spécialisés.
    current_send = discord.TextChannel.send
    if getattr(current_send, "_sentrix_fixed_compact_v56", False):
        return

    async def send_fixed(self: discord.TextChannel, *args, **kwargs):
        embed = kwargs.get("embed")
        if embed is None:
            for arg in args:
                if isinstance(arg, discord.Embed):
                    embed = arg
                    break
        view = kwargs.get("view")
        file = kwargs.get("file")

        looks_like_log = False
        if output is not None:
            try:
                looks_like_log = output._looks_like_log(
                    self,
                    embed if isinstance(embed, discord.Embed) else None,
                    view,
                )
            except Exception:
                looks_like_log = False

        if (
            looks_like_log
            and isinstance(embed, discord.Embed)
            and view is None
            and not _is_transcript_file(file)
        ):
            try:
                log_type = output._channel_log_type(self, embed) if output is not None else "system"
                try:
                    inherited = v30._button_items(self.guild, log_type, embed)
                except Exception:
                    inherited = []
                kwargs.pop("embed", None)
                kwargs["view"] = FixedCompactLogV56(
                    bot,
                    self.guild,
                    str(log_type),
                    embed,
                    inherited,
                )
            except Exception:
                pass

        return await current_send(self, *args, **kwargs)

    send_fixed._sentrix_fixed_compact_v56 = True
    send_fixed._sentrix_original = current_send
    discord.TextChannel.send = send_fixed


__all__ = ["install", "FixedCompactLogV56"]
