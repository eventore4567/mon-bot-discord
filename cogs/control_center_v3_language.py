"""Pont FR/EN final pour le Control Center V3/V4 + vérification V5.

Ordre déterministe :
1. V4 enrichit les pages métier du Setup sans casser le contrat public V3 ;
2. V5 remplace le moteur de vérification par les 40 signaux adaptatifs ;
3. la calibration collecte jusqu'à 1 000 vraies évaluations ;
4. la langue enveloppe le renderer final ;
5. la finition UI reste la toute dernière couche (toggle unique + tickets dynamiques) ;
6. les logs vocaux V2 propres restent réinstallés en dernier.
"""
from __future__ import annotations

import logging

import discord
from discord.ext import commands

from . import automatic_verification_v5
from . import control_center_v3
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
from .voice_logs_v2 import install as install_voice_logs_v2

logger = logging.getLogger("bot.control-center-v3-language")


class _V4CategorySelectCompat(control_center_v3.V3CategorySelect):
    """Navigation V4 qui étend réellement le contrat public V3.

    On hérite uniquement de ``V3CategorySelect``. L'ancien héritage multiple
    V4+V3 faisait suivre le ``super()`` du constructeur V4 vers le constructeur
    V3 avec des arguments incompatibles. Cette version conserve donc le type V3,
    ses valeurs publiques historiques et ajoute seulement les sous-pages V4.
    """

    def __init__(self, owner):
        super().__init__(owner)
        self.placeholder = "Choisir une page du Control Center"

        # La valeur publique historique reste stable pour les vues persistantes,
        # les audits et le pont de langue. Seul son libellé décrit le moteur actuel.
        for option in self.options:
            if str(option.value) == "security_verification":
                option.label = "Sécurité — Vérification auto"
                option.description = "40 signaux adaptatifs, seuil calibré et honeypot"
                break

        extras = (
            ("tickets_center", "Tickets — Ticket Center", "Panels, types, formulaires, boutons staff et transcripts"),
            ("welcome_messages", "Accueil — Messages", "Textes, variables et image de bienvenue/départ"),
            ("levels_economy", "Niveaux — Économie", "Monnaie et paramètres économie"),
            ("ai_natural", "IA — Conversation naturelle", "Déclencheur sentrix ..., limites et mémoire"),
        )
        existing = {str(option.value) for option in self.options}
        for value, label, description in extras:
            if value not in existing and len(self.options) < 25:
                self.options.append(
                    discord.SelectOption(label=label, value=value, description=description[:100])
                )

    async def callback(self, interaction: discord.Interaction):
        value = self.values[0]
        self.owner._v3_subpage = None
        self.owner._v4_subpage = None
        mapping = {
            "security_verification": ("security", "auto_verification"),
            "tickets_center": ("tickets", "ticket_center"),
            "welcome_messages": ("welcome", "messages"),
            "roles_panel": ("roles", "panel"),
            "levels_economy": ("levels", "economy"),
            "ai_natural": ("ai", "natural"),
        }
        if value == "__home__":
            self.owner.category = None
        elif value in mapping:
            self.owner.category, self.owner._v4_subpage = mapping[value]
            if value == "roles_panel":
                self.owner._v3_subpage = "panel"
        else:
            self.owner.category = value
        self.owner.selected_log = None
        self.owner.selected_ticket = None
        self.owner.selected_notification = None
        await self.owner.refresh(interaction)


def _install_v4_v3_compat() -> None:
    current = control_center_v4.V4CategorySelect
    if issubclass(current, control_center_v3.V3CategorySelect):
        return
    control_center_v4.V4CategorySelect = _V4CategorySelectCompat


async def install(bot: commands.Bot) -> None:
    # V4 garde les pages métier tout en restant reconnaissable comme navigation V3.
    _install_v4_v3_compat()
    await control_center_v4.install(bot)
    await automatic_verification_v5.install(bot)
    await verification_calibration_v5.install(bot)

    view_cls = setup_control_center.SetupView
    if getattr(view_cls, "_sentrix_control_center_v3_language", False):
        # Même lors d'une réinstallation runtime, les deux finitions doivent rester
        # extérieures : Setup propre + listener vocal V2 propre.
        install_control_center_v3_ui_fix(bot)
        install_voice_logs_v2(bot)
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

    # Dernières autorités runtime : évitent de réintroduire le gros toggle historique
    # et le listener vocal générique après les wrappers V4/V5/langue.
    install_control_center_v3_ui_fix(bot)
    install_voice_logs_v2(bot)
    logger.info(
        "FR/EN rebranché sur Control Center V4 compatible V3 + V5 ; calibration 1000 + finition UI + logs vocaux V2 actifs."
    )


__all__ = ["install"]
