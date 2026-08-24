"""SentriX V26 — layout de logs proche de la carte de référence utilisateur.

Objectif visuel : reprendre la présence de la grande carte de référence utilisateur, en environ
15–20 % plus petit. Discord garde le contrôle de la largeur exacte selon le client,
mais la structure est volontairement plus ample que le mini-layout V25 :
header/titre/description avec avatar à droite, section de détail, footer, boutons.

V27 reste la couche de normalisation/Audit Log. V28 conserve les IDs, la déduplication
exacte et les mentions silencieuses. V30 est désormais le renderer visuel final.
V31 force les anciens logs directs (notamment tickets dédiés) à utiliser ce renderer.
V32 ajoute les journaux salons/dossiers/anti-spam/anti-raid/staff et le mode adaptatif
pour les messages réellement longs, sans modifier le rendu des petits messages.
V33 ajoute +testlogs / /testlogs pour tester tous les anciens et nouveaux journaux.
V34 ajoute +createalllogs / /createalllogs et fait aussi de +create-logs une installation
complète des 13 salons de logs réellement utilisés.
V34 Ticket Transcript s'installe en tout dernier pour les fermetures : carte dédiée,
participants, raison, transcript HTML joint et bouton Transcript.
V50 est installé après toutes ces couches et impose la structure visuelle uniforme des
cartes standards : mêmes blocs, padding invisible et taille maximale des contenus.
V52 élargit légèrement la présence visuelle des cartes sans modifier leur hauteur cible.
"""
from __future__ import annotations

import re

import discord
from discord.ext import commands

from . import premium_logs_v2
from .premium_logs import _button_items
from .log_rectangle_v25 import (
    CATEGORY_LABELS,
    _event_title,
    _event_timestamp,
    _field_value,
    _fingerprint_embed,
    _is_role_batch,
    _sanitized_embed,
    _target_id,
)

_INSTALLED = False


def _avatar_url(bot: commands.Bot, guild: discord.Guild, embed: discord.Embed) -> str | None:
    for token in ("auteur", "membre", "utilisateur", "cible"):
        raw = _field_value(embed, token)
        match = re.search(r"(?<!\d)(\d{15,22})(?!\d)", raw or "")
        if not match:
            continue
        uid = int(match.group(1))
        member = guild.get_member(uid)
        user = member or bot.get_user(uid)
        if user is not None:
            try:
                return str(user.display_avatar.url)
            except Exception:
                pass
    if guild.icon:
        return str(guild.icon.url)
    if bot.user:
        return str(bot.user.display_avatar.url)
    return None


def _clean_description(embed: discord.Embed) -> str:
    description = (embed.description or "").strip()
    return description[:900] if description else ""


def _detail_text(embed: discord.Embed) -> str:
    if _is_role_batch(embed):
        description = (embed.description or "").strip()
        return description[:3200] if description else "*Aucun détail disponible.*"
    author = _field_value(embed, "auteur", "membre", "utilisateur", "cible")
    salon = _field_value(embed, "salon")
    content = _field_value(embed, "contenu")
    before = _field_value(embed, "avant")
    after = _field_value(embed, "apres")
    actor = _field_value(embed, "effectue par", "moderateur", "acteur")
    reason = _field_value(embed, "raison")
    duration = _field_value(embed, "duree", "fin du timeout", "nouvel etat")
    parts: list[str] = []
    if salon:
        parts.append(f"### 💬 Salon\n{salon[:500]}")
    if author:
        parts.append(f"### 👤 Auteur\n{author[:500]}")
    if content:
        parts.append(f"### 📝 Contenu\n{content[:900]}")
    elif before or after:
        if before:
            parts.append(f"### ◀️ Avant\n{before[:650]}")
        if after:
            parts.append(f"### ▶️ Après\n{after[:650]}")
    extras: list[str] = []
    if actor:
        extras.append(f"**🛡️ Effectué par**\n{actor[:450]}")
    if reason:
        extras.append(f"**📝 Raison**\n{reason[:600]}")
    if duration:
        extras.append(f"**⏱️ Durée / fin**\n{duration[:450]}")
    if extras:
        parts.append("\n\n".join(extras))
    return "\n\n".join(parts[:3])[:2600]


