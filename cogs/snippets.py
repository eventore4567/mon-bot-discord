"""Messages enregistrés du staff, pilotés avec /snippet.

Ne crée aucun nouvel écouteur, n'autorise aucune mention et suit le style SentriX.
"""
from __future__ import annotations

import re
import time
import logging

import discord
from discord.ext import commands
from utils import sentrix_panels as panels

logger = logging.getLogger("bot.snippets")
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,31}$")

SCHEMA = """
CREATE TABLE IF NOT EXISTS snippets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    content TEXT NOT NULL,
    created_by INTEGER NOT NULL,
    created_at INTEGER NOT NULL,
    UNIQUE (guild_id, name)
)
"""


def normal_name(value: str) -> str | None:
    value = str(value or "").strip().casefold()
    return value if NAME_RE.fullmatch(value) else None


def response(title: str, description: str, *, kind: str = "info"):
    return panels.Panneau(titre=title, sous_titre=description, kind=kind)


class Snippets(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        await self.bot.db.execute(SCHEMA)

    @commands.group(name="snippet", invoke_without_command=True)
    @commands.guild_only()
    async def snippet(self, ctx):
        await self.snippet_list(ctx)

    @snippet.command(name="create", help="Enregistrer un texte réutilisable par le staff.")
    async def snippet_create(self, ctx, nom: str, *, texte: str):
        name = normal_name(nom)
        if name is None:
            return await panels.envoyer(ctx, response("Nom invalide", "Utilisez 2 à 32 lettres minuscules, chiffres, tirets ou underscores.", kind="danger"))
        content = str(texte).strip()
        if not 1 <= len(content) <= 1700:
            return await panels.envoyer(ctx, response("Texte invalide", "Le message doit contenir entre 1 et 1 700 caractères.", kind="danger"))
        existing = await self.bot.db.fetchone(
            "SELECT id FROM snippets WHERE guild_id=? AND name=?", (ctx.guild.id, name),
        )
        if existing:
            await self.bot.db.execute(
                "UPDATE snippets SET content=?, created_by=?, created_at=? WHERE guild_id=? AND name=?",
                (content, ctx.author.id, int(time.time()), ctx.guild.id, name),
            )
        else:
            count = await self.bot.db.fetchone("SELECT COUNT(*) AS total FROM snippets WHERE guild_id=?", (ctx.guild.id,))
            if count and count["total"] >= 50:
                return await panels.envoyer(ctx, response("Limite atteinte", "Ce serveur possède déjà 50 snippets.", kind="warning"))
            await self.bot.db.execute(
                "INSERT INTO snippets (guild_id,name,content,created_by,created_at) VALUES (?,?,?,?,?)",
                (ctx.guild.id, name, content, ctx.author.id, int(time.time())),
            )
        await panels.envoyer(ctx, response("Snippet enregistré", f"Le texte {name} est disponible avec /snippet send.", kind="success"))

    @snippet.command(name="send", help="Publier un message enregistré dans le salon actuel.")
    async def snippet_send(self, ctx, nom: str):
        name = normal_name(nom)
        row = await self.bot.db.fetchone(
            "SELECT content FROM snippets WHERE guild_id=? AND name=?",
            (ctx.guild.id, name or ""),
        )
        if not row:
            return await panels.envoyer(ctx, response("Snippet introuvable", "Vérifiez le nom avec /snippet list.", kind="warning"))
        try:
            await ctx.channel.send(str(row["content"]), allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException:
            return await panels.envoyer(ctx, response("Envoi impossible", "SentriX ne peut pas publier dans ce salon.", kind="danger"))
        # La confirmation n'ajoute aucune notification.
        if ctx.interaction:
            await ctx.send("Snippet publié.", ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    @snippet.command(name="list", help="Lister les messages enregistrés du serveur.")
    async def snippet_list(self, ctx):
        rows = await self.bot.db.fetchall(
            "SELECT name FROM snippets WHERE guild_id=? ORDER BY name LIMIT 50", (ctx.guild.id,),
        )
        names = ", ".join(str(r["name"]) for r in rows) if rows else "Aucun snippet enregistré."
        await panels.envoyer(ctx, response("Snippets du serveur", names))

    @snippet.command(name="delete", help="Supprimer un message enregistré.")
    async def snippet_delete(self, ctx, nom: str):
        name = normal_name(nom)
        row = await self.bot.db.fetchone(
            "SELECT id FROM snippets WHERE guild_id=? AND name=?", (ctx.guild.id, name or ""),
        )
        if not row:
            return await panels.envoyer(ctx, response("Snippet introuvable", "Aucun texte enregistré sous ce nom.", kind="warning"))
        await self.bot.db.execute("DELETE FROM snippets WHERE guild_id=? AND name=?", (ctx.guild.id, name))
        await panels.envoyer(ctx, response("Snippet supprimé", f"Le texte {name} a été supprimé.", kind="success"))


async def setup(bot):
    await bot.add_cog(Snippets(bot))
