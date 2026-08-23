"""SentriX V24 — journal unique, grand et détaillé pour toutes les catégories.

Objectifs :
- UNE seule carte par événement même lorsque deux services Railway exécutent SentriX ;
- titre de l'événement très visible, jamais un générique « SentriX • Journal » ;
- sections pleine largeur avec davantage de contexte pour tous les types de logs ;
- conservation de l'Audit Log, raisons, IDs, contenus et pièces jointes déjà collectés ;
- les rafales de >=3 rôles dans la fenêtre de 3 secondes restent UNE grande liste.

Discord impose lui-même la largeur maximale d'un message. On ne peut pas forcer une carte
au-delà de cette largeur, mais ce layout évite les sections étroites inutiles et utilise
la largeur disponible avec des titres/sections plus grands.
"""
from __future__ import annotations

import logging
import os
import re
import unicodedata
from datetime import datetime, timezone

import discord
from discord.ext import commands

from utils import log_service
from . import premium_logs_v2
from .premium_logs import style_log, _button_items

logger = logging.getLogger("bot.log-detail-layout-v24")
_INSTALLED = False

DEFAULT_PRIMARY_LOG_SERVICE = "mon-bot-discord"

CATEGORY_LABELS = {
    "messages": "MESSAGES",
    "members": "MEMBRES",
    "roles": "RÔLES",
    "server": "SERVEUR",
    "voice": "VOCAL",
    "moderation": "MODÉRATION",
    "automod": "SÉCURITÉ",
    "security": "SÉCURITÉ",
    "tickets": "TICKETS",
    "economy": "ÉCONOMIE",
    "levels": "NIVEAUX",
    "ai": "IA",
    "games": "JEUX",
    "system": "SYSTÈME",
}


def _plain(value: str | None) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", re.sub(r"[^a-zA-Z0-9]+", " ", text)).casefold().strip()


def _first_id(value: str | None) -> int | None:
    match = re.search(r"(?<!\d)(\d{15,22})(?!\d)", value or "")
    return int(match.group(1)) if match else None


def _footer_target(embed: discord.Embed) -> int | None:
    return _first_id(getattr(getattr(embed, "footer", None), "text", None))


def _field_exists(embed: discord.Embed, *labels: str) -> bool:
    wanted = {_plain(label) for label in labels}
    for field in embed.fields:
        if _plain(str(field.name)) in wanted:
            return True
    return False


def _add_field(embed: discord.Embed, name: str, value: str, *, inline: bool = False) -> None:
    if len(embed.fields) >= 25 or _field_exists(embed, name):
        return
    embed.add_field(name=name[:256], value=(value or "Aucune information")[:1024], inline=inline)


def _event_timestamp(embed: discord.Embed) -> int:
    stamp = embed.timestamp
    if stamp is None:
        stamp = datetime.now(timezone.utc)
    elif stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return int(stamp.timestamp())


def _is_primary_log_service() -> bool:
    """Évite qu'une même gateway SentriX journalise deux fois via deux Railway services."""
    service = (os.getenv("RAILWAY_SERVICE_NAME") or "").strip().casefold()
    if not service:
        # Local/autre hébergeur : ne pas désactiver les logs par accident.
        return True
    primary = (
        os.getenv("SENTRIX_LOG_PRIMARY_SERVICE")
        or os.getenv("SENTRIX_ALERT_PRIMARY_SERVICE")
        or DEFAULT_PRIMARY_LOG_SERVICE
    ).strip().casefold()
    if not primary:
        return True
    return service == primary or primary in service


def _user_context(bot: commands.Bot, guild: discord.Guild, user_id: int) -> str:
    member = guild.get_member(user_id)
    user = member or bot.get_user(user_id)
    lines: list[str] = []
    if user is not None:
        display = getattr(user, "display_name", None) or str(user)
        mention = getattr(user, "mention", f"<@{user_id}>")
        lines.append(f"{mention} • **{display}**")
        lines.append(f"ID : `{user_id}` • {'🤖 Bot' if getattr(user, 'bot', False) else '👤 Utilisateur'}")
        created = getattr(user, "created_at", None)
        if created is not None:
            created_ts = int(created.timestamp())
            lines.append(f"Compte créé : <t:{created_ts}:F> • <t:{created_ts}:R>")
    else:
        lines.append(f"<@{user_id}> • ID : `{user_id}`")

    if member is not None:
        if member.joined_at is not None:
            joined_ts = int(member.joined_at.timestamp())
            lines.append(f"Arrivée serveur : <t:{joined_ts}:F> • <t:{joined_ts}:R>")
        roles = [role for role in member.roles if not role.is_default()]
        top = member.top_role.mention if not member.top_role.is_default() else "Aucun rôle"
        lines.append(f"Rôle principal : {top} • **{len(roles)} rôle(s)**")
        lines.append(f"Compte serveur : **{'Bot' if member.bot else 'Membre'}**")
    return "\n".join(lines)


