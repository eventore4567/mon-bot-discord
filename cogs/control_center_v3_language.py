"""Pont FR/EN final pour le Control Center V3.

Le Control Center V3 remplace le renderer du Setup officiel après l'installation du
pont historique. Cette couche légère rebranche donc la langue sur le renderer final,
sans restaurer l'ancienne interface ni ajouter une catégorie de configuration.
"""
from __future__ import annotations

import logging

from discord.ext import commands

from . import setup_control_center
from .language_official_bridge import (
    OfficialLanguageSelect,
    _english,
    _is_english,
    _translate_component,
)

logger = logging.getLogger("bot.control-center-v3-language")


def install(bot: commands.Bot) -> None:
    view_cls = setup_control_center.SetupView
    if getattr(view_cls, "_sentrix_control_center_v3_language", False):
        return

    current_render = view_cls.render
    current_build_embed = view_cls.build_embed

    def render(self) -> None:
        current_render(self)
        # La langue reste un réglage transversal : elle n'occupe aucune page/module.
        if getattr(self, "category", None) is None:
            self.add_item(OfficialLanguageSelect(self))
        if _is_english(self):
            for item in self.children:
                _translate_component(item)

    async def build_embed(self):
        embed = await current_build_embed(self)
        if not _is_english(self):
            return embed
        if embed.title:
            embed.title = _english(embed.title)
        if embed.description:
            embed.description = _english(embed.description)
        for index, field in enumerate(list(embed.fields)):
            embed.set_field_at(
                index,
                name=_english(field.name) or field.name,
                value=_english(field.value) or field.value,
                inline=field.inline,
            )
        if embed.footer and embed.footer.text:
            embed.set_footer(
                text=_english(embed.footer.text),
                icon_url=embed.footer.icon_url or None,
            )
        return embed

    view_cls.render = render
    view_cls.build_embed = build_embed
    view_cls._sentrix_control_center_v3_language = True
    # Les audits historiques utilisent ces marqueurs comme contrat de compatibilité.
    view_cls._sentrix_official_language_bridge = True
    view_cls._sentrix_language_payload_guard = True
    bot._sentrix_control_center_v3_language = True
    logger.info("FR/EN rebranché sur le renderer final Control Center V3.")


__all__ = ["install"]
