"""Style premium/OXYDE-like for every SentriX log.

This module wraps the central log service once all existing routing/audit patches are
installed. It keeps the current log destinations and permissions, but improves the visual
presentation of every embed and adds useful ID buttons. It also enriches timeout events
with their exact duration and end date when Discord exposes the timeout timestamp.
"""
from __future__ import annotations

import logging
import re
import time
import unicodedata

import discord
from discord.ext import commands

from utils import log_service

logger = logging.getLogger("bot.premium-logs")
_INSTALLED = False

COLORS = {
    "success": 0x57F287,
    "danger": 0xED4245,
    "warning": 0xF0B232,
    "info": 0x5865F2,
    "voice": 0x3498DB,
    "security": 0x9B59B6,
    "neutral": 0x6D5DFB,
}

FIELD_LABELS = {
    "Auteur": "👤 Auteur",
    "Salon": "💬 Salon",
    "Contenu": "📝 Contenu",
    "Pièces jointes": "📎 Pièces jointes",
    "Avant": "◀️ Avant",
    "Après": "▶️ Après",
    "Accès": "🔗 Accès",
    "Compte créé": "📅 Compte créé",
    "Rôles": "🛡️ Rôles",
    "Ajoutés": "🟢 Rôle attribué",
    "Retirés": "🔴 Rôle retiré",
    "Nouvel état": "🕓 Fin du timeout",
    "Effectué par": "🛡️ Effectué par",
    "Acteur": "🛡️ Effectué par",
    "Modérateur": "🛡️ Modérateur",
    "Raison": "📝 Raison",
    "Raison Audit Log": "📝 Raison",
    "Durée": "⏱️ Durée",
    "Fin": "🕓 Fin",
    "Membre": "👤 Membre",
    "Utilisateur": "👤 Utilisateur",
    "Rôle": "🛡️ Rôle",
    "Micro": "🎙️ Micro",
    "Casque": "🎧 Casque",
}


def _plain(value: str | None) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    return text.casefold()


def _first_id(value: str | None) -> int | None:
    match = re.search(r"(?<!\d)(\d{15,22})(?!\d)", value or "")
    return int(match.group(1)) if match else None


def _field(embed: discord.Embed, *names: str) -> str:
    wanted = {_plain(name) for name in names}
    for field in embed.fields:
        raw = _plain(str(field.name))
        raw = re.sub(r"^[^a-z0-9]+", "", raw).strip()
        if raw in wanted or any(raw.endswith(name) for name in wanted):
            return str(field.value)
    return ""


def _footer_id(embed: discord.Embed) -> int | None:
    return _first_id(getattr(getattr(embed, "footer", None), "text", None))


def _action_name(embed: discord.Embed) -> str:
    title = str(embed.title or "Log")
    # Remove a leading emoji only; preserve dossier numbers and useful wording.
    title = re.sub(r"^[^\wÀ-ÿ#]+\s*", "", title).strip()
    return title or "Log"


def _role_event_title(embed: discord.Embed, title: str) -> str:
    if _plain(title) != "roles d'un membre modifies":
        return title
    added = bool(_field(embed, "Ajoutés", "Rôle attribué"))
    removed = bool(_field(embed, "Retirés", "Rôle retiré"))
    if added and not removed:
        return "Rôle attribué"
    if removed and not added:
        return "Rôle retiré"
    return "Rôles modifiés"


def _timeout_title_and_timestamp(embed: discord.Embed, title: str) -> tuple[str, int | None]:
    if "timeout" not in _plain(title):
        return title, None
    state = _field(embed, "Nouvel état", "Fin du timeout")
    if "retir" in _plain(state):
        return "Timeout retiré", None
    match = re.search(r"<t:(\d+)(?::[A-Za-z])?>", state)
    if not match:
        return ("Timeout appliqué" if _plain(title) == "timeout modifie" else title), None
    return "Timeout appliqué", int(match.group(1))