def _role_context(guild: discord.Guild, role_id: int, embed: discord.Embed) -> str:
    role = guild.get_role(role_id)
    if role is None:
        description = (embed.description or "").splitlines()[0].strip()
        label = description if description and not description.startswith("<@&") else "Rôle supprimé"
        return f"**{label[:100]}**\nID : `{role_id}`\nÉtat : **supprimé / introuvable**"

    enabled_permissions = sum(1 for _name, enabled in role.permissions if enabled)
    return (
        f"{role.mention} • **{role.name}**\n"
        f"ID : `{role.id}` • Position : **{role.position}** • Couleur : `{role.colour}`\n"
        f"Affiché séparément : **{'Oui' if role.hoist else 'Non'}** • "
        f"Mentionnable : **{'Oui' if role.mentionable else 'Non'}**\n"
        f"Permissions actives : **{enabled_permissions}** • Géré par intégration : **{'Oui' if role.managed else 'Non'}**"
    )


def _channel_context(guild: discord.Guild, channel_id: int, embed: discord.Embed) -> str:
    channel = guild.get_channel(channel_id)
    if channel is None:
        description = (embed.description or "").splitlines()[0].strip()
        label = description[:120] if description else "Salon supprimé ou inaccessible"
        return f"**{label}**\nID : `{channel_id}`\nÉtat : **supprimé / inaccessible**"

    mention = getattr(channel, "mention", f"`{channel.name}`")
    category = getattr(channel, "category", None)
    category_text = category.name if category is not None else "Aucune catégorie"
    lines = [
        f"{mention} • **{channel.name}**",
        f"ID : `{channel.id}` • Type : `{channel.type}` • Position : **{channel.position}**",
        f"Catégorie : **{category_text}**",
    ]
    slowmode = getattr(channel, "slowmode_delay", 0)
    if slowmode:
        lines.append(f"Mode lent : **{slowmode} s**")
    if isinstance(channel, discord.TextChannel):
        lines.append(f"NSFW : **{'Oui' if channel.nsfw else 'Non'}** • Topic : **{'Oui' if channel.topic else 'Non'}**")
    return "\n".join(lines)


def _looks_like_member_target(log_type: str, title: str) -> bool:
    text = _plain(title)
    if log_type in {"members", "voice", "moderation", "economy", "levels", "ai", "games"}:
        return True
    return any(
        marker in text
        for marker in (
            "membre", "utilisateur", "timeout", "banni", "bannissement", "debanni",
            "unban", "kick", "expulse", "mute", "warn", "surnom",
        )
    )


def _looks_like_role_target(log_type: str, title: str) -> bool:
    text = _plain(title)
    if log_type != "roles":
        return False
    if "membre" in text or "attribue" in text or "retire" in text:
        return False
    # Un batch a comme footer générique ; ne jamais créer une section par rôle.
    if re.search(r"(?:creation|suppression|modification) de roles \(\d+\)", text):
        return False
    return "role" in text


def _looks_like_channel_target(log_type: str, title: str) -> bool:
    return log_type == "server" and "salon" in _plain(title)


def _is_message_target(log_type: str, title: str) -> bool:
    return log_type == "messages" or "message" in _plain(title)


