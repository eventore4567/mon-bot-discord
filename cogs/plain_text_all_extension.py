"""Extension Railway finale : texte natif propre pour toutes les commandes ordinaires."""
from __future__ import annotations

import re

import discord
from discord.ext import commands

from . import plain_text_all_runtime as plain
from .community_v32 import strip_decorative_emoji


_CDN_LINE = re.compile(r"^<?https://(?:cdn|media)\.discordapp\.(?:com|net)/.+>?$", re.I)


def _remove_completion_fallbacks(bot: commands.Bot) -> None:
    """Supprime les anciens accusés automatiques qui créaient une 2e réponse."""
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
    """Nettoie le contenu converti depuis les anciens embeds."""
    def clean(value) -> str:
        text = str(value or "").replace("**", "").strip()
        text = strip_decorative_emoji(text)
        text = re.sub(r"[ \t]{2,}", " ", text)
        return text.strip()

    def embed_to_text(embed) -> str:
        if not isinstance(embed, discord.Embed):
            return ""

        lines: list[str] = []
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
            lines.append(title)
        if description:
            lines.append(description)

        for field in list(embed.fields):
            name = clean(field.name)
            value = clean(field.value)
            if not value:
                continue
            if name and name.casefold() not in {"information", "détail", "detail"}:
                lines.append(f"{name}: {value}")
            else:
                lines.append(value)

        # Les thumbnails/avatars n'ont rien à faire sous forme de lien brut dans une réponse texte.
        cleaned_lines = []
        for line in lines:
            stripped = line.strip()
            if _CDN_LINE.match(stripped):
                continue
            cleaned_lines.append(line)
        return "\n".join(cleaned_lines).strip()

    plain._clean = clean
    plain._embed_to_text = embed_to_text


def _apply(bot: commands.Bot) -> None:
    _install_clean_text_conversion()
    _remove_completion_fallbacks(bot)
    plain.install(bot)


async def setup(bot: commands.Bot) -> None:
    _apply(bot)

    if getattr(bot, "_sentrix_plain_text_ready_listener", False):
        return

    async def apply_plain_text_when_ready():
        _apply(bot)

    bot.add_listener(apply_plain_text_when_ready, "on_ready")
    bot._sentrix_plain_text_ready_listener = True
