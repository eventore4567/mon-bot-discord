"""Garde de largeur des embeds de logs SentriX.

Reprend le double système du prototype fourni : image 1024 px + champ visuellement vide
qui conserve une carte large pendant le chargement de la bannière.
"""
from __future__ import annotations

from utils import log_banners

SPACER_FIELD_NAME = "\u200b"
SPACER_FIELD_VALUE = "\u200b" * 50 + "\u3000" * 25


def install() -> None:
    if getattr(log_banners, "_sentrix_wide_guard", False):
        return

    original_render = log_banners._render_embed

    def render_with_width_guard(log_type, source):
        rendered, style = original_render(log_type, source)
        already_present = any(
            str(field.name) == SPACER_FIELD_NAME
            and str(field.value) == SPACER_FIELD_VALUE
            for field in rendered.fields
        )
        if not already_present and len(rendered.fields) < 25:
            rendered.add_field(
                name=SPACER_FIELD_NAME,
                value=SPACER_FIELD_VALUE,
                inline=False,
            )
        return rendered, style

    log_banners._render_embed = render_with_width_guard
    log_banners._sentrix_wide_guard = True