def enrich_embed(
    bot: commands.Bot,
    guild: discord.Guild,
    log_type: str,
    source: discord.Embed,
) -> discord.Embed:
    embed = source.copy()
    title = str(embed.title or "Log SentriX")
    target_id = _footer_target(embed)
    event_ts = _event_timestamp(embed)

    # Détails généraux présents sur TOUS les logs, même les événements d'une seule ligne.
    _add_field(
        embed,
        "🕒 Informations de l’événement",
        (
            f"Date exacte : <t:{event_ts}:F>\n"
            f"Moment : <t:{event_ts}:R>\n"
            f"Catégorie : **{CATEGORY_LABELS.get(log_type, log_type.upper())}**"
        ),
        inline=False,
    )
    _add_field(
        embed,
        "🖥️ Informations du serveur",
        (
            f"**{guild.name}**\nID serveur : `{guild.id}`\n"
            f"Membres : **{guild.member_count or 0}** • Rôles : **{len(guild.roles)}** • "
            f"Salons : **{len(guild.channels)}**"
        ),
        inline=False,
    )

    if target_id:
        if _is_message_target(log_type, title):
            _add_field(embed, "💬 Identifiant du message", f"`{target_id}`", inline=False)
        elif _looks_like_role_target(log_type, title):
            _add_field(embed, "🏷️ Informations du rôle", _role_context(guild, target_id, embed), inline=False)
        elif _looks_like_channel_target(log_type, title):
            _add_field(embed, "#️⃣ Informations du salon", _channel_context(guild, target_id, embed), inline=False)
        elif _looks_like_member_target(log_type, title):
            _add_field(embed, "👤 Informations de la cible", _user_context(bot, guild, target_id), inline=False)
        else:
            _add_field(embed, "🆔 Identifiant de la cible", f"`{target_id}`", inline=False)

    grouped = re.search(r"(?:Création|Suppression|Modification) de rôles \((\d+)\)", title, re.IGNORECASE)
    if grouped:
        count = int(grouped.group(1))
        _add_field(
            embed,
            "📦 Rafale de rôles",
            (
                f"**{count} rôles** détectés dans la même fenêtre de **3 secondes**.\n"
                "Une seule carte est envoyée et la liste complète des rôles reste regroupée dans le résumé."
            ),
            inline=False,
        )

    return embed


def _field_heading(name: str) -> str:
    text = str(name).strip()
    # Les noms possèdent déjà souvent un emoji ; conserver le rendu mais le rendre grand.
    return text[:180] or "Détail"


def _description_block(embed: discord.Embed) -> str | None:
    text = (embed.description or "").strip()
    if not text:
        return None
    # Une mention seule est déjà répétée dans les détails de cible ; l'afficher reste utile
    # pour garder le résumé de l'événement immédiatement visible sous le titre.
    return f"### Résumé\n{text[:3800]}"


def _thumbnail_url(embed: discord.Embed, bot: commands.Bot, guild: discord.Guild) -> str | None:
    thumb = getattr(embed.thumbnail, "url", None)
    if thumb:
        return str(thumb)
    if guild.icon:
        return str(guild.icon.url)
    if bot.user:
        return str(bot.user.display_avatar.url)
    return None


class DetailedPremiumLogLayout(discord.ui.LayoutView):
    """Layout pleine largeur : grand titre + blocs verticaux, sans header générique."""

    def __init__(
        self,
        bot: commands.Bot,
        guild: discord.Guild,
        log_type: str,
        embed: discord.Embed,
        buttons: list[tuple[str, int]],
    ):
        super().__init__(timeout=6 * 60 * 60)
        detailed = enrich_embed(bot, guild, log_type, embed)
        accent = int(detailed.colour.value) if detailed.colour else 0x7C5CFC
        category = CATEGORY_LABELS.get(log_type, log_type.upper())
        title = str(detailed.title or "Journal SentriX").strip()

        container = discord.ui.Container(accent_colour=accent)

        # PLEINE LARGEUR : le titre n'est volontairement pas dans une Section avec image,
        # ce qui laisse tout l'espace horizontal disponible au nom de l'événement.
        container.add_item(
            discord.ui.TextDisplay(
                f"-# 🛡️ SENTRIX  •  {category}  •  {guild.name}\n# {title}"
            )
        )

        summary = _description_block(detailed)
        if summary:
            container.add_item(discord.ui.Separator())
            container.add_item(discord.ui.TextDisplay(summary))

        # Les détails métier et le contexte sont affichés comme de vrais blocs verticaux.
        for field in detailed.fields:
            container.add_item(discord.ui.Separator())
            value = str(field.value).strip() or "*Aucune information disponible.*"
            container.add_item(
                discord.ui.TextDisplay(
                    f"## {_field_heading(str(field.name))}\n{value[:3800]}"
                )
            )

        image_url = getattr(detailed.image, "url", None)
        if image_url:
            gallery = discord.ui.MediaGallery()
            gallery.add_item(media=str(image_url), description=f"Aperçu — {title[:80]}")
            container.add_item(discord.ui.Separator())
            container.add_item(gallery)

        container.add_item(discord.ui.Separator())
        event_ts = _event_timestamp(detailed)
        target_id = _footer_target(detailed)
        footer = f"-# SentriX • Journal sécurisé • <t:{event_ts}:F> • <t:{event_ts}:R>"
        if target_id:
            footer += f" • ID `{target_id}`"
        container.add_item(discord.ui.TextDisplay(footer))

        final_buttons = _button_items(detailed, title) or buttons
        if final_buttons:
            row = discord.ui.ActionRow()
            seen: set[tuple[str, int]] = set()
            for index, (label, value) in enumerate(final_buttons[:5]):
                key = (str(label), int(value))
                if key in seen:
                    continue
                seen.add(key)
                row.add_item(premium_logs_v2.CopyIdButton(str(label), int(value), index))
            if row.children:
                container.add_item(row)

        self.add_item(container)


