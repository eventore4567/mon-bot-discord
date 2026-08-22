"""Installation SentriX complète en une seule commande : +create sentrix.

La commande configure le serveur Discord courant ; un bot ne peut pas créer une nouvelle
guilde Discord. Elle réutilise le moteur ServerBuilder existant, complète le modèle avec
un espace Animations dédié, configure les protections de base et mémorise le succès afin
que l'installation complète ne puisse être lancée qu'une seule fois par serveur.

Important : le verrou n'est enregistré qu'APRÈS une installation réussie. Une erreur de
permission, une coupure Discord ou un échec partiel laisse donc la commande relançable ;
ServerBuilder est idempotent et réutilise les éléments portant déjà le même nom.
"""
from __future__ import annotations

import asyncio
import logging
import time

import discord
from discord.ext import commands

from utils import checks

logger = logging.getLogger("bot.create-sentrix")

INSTALL_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS sentrix_server_installations (
    guild_id INTEGER PRIMARY KEY,
    installed_at INTEGER NOT NULL,
    installed_by INTEGER NOT NULL,
    template_key TEXT NOT NULL DEFAULT 'communaute'
)
"""

ANIMATION_TEXT_CHANNELS = (
    ("annonces-animations", True, "Annonces officielles des prochaines animations du serveur."),
    ("planning-animations", True, "Calendrier et horaires des animations à venir."),
    ("animations", False, "Salon principal pour participer et discuter pendant les animations."),
    ("inscriptions-animations", False, "Inscriptions aux animations organisées par le staff."),
    ("idées-animations", False, "Proposez de nouvelles idées d'animations pour la communauté."),
)

CORE_AUTOMOD = (
    "antispam",
    "antiinvite",
    "antimention",
    "antiraid",
    "antiscam",
)


class CreateSentrix(commands.Cog, name="CreateSentrix"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._locks: dict[int, asyncio.Lock] = {}

    def _lock_for(self, guild_id: int) -> asyncio.Lock:
        lock = self._locks.get(guild_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[guild_id] = lock
        return lock

    async def _ensure_table(self) -> None:
        await self.bot.db.execute(INSTALL_TABLE_SQL)

    async def _installation(self, guild_id: int):
        await self._ensure_table()
        return await self.bot.db.fetchone(
            "SELECT guild_id, installed_at, installed_by, template_key "
            "FROM sentrix_server_installations WHERE guild_id = ?",
            (guild_id,),
        )

    async def _mark_installed(self, guild_id: int, user_id: int) -> None:
        await self.bot.db.execute(
            "INSERT OR IGNORE INTO sentrix_server_installations "
            "(guild_id, installed_at, installed_by, template_key) VALUES (?, ?, ?, ?)",
            (guild_id, int(time.time()), user_id, "communaute"),
        )

    async def _ensure_animation_space(self, guild: discord.Guild) -> dict[str, int]:
        """Ajoute un espace Animations complémentaire, sans toucher aux salons existants."""
        me = guild.me
        default = guild.default_role

        category = discord.utils.get(guild.categories, name="ANIMATIONS")
        if category is None:
            category = await guild.create_category(
                "ANIMATIONS",
                reason="Installation +create sentrix",
            )

        created_text = 0
        reused_text = 0
        for name, readonly, topic in ANIMATION_TEXT_CHANNELS:
            channel = discord.utils.get(guild.text_channels, name=name)
            if channel is None:
                overwrites = {
                    default: discord.PermissionOverwrite(
                        view_channel=True,
                        send_messages=not readonly,
                        read_message_history=True,
                    ),
                }
                if me is not None:
                    overwrites[me] = discord.PermissionOverwrite(
                        view_channel=True,
                        send_messages=True,
                        manage_messages=True,
                        manage_channels=True,
                        read_message_history=True,
                    )
                await guild.create_text_channel(
                    name,
                    category=category,
                    topic=topic,
                    overwrites=overwrites,
                    reason="Installation +create sentrix",
                )
                created_text += 1
            else:
                reused_text += 1
                if channel.category_id != category.id:
                    try:
                        await channel.edit(category=category, reason="Organisation +create sentrix")
                    except discord.HTTPException:
                        pass

        voice = discord.utils.get(guild.voice_channels, name="Animation vocale")
        voice_created = 0
        if voice is None:
            await guild.create_voice_channel(
                "Animation vocale",
                category=category,
                reason="Installation +create sentrix",
            )
            voice_created = 1
        elif voice.category_id != category.id:
            try:
                await voice.edit(category=category, reason="Organisation +create sentrix")
            except discord.HTTPException:
                pass

        return {
            "text_created": created_text,
            "text_reused": reused_text,
            "voice_created": voice_created,
        }

    async def _apply_sentrix_defaults(self, guild: discord.Guild) -> None:
        """Active uniquement les protections de base peu risquées après la création."""
        await self.bot.db.ensure_guild(guild.id)
        for field in CORE_AUTOMOD:
            try:
                await self.bot.db.set_automod(guild.id, field, 1)
            except Exception:
                logger.warning(
                    "Impossible d'activer %s pendant +create sentrix sur %s",
                    field,
                    guild.id,
                    exc_info=True,
                )

        try:
            await self.bot.db.set_guild_config(guild.id, "security_level", "moyen")
        except Exception:
            logger.warning("Impossible de régler le niveau sécurité SentriX.", exc_info=True)

    @commands.group(name="create", invoke_without_command=True)
    @checks.is_owner_or_admin_for("configuration")
    async def create(self, ctx: commands.Context):
        """Centre de création automatique SentriX."""
        if ctx.invoked_subcommand is None:
            await ctx.send("Utilise `+create sentrix` pour installer la structure SentriX complète sur ce serveur.")

    @create.command(name="sentrix")
    @checks.is_owner_or_admin_for("configuration")
    async def create_sentrix(self, ctx: commands.Context):
        """Crée une fois la structure SentriX complète dans le serveur courant."""
        guild = ctx.guild
        if guild is None:
            return await ctx.send("Cette commande doit être utilisée dans un serveur Discord.")

        me = guild.me
        if me is None or not me.guild_permissions.administrator:
            return await ctx.send(
                "SentriX doit avoir la permission Administrateur pour créer correctement les rôles, salons et permissions."
            )

        lock = self._lock_for(guild.id)
        if lock.locked():
            return await ctx.send("Une installation SentriX est déjà en cours sur ce serveur.")

        async with lock:
            previous = await self._installation(guild.id)
            if previous is not None:
                installed_at = int(previous["installed_at"])
                return await ctx.send(
                    "La création SentriX complète a déjà été utilisée sur ce serveur "
                    f"le <t:{installed_at}:F>. Elle ne peut être lancée qu'une seule fois."
                )

            builder = self.bot.get_cog("ServerBuilder")
            if builder is None or not hasattr(builder, "build_server"):
                logger.error("+create sentrix : ServerBuilder introuvable.")
                return await ctx.send("Le module de création de serveur SentriX n'est pas chargé. Réessaie après un redémarrage du bot.")

            progress = await ctx.send(
                "Installation SentriX en cours...\n"
                "Création des rôles, catégories, salons, tickets, accueil, départs, événements, économie, staff, vocaux et logs.\n"
                "Ne relance pas la commande pendant l'installation."
            )

            try:
                result = await builder.build_server(guild, "communaute", ctx.author)

                result_title = str(getattr(result, "title", "") or "")
                if result_title != "Configuration terminée":
                    description = str(getattr(result, "description", "") or "L'installation n'a pas pu être terminée.")
                    await progress.edit(content=f"Installation interrompue.\n{description}", embed=None, view=None)
                    return

                animation_stats = await self._ensure_animation_space(guild)
                await self._apply_sentrix_defaults(guild)
                await self._mark_installed(guild.id, ctx.author.id)

                from .server_builder import SERVER_TEMPLATES

                template = SERVER_TEMPLATES.get("communaute", {})
                categories = template.get("categories", [])
                role_count = len(template.get("roles", []))
                base_channel_count = sum(len(category.get("channels", [])) for category in categories)
                total_categories = len(categories) + 1
                total_channels = base_channel_count + len(ANIMATION_TEXT_CHANNELS) + 1

                await progress.edit(
                    content=(
                        "Installation SentriX terminée.\n\n"
                        f"Structure : {total_categories} catégories, environ {total_channels} salons et {role_count} rôles gérés.\n"
                        "Inclus : bienvenue, départs, règlement, annonces, communauté, jeux, animations, événements, économie, "
                        "créateurs, tickets, vocaux, partenariats, staff, logs et archives.\n"
                        "Tickets : panneau et catégorie de tickets configurés automatiquement.\n"
                        "Sécurité : anti-spam, anti-invitations, anti-mentions abusives, anti-raid et anti-scam activés.\n"
                        f"Animations : {animation_stats['text_created']} salon(s) texte créé(s), "
                        f"{animation_stats['text_reused']} réutilisé(s).\n\n"
                        "La commande `+create sentrix` est maintenant verrouillée définitivement pour ce serveur. "
                        "Tu peux toujours personnaliser ensuite avec `+setup`."
                    ),
                    embed=None,
                    view=None,
                )
            except discord.Forbidden:
                logger.warning("+create sentrix refusé par Discord sur guild=%s", guild.id, exc_info=True)
                await progress.edit(
                    content=(
                        "Installation arrêtée : Discord a refusé une création ou une modification. "
                        "Vérifie que SentriX a Administrateur et que son rôle est assez haut. "
                        "La commande n'a PAS été consommée : tu peux la relancer après correction."
                    ),
                    embed=None,
                    view=None,
                )
            except discord.HTTPException as exc:
                logger.warning("+create sentrix HTTP error guild=%s: %s", guild.id, exc, exc_info=True)
                await progress.edit(
                    content=(
                        "Installation interrompue par Discord. Les éléments déjà créés seront réutilisés au prochain essai. "
                        "La commande n'a PAS été consommée : attends un peu puis relance `+create sentrix`."
                    ),
                    embed=None,
                    view=None,
                )
            except Exception:
                logger.exception("Erreur inattendue +create sentrix guild=%s", guild.id)
                try:
                    await progress.edit(
                        content=(
                            "Installation interrompue par une erreur technique. Aucun verrou définitif n'a été posé. "
                            "Les éléments déjà créés seront réutilisés si tu relances `+create sentrix`."
                        ),
                        embed=None,
                        view=None,
                    )
                except discord.HTTPException:
                    pass


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(CreateSentrix(bot))
