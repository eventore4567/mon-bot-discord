"""Pont FR/EN final pour le Control Center V3/V4 + vérification V5.

Ordre déterministe :
1. V4 enrichit les pages métier du Setup ;
2. V5 remplace le moteur de vérification par les 40 signaux adaptatifs ;
3. la calibration collecte jusqu'à 1 000 vraies évaluations ;
4. la langue enveloppe le renderer final ;
5. la finition UI reste la toute dernière couche (toggle unique + tickets dynamiques).
"""
from __future__ import annotations

import logging

from discord.ext import commands

from . import automatic_verification_v5
from . import control_center_v4
from . import setup_control_center
from . import verification_calibration_v5
from .control_center_v3_ui_fix import install as install_control_center_v3_ui_fix
from .language_official_bridge import (
    OfficialLanguageSelect,
    _english,
    _is_english,
    _translate_component,
)

logger = logging.getLogger("bot.control-center-v3-language")


async def install(bot: commands.Bot) -> None:
    # V4 garde les pages métier ; V5 remplace uniquement le moteur de vérification.
    await control_center_v4.install(bot)
    await automatic_verification_v5.install(bot)
    await verification_calibration_v5.install(bot)

    view_cls = setup_control_center.SetupView
    if getattr(view_cls, "_sentrix_control_center_v3_language", False):
        # Même lors d'une réinstallation runtime, la finition doit rester extérieure.
        install_control_center_v3_ui_fix(bot)
        return

    current_render = view_cls.render
    current_build_embed = view_cls.build_embed

    def render(self) -> None:
        current_render(self)
        if getattr(self, "category", None) is None:
            has_language_select = any(
                isinstance(item, OfficialLanguageSelect) for item in self.children
            )
            if not has_language_select:
                try:
                    self.add_item(OfficialLanguageSelect(self))
                except ValueError:
                    pass
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
    view_cls._sentrix_official_language_bridge = True
    view_cls._sentrix_language_payload_guard = True
    bot._sentrix_control_center_v3_language = True
    bot._sentrix_control_center_v4_language = True

    # Dernière autorité visuelle : évite de réintroduire le gros toggle historique et
    # restaure les contrôles dynamiques Tickets/Notifications après les wrappers V4/V5.
    install_control_center_v3_ui_fix(bot)
    logger.info(
        "FR/EN rebranché sur Control Center V4 + V5 ; calibration 1000 + finition UI finales."
    )


__all__ = ["install"]