def _reset_file(file: discord.File | None) -> None:
    if file is None:
        return
    try:
        file.reset(seek=True)
    except Exception:
        pass


def install(bot: commands.Bot, extension_name: str = "") -> None:
    del extension_name
    global _INSTALLED
    if _INSTALLED:
        return

    if not all(hasattr(discord.ui, name) for name in ("LayoutView", "Container", "TextDisplay")):
        logger.warning("V24 : Components V2 indisponibles ; grand layout ignoré.")
        return

    # premium_logs_v2 résout cette classe au moment de chaque envoi. La remplacer ici
    # change le rendu sans ajouter un deuxième listener ni un deuxième événement.
    DetailedPremiumLogLayout._sentrix_detailed_v24 = True
    premium_logs_v2.PremiumLogLayout = DetailedPremiumLogLayout

    previous_send = log_service.send_log
    if not getattr(previous_send, "_sentrix_single_large_logs_v24", False):
        async def send_single_large_log(
            inner_bot,
            guild: discord.Guild,
            log_type: str,
            embed: discord.Embed,
            file: discord.File | None = None,
        ) -> bool:
            # Deux services Railway avec le même bot reçoivent le même Gateway event.
            # Le secondaire ne doit JAMAIS envoyer une seconde copie du journal.
            if not _is_primary_log_service():
                return True

            # Sans fichier, laisser toute la chaîne existante (routage + batch rôles + V2)
            # travailler. Le renderer V2 utilisera notre classe pleine largeur ci-dessus.
            if file is None:
                return await previous_send(inner_bot, guild, log_type, embed, file=None)

            # Pour un transcript/pièce jointe, envoyer également le grand Components V2.
            try:
                styled = style_log(inner_bot, guild, log_type, embed)
                premium_logs_v2._fix_timeout_duration(styled, embed)
                styled = enrich_embed(inner_bot, guild, log_type, styled)
                buttons = _button_items(styled, str(styled.title or ""))

                setting = await log_service.get_log_setting(inner_bot, guild.id, log_type)
                if not setting["enabled"]:
                    return False
                ok, _reason = log_service.validate_channel(guild, setting["channel_id"], needs_file=True)
                if not ok:
                    return await previous_send(inner_bot, guild, log_type, embed, file=file)
                channel = guild.get_channel(setting["channel_id"])
                if not isinstance(channel, discord.TextChannel):
                    return await previous_send(inner_bot, guild, log_type, embed, file=file)

                layout = DetailedPremiumLogLayout(inner_bot, guild, log_type, styled, buttons)
                _reset_file(file)
                await channel.send(
                    view=layout,
                    file=file,
                    allowed_mentions=discord.AllowedMentions.none(),
                )
                return True
            except Exception:
                logger.exception("V24 : grand log avec fichier refusé, fallback historique (%s).", log_type)
                _reset_file(file)
                return await previous_send(inner_bot, guild, log_type, embed, file=file)

        send_single_large_log._sentrix_single_large_logs_v24 = True
        send_single_large_log._sentrix_original = previous_send
        log_service.send_log = send_single_large_log

    _INSTALLED = True
    logger.info(
        "V24 : grand layout pleine largeur actif ; service logs primaire=%s ; rafales rôles conservées à 3 s.",
        _is_primary_log_service(),
    )


__all__ = ["install", "enrich_embed", "DetailedPremiumLogLayout"]
