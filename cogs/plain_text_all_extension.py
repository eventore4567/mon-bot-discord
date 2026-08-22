"""Politique visuelle finale SentriX : texte libre + vraies cartes, sans mélange aléatoire."""
from __future__ import annotations

import re

import discord
from discord.ext import commands

from . import plain_text_all_runtime as plain
from .community_v32 import strip_decorative_emoji
from .profile_oxyde_runtime import install as install_clean_profile


# Les commandes de consultation riches gardent une carte. Les actions et réponses courtes
# restent en texte Discord natif. Cela donne une hiérarchie visuelle stable au lieu de tout
# encadrer ou de tout aplatir.
CARD_ROOTS = frozenset({
    "profile",
    "help",
    "userinfo",
    "serverinfo",
    "botinfo",
    "avatar",
    "stats",
    "shop",
    "inventory",
    "economyleaderboard",
    "repleaderboard",
    "leaderboard-levels",
})

_CDN_LINE = re.compile(r"^<?https://(?:cdn|media)\.discordapp\.(?:com|net)/.+>?$", re.I)


def _remove_completion_fallbacks(bot: commands.Bot) -> None:
    """Supprime les anciens accusés automatiques qui créaient une deuxième réponse."""
    targets = {
        "on_command_completion": {"ensure_prefix_command_response"},
        "on_app_command_completion": {"ensure_slash_command_response"},
    }
    for event_name, names in targets.items():
        listeners = list(getattr(bot, "extra_events", {}).get(event_name, []))
        for listener in listeners:
            if getattr(listener, "__name__", "") in names:
                bot.remove_listener(listener, event_name)


def _install_clean_text_conversion() -> None:
    """Nettoie et aère le contenu converti depuis les anciens embeds."""
    def clean(value) -> str:
        text = str(value or "").replace("**", "").strip()
        text = strip_decorative_emoji(text)
        text = re.sub(r"[ \t]{2,}", " ", text)
        # Espacement stable autour des deux-points, sans coller les valeurs.
        text = re.sub(r"[ \t]*:[ \t]*", " : ", text)
        # Pas de cinq lignes vides, mais on conserve les vrais paragraphes des réponses longues.
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    def embed_to_text(embed) -> str:
        if not isinstance(embed, discord.Embed):
            return ""

        sections: list[str] = []
        title = clean(embed.title)
        description = clean(embed.description)

        generic_titles = {
            "information", "succès", "succes", "erreur", "avertissement",
            "action terminée", "action terminee", "commande exécutée", "commande executee",
            "sentrix / utilitaires", "sentrix / économie", "sentrix / economie",
            "sentrix / modération", "sentrix / moderation",
            "sentrix / intelligence artificielle",
        }
        if title and title.casefold() not in generic_titles and not title.casefold().startswith("sentrix /"):
            sections.append(title)
        if description:
            sections.append(description)

        field_lines: list[str] = []
        for field in list(embed.fields):
            name = clean(field.name)
            value = clean(field.value)
            if not value:
                continue
            if name and name.casefold() not in {"information", "détail", "detail"}:
                field_lines.append(f"{name} : {value}")
            else:
                field_lines.append(value)
        if field_lines:
            sections.append("\n".join(field_lines))

        # Une image/PP d'embed ne devient jamais une URL brute dans une réponse texte.
        cleaned_sections: list[str] = []
        for section in sections:
            lines = [line for line in section.splitlines() if not _CDN_LINE.match(line.strip())]
            value = "\n".join(lines).strip()
            if value:
                cleaned_sections.append(value)
        return "\n".join(cleaned_sections).strip()

    plain._clean = clean
    plain._embed_to_text = embed_to_text
    plain.RICH_ROOTS = frozenset(set(plain.RICH_ROOTS) | set(CARD_ROOTS))


def _apply(bot: commands.Bot) -> None:
    _install_clean_text_conversion()
    _remove_completion_fallbacks(bot)
    plain.install(bot)
    install_clean_profile(bot)


async def setup(bot: commands.Bot) -> None:
    _apply(bot)

    if getattr(bot, "_sentrix_plain_text_ready_listener", False):
        return

    async def apply_visual_policy_when_ready():
        _apply(bot)

    bot.add_listener(apply_visual_policy_when_ready, "on_ready")
    bot._sentrix_plain_text_ready_listener = True
