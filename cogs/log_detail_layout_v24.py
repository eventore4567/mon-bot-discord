"""SentriX V24 — grands journaux détaillés pour toutes les catégories.

Le moteur PremiumLogLayout V2 est déjà le point visuel commun à tous les logs. Cette
couche enrichit la copie de l'embed juste avant le rendu afin que même un événement très
court produise une grande carte lisible et utile.

Garanties :
- les détails métier existants restent prioritaires et ne sont jamais supprimés ;
- chaque carte reçoit un contexte temporel + serveur ;
- membre/utilisateur, rôle, salon et message reçoivent des métadonnées spécifiques quand
  leur ID peut être déduit du log ;
- les rafales de rôles restent UNE liste dans UNE carte, jamais un champ par rôle ;
- le rendu s'applique aussi aux logs avec fichier quand Components V2 les accepte, avec
  repli sûr sur le sender précédent en cas de refus Discord.
"""
from __future__ import annotations

import logging
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
        current = _plain(str(field.name))
        if current in wanted:
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


def _user_context(bot: commands.Bot, guild: discord.Guild, user_id: int) -> str:
    member = guild.get_member(user_id)
    user = member or bot.get_user(user_id)
    lines: list[str] = []
    if user is not None:
        display = getattr(user, "display_name", None) or str(user)
        mention = getattr(user, "mention", f"<@{user_id}>")
        lines.append(f"{mention} • **{display}**")
        lines.append(f"ID : `{user_id}` • {'Bot' if getattr(user, 'bot', False) else 'Utilisateur'}")
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
        lines.append(f"Rôle principal : {top} • {len(roles)} rôle(s)")
    return "\n".join(lines)


def _role_context(guild: discord.Guild, role_id: int, embed: discord.Embed) -> str:
    role = guild.get_role(role_id)
    if role is None:
        # Pour un rôle supprimé, son objet n'existe plus ; le log original conserve son nom.
        description = (embed.description or "").splitlines()[0].strip()
        label = description if description and not description.startswith("<@&") else "Rôle supprimé"
        return f"**{label[:100]}**\nID : `{role_id}` • Le rôle n'existe plus sur le serveur."

    enabled_permissions = sum(1 for _name, enabled in role.permissions if enabled)
    colour = str(role.colour)
    return (
        f"{role.mention} • **{role.name}**\n"
        f"ID : `{role.id}` • Position : `{role.position}` • Couleur : `{colour}`\n"
        f"Affiché séparément : **{'Oui' if role.hoist else 'Non'}** • "
        f"Mentionnable : **{'Oui' if role.mentionable else 'Non'}** • "
        f"Permissions actives : **{enabled_permissions}**"
    )


def _channel_context(guild: discord.Guild, channel_id: int, embed: discord.Embed) -> str:
    channel = guild.get_channel(channel_id)
    if channel is None:
        description = (embed.description or "").splitlines()[0].strip()
        label = description[:120] if description else "Salon supprimé ou inaccessible"
        return f"**{label}**\nID : `{channel_id}` • Le salon n'existe plus sur le serveur."

    mention = getattr(channel, "mention", f"`{channel.name}`")
    category = getattr(channel, "category", None)
    category_text = category.name if category is not None else "Aucune catégorie"
    lines = [
        f"{mention} • **{channel.name}**",
        f"ID : `{channel.id}` • Type : `{channel.type}` • Position : `{channel.position}`",
        f"Catégorie : **{category_text}**",
    ]
    slowmode = getattr(channel, "slowmode_delay", 0)
    if slowmode:
        lines.append(f"Mode lent : **{slowmode} s**")
    if isinstance(channel, discord.TextChannel):
        lines.append(f"NSFW : **{'Oui' if channel.nsfw else 'Non'}**")
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
    # Les logs « rôle attribué/retiré à un membre » ont comme footer l'ID du membre.
    if "membre" in text or "attribue" in text or "retire" in text:
        return False
    return "role" in text and "roles (" not in text


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

    # Ces deux blocs rendent chaque journal réellement informatif même si l'événement
    # source ne contient qu'une ligne (ban, création de rôle, création de salon, etc.).
    _add_field(
        embed,
        "🕒 Événement",
        f"Date : <t:{event_ts}:F>\nIl y a : <t:{event_ts}:R>\nCatégorie : **{log_type.upper()}**",
        inline=False,
    )
    _add_field(
        embed,
        "🖥️ Serveur",
        (
            f"**{guild.name}**\nID : `{guild.id}`\n"
            f"Membres : **{guild.member_count or 0}** • Rôles : **{len(guild.roles)}** • "
            f"Salons : **{len(guild.channels)}**"
        ),
        inline=False,
    )

    if target_id:
        if _is_message_target(log_type, title):
            _add_field(embed, "💬 Trace du message", f"ID message : `{target_id}`", inline=False)
        elif _looks_like_role_target(log_type, title):
            _add_field(embed, "🏷️ Détails du rôle", _role_context(guild, target_id, embed), inline=False)
        elif _looks_like_channel_target(log_type, title):
            _add_field(embed, "#️⃣ Détails du salon", _channel_context(guild, target_id, embed), inline=False)
        elif _looks_like_member_target(log_type, title):
            _add_field(embed, "👤 Détails de la cible", _user_context(bot, guild, target_id), inline=False)
        else:
            _add_field(embed, "🆔 Cible", f"Identifiant : `{target_id}`", inline=False)

    # Les batches de rôles doivent rester une LISTE unique, pas 1 bloc par rôle.
    grouped = re.search(r"(?:Création|Suppression|Modification) de rôles \((\d+)\)", title, re.IGNORECASE)
    if grouped:
        count = int(grouped.group(1))
        _add_field(
            embed,
            "📦 Regroupement automatique",
            (
                f"**{count} rôles** détectés dans la même fenêtre de **3 secondes**.\n"
                "Ils sont volontairement réunis dans cette seule carte ; la liste complète reste au-dessus."
            ),
            inline=False,
        )

    return embed


