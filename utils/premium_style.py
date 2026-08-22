"""Identité visuelle et éditoriale globale de SentriX.

Ce module ne contient aucune logique métier. Il harmonise les embeds, messages et
composants Discord afin que toutes les commandes partagent la même présentation et la
même microcopy : concise, claire, professionnelle et accessible.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

import discord

from utils import brand_assets, microcopy


COLORS: dict[str, int] = {
    "brand": 0x6C5CE7,
    "info": 0x5865F2,
    "success": 0x2FBF71,
    "warning": 0xF0B232,
    "danger": 0xED4245,
    "neutral": 0x4B5563,
    "moderation": 0xE05A67,
    "security": 0x7A68D8,
    "tickets": 0x4C9AFF,
    "economy": 0xD6A94A,
    "levels": 0x45B889,
    "games": 0x33A8B8,
    "music": 0xC7689D,
    "events": 0xDA8058,
    "invites": 0x35A794,
    "ai": 0x8069D8,
    "configuration": 0x6C5CE7,
    "logs": 0x667085,
    "utility": 0x5865F2,
    "profile": 0x00B8D9,
    "shop": 0xE6B84A,
    "leaderboard": 0x4C7DFF,
    "premium": 0xF2C94C,
}

# Contrat visuel V4. Ces limites sont volontairement plus strictes que les limites
# techniques de Discord : un panneau doit rester lisible sur mobile sans devenir une
# page de documentation.
VISUAL_LIMITS: dict[str, int] = {
    "title": 72,
    "button_label": 24,
    "select_label": 60,
    "select_description": 72,
    "compact_items": 8,
    "shop_items": 6,
    "leaderboard_items": 10,
}

CATEGORY_NAMES: dict[str, str] = {
    "moderation": "Modération",
    "security": "Sécurité",
    "tickets": "Tickets",
    "economy": "Économie",
    "levels": "Niveaux",
    "games": "Mini-jeux",
    "music": "Musique",
    "events": "Événements",
    "invites": "Invitations",
    "ai": "Intelligence artificielle",
    "configuration": "Configuration",
    "logs": "Journal",
    "utility": "Utilitaires",
    "profile": "Profil",
    "shop": "Boutique",
    "leaderboard": "Classement",
    "premium": "Premium",
    "brand": "SentriX",
}

STATE_LABELS: dict[str, str] = {
    "success": "Terminé",
    "warning": "Attention",
    "danger": "Erreur",
}

SYSTEM_COLOURS = {
    0x57F287, 0x23A559, 0x2ECC71,
    0xED4245, 0xF23F43, 0xE74C3C,
    0xFEE75C, 0xF0B232, 0xF39C12,
    0x5865F2, 0x5847EB, 0x7C5CFC, 0x7C6CFF,
    0x3498DB, 0x1ABC9C, 0x00BCD4, 0x8E44AD,
}

LEADING_DECORATION = re.compile(
    r"^(?:[\s\u200b]*[\W_]{1,4}[\s\u200b]*)+",
    flags=re.UNICODE,
)
SPACE_RE = re.compile(r"[ \t]{2,}")
SENTRIX_TITLE_RE = re.compile(r"^SENTRIX\s*(?:/|•)\s*", re.IGNORECASE)

_GENERIC_TITLES = {
    "action terminée", "action terminee", "action impossible",
    "vérification nécessaire", "verification necessaire", "à vérifier",
    "information", "succès", "succes", "erreur", "avertissement",
}


def clip(value: Any, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def format_number(value: Any) -> str:
    """Nombre lisible en français, stable pour l'économie, l'XP et les statistiques."""
    try:
        return f"{int(value or 0):,}".replace(",", " ")
    except (TypeError, ValueError):
        return "0"


def format_duration(seconds: Any) -> str:
    """Durée compacte sans unité inutile : 4 h 12 min, 8 min ou 35 s."""
    try:
        total = max(0, int(seconds or 0))
    except (TypeError, ValueError):
        total = 0
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours} h {minutes} min" if minutes else f"{hours} h"
    if minutes:
        return f"{minutes} min" if not secs else f"{minutes} min {secs} s"
    return f"{secs} s"


def compact_lines(lines: Any, *, limit: int | None = None) -> list[str]:
    """Nettoie une liste de lignes et ajoute un résumé lorsque la liste déborde."""
    maximum = max(1, int(limit or VISUAL_LIMITS["compact_items"]))
    cleaned = [SPACE_RE.sub(" ", str(line)).strip() for line in list(lines or [])]
    cleaned = [line for line in cleaned if line]
    if len(cleaned) <= maximum:
        return cleaned
    hidden = len(cleaned) - maximum
    return [*cleaned[:maximum], f"+{hidden} autre{'s' if hidden > 1 else ''}"]


def progress_bar(value: float, maximum: float, *, length: int = 12) -> str:
    """Barre compacte sans emoji, stable dans toutes les polices Discord."""
    try:
        ratio = float(value) / float(maximum) if float(maximum) > 0 else 0.0
    except (TypeError, ValueError, ZeroDivisionError):
        ratio = 0.0
    ratio = max(0.0, min(ratio, 1.0))
    length = max(4, min(int(length), 20))
    filled = round(ratio * length)
    return f"{'▰' * filled}{'▱' * (length - filled)}  {round(ratio * 100)} %"


def clean_title(value: Any, fallback: str = "Information") -> str:
    text = clip(value, 256)
    if not text:
        return fallback
    cleaned = LEADING_DECORATION.sub("", text).strip(" —–-|•·")
    cleaned = SPACE_RE.sub(" ", cleaned).strip()
    cleaned = microcopy.polish_text(cleaned)
    return cleaned or fallback


def display_label(value: Any, fallback: str = "Information") -> str:
    """Transforme un ancien titre tout en capitales en libellé premium plus calme."""
    text = clean_title(value, fallback)
    if text.isupper():
        text = text[:1].upper() + text[1:].lower()
    replacements = {
        " ia": " IA",
        " ai": " AI",
        " xp": " XP",
        " automod": " AutoMod",
    }
    padded = f" {text}"
    for source, target in replacements.items():
        padded = re.sub(rf"{re.escape(source)}\b", target, padded, flags=re.IGNORECASE)
    return padded.strip()


def infer_kind(embed: discord.Embed | None = None, content: str = "") -> str:
    text = " ".join(
        part for part in (
            getattr(embed, "title", None) if embed else None,
            getattr(embed, "description", None) if embed else None,
            content,
        ) if part
    ).casefold()
    value = getattr(getattr(embed, "colour", None), "value", 0) if embed else 0

    if value in {0xED4245, 0xF23F43, 0xE74C3C} or any(word in text for word in (
        "erreur", "impossible", "refusé", "interdit", "introuvable", "échoué",
        "manquante", "bloqué", "banni", "sanction",
    )):
        return "danger"
    if value in {0xFEE75C, 0xF0B232, 0xF39C12} or any(word in text for word in (
        "attention", "avertissement", "à vérifier", "déjà", "recharge", "cooldown",
    )):
        return "warning"
    if value in {0x57F287, 0x23A559, 0x2ECC71} or any(word in text for word in (
        "réussi", "terminé", "enregistré", "créé", "activé", "ajouté", "envoyé",
        "configuré", "effectué",
    )):
        return "success"
    return "info"


def infer_category(*, command: Any = None, embed: discord.Embed | None = None, hint: str | None = None) -> str:
    if hint in CATEGORY_NAMES:
        return str(hint)

    cog_name = ""
    command_name = ""
    if command is not None:
        cog_name = str(getattr(command, "cog_name", "") or "").casefold()
        command_name = str(getattr(command, "qualified_name", "") or "").casefold()

    title = str(getattr(embed, "title", "") or "").casefold()
    direct_categories = {
        "moderation": "moderation",
        "automod": "security",
        "security": "security",
        "securitycommandcenter": "security",
        "securityv2runtime": "security",
        "tickets": "tickets",
        "economy": "economy",
        "levels": "levels",
        "minigames": "games",
        "games_setup": "games",
        "music": "music",
        "events": "events",
        "invites": "invites",
        "ai": "ai",
        "configuration": "configuration",
        "serverbuilder": "configuration",
        "server_builder": "configuration",
        "logs": "logs",
    }
    haystack = f"{cog_name} {command_name} {title}"
    priority_rules = (
        ("premium", ("sentrixpro", "sentrixplus", "sentrixultimate", "sentrix_ultimate", "premium", "ultimate")),
        ("leaderboard", ("leaderboard", "classement", "top serveur", "top 10")),
        ("profile", ("profile", "profil", "set-bio", "badge", "missions")),
        ("shop", ("shop", "boutique", "inventory", "inventaire", "buy", "sell", "acheter")),
    )
    for resolved, words in priority_rules:
        if any(word in haystack for word in words):
            return resolved

    if cog_name in direct_categories:
        return direct_categories[cog_name]

    rules = (
        ("moderation", ("moderation", "sanction", "warn", "mute", "kick", "ban", "quarantaine")),
        ("security", ("automod", "security", "sécurité", "antinuke", "anti-", "blacklist", "whitelist")),
        ("tickets", ("ticket", "support")),
        ("economy", ("economy", "économie", "balance", "banque", "argent", "daily", "work")),
        ("levels", ("level", "niveau", "xp", "réputation", "reputation")),
        ("games", ("game", "jeu", "trivia", "slots", "blackjack", "quiz", "guess")),
        ("music", ("music", "musique", "playlist", "queue", "lecture")),
        ("events", ("event", "giveaway", "tournoi", "tournament", "événement")),
        ("invites", ("invite", "invitation")),
        ("ai", (" ai", "intelligence", "sentrix", "openai", "image")),
        ("configuration", ("configuration", "setup", "config", "rôle", "salon", "serveur", "create-server", "wipe-server")),
        ("logs", ("log", "journal", "audit")),
    )
    for category, words in rules:
        if any(word in haystack for word in words):
            return category
    return "utility"


def _footer_text(*, guild: discord.Guild | None = None, requester: Any = None) -> str:
    """Footer volontairement court : marque + serveur, sans répéter le pseudo utilisateur."""
    parts = ["SentriX"]
    if guild is not None:
        parts.append(clip(getattr(guild, "name", "Serveur"), 60))
    return " • ".join(parts)


def _canonical_title(category: str, *, log_type: str | None = None) -> str:
    label = CATEGORY_NAMES.get(category, "Information")
    if log_type:
        return clip(f"SentriX • Journal {label}", VISUAL_LIMITS["title"])
    return clip(f"SentriX • {label}", VISUAL_LIMITS["title"])


def _detail_title(original_title: Any, category: str) -> str | None:
    if not original_title:
        return None
    cleaned = clean_title(original_title)
    if SENTRIX_TITLE_RE.match(cleaned):
        return None
    lowered = cleaned.casefold()
    if lowered in _GENERIC_TITLES:
        return None
    if lowered == CATEGORY_NAMES.get(category, "").casefold():
        return None
    return cleaned


def _merge_detail(description: Any, detail: str | None) -> str | None:
    body = microcopy.polish_text(clip(description, 4096)) if description else ""
    if not detail:
        return body or None
    detail = microcopy.polish_text(detail)
    marker = f"**{detail}**"
    if body.startswith(marker):
        return body
    if not body:
        return marker
    return clip(f"{marker}\n{body}", 4096)


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
    """Harmonise un embed existant sans supprimer ses données, images ou champs."""
    if not isinstance(embed, discord.Embed):
        return embed

    category = infer_category(command=command, embed=embed, hint=category)
    kind = kind or infer_kind(embed)

    original_title = getattr(embed, "title", None)
    cleaned_original = clean_title(original_title) if original_title else ""
    if cleaned_original and SENTRIX_TITLE_RE.match(cleaned_original):
        # Les centres spécialisés gardent leur nom, avec une typographie moins agressive.
        panel_name = SENTRIX_TITLE_RE.sub("", cleaned_original).strip()
        brand_name = CATEGORY_NAMES.get("brand", "SentriX")
        embed.title = clip(f"{brand_name} • {display_label(panel_name)}", VISUAL_LIMITS["title"])
        detail = None
    else:
        detail = _detail_title(original_title, category)
        embed.title = _canonical_title(category, log_type=log_type)
    embed.description = _merge_detail(getattr(embed, "description", None), detail)

    current_colour = getattr(getattr(embed, "colour", None), "value", 0) or 0
    state_colour = COLORS.get(kind)
    category_colour = COLORS.get(category, COLORS["brand"])
    if kind in {"success", "warning", "danger"} and state_colour:
        embed.colour = discord.Colour(state_colour)
    elif not current_colour or current_colour in SYSTEM_COLOURS:
        embed.colour = discord.Colour(category_colour)

    # Le message Discord possède déjà son heure. On réserve le timestamp interne aux
    # journaux afin d'alléger toutes les cartes de commandes ordinaires.
    if log_type and embed.timestamp is None:
        embed.timestamp = datetime.now(timezone.utc)

    # La photo de profil configurée sur le compte bot reste l'identité principale.
    # Elle reste dans la petite icône d'auteur ; aucune photo de catégorie n'est jointe.
    avatar = None
    if bot_user is not None:
        avatar = getattr(getattr(bot_user, "display_avatar", None), "url", None)

    current_author = getattr(embed, "author", None)
    if bot_user is not None and not getattr(current_author, "name", None):
        brand_name = CATEGORY_NAMES.get("brand", "SentriX")
        state_label = STATE_LABELS.get(kind)
        author_name = f"{brand_name} • {state_label}" if state_label else brand_name
        if category == "premium" and not state_label:
            author_name = f"{brand_name} • Premium"
        if avatar:
            embed.set_author(name=author_name, icon_url=str(avatar))
        else:
            embed.set_author(name=author_name)

    current_footer = getattr(embed, "footer", None)
    footer_text = getattr(current_footer, "text", None) if current_footer else None
    footer_icon = getattr(current_footer, "icon_url", None) if current_footer else None
    base_footer = _footer_text(guild=guild, requester=requester)
    if footer_text and "Page " in str(footer_text):
        page_text = clean_title(footer_text, fallback="")
        final_footer = f"{page_text} • {base_footer}" if page_text else base_footer
    elif not footer_text or str(footer_text).startswith("SentriX"):
        final_footer = base_footer
    else:
        final_footer = microcopy.polish_text(clip(str(footer_text), 2048))
    if footer_icon:
        embed.set_footer(text=clip(final_footer, 2048), icon_url=footer_icon)
    else:
        embed.set_footer(text=clip(final_footer, 2048))

    fields = list(embed.fields[:25])
    if len(embed.fields) > 25:
        embed.clear_fields()
        for field in fields:
            embed.add_field(name=field.name, value=field.value, inline=field.inline)

    # Le résumé de +setup n'a pas besoin de répéter tous les modules : le menu situé
    # juste dessous les contient déjà. Les trois métriques restantes sont regroupées
    # sur une ligne afin que le panneau garde la hauteur d'un petit centre de tickets.
    if category == "configuration" and "configuration" in str(embed.title or "").casefold():
        summary_parts: list[str] = []
        for index in range(len(embed.fields) - 1, -1, -1):
            field = embed.fields[index]
            field_name = clean_title(field.name).casefold()
            if field_name in {"modules", "module"}:
                embed.remove_field(index)
            elif field_name in {"serveur", "server", "progression", "langue", "language"}:
                label = {
                    "server": "Serveur",
                    "language": "Langue",
                }.get(field_name, display_label(field.name))
                summary_parts.append(f"**{label} :** {microcopy.polish_text(str(field.value))}")
                embed.remove_field(index)
        if summary_parts:
            summary_parts.reverse()
            metrics = " • ".join(summary_parts)
            body = str(embed.description or "").strip()
            embed.description = clip(f"{body}\n\n{metrics}" if body else metrics, 4096)

    for index, field in enumerate(list(embed.fields)):
        # Les champs en Title Case sont plus lisibles que des libellés entièrement en capitales.
        field_name = clean_title(field.name, "Information")
        field_value = microcopy.polish_text(clip(field.value, 1024)) or "—"
        embed.set_field_at(
            index,
            name=clip(field_name, 256),
            value=field_value,
            inline=bool(field.inline),
        )
    return embed


def can_wrap_content(content: Any, kwargs: dict[str, Any]) -> bool:
    if content is None:
        return False
    text = str(content).strip()
    if not text or len(text) > 3900:
        return False
    if any(key in kwargs for key in ("file", "files", "stickers", "poll")):
        return False
    if kwargs.get("embed") is not None or kwargs.get("embeds"):
        return False
    if re.search(r"<@!?&?\d+>|@everyone|@here", text):
        return False
    if text.startswith(("http://", "https://")):
        return False
    return True


def content_embed(
    content: Any,
    *,
    command: Any = None,
    guild: discord.Guild | None = None,
    requester: Any = None,
    bot_user: Any = None,
) -> discord.Embed:
    text = microcopy.polish_text(clip(content, 4096))
    kind = infer_kind(content=text)
    category = infer_category(command=command)
    embed = discord.Embed(description=text)
    return style_embed(
        embed,
        command=command,
        guild=guild,
        requester=requester,
        category=category,
        kind=kind,
        bot_user=bot_user,
    )


def style_view(view: discord.ui.View | None) -> discord.ui.View | None:
    """Uniformise boutons et menus sans toucher aux callbacks persistants."""
    if view is None:
        return None
    primary_rows: set[int] = set()
    for item in getattr(view, "children", []):
        if isinstance(item, discord.ui.Select):
            if item.placeholder:
                placeholder = microcopy.polish_text(str(item.placeholder))
                item.placeholder = clip(placeholder or "Choisir une option…", 150)
            for option in list(getattr(item, "options", []) or []):
                option.label = clip(
                    microcopy.polish_text(str(option.label)),
                    VISUAL_LIMITS["select_label"],
                )
                if option.description:
                    option.description = clip(
                        microcopy.polish_text(str(option.description)),
                        VISUAL_LIMITS["select_description"],
                    )
            continue
        if not isinstance(item, discord.ui.Button):
            continue
        if item.label:
            item.label = clip(
                microcopy.polish_button_label(item.label),
                VISUAL_LIMITS["button_label"],
            )
        if item.style is discord.ButtonStyle.link:
            continue
        label = str(item.label or "").casefold()
        custom_id = str(item.custom_id or "").casefold()
        haystack = f"{label} {custom_id}"
        if any(word in haystack for word in (
            "supprimer", "delete", "fermer", "close", "annuler", "cancel",
            "ban", "reset", "wipe", "retirer", "remove",
        )):
            item.style = discord.ButtonStyle.danger
        elif any(word in haystack for word in (
            "enregistrer", "save", "confirmer", "confirm", "valider", "verify",
            "créer", "create", "envoyer", "send", "activer", "enable",
        )):
            item.style = discord.ButtonStyle.primary
        elif item.style is discord.ButtonStyle.primary:
            # Une vue peut désigner explicitement son action principale : on la conserve.
            item.style = discord.ButtonStyle.primary
        else:
            item.style = discord.ButtonStyle.secondary

        # Un seul appel à l'action principal par rangée. Les autres restent visibles,
        # mais ne concurrencent pas le bouton important sur mobile.
        row = int(getattr(item, "row", None) or 0)
        if item.style is discord.ButtonStyle.primary:
            if row in primary_rows:
                item.style = discord.ButtonStyle.secondary
            else:
                primary_rows.add(row)
    return view


def style_kwargs(
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    *,
    command: Any = None,
    guild: discord.Guild | None = None,
    requester: Any = None,
    bot_user: Any = None,
    allow_content_wrap: bool = False,
    include_brand_asset: bool = False,
    category: str | None = None,
    log_type: str | None = None,
) -> tuple[tuple[Any, ...], dict[str, Any]]:
    """Prépare les arguments d'un send/edit en restant compatible avec discord.py."""
    new_args = list(args)
    new_kwargs = dict(kwargs)

    content = new_kwargs.get("content")
    if content is None and new_args:
        content = new_args[0]

    embed = new_kwargs.get("embed")
    if isinstance(embed, discord.Embed):
        new_kwargs["embed"] = style_embed(
            embed,
            command=command,
            guild=guild,
            requester=requester,
            category=category,
            bot_user=bot_user,
            log_type=log_type,
        )

    embed_list = new_kwargs.get("embeds")
    if embed_list:
        new_kwargs["embeds"] = [
            style_embed(
                item,
                command=command,
                guild=guild,
                requester=requester,
                category=category,
                bot_user=bot_user,
                log_type=log_type,
            ) if isinstance(item, discord.Embed) else item
            for item in embed_list
        ]

    if allow_content_wrap and can_wrap_content(content, new_kwargs):
        wrapped = content_embed(
            content,
            command=command,
            guild=guild,
            requester=requester,
            bot_user=bot_user,
        )
        new_kwargs["embed"] = wrapped
        if new_args:
            new_args[0] = None
            new_kwargs.pop("content", None)
        else:
            new_kwargs["content"] = None

    if "view" in new_kwargs:
        new_kwargs["view"] = style_view(new_kwargs.get("view"))

    if include_brand_asset:
        target_embed = new_kwargs.get("embed")
        if not isinstance(target_embed, discord.Embed):
            candidates = new_kwargs.get("embeds") or []
            target_embed = candidates[0] if candidates and isinstance(candidates[0], discord.Embed) else None
        if isinstance(target_embed, discord.Embed):
            resolved_category = infer_category(
                command=command,
                embed=target_embed,
                hint=category,
            )
            new_kwargs = brand_assets.decorate_send_kwargs(
                new_kwargs,
                embed=target_embed,
                category=resolved_category,
            )
    return tuple(new_args), new_kwargs
