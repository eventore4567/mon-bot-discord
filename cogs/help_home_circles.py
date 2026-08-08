"""Rend uniquement l'accueil de +help sobre avec des puces noires."""

from __future__ import annotations

import logging

import discord
from discord.ext import commands

from .help_category_rework import install as install_help_category_rework

logger = logging.getLogger("bot.help-home-circles")
_INSTALLED = False
_CIRCLE = "●"
_SECTION_NAMES = {"Essentiels", "Communauté", "Administration"}


def _remove_leading_symbol(value: str) -> str:
    """Retire un emoji ou symbole placé avant un libellé, sans toucher au texte."""
    text = str(value or "").strip()
    if text.startswith(f"{_CIRCLE} "):
        text = text[len(_CIRCLE) + 1 :].lstrip()
    first, separator, rest = text.partition(" ")
    if separator and first and not any(character.isalnum() for character in first):
        return rest.strip()
    return text


def _circle_label(value: str) -> str:
    clean = _remove_leading_symbol(value)
    return f"{_CIRCLE} {clean}" if clean else _CIRCLE


def _circle_category_lines(value: str) -> str:
    lines: list[str] = []
    for raw_line in str(value or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        # Les catégories sont en gras. On supprime tout symbole situé avant le premier
        # marqueur Markdown, puis on ajoute une seule puce noire.
        bold_index = line.find("**")
        if bold_index >= 0:
            line = line[bold_index:]
        else:
            line = _remove_leading_symbol(line)
        lines.append(_circle_label(line))
    return "\n".join(lines)


def _apply_circle_home(embed: discord.Embed) -> discord.Embed:
    """Modifie l'embed en place et reste sûre lorsqu'elle est appelée deux fois."""
    if embed.title:
        embed.title = _remove_leading_symbol(str(embed.title))

    for index, field in enumerate(list(embed.fields)):
        clean_name = _remove_leading_symbol(str(field.name))
        new_value = str(field.value)
        if clean_name in _SECTION_NAMES:
            new_value = _circle_category_lines(new_value)
        embed.set_field_at(
            index,
            name=_circle_label(clean_name),
            value=new_value,
            inline=bool(field.inline),
        )
    return embed


def _clean_home_components(view: discord.ui.View) -> None:
    """Retire aussi les emojis du menu et des boutons sans pouvoir casser +help."""
    for item in view.children:
        try:
            if isinstance(item, discord.ui.Select):
                item.placeholder = "Choisissez une catégorie..."
                for option in item.options:
                    option.label = _circle_label(option.label)[:100]
                    option.emoji = None
            elif isinstance(item, discord.ui.Button):
                if item.label:
                    item.label = _circle_label(item.label)[:80]
                item.emoji = None
        except Exception:
            # Une différence de version de discord.py ne doit jamais empêcher l'aide
            # principale de s'afficher. L'embed reste nettoyé même si un composant refuse.
            logger.debug("Composant de l'accueil help non modifiable.", exc_info=True)


def install(bot: commands.Bot) -> None:
    """Installe les catégories canoniques puis le style sobre de +help."""
    global _INSTALLED
    if _INSTALLED:
        return

    # Le classement doit être en place avant que le dashboard et le style n'enveloppent
    # l'accueil. Cela garantit que menu, recherche et pages utilisent les mêmes catégories.
    install_help_category_rework(bot)

    from . import help_complete, utility

    original_module_home = help_complete._home_embed

    def module_home_with_circles(*args, **kwargs):
        return _apply_circle_home(original_module_home(*args, **kwargs))

    help_complete._home_embed = module_home_with_circles

    # Le dashboard enveloppe déjà build_help_home et ajoute son propre champ. Cette
    # seconde couche nettoie donc également ce champ sans supprimer le lien.
    original_utility_home = utility.build_help_home

    def utility_home_with_circles(*args, **kwargs):
        return _apply_circle_home(original_utility_home(*args, **kwargs))

    utility.build_help_home = utility_home_with_circles

    original_help_view_init = utility.HelpView.__init__

    def help_view_init(self, *args, **kwargs):
        original_help_view_init(self, *args, **kwargs)
        _clean_home_components(self)

    utility.HelpView.__init__ = help_view_init

    _INSTALLED = True
    logger.info("Accueil de +help simplifié : catégories canoniques et cercles noirs actifs.")