class DetailedPremiumLogLayout(premium_logs_v2.PremiumLogLayout):
    def __init__(
        self,
        bot: commands.Bot,
        guild: discord.Guild,
        log_type: str,
        embed: discord.Embed,
        buttons: list[tuple[str, int]],
    ):
        detailed = enrich_embed(bot, guild, log_type, embed)
        # Recalculer les boutons après enrichissement n'est pas nécessaire pour les IDs
        # existants, mais garantit qu'une future catégorie ajoutant sa cible ici en profite.
        detailed_buttons = _button_items(detailed, str(detailed.title or "")) or buttons
        super().__init__(bot, guild, log_type, detailed, detailed_buttons)


def _reset_file(file: discord.File | None) -> None:
    if file is None:
        return
    try:
        file.reset(seek=True)
    except Exception:
        pass


def install(bot: commands.Bot) -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    if not all(hasattr(discord.ui, name) for name in ("LayoutView", "Container", "Section", "TextDisplay")):
        logger.warning("V24 : Components V2 indisponibles ; enrichissement visuel ignoré.")
        return

    # Le sender V2 résout PremiumLogLayout dans le module au moment de l'envoi : remplacer
    # la classe ici suffit donc pour TOUS les futurs logs sans réécrire les listeners.
    if not getattr(premium_logs_v2.PremiumLogLayout, "_sentrix_detailed_v24", False):
        DetailedPremiumLogLayout._sentrix_detailed_v24 = True
        premium_logs_v2.PremiumLogLayout = DetailedPremiumLogLayout

    previous_send = log_service.send_log
    if not getattr(previous_send, "_sentrix_large_file_logs_v24", False):
        async def send_large_logs(
            inner_bot,
            guild: discord.Guild,
            log_type: str,
            embed: discord.Embed,
            file: discord.File | None = None,
        ) -> bool:
            # Sans fichier, le sender V2 normal profite déjà de DetailedPremiumLogLayout.
            if file is None:
                return await previous_send(inner_bot, guild, log_type, embed, file=None)

            # Les logs avec transcript/pièce jointe ont désormais eux aussi la grande carte.
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

                layout = premium_logs_v2.PremiumLogLayout(inner_bot, guild, log_type, styled, buttons)
                _reset_file(file)
                await channel.send(view=layout, file=file)
                return True
            except Exception:
                logger.exception("V24 : grande carte avec fichier refusée, fallback historique (%s).", log_type)
                _reset_file(file)
                return await previous_send(inner_bot, guild, log_type, embed, file=file)

        send_large_logs._sentrix_large_file_logs_v24 = True
        log_service.send_log = send_large_logs

    _INSTALLED = True
    logger.info("V24 : toutes les catégories de logs utilisent des cartes grandes et détaillées.")


__all__ = ["install", "enrich_embed"]
