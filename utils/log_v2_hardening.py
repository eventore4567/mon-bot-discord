"""Durcissement ciblé du renderer de logs Components V2.

Objectifs :
- une vignette invalide ne doit jamais faire perdre la bannière ;
- un bouton impossible à convertir ne doit jamais faire perdre la bannière ;
- aucun ``description=`` n'est passé au Thumbnail ;
- les anciennes barres décoratives en texte sont retirées du corps V2 ;
- les étapes A/B/C sont visibles dans Railway pour isoler immédiatement le composant fautif.

Ce module ne monkey-patch PAS ``channel.send`` et n'ajoute aucun fallback embed classique.
"""
from __future__ import annotations

import logging
import re

import discord

from . import wide_logs

logger = logging.getLogger("bot.log-v2-hardening")
_DECORATIVE_LINE_RE = re.compile(r"^[\s━─═—–_\-•·┄┈┉┅┇]{8,}$")
_INSTALLED = False


def _clean_description(value: object) -> str:
    lines: list[str] = []
    for raw in str(value or "").replace("\r", "").splitlines():
        line = raw.strip()
        if line and _DECORATIVE_LINE_RE.fullmatch(line):
            continue
        lines.append(raw)
    return "\n".join(lines).strip()


def _copy_buttons_safe(container: discord.ui.Container, old_view: discord.ui.View | None) -> None:
    """Copie les boutons par groupes ; un groupe invalide est simplement ignoré."""
    if old_view is None:
        logger.warning("SENTRIX V2 PHASE C buttons=none")
        return

    buttons: list[discord.ui.Button] = []
    for item in old_view.children:
        if not isinstance(item, discord.ui.Button):
            continue
        try:
            button = wide_logs._clone_button(item)
        except Exception:
            logger.exception("SENTRIX V2 PHASE C clone_button=failed")
            continue
        if button is not None:
            buttons.append(button)

    if not buttons:
        logger.warning("SENTRIX V2 PHASE C buttons=none_after_clone")
        return

    rows: list[discord.ui.ActionRow] = []
    for start in range(0, len(buttons), 5):
        try:
            rows.append(discord.ui.ActionRow(*buttons[start:start + 5]))
        except Exception:
            logger.exception(
                "SENTRIX V2 PHASE C action_row=failed start=%s count=%s",
                start,
                len(buttons[start:start + 5]),
            )

    if not rows:
        logger.warning("SENTRIX V2 PHASE C buttons=degraded_all_rows_failed")
        return

    try:
        container.add_item(discord.ui.Separator())
        for row in rows:
            container.add_item(row)
        logger.warning("SENTRIX V2 PHASE C buttons=ok rows=%s", len(rows))
    except Exception:
        logger.exception("SENTRIX V2 PHASE C container_add=failed")


def _wide_log_init_safe(
    self,
    embed: discord.Embed,
    banner_filename: str,
    old_view: discord.ui.View | None = None,
    accent: int | None = None,
) -> None:
    """Renderer fail-soft : la bannière reste prioritaire sur vignette et boutons."""
    discord.ui.LayoutView.__init__(self, timeout=None)

    accent_colour = discord.Colour(accent) if accent is not None else None
    container = discord.ui.Container(accent_colour=accent_colour)

    # PHASE A : bannière seule. Si ceci casse, l'échec est réellement MediaGallery/fichier.
    gallery = discord.ui.MediaGallery()
    gallery.add_item(media=f"attachment://{banner_filename}")
    container.add_item(gallery)
    logger.warning("SENTRIX V2 PHASE A banner=ok filename=%s", banner_filename)

    title = wide_logs.safe_text(embed.title or "Journal SentriX")[:256]
    thumbnail = getattr(embed.thumbnail, "url", None)

    # PHASE B : Section + Thumbnail. Aucun description= n'est passé au Thumbnail.
    section_ok = False
    if thumbnail:
        try:
            container.add_item(
                discord.ui.Section(
                    discord.ui.TextDisplay(f"## {title}"),
                    accessory=discord.ui.Thumbnail(str(thumbnail)),
                )
            )
            section_ok = True
            logger.warning("SENTRIX V2 PHASE B thumbnail=ok")
        except Exception:
            logger.exception("SENTRIX V2 PHASE B thumbnail=failed; title_only=1")

    if not section_ok:
        container.add_item(discord.ui.TextDisplay(f"## {title}"))
        if not thumbnail:
            logger.warning("SENTRIX V2 PHASE B thumbnail=none")

    description = _clean_description(wide_logs.safe_text(embed.description))[:900]
    if description:
        container.add_item(discord.ui.TextDisplay(description))

    fields = wide_logs.compact_fields(embed, limit=2200)
    if fields:
        container.add_item(discord.ui.Separator())
        container.add_item(discord.ui.TextDisplay(fields))

    footer = getattr(embed.footer, "text", None)
    if footer:
        container.add_item(discord.ui.Separator())
        container.add_item(discord.ui.TextDisplay(f"-# {wide_logs.safe_text(footer)[:300]}"))

    # PHASE C : boutons. Un problème ici ne doit jamais invalider le reste du Container.
    _copy_buttons_safe(container, old_view)
    self.add_item(container)


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    if getattr(wide_logs.WideLogView, "_sentrix_v2_fail_soft", False):
        _INSTALLED = True
        return

    wide_logs.copy_buttons = _copy_buttons_safe
    wide_logs.WideLogView.__init__ = _wide_log_init_safe
    wide_logs.WideLogView._sentrix_v2_fail_soft = True
    _INSTALLED = True
    logger.info(
        "Logs V2 durcis : Thumbnail sans description, boutons fail-soft, barres décoratives filtrées."
    )


__all__ = ["install"]