class ReferenceLogLayout(discord.ui.LayoutView):
    _sentrix_log_layout = True
    _sentrix_rectangle_v25 = True
    _sentrix_reference_v26 = True

    def __init__(self, bot: commands.Bot, guild: discord.Guild, log_type: str, embed: discord.Embed, buttons: list[tuple[str, int]]):
        super().__init__(timeout=6 * 60 * 60)
        clean = _sanitized_embed(bot, guild, embed)
        accent = int(clean.colour.value) if clean.colour else 0x7C5CFC
        category = CATEGORY_LABELS.get(log_type, log_type.upper())
        title = _event_title(clean)
        container = discord.ui.Container(accent_colour=accent)
        header_lines = [f"-# 🛡️ SENTRIX • {category} • {guild.name}", f"# {title}"]
        description = _clean_description(clean)
        if description and not _is_role_batch(clean):
            header_lines.append(description)
        header = discord.ui.TextDisplay("\n\n".join(header_lines)[:3900])
        avatar = _avatar_url(bot, guild, clean)
        if avatar:
            try:
                container.add_item(discord.ui.Section(header, accessory=discord.ui.Thumbnail(avatar, description="Avatar lié à l'événement")))
            except Exception:
                container.add_item(header)
        else:
            container.add_item(header)
        details = _detail_text(clean)
        if details:
            container.add_item(discord.ui.Separator())
            container.add_item(discord.ui.TextDisplay(details))
        container.add_item(discord.ui.Separator())
        ts = _event_timestamp(clean)
        target = _target_id(clean)
        footer = f"-# SentriX • Journal sécurisé • <t:{ts}:R>"
        if target:
            footer += f" • ID `{target}`"
        container.add_item(discord.ui.TextDisplay(footer))
        final_buttons = _button_items(clean, str(clean.title or "")) or buttons
        if final_buttons:
            row = discord.ui.ActionRow()
            seen: set[tuple[str, int]] = set()
            for index, (label, value) in enumerate(final_buttons[:2]):
                key = (str(label), int(value))
                if key in seen:
                    continue
                seen.add(key)
                row.add_item(premium_logs_v2.CopyIdButton(str(label), int(value), index))
            if row.children:
                container.add_item(row)
        self._sentrix_log_fingerprint = _fingerprint_embed(guild.id, clean)
        self._sentrix_is_log_layout = True
        self.add_item(container)


async def install(bot: commands.Bot, extension_name: str = "") -> None:
    global _INSTALLED
    required = ("LayoutView", "Container", "Section", "TextDisplay", "Thumbnail", "Separator")
    if not all(hasattr(discord.ui, name) for name in required):
        return
    premium_logs_v2.PremiumLogLayout = ReferenceLogLayout
    _INSTALLED = True

    from .log_premium_v28 import install_source_guard as install_v28_source
    install_v28_source(bot)
    from .log_single_pipeline_v27 import install as install_v27
    install_v27(bot, extension_name)
    from .log_premium_v28 import install as install_v28
    install_v28(bot, extension_name)
    from .log_ultra_style_v29 import install as install_v29
    install_v29(bot, extension_name)
    from .log_preferred_style_v30 import install as install_v30
    install_v30(bot, extension_name)
    from .log_category_unifier_v31 import install as install_v31
    install_v31(bot, extension_name)
    from .log_catalog_v32 import install as install_v32
    install_v32(bot, extension_name)
    from .log_test_all_v33 import install as install_v33
    await install_v33(bot, extension_name)
    from .create_all_logs_v34 import install as install_v34
    await install_v34(bot, extension_name)
    # Toujours le dernier wrapper TextChannel.send pour les fermetures de tickets + transcript.
    from .ticket_transcript_logs_v34 import install as install_ticket_transcript_v34
    install_ticket_transcript_v34(bot, extension_name)

    # V50 doit être la dernière couche VISUELLE. La garde de sortie V25 considère
    # `_sentrix_rectangle_v25` comme le marqueur de compatibilité ; sans ce marqueur elle
    # prenait V50 pour un ancien layout et supprimait silencieusement tous les logs.
    from . import log_fixed_height_v50 as fixed_v50
    FixedHeightLogV50 = fixed_v50.FixedHeightLogV50
    FixedHeightLogV50._sentrix_rectangle_v25 = True
    FixedHeightLogV50._sentrix_reference_v26 = True
    FixedHeightLogV50._sentrix_unified_v27 = True
    FixedHeightLogV50._sentrix_premium_v28 = True

    # V52 : Discord ne donne pas de propriété `width` aux Components V2. Pour gagner
    # légèrement en largeur sans ajouter une ligne ni modifier la hauteur, on réserve
    # quelques espaces Unicode de largeur réelle à la fin de la description du header.
    # Cela pousse le Container à utiliser un peu plus de largeur sur desktop, tout en
    # restant responsive sur mobile.
    if not getattr(fixed_v50, "_sentrix_wider_v52", False):
        original_description = fixed_v50._description

        def wider_description(embed: discord.Embed) -> str:
            return original_description(embed) + ("\u2003" * 7)

        fixed_v50._description = wider_description
        fixed_v50._sentrix_wider_v52 = True

    fixed_v50.install(bot, extension_name)

    # Panneau de vérification V51 : aucune nouvelle commande, uniquement le runtime de
    # +setup > Sécurité et les boutons persistants du portail.
    from .verification_polish_v51 import install as install_verification_polish_v51
    install_verification_polish_v51(bot)


__all__ = ["install", "ReferenceLogLayout"]