def _pretty_duration(seconds: int) -> str:
    seconds = max(0, int(seconds))
    units = ((86400, "j"), (3600, "h"), (60, "min"), (1, "s"))
    parts: list[str] = []
    for size, label in units:
        if seconds >= size or (label == "s" and not parts):
            amount, seconds = divmod(seconds, size)
            if amount:
                parts.append(f"{amount} {label}")
        if len(parts) >= 3:
            break
    return " ".join(parts) or "moins d’une seconde"


def _colour_for(log_type: str, title: str) -> int:
    text = _plain(title)
    if any(word in text for word in ("supprime", "banni", "bannissement", "expulse", "kick", "retire", "timeout applique", "sanction")):
        return COLORS["danger"]
    if any(word in text for word in ("cree", "arrive", "attribue", "debanni", "unban", "unmute", "termine", "valide")):
        return COLORS["success"]
    if any(word in text for word in ("modifie", "avert", "warn", "ralenti", "lock", "mute")):
        return COLORS["warning"]
    if log_type == "voice":
        return COLORS["voice"]
    if log_type in {"automod", "security"}:
        return COLORS["security"]
    if log_type in {"messages", "members", "roles", "server", "moderation"}:
        return COLORS["info"]
    return COLORS["neutral"]


def _emoji_for(title: str, log_type: str) -> str:
    text = _plain(title)
    checks = (
        (("message supprime",), "🗑️"),
        (("message modifie",), "✏️"),
        (("role attribue",), "🟢"),
        (("role retire", "role supprime"), "🔴"),
        (("role cree", "roles modifies", "role modifie"), "🛡️"),
        (("timeout applique", "mute"), "🔇"),
        (("timeout retire", "unmute"), "🔊"),
        (("banni", "bannissement"), "🔨"),
        (("debanni", "unban"), "🔓"),
        (("expulse", "kick"), "👢"),
        (("membre arrive",), "📥"),
        (("membre parti",), "📤"),
        (("surnom",), "🪪"),
        (("salon cree",), "📁"),
        (("salon supprime",), "🗑️"),
        (("salon modifie", "serveur modifie"), "⚙️"),
    )
    for words, emoji in checks:
        if any(word in text for word in words):
            return emoji
    return {
        "voice": "🎙️",
        "moderation": "🛡️",
        "automod": "🛡️",
        "tickets": "🎫",
        "games": "🎮",
        "economy": "🪙",
        "levels": "📈",
        "ai": "🤖",
        "system": "⚙️",
    }.get(log_type, "📋")


def _target_kind(title: str) -> str:
    text = _plain(title)
    if "message" in text:
        return "message"
    if "salon" in text:
        return "salon"
    if "serveur" in text:
        return "serveur"
    if "role" in text and "membre" not in text and "attribue" not in text and "retire" not in text:
        return "rôle"
    return "membre"


def _target_id(embed: discord.Embed, title: str) -> int | None:
    footer_id = _footer_id(embed)
    if footer_id:
        return footer_id
    for name in ("👤 Membre", "Membre", "👤 Utilisateur", "Utilisateur", "Cible"):
        value = _field(embed, name)
        found = _first_id(value)
        if found:
            return found
    return None


def _actor_id(embed: discord.Embed) -> int | None:
    for name in ("Effectué par", "Modérateur", "Acteur"):
        found = _first_id(_field(embed, name))
        if found:
            return found
    return None


def _message_author_id(embed: discord.Embed) -> int | None:
    return _first_id(_field(embed, "Auteur"))


def _role_ids(embed: discord.Embed) -> list[int]:
    values = "\n".join(
        value for value in (
            _field(embed, "Ajoutés", "Rôle attribué"),
            _field(embed, "Retirés", "Rôle retiré"),
            _field(embed, "Rôle"),
        ) if value
    )
    return [int(x) for x in re.findall(r"<@&(\d{15,22})>", values)][:3]


