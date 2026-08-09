"""Filtre anti-GIF persistant pour SentriX.

Ajoute la commande texte ``+antigif on|off`` sans modifier le schéma historique
``automod_settings``. Le réglage est stocké dans sa propre table SQLite afin de rester
compatible avec les bases déjà déployées.

Le propriétaire réel du serveur est toujours immunisé. Le filtre reconnaît les fichiers,
les embeds Discord et les principaux liens/fournisseurs de GIF ; il supprime uniquement le
message concerné et n'applique aucune sanction au membre.
"""

from __future__ import annotations

import asyncio
import logging
import re
import sys

import discord
from discord.ext import commands

from utils import embeds, checks

logger = logging.getLogger("bot.antigif")

_GIF_FILE_RE = re.compile(
    r"https?://[^\s<>]+\.(?:gif|gifv)(?:[?#][^\s<>]*)?",
    re.IGNORECASE,
)
_GIF_PROVIDER_RE = re.compile(
    r"https?://(?:[^/]+\.)?(?:tenor\.com|giphy\.com|gfycat\.com|redgifs\.com|klipy\.com)(?:/|$)",
    re.IGNORECASE,
)
_GIF_QUERY_RE = re.compile(
    r"https?://[^\s<>]+(?:[?&](?:format|fm)=gif(?:[&#]|$)|[?&]animated=true(?:[&#]|$))",
    re.IGNORECASE,
)
_ON_VALUES = {"on", "oui", "activer", "active", "enable", "enabled", "1"}
_OFF_VALUES = {"off", "non", "desactiver", "désactiver", "disable", "disabled", "0"}


def _looks_like_gif_url(value: str | None) -> bool:
    text = str(value or "")
    return bool(
        _GIF_FILE_RE.search(text)
        or _GIF_PROVIDER_RE.search(text)
        or _GIF_QUERY_RE.search(text)
    )


