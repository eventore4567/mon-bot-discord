"""Interface publique « Mots interdits » pour SentriX.

Conserve le moteur AutoMod existant et remplace les anciens noms blacklist dans
l'interface publique. Les anciens noms restent cachés pour compatibilité interne.
"""
from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from utils import checks, embeds
from utils import sentrix_panels as panels

logger = logging.getLogger("bot.forbidden-words-ui")

PUBLIC_FILTER_MESSAGE = "votre message a été censuré, car il contenait un mot interdit sur le serveur."
NATIVE_FILTER_MESSAGE = "Votre message a été censuré, car il contenait un mot interdit sur le serveur."


class ForbiddenWordsUI(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._patched = False

    async def cog_load(self):
        self._patch_runtime()

    def _patch_runtime(self) -> None:
        automod = self.bot.get_cog("Automod")
        if automod is None or self._patched:
            return

        original = automod._public_automod_message

        def public_message(filter_name: str, reason: str) -> str:
            if filter_name == "blacklist_word":
                return PUBLIC_FILTER_MESSAGE
            return original(filter_name, reason)

        automod._public_automod_message = public_message

        try:
            from cogs import automod as automod_module
            automod_module.NATIVE_BLACKLIST_CUSTOM_MESSAGE = NATIVE_FILTER_MESSAGE
        except Exception:
            logger.exception("Impossible de mettre à jour le message natif mots interdits.")

        for old_name in ("blacklist-add", "blacklist-remove", "blacklist-list"):
            command = self.bot.get_command(old_name)
            if command is not None:
                command.hidden = True
        for old_name in ("blacklist-add", "blacklist-list"):
            try:
                self.bot.tree.remove_command(old_name, type=discord.AppCommandType.chat_input)
            except Exception:
                pass
        self._patched = True

    def _automod(self):
        return self.bot.get_cog("Automod")

    async def _sync(self, guild: discord.Guild) -> None:
        automod = self._automod()
        if automod is None:
            return
        cache = getattr(automod, "blacklist_words_cache", None)
        if isinstance(cache, dict):
            cache.pop(guild.id, None)
        sync = getattr(automod, "_sync_native_blacklist_rule", None)
        if callable(sync):
            try:
                await sync(guild)
            except Exception:
                logger.exception("Synchronisation mots interdits impossible guild=%s", guild.id)

    @commands.Cog.listener()
    async def on_ready(self):
        self._patch_runtime()
        for guild in self.bot.guilds:
            await self._sync(guild)

    @commands.hybrid_command(
        name="mots-interdits-ajouter",
        description="Ajouter un mot ou une expression aux mots interdits.",
    )
    @app_commands.describe(mot="Mot ou expression à censurer")
    @checks.is_owner_or_admin_for("securite")
    async def forbidden_add(self, ctx: commands.Context, *, mot: str):
        word = str(mot or "").strip().casefold()
        if not word or len(word) > 80:
            return await panels.envoyer(
                ctx,
                panels.depuis_embed(embeds.error("Le mot ou l’expression doit contenir entre 1 et 80 caractères.")),
            )
        exists = await self.bot.db.fetchone(
            "SELECT 1 FROM blacklist_words WHERE guild_id=? AND lower(word)=lower(?) LIMIT 1",
            (ctx.guild.id, word),
        )
        if not exists:
            await self.bot.db.execute(
                "INSERT INTO blacklist_words (guild_id, word) VALUES (?, ?)",
                (ctx.guild.id, word),
            )
        await self._sync(ctx.guild)
        await panels.envoyer(
            ctx,
            panels.depuis_embed(embeds.success(f"`{word}` a été ajouté aux **mots interdits**.")),
        )

    @commands.hybrid_command(
        name="mots-interdits-retirer",
        description="Retirer un mot ou une expression des mots interdits.",
        with_app_command=False,
    )
    @app_commands.describe(mot="Mot ou expression à autoriser de nouveau")
    @checks.is_owner_or_admin_for("securite")
    async def forbidden_remove(self, ctx: commands.Context, *, mot: str):
        word = str(mot or "").strip().casefold()
        await self.bot.db.execute(
            "DELETE FROM blacklist_words WHERE guild_id=? AND lower(word)=lower(?)",
            (ctx.guild.id, word),
        )
        await self._sync(ctx.guild)
        await panels.envoyer(
            ctx,
            panels.depuis_embed(embeds.success(f"`{word}` a été retiré des **mots interdits**.")),
        )

    @commands.hybrid_command(
        name="mots-interdits",
        description="Afficher les mots interdits de ce serveur.",
    )
    @checks.is_owner_or_admin_for("securite")
    async def forbidden_list(self, ctx: commands.Context):
        rows = await self.bot.db.fetchall(
            "SELECT word FROM blacklist_words WHERE guild_id=? ORDER BY word",
            (ctx.guild.id,),
        )
        if not rows:
            return await panels.envoyer(
                ctx,
                panels.depuis_embed(embeds.info("Aucun mot interdit configuré.")),
            )
        words = ", ".join(f"`{row['word']}`" for row in rows)
        await panels.envoyer(
            ctx,
            panels.depuis_embed(embeds.neutral("🚫 Mots interdits", words[:3900])),
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(ForbiddenWordsUI(bot))
