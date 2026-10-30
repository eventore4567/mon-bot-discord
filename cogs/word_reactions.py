"""Réactions automatiques à des mots entiers, sans écouteur on_message supplémentaire."""
from __future__ import annotations

import re
import logging
import time

import discord
from discord.ext import commands

from utils.text_normalization import normaliser
from utils import sentrix_panels as panels

logger = logging.getLogger("bot.wordreact")
SCHEMA = """
CREATE TABLE IF NOT EXISTS word_reactions (
    guild_id INTEGER NOT NULL,
    word TEXT NOT NULL,
    emoji TEXT NOT NULL,
    PRIMARY KEY (guild_id, word)
)
"""
WORD_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,31}$")
_CACHE: dict[int, tuple[float, list]] = {}


def matches(text: str, word: str) -> bool:
    normalized = normaliser(text)
    token = normaliser(word)
    return bool(token and re.search(r"(?<![a-z0-9])" + re.escape(token) + r"(?![a-z0-9])", normalized))


async def react_for_message(bot, message: discord.Message) -> bool:
    if message.guild is None or message.author.bot or not message.content:
        return False
    cached = _CACHE.get(message.guild.id)
    if cached is None or time.monotonic() - cached[0] >= 60:
        rows = list(await bot.db.fetchall(
            "SELECT word,emoji FROM word_reactions WHERE guild_id=? ORDER BY word",
            (message.guild.id,),
        ))
        _CACHE[message.guild.id] = (time.monotonic(), rows)
    else:
        rows = cached[1]
    for row in rows:
        if not matches(message.content, row["word"]):
            continue
        try:
            emoji = discord.PartialEmoji.from_str(str(row["emoji"]))
            await message.add_reaction(emoji if emoji.id else emoji.name)
        except (discord.Forbidden, discord.HTTPException, ValueError):
            logger.debug("Réaction automatique refusée dans %s", message.guild.id)
        return True  # Au maximum UNE réaction par message.
    return False


def panel(title, subtitle, kind="info"):
    return panels.Panneau(titre=title, sous_titre=subtitle, kind=kind)


class WordReactions(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        await self.bot.db.execute(SCHEMA)

    @commands.group(name="wordreact", invoke_without_command=True)
    @commands.guild_only()
    async def wordreact(self, ctx):
        await self.wordreact_list(ctx)

    @wordreact.command(name="add", help="Associer un emoji à un mot.")
    async def wordreact_add(self, ctx, mot: str, emoji: str):
        word = normaliser(mot)
        if not WORD_RE.fullmatch(word):
            return await panels.envoyer(ctx, panel("Mot invalide", "Utilisez un seul mot de 2 à 32 caractères.", "danger"))
        emoji = emoji.strip()
        if not 1 <= len(emoji) <= 80:
            return await panels.envoyer(ctx, panel("Emoji invalide", "Indiquez un emoji Unicode ou personnalisé.", "danger"))
        existing = await self.bot.db.fetchone(
            "SELECT word FROM word_reactions WHERE guild_id=? AND word=?", (ctx.guild.id, word),
        )
        if not existing:
            count = await self.bot.db.fetchone("SELECT COUNT(*) AS total FROM word_reactions WHERE guild_id=?", (ctx.guild.id,))
            if count and count["total"] >= 30:
                return await panels.envoyer(ctx, panel("Limite atteinte", "Maximum 30 mots par serveur.", "warning"))
        await self.bot.db.execute(
            "INSERT INTO word_reactions(guild_id,word,emoji) VALUES (?,?,?) "
            "ON CONFLICT(guild_id,word) DO UPDATE SET emoji=excluded.emoji",
            (ctx.guild.id, word, emoji),
        )
        _CACHE.pop(ctx.guild.id, None)
        await panels.envoyer(ctx, panel("Réaction enregistrée", f"Le mot {word} déclenchera désormais une réaction.", "success"))

    @wordreact.command(name="remove", help="Retirer une réaction de mot.")
    async def wordreact_remove(self, ctx, mot: str):
        word = normaliser(mot)
        await self.bot.db.execute("DELETE FROM word_reactions WHERE guild_id=? AND word=?", (ctx.guild.id, word))
        _CACHE.pop(ctx.guild.id, None)
        await panels.envoyer(ctx, panel("Réaction retirée", f"La règle {word} a été supprimée.", "success"))

    @wordreact.command(name="list", help="Lister les mots avec réactions.")
    async def wordreact_list(self, ctx):
        rows = await self.bot.db.fetchall(
            "SELECT word,emoji FROM word_reactions WHERE guild_id=? ORDER BY word LIMIT 30", (ctx.guild.id,),
        )
        text = ", ".join(str(r["word"]) for r in rows) if rows else "Aucune réaction configurée."
        await panels.envoyer(ctx, panel("Réactions de mots", text))


async def setup(bot):
    await bot.add_cog(WordReactions(bot))