class LogIdView(discord.ui.View):
    """Short-lived utility buttons displayed under a log."""

    def __init__(self, items: list[tuple[str, int]]):
        super().__init__(timeout=6 * 60 * 60)
        seen: set[tuple[str, int]] = set()
        for index, (label, value) in enumerate(items[:5]):
            key = (label, int(value))
            if key in seen:
                continue
            seen.add(key)
            button = discord.ui.Button(
                label=label[:80],
                style=discord.ButtonStyle.secondary,
                custom_id=f"sentrix_log_copy:{index}:{int(value)}",
            )

            async def callback(interaction: discord.Interaction, *, copied=int(value), copied_label=label):
                name = copied_label.replace("Copier ", "").replace("l'", "").replace("du ", "").strip()
                await interaction.response.send_message(
                    f"📋 **{name.capitalize()} :** `{copied}`",
                    ephemeral=True,
                )

            button.callback = callback
            self.add_item(button)


def _button_items(embed: discord.Embed, title: str) -> list[tuple[str, int]]:
    items: list[tuple[str, int]] = []
    target = _target_id(embed, title)
    kind = _target_kind(title)
    if target:
        article = "de l'" if kind in {"auteur"} else "du "
        if kind == "membre":
            items.append(("Copier l'ID du membre", target))
        elif kind == "message":
            items.append(("Copier l'ID du message", target))
        elif kind == "rôle":
            items.append(("Copier l'ID du rôle", target))
        elif kind == "salon":
            items.append(("Copier l'ID du salon", target))
        elif kind == "serveur":
            items.append(("Copier l'ID du serveur", target))
        else:
            items.append((f"Copier l'ID {article}{kind}", target))

    if "message" in _plain(title):
        author_id = _message_author_id(embed)
        if author_id and author_id != target:
            items.append(("Copier l'ID de l'auteur", author_id))

    actor = _actor_id(embed)
    if actor and actor != target:
        items.append(("Copier l'ID du modérateur", actor))

    for role_id in _role_ids(embed):
        if all(existing_id != role_id for _, existing_id in items):
            items.append(("Copier l'ID du rôle", role_id))
    return items[:5]


def _add_timeout_details(embed: discord.Embed, timeout_ts: int | None) -> None:
    if timeout_ts is None:
        return
    remaining = max(0, timeout_ts - int(time.time()))
    names = {_plain(str(f.name)) for f in embed.fields}
    if not any("duree" in name for name in names):
        embed.add_field(name="⏱️ Durée", value=f"**{_pretty_duration(remaining)}**", inline=True)
    # Replace the generic state with a richer end-date field when present.
    for index, field in enumerate(list(embed.fields)):
        raw = _plain(str(field.name))
        if "nouvel etat" in raw or "fin du timeout" in raw:
            embed.set_field_at(
                index,
                name="🕓 Fin du timeout",
                value=f"<t:{timeout_ts}:F>\n<t:{timeout_ts}:R>",
                inline=True,
            )
            return
    embed.add_field(
        name="🕓 Fin du timeout",
        value=f"<t:{timeout_ts}:F>\n<t:{timeout_ts}:R>",
        inline=True,
    )


def _restyle_fields(embed: discord.Embed) -> None:
    for index, field in enumerate(list(embed.fields)):
        original_name = str(field.name)
        new_name = FIELD_LABELS.get(original_name)
        if new_name is None:
            plain_name = re.sub(r"^[^A-Za-zÀ-ÿ0-9]+\s*", "", original_name).strip()
            new_name = FIELD_LABELS.get(plain_name, original_name)
        embed.set_field_at(index, name=new_name, value=str(field.value), inline=field.inline)


