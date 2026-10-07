"""Traduction — /translate text et le menu contextuel « Translate Message ».

La logique vit dans services/translation.py (fournisseur, langues, délais, codes
d'erreur), testé sans bot. Ce cog expose trois portes vers le même service :

- `+translate <langue> <texte>` en préfixe ;
- `/translate text`, commande native avec autocomplétion des langues ;
- clic droit sur un message > Applications > « Translate Message » : traduit le
  message dans la langue de TON Discord, en réponse privée. C'est l'équivalent
  d'un bouton « Traduire » sous chaque message, sans ajouter de commande slash.

Une seule décision de permission (`access_matrix`, commande « translate »), et
aucune mention ne peut sonner : le texte traduit d'un message contenant
@everyone reste muet.
"""
from __future__ import annotations

import logging
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from services import translation as tr
from utils import embeds
from utils import sentrix_panels as panels

logger = logging.getLogger("bot.translation")

MAX_SHOWN = 3500

TEXTS: dict[str, dict[str, Any]] = {
    "fr": {
        "title": "Traduction",
        "to": "vers",
        "original": "Message d'origine",
        "errors": {
            "empty": "Il n'y a rien à traduire.",
            "too_long": f"Le texte est trop long : {tr.MAX_LENGTH} caractères au maximum.",
            "missing_language": "Indiquez la langue cible, par exemple `en`, `es` ou `de`.",
            "unsupported_language": "Cette langue n'est pas prise en charge. Essayez `en`, `es`, `de`…",
            "unavailable": "Le service de traduction ne répond pas. Réessayez dans un instant.",
        },
        "no_text": "Ce message ne contient pas de texte à traduire.",
        "guild_only": "Cette commande s'utilise sur un serveur.",
    },
    "en": {
        "title": "Translation",
        "to": "to",
        "original": "Original message",
        "errors": {
            "empty": "There is nothing to translate.",
            "too_long": f"The text is too long: {tr.MAX_LENGTH} characters at most.",
            "missing_language": "Give the target language, for example `en`, `es` or `de`.",
            "unsupported_language": "This language is not supported. Try `en`, `es`, `de`…",
            "unavailable": "The translation service is not responding. Try again shortly.",
        },
        "no_text": "This message has no text to translate.",
        "guild_only": "This command works in a server.",
    },
}


async def lang_of(bot: Any, guild_id: int | None) -> dict[str, Any]:
    try:
        from cogs import language_runtime

        code = await language_runtime.get_language(bot, guild_id)
    except Exception:  # noqa: BLE001 — la langue ne doit jamais bloquer une traduction
        code = "fr"
    return TEXTS.get(code, TEXTS["fr"])


def _shown(text: str) -> str:
    text = str(text or "")
    return text if len(text) <= MAX_SHOWN else text[: MAX_SHOWN - 1].rstrip() + "…"


def render(result: tr.Translation, t: dict[str, Any], *, original_url: str | None = None) -> panels.Panneau:
    name = tr.LANGUAGES.get(result.target, result.target)
    sections = [panels.Section(f"{t['title']} {t['to']} {name}", texte=_shown(result.text))]
    if original_url:
        sections.append(panels.Section(t["original"], texte=original_url))
    return panels.Panneau(titre=t["title"], sections=sections, kind="info", pied="SentriX • Translation")


async def _allowed(bot: Any, interaction: discord.Interaction) -> bool:
    from utils import access_matrix

    decision = await access_matrix.evaluate(
        bot, command_name="translate", author=interaction.user, guild=interaction.guild
    )
    if decision.allowed:
        return True
    await panels.envoyer(
        interaction, panels.depuis_embed(embeds.error(decision.message or decision.reason)), ephemere=True
    )
    return False


class Translation(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.menu = app_commands.ContextMenu(name="Translate Message", callback=self.translate_message)

    async def cog_load(self) -> None:
        self.bot.tree.add_command(self.menu, override=True)

    async def cog_unload(self) -> None:
        self.bot.tree.remove_command(self.menu.name, type=self.menu.type)

    async def _translate(self, guild_id: int | None, text: str, target: str, source: str = "auto"):
        t = await lang_of(self.bot, guild_id)
        try:
            return await tr.translate(text, target, source=source), t
        except tr.TranslationError as error:
            return t["errors"].get(error.code, t["errors"]["unavailable"]), t

    async def translate_message(self, interaction: discord.Interaction, message: discord.Message) -> None:
        """Menu contextuel : traduit un message dans la langue de l'utilisateur."""
        t = await lang_of(self.bot, getattr(interaction.guild, "id", None))
        if interaction.guild is None:
            return await panels.envoyer(interaction, panels.depuis_embed(embeds.error(t["guild_only"])), ephemere=True)
        if not await _allowed(self.bot, interaction):
            return
        text = (message.content or "").strip()
        if not text:
            return await panels.envoyer(interaction, panels.depuis_embed(embeds.error(t["no_text"])), ephemere=True)
        await interaction.response.defer(ephemeral=True, thinking=True)
        result, t = await self._translate(interaction.guild.id, text, tr.locale_to_language(interaction.locale))
        if isinstance(result, str):
            return await panels.envoyer(interaction, panels.depuis_embed(embeds.error(result)), ephemere=True)
        await panels.envoyer(interaction, render(result, t, original_url=message.jump_url), ephemere=True)

    @commands.command(name="translate", help="Traduire un texte : +translate <langue> <texte>.")
    async def translate(self, ctx: commands.Context, langue: str, *, texte: str) -> None:
        result, t = await self._translate(getattr(ctx.guild, "id", None), texte, langue)
        if isinstance(result, str):
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error(result)))
        await panels.envoyer(ctx, render(result, t))


def _native_translate(bot: commands.Bot) -> app_commands.Command:
    """/translate text, avec autocomplétion des langues."""

    async def callback(interaction: discord.Interaction, language: str, text: str, source: str = "auto") -> None:
        cog = bot.get_cog("Translation")
        if cog is None:
            return
        if interaction.guild is not None and not await _allowed(bot, interaction):
            return
        await interaction.response.defer(thinking=True)
        result, t = await cog._translate(getattr(interaction.guild, "id", None), text, language, source)
        if isinstance(result, str):
            return await panels.envoyer(interaction, panels.depuis_embed(embeds.error(result)))
        await panels.envoyer(interaction, render(result, t))

    callback._sentrix_original_command = "translate"
    command = app_commands.Command(name="text", description="Translate a text.", callback=callback)

    @command.autocomplete("language")
    async def _languages(_interaction: discord.Interaction, current: str):
        return [app_commands.Choice(name=label, value=code) for label, code in tr.suggestions(current)]

    @command.autocomplete("source")
    async def _sources(_interaction: discord.Interaction, current: str):
        choices = [app_commands.Choice(name="Auto-detect (auto)", value="auto")]
        choices += [app_commands.Choice(name=label, value=code) for label, code in tr.suggestions(current)]
        return choices[:25]

    return command


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Translation(bot))
    from utils import slash_catalog

    slash_catalog.register_native("translate", _native_translate)