class AntiGifRuntime:
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.cache: dict[int, bool] = {}
        self._table_ready = False
        self._table_lock = asyncio.Lock()

    async def ensure_table(self) -> None:
        if self._table_ready:
            return
        async with self._table_lock:
            if self._table_ready:
                return
            await self.bot.db.execute(
                """
                CREATE TABLE IF NOT EXISTS antigif_settings (
                    guild_id INTEGER PRIMARY KEY,
                    enabled INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            self._table_ready = True

    async def is_enabled(self, guild_id: int) -> bool:
        if guild_id in self.cache:
            return self.cache[guild_id]
        await self.ensure_table()
        row = await self.bot.db.fetchone(
            "SELECT enabled FROM antigif_settings WHERE guild_id = ?",
            (guild_id,),
        )
        enabled = bool(row["enabled"]) if row else False
        self.cache[guild_id] = enabled
        return enabled

    async def set_enabled(self, guild_id: int, enabled: bool) -> None:
        await self.ensure_table()
        await self.bot.db.execute(
            """
            INSERT INTO antigif_settings (guild_id, enabled)
            VALUES (?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET enabled = excluded.enabled
            """,
            (guild_id, 1 if enabled else 0),
        )
        self.cache[guild_id] = enabled

    @staticmethod
    def message_contains_gif(message: discord.Message) -> bool:
        # Fichier GIF envoyé directement.
        for attachment in message.attachments:
            filename = str(getattr(attachment, "filename", "") or "").casefold()
            content_type = str(getattr(attachment, "content_type", "") or "").casefold()
            if filename.endswith((".gif", ".gifv")) or content_type == "image/gif":
                return True
            if _looks_like_gif_url(getattr(attachment, "url", None)):
                return True
            if _looks_like_gif_url(getattr(attachment, "proxy_url", None)):
                return True

        # Liens collés dans le message : .gif/.gifv, Tenor/Giphy/etc. et proxies animés.
        content = str(message.content or "")
        if _looks_like_gif_url(content):
            return True

        # Le sélecteur GIF Discord et certains services envoient un embed de type gifv.
        # Cette vérification bloque aussi les liens dont l'URL finale n'est ajoutée qu'après
        # la création de l'embed par Discord.
        for embed in message.embeds:
            if str(getattr(embed, "type", "") or "").casefold() == "gifv":
                return True

            candidates = [
                getattr(embed, "url", None),
                getattr(getattr(embed, "image", None), "url", None),
                getattr(getattr(embed, "thumbnail", None), "url", None),
                getattr(getattr(embed, "video", None), "url", None),
                getattr(getattr(embed, "provider", None), "url", None),
            ]
            if any(_looks_like_gif_url(value) for value in candidates):
                return True

        return False

    async def handle_message(self, message: discord.Message) -> None:
        if message.guild is None or message.author.bot:
            return

        # Immunité absolue du propriétaire du serveur : même avec Anti-GIF activé, ses
        # fichiers, liens et embeds GIF restent autorisés.
        if message.author.id == message.guild.owner_id:
            return

        if not await self.is_enabled(message.guild.id):
            return
        if not self.message_contains_gif(message):
            return

        try:
            await message.delete(reason="SentriX Anti-GIF activé")
        except (discord.NotFound, discord.Forbidden):
            return
        except discord.HTTPException:
            logger.exception("Impossible de supprimer un GIF dans %s", message.guild.id)
            return

        # Politique SentriX : un filtre de contenu supprime seulement le contenu interdit.
        # Pas de mute, kick ou ban pour un GIF.
        try:
            await message.channel.send(
                embed=embeds.warning(
                    "Les GIFs sont désactivés sur ce serveur : le message a simplement été supprimé."
                ),
                delete_after=5,
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except (discord.Forbidden, discord.HTTPException):
            pass


def _patch_permission_policy() -> None:
    """Classe +antigif dans la même catégorie de sécurité que les autres anti-*.

    main.py tourne comme ``__main__`` en production. Modifier ses ensembles en mémoire
    évite d'avoir à dupliquer toute la grosse table de permissions juste pour une commande.
    """
    main_module = sys.modules.get("__main__")
    if main_module is None:
        return

    categories = getattr(main_module, "CATEGORY_COMMANDS", None)
    if isinstance(categories, dict) and "securite" in categories:
        categories["securite"] = frozenset(set(categories["securite"]) | {"antigif"})

    known = getattr(main_module, "KNOWN_PERMISSION_COMMANDS", None)
    if known is not None:
        main_module.KNOWN_PERMISSION_COMMANDS = frozenset(set(known) | {"antigif"})


def install(bot: commands.Bot) -> None:
    """Installe le filtre, ses listeners et la commande +antigif une seule fois."""
    if getattr(bot, "_sentrix_antigif_runtime", None) is not None:
        return

    runtime = AntiGifRuntime(bot)
    bot._sentrix_antigif_runtime = runtime
    _patch_permission_policy()

    @commands.command(
        name="antigif",
        aliases=["gifs"],
        help="Activer ou désactiver le blocage des GIFs.",
        description="Activer ou désactiver le blocage des GIFs.",
    )
    @commands.guild_only()
    @checks.is_owner_or_admin_for("securite")
    async def antigif(ctx: commands.Context, etat: str | None = None):
        if etat is None:
            enabled = await runtime.is_enabled(ctx.guild.id)
            state = "activé" if enabled else "désactivé"
            return await ctx.send(
                embed=embeds.neutral(
                    "Anti-GIF",
                    f"Le blocage des GIFs est actuellement **{state}**.\n"
                    f"Utilisez `{ctx.clean_prefix}antigif on` ou `{ctx.clean_prefix}antigif off`.",
                )
            )

        value = str(etat).casefold().strip()
        if value in _ON_VALUES:
            await runtime.set_enabled(ctx.guild.id, True)
            return await ctx.send(
                embed=embeds.success(
                    "Anti-GIF activé. Les GIFs et liens GIF seront automatiquement supprimés, sans sanction du membre."
                )
            )
        if value in _OFF_VALUES:
            await runtime.set_enabled(ctx.guild.id, False)
            return await ctx.send(
                embed=embeds.success(
                    "Anti-GIF désactivé. Les GIFs sont de nouveau autorisés."
                )
            )

        await ctx.send(
            embed=embeds.error(
                f"Utilisez `{ctx.clean_prefix}antigif on` pour bloquer les GIFs ou "
                f"`{ctx.clean_prefix}antigif off` pour les autoriser."
            )
        )

    if bot.get_command("antigif") is None:
        bot.add_command(antigif)

    async def on_message(message: discord.Message):
        await runtime.handle_message(message)

    async def on_message_edit(before: discord.Message, after: discord.Message):
        # Certains liens GIF reçoivent leur embed quelques instants après l'envoi.
        # On revérifie donc le message modifié afin de bloquer ces cas aussi.
        await runtime.handle_message(after)

    bot.add_listener(on_message, "on_message")
    bot.add_listener(on_message_edit, "on_message_edit")

    # La base est déjà connectée quand ce runtime est installé dans setup_hook().
    # Pré-créer la table réduit le premier accès, mais toutes les méthodes restent sûres
    # même si cette tâche est retardée.
    try:
        asyncio.create_task(runtime.ensure_table())
    except RuntimeError:
        pass

    logger.info("Anti-GIF installé : +antigif on/off, liens GIF inclus, suppression seule.")