def _identity_block(bot: commands.Bot, guild: discord.Guild, embed: discord.Embed, title: str) -> None:
    target = _target_id(embed, title)
    kind = _target_kind(title)

    bot_avatar = str(bot.user.display_avatar.url) if bot.user else None
    embed.set_author(
        name=f"SentriX — Logs • {guild.name}"[:256],
        icon_url=bot_avatar or None,
    )

    thumbnail = None
    if target and kind == "membre":
        user = guild.get_member(target) or bot.get_user(target)
        if user is not None:
            thumbnail = str(user.display_avatar.url)
            display_name = getattr(user, "display_name", str(user))
            current = (embed.description or "").strip()
            trivial = {f"<@{target}>", str(user), display_name}
            identity = f"**{display_name}** • <@{target}>\n> ID : `{target}`"
            embed.description = identity if not current or current in trivial else f"{identity}\n\n{current}"
    if thumbnail is None and guild.icon:
        thumbnail = str(guild.icon.url)
    if thumbnail is None:
        thumbnail = bot_avatar
    if thumbnail:
        embed.set_thumbnail(url=thumbnail)

    if target:
        embed.set_footer(text=f"SentriX • Logs • ID : {target}")
    else:
        embed.set_footer(text="SentriX • Logs")


def style_log(bot: commands.Bot, guild: discord.Guild, log_type: str, source: discord.Embed) -> discord.Embed:
    embed = source.copy()
    title = _role_event_title(embed, _action_name(embed))
    title, timeout_ts = _timeout_title_and_timestamp(embed, title)
    emoji = _emoji_for(title, log_type)

    embed.title = f"{emoji}  {title}"[:256]
    embed.colour = discord.Colour(_colour_for(log_type, title))
    embed.timestamp = discord.utils.utcnow()
    _add_timeout_details(embed, timeout_ts)
    _restyle_fields(embed)
    _identity_block(bot, guild, embed, title)
    return embed


def install(bot: commands.Bot) -> None:
    """Install the global premium log sender once, after the routing/audit patches."""
    global _INSTALLED
    if _INSTALLED:
        return

    original_send = log_service.send_log
    if getattr(original_send, "_sentrix_premium_logs", False):
        _INSTALLED = True
        return

    async def send_premium_log(
        inner_bot,
        guild: discord.Guild,
        log_type: str,
        embed: discord.Embed,
        file: discord.File | None = None,
    
        **identity,
    ) -> bool:
        styled = style_log(inner_bot, guild, log_type, embed, **identity)
        buttons = _button_items(styled, str(styled.title or ""))
        view = LogIdView(buttons) if buttons else None

        try:
            setting = await log_service.get_log_setting(inner_bot, guild.id, log_type)
            if not setting["enabled"]:
                return False

            ok, _reason = log_service.validate_channel(
                guild,
                setting["channel_id"],
                needs_file=file is not None,
            )
            if not ok:
                try:
                    from .moderation_logs_fix import _repair_log_target
                    repaired = await _repair_log_target(
                        inner_bot,
                        guild,
                        log_type,
                        needs_file=file is not None,
                    )
                except Exception:
                    repaired = None
                if not repaired:
                    return False
                setting = await log_service.get_log_setting(inner_bot, guild.id, log_type)
                ok, _reason = log_service.validate_channel(
                    guild,
                    setting["channel_id"],
                    needs_file=file is not None,
                )
                if not ok:
                    return False

            channel = guild.get_channel(setting["channel_id"])
            if not isinstance(channel, discord.TextChannel):
                return False

            kwargs = {"embed": styled}
            if file is not None:
                kwargs["file"] = file
            if view is not None:
                kwargs["view"] = view
            await channel.send(**kwargs)
            return True
        except (discord.Forbidden, discord.HTTPException):
            logger.warning(
                "Envoi du log premium impossible (%s, guild=%s).",
                log_type,
                guild.id,
                exc_info=True,
            )
            return False
        except Exception:
            logger.exception("Erreur inattendue du moteur de logs premium (%s, guild=%s).", log_type, guild.id)
            # Fallback to the previous sender so an aesthetic failure never loses the log.
            try:
                return await original_send(inner_bot, guild, log_type, styled, file=file)
            except Exception:
                return False

    send_premium_log._sentrix_premium_logs = True
    log_service.send_log = send_premium_log
    _INSTALLED = True
    logger.info("Style premium global des logs activé.")
